"""TREND OS shell main loop.

Modes: "launcher" (carousel + stats), "app" (an app owns the area below the title),
"power" (power menu), "halt" (shutting down). Independently the screen can be asleep.

Each frame draws into the framebuffer page shown 2 flips ago (triple buffering) and remembers
per page what it drew, so only changed parts are redrawn and the visible page is never touched.
"""
import select, subprocess, time

from .config import (W, H, NPAGES, TOP, TITLE, TITLE_Y, TITLE_H, BAND, ACCENT, GREET_NAME, BLEND,
                     MAX_FPS, SLEEP_AFTER, LONG_PRESS, KEY_HOME, KEY_BACK, KEY_POWER)
from .fb import Framebuffer
from .gfx import text_strip
from .inputdev import Input
from .launcher import Launcher, default_entries
from .render import Renderer
from .stats import StatsPanel
from .title import TitleAnim
from . import boot, power


class Shell:
    def __init__(self):
        self.fb = Framebuffer()
        self.renderer = Renderer()
        self.input = Input()
        self.entries = default_entries()

    # ---- startup ----------------------------------------------------------------------------
    def take_over_from_boot(self):
        """Paint the boot frame's title/stats parts on every page (the band still shows the
        ramdisk's loading spin), stop that animation and start the sound."""
        bf = boot.boot_frame(self.renderer, self.entries[0].shape)
        for pg in self.fb.pages:
            pg[:TOP] = bf[:TOP]
            pg[TOP + BAND:] = bf[TOP + BAND:]
        boot.stop_bootanim()
        boot.play_startup_sound()

    def run(self):
        self.take_over_from_boot()
        now = time.monotonic()
        self.start = self.last = self.last_input = now
        self.launcher = Launcher(self.entries, now)
        self.stats = StatsPanel()
        self.title = TitleAnim(TITLE, f"Welcome, {GREET_NAME}")
        self.mode, self.app = "launcher", None
        self.asleep = False
        self.power_down_t, self.power_handled = None, False
        self.menu_pressed, self.prev_mode = None, "launcher"
        self.page, self.frames, self.fps, self.fps_t0 = 1, 0, 0.0, now
        self.shown = {}                                   # region -> per-page "what is drawn"
        self.repaint_all()
        self.shown["base"] = ["launcher"] * NPAGES     # boot frame is already a launcher screen
        while True:
            if self.asleep:
                self.sleep_until_wake()
                continue
            self.frame()

    def repaint_all(self):
        """Forget what every page shows, so everything is redrawn on all pages."""
        self.shown = {k: [None] * NPAGES for k in ("title", "app", "base")}
        self.launcher.invalidate()
        self.stats.invalidate()

    # ---- sleep ----------------------------------------------------------------------------------
    def sleep_until_wake(self):
        """Screen off: no drawing, block on input until Power or Home."""
        select.select(self.input.fds, [], [], 5.0)
        for ev, code, val, _ in self.input.poll():
            if ev == "key" and val == 1 and code in (KEY_POWER, KEY_HOME):
                self.fb.screen_on((self.page - 1) % NPAGES)
                self.asleep = False
                self.last = self.last_input = time.monotonic()
                self.power_down_t, self.power_handled = None, True     # ignore this press's release
                self.repaint_all()
                return

    def go_to_sleep(self):
        self.asleep = True
        self.fb.screen_off()

    # ---- one frame ------------------------------------------------------------------------------
    def frame(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        for ev in self.input.poll():
            self.handle(ev, now)
        if self.power_down_t is not None and not self.power_handled and now - self.power_down_t >= LONG_PRESS:
            self.power_handled = True
            self.open_power_menu()
        if self.mode in ("launcher", "app") and now - self.last_input > SLEEP_AFTER:
            self.asleep = True
        if self.asleep:
            self.go_to_sleep()
            return
        if self.mode == "halt":
            time.sleep(0.5)
            return

        blend = min(1.0, (now - self.start) / BLEND)
        blend = blend * blend * (3 - 2 * blend)                       # smoothstep
        self.launcher.update(now, dt, blend)
        buf = self.fb.pages[self.page]
        if self.mode == "launcher":
            self.draw_launcher(buf, now, blend)
        elif self.mode == "power":
            self.draw_region(buf, "app", ("power", self.menu_pressed), lambda: power.render(self.menu_pressed))
            self.draw_title(buf, ("power",), lambda: text_strip(TITLE, 28, ACCENT, TITLE_H))
        else:
            self.draw_region(buf, "app", self.app.key(now), lambda: self.app.render(now))
            self.draw_title(buf, ("app", self.app.name),
                            lambda: text_strip("‹ " + self.app.name, 28, ACCENT, TITLE_H, x=16))
        self.fb.show(self.page)
        self.page = (self.page + 1) % NPAGES
        self.count_fps()
        spare = 1.0 / MAX_FPS - (time.monotonic() - now)
        if spare > 0:
            time.sleep(spare)

    def count_fps(self):
        self.frames += 1
        if self.frames % 15 == 0:
            t = time.monotonic()
            self.fps, self.fps_t0 = 15 / (t - self.fps_t0), t

    # ---- drawing helpers ----------------------------------------------------------------------------
    def draw_title(self, buf, key, render):
        if self.shown["title"][self.page] != key:
            buf[TITLE_Y:TITLE_Y + TITLE_H] = render()
            self.shown["title"][self.page] = key

    def draw_region(self, buf, region, key, render):
        """Full app-area redraw on this page only when its key changed."""
        if self.shown[region][self.page] != key:
            buf[TOP:H] = render()
            self.shown[region][self.page] = key

    def draw_launcher(self, buf, now, blend):
        if self.shown["base"][self.page] != "launcher":
            # coming back from an app/menu: the launcher only repaints the parts it owns
            # (band, title, stats rows), so clear the whole area below the title once per page
            buf[TOP:H] = 0
            self.shown["base"][self.page] = "launcher"
        self.launcher.draw(buf, self.page, self.renderer, blend)
        st = self.title.state(now - self.start)
        self.draw_title(buf, st, lambda: self.title.render(*st))
        self.stats.update(now, self.fps, may_render=not self.launcher.busy)   # no stats work mid-swipe
        self.stats.sync(buf, self.page)

    # ---- input ---------------------------------------------------------------------------------------
    def handle(self, ev, now):
        kind, x, y, t = ev
        self.last_input = now
        if kind == "key" and x == KEY_POWER:
            self.on_power_key(y, now)
        elif self.mode == "power":
            self.on_power_menu(kind, x, y)
        elif self.mode == "app":
            self.on_app(kind, x, y)
        elif self.mode == "launcher":
            if kind == "key":
                if y == 1 and x == KEY_HOME:
                    self.launcher.on_home(now)
            else:
                app = self.launcher.on_touch(kind, x, y, t, now)
                if app is not None:
                    self.mode, self.app = "app", app
                    self.repaint_all()

    def on_power_key(self, pressed, now):
        """Short press: screen off. Long press (handled in frame()): power menu."""
        if pressed:
            self.power_down_t, self.power_handled = now, False
        elif self.power_down_t is not None:
            if not self.power_handled and self.mode != "power":
                self.asleep = True
            self.power_down_t = None

    def on_app(self, kind, x, y):
        back = (kind == "key" and y == 1 and x in (KEY_BACK, KEY_HOME)) or (kind == "up" and y < TOP)
        if back:
            self.mode, self.app = "launcher", None
            self.repaint_all()
        elif kind in ("down", "move", "up"):
            self.app.touch(kind, x, y)

    def open_power_menu(self):
        if self.mode in ("launcher", "app"):
            self.prev_mode, self.mode, self.menu_pressed = self.mode, "power", None
            if self.prev_mode == "launcher":
                self.launcher.reset_position()

    def close_power_menu(self):
        self.mode = self.prev_mode
        self.repaint_all()

    def on_power_menu(self, kind, x, y):
        if kind == "key":
            if y == 1 and x in (KEY_BACK, KEY_HOME):
                self.close_power_menu()
        elif kind == "down":
            self.menu_pressed = power.button_at(x, y)
        elif kind == "move":
            if power.button_at(x, y) != self.menu_pressed:
                self.menu_pressed = None
        elif kind == "up":
            b = power.button_at(x, y)
            if b is not None and b == self.menu_pressed:
                if b == power.CANCEL:
                    self.close_power_menu()
                else:
                    self.halt("poweroff" if b == power.SHUTDOWN else "reboot")
            self.menu_pressed = None

    def halt(self, cmd):
        msg = power.message("Shutting down..." if cmd == "poweroff" else "Restarting...")
        for pg in self.fb.pages:
            pg[:] = msg
        self.fb.show(self.page)
        subprocess.Popen([cmd])                       # OpenRC stops this service on the way down
        self.mode = "halt"

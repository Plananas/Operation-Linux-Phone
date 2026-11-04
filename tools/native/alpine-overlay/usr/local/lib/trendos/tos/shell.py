"""TREND OS shell main loop.

Modes: "launcher" (carousel + stats), "app" (an app owns the area below the title),
"transition" (sliding between launcher and an app), "power" (power menu), "halt" (shutting
down). Independently the screen can be asleep. The launcher is frozen while not visible.

Each frame draws into the framebuffer page shown 2 flips ago (triple buffering) and remembers
per page what it drew, so only changed parts are redrawn and the visible page is never touched.
"""
import math, select, subprocess, time

import numpy as np

from .config import (W, H, NPAGES, TOP, TITLE, TITLE_Y, TITLE_H, BAND, ACCENT, GREET_NAME, BLEND,
                     MAX_FPS, SLEEP_AFTER, LONG_PRESS, KEY_HOME, KEY_BACK, KEY_POWER)
from .fb import Framebuffer
from .gfx import text_strip
from .inputdev import Input
from .launcher import Launcher, default_entries, settings_entries
from .render import MINI, MINI_CW, MINI_CH, draw_view, matrix
from .stats import StatsPanel
from .title import TitleAnim
from . import boot, power
from .transition import Slide
from .flight import Flight, badge_angles, carousel_angles


class Shell:
    def __init__(self):
        self.fb = Framebuffer()
        self.input = Input()
        self.entries = default_entries()

    # ---- startup ----------------------------------------------------------------------------
    def take_over_from_boot(self):
        """Paint the boot frame's title/stats parts on every page (the band still shows the
        ramdisk's loading spin), stop that animation and start the sound."""
        bf = boot.boot_frame(self.entries[0].shape)
        for pg in self.fb.pages:
            pg[:TOP] = bf[:TOP]
            pg[TOP + BAND:] = bf[TOP + BAND:]
        # The display may be asleep if this service was restarted while the screen was off
        # (e.g. after auto-sleep). Waking an awake display is a no-op, so always do it.
        self.fb.screen_on(0)
        boot.stop_bootanim()
        boot.play_startup_sound()

    def run(self):
        self.take_over_from_boot()
        now = time.monotonic()
        self.start = self.last = self.last_input = now
        self.home = Launcher(self.entries, now)
        self.launcher = self.home            # current carousel (home or a sub-menu)
        self.carousel_is_home = True
        self.settings = None                 # built lazily on first open
        self.home_snap = None                # home screen image, to slide back to from settings
        self.stats = StatsPanel()
        self.title = TitleAnim(TITLE, f"Welcome, {GREET_NAME}")
        self.mode, self.app = "launcher", None
        self.asleep = False
        self.power_down_t, self.power_handled = None, False
        self.menu, self.prev_mode = None, "launcher"
        self.trans, self.trans_target, self.launcher_snap = None, None, None
        self.flight = None                     # the open app's icon flight (closing replays it)
        self.trans_live = None                 # carousel whose spin advances during a transition
        self.held_events = []                 # touches made while an app is sliding open
        self.warm = [en.app for en in self.entries if en.app is not None]   # apps to pre-render
        self.page, self.frames, self.fps, self.fps_t0 = 1, 0, 0.0, now
        self.bg_apps = [en.app for en in self.entries if en.app is not None]
        self.next_bg = now
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
        self.shown = {k: [None] * NPAGES for k in ("title", "app", "base", "full")}
        self._region_cache = (None, None)        # (key, image) of the last rendered app area
        self.launcher.invalidate()
        self.stats.invalidate()

    # ---- sleep ----------------------------------------------------------------------------------
    def sleep_until_wake(self):
        """Screen off: no drawing, block on input until Power or Home."""
        select.select(self.input.fds, [], [], 2.0)
        if self.run_background(time.monotonic()):
            return
        for ev, code, val, _ in self.input.poll():
            if ev == "key" and val == 1 and code in (KEY_POWER, KEY_HOME):
                self.fb.screen_on((self.page - 1) % NPAGES)
                self.asleep = False
                self.last = self.last_input = time.monotonic()
                self.power_down_t, self.power_handled = None, True     # ignore this press's release
                self.repaint_all()
                return

    # ---- background apps (alarms) ------------------------------------------------------------
    def run_background(self, now):
        """Let apps check timers about once a second; True if one was brought to the front."""
        if now < self.next_bg or self.mode == "halt":
            return False
        self.next_bg = now + 1.0
        for app in self.bg_apps:
            try:
                wants = app.background(now)
            except Exception:
                wants = False
            if wants:
                self.summon(app)
                return True
        return False

    def summon(self, app):
        """Bring app to the front now: wake the screen, close whatever else is open (no slide;
        Back later slides to the home carousel)."""
        now = time.monotonic()
        if self.asleep:
            self.fb.screen_on((self.page - 1) % NPAGES)
            self.asleep = False
            self.last = now
        self.last_input = now
        self.power_down_t, self.power_handled = None, True
        self.menu = None
        if self.app is not None and self.app is not app:
            self.app.on_close()
        if self.settings is not None:
            self.settings.reset_position()
        self.home.cur, self.home.off = 0, 0.0
        self.home.reset_position()
        self.launcher = self.home; self.carousel_is_home = True
        self.launcher_snap = self.carousel_frame(self.home, "Welcome, " + GREET_NAME, now)
        self.flight = None                    # no carousel object to fly back to
        if self.app is not app:
            self.app = app
            app.on_open()
        self.trans, self.trans_live, self.held_events = None, None, []
        self.mode = "app"
        self.repaint_all()

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
        self.run_background(now)
        if self.mode == "app" and self.app.keep_awake:
            self.last_input = now
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
        buf = self.fb.pages[self.page]
        if self.mode == "power":
            if not self.draw_power_menu(buf, now):
                return
        elif self.mode == "transition":
            self.draw_transition(buf, now, dt)
        if self.mode == "launcher":
            self.launcher.update(now, dt, blend)                      # frozen while not visible
            self.draw_launcher(buf, now, blend)
            if self.warm and self.carousel_is_home and now - self.start > 6 and not self.launcher.busy:
                self.warm.pop().render(now)       # pre-render one app per frame: instant first open
        elif self.mode == "app":
            self.clear_base(buf, "app")
            self.draw_region(buf, "app", self.app.key(now), lambda: self.app.render(now))
            self.draw_title(buf, ("app", self.app.name),
                            lambda: text_strip("‹ " + self.app.name, 28, ACCENT, TITLE_H, x=16))
            self.draw_badge(buf, self.app, now)
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
    BADGE_COLS, BADGE_ROWS = 13, 9                       # mini cells (5 x 7 px): 65 x 63 px
    BADGE_X = W - 14 - BADGE_COLS * MINI_CW

    def draw_badge(self, buf, app, now):
        """The app's launcher icon, small and slowly spinning, at the right of its title bar."""
        if app.icon_shape is None:
            return
        x, y = self.BADGE_X, 2
        buf[y:y + self.BADGE_ROWS * MINI_CH, x:x + self.BADGE_COLS * MINI_CW] = 0
        m9 = matrix(*badge_angles(now))
        draw_view(buf, app.icon_shape, m9, self.BADGE_COLS * 1.45, self.BADGE_COLS,
                           self.BADGE_ROWS, x, y, MINI, MINI_CW, MINI_CH)

    def draw_title(self, buf, key, render):
        if self.shown["title"][self.page] != key:
            buf[TITLE_Y:TITLE_Y + TITLE_H] = render()
            self.shown["title"][self.page] = key

    def draw_region(self, buf, region, key, render):
        """App-area redraw on this page only when its key changed. The image is rendered once
        per key and copied to the other pages (not re-rendered for each of the 3 pages)."""
        if self.shown[region][self.page] != key:
            if self._region_cache[0] != key:
                self._region_cache = (key, render())
            buf[TOP:H] = self._region_cache[1]
            self.shown[region][self.page] = key

    def draw_power_menu(self, buf, now):
        """Returns False if the frame should not be shown (menu just closed / halting)."""
        if self.menu.done_closing(now):
            self.mode, self.menu = self.prev_mode, None
            self.repaint_all()            # launcher/app redraws the frozen frame: seamless
            return True
        if self.menu.ready_to_halt(now):  # screen has faded to black
            subprocess.Popen(["poweroff" if self.menu.action == power.SHUTDOWN else "reboot"])
            self.mode = "halt"            # OpenRC stops this service on the way down
            return False
        key, draw = self.menu.frame(now)
        if self.shown["full"][self.page] != key:
            draw(buf)
            self.shown["full"][self.page] = key
        return True

    def clear_base(self, buf, base):
        """Screens only repaint the parts they own; after switching screens clear each page
        once so nothing of the previous screen (or a transition) is left behind."""
        if self.shown["base"][self.page] != base:
            buf[:] = 0
            self.shown["base"][self.page] = base

    def carousel_frame(self, carousel, title_text, now, skip_current=False):
        """Full-screen image of a carousel (title + its band) for slide transitions. The home
        greeting is centred (matching the live home title); sub-menu titles are left-aligned
        next to their back chevron."""
        f = np.zeros((H, W, 4), np.uint8)
        x = None if carousel is self.home else 16          # None = centred
        f[TITLE_Y:TITLE_Y + TITLE_H] = text_strip(title_text, 28, ACCENT, TITLE_H, x=x)
        f[TOP:TOP + BAND] = carousel.render_band(skip_current=skip_current)
        return f

    def app_frame(self, app, now, badge=True):
        """Full-screen image of an app as it will appear (title + app area)."""
        f = np.zeros((H, W, 4), np.uint8)
        f[TITLE_Y:TITLE_Y + TITLE_H] = text_strip("\u2039 " + app.name, 28, ACCENT, TITLE_H, x=16)
        f[TOP:H] = app.render(now)
        if badge:
            self.draw_badge(f, app, now)
        return f

    def start_transition(self, back, front, opening, target, live_carousel=None, live_side=None,
                         live_title="", skip_current=False, overlay=None):
        """live_carousel keeps spinning during the slide (rendered live on live_side, without
        its centred object if skip_current); overlay(buf, e, now) draws over each frame."""
        self.trans_live = live_carousel           # its sway keeps advancing (see draw_transition)
        live_fn = None
        if live_carousel is not None and not skip_current:
            # re-render it each frame so it keeps moving. Not when its centred object is the one
            # flying (skip_current): nothing else in it moves, so the static back is enough.
            live_fn = lambda now: self.carousel_frame(live_carousel, live_title, now)
        self.trans = Slide(back, front, time.monotonic(), opening,
                           live_fn=live_fn, live_side=live_side, overlay=overlay)
        self.held_events = []
        self.trans_target, self.mode = target, "transition"
        self.shown["full"] = [None] * NPAGES

    def draw_transition(self, buf, now, dt):
        if self.trans_live is not None:
            self.trans_live.update(now, dt, 1.0)          # keep its spin advancing
        if self.trans.done(now):
            self.mode, self.trans = self.trans_target, None
            self.repaint_all()                   # the target screen redraws its final frame
            held, self.held_events = self.held_events, []
            if self.mode == "app":               # deliver taps made while it was sliding open
                for kind, x, y in held:
                    self.app.touch(kind, x, y)
            return
        key = self.trans.key(now)
        if self.shown["full"][self.page] != key:
            self.trans.draw(buf, now)
            self.shown["full"][self.page] = key

    def open_app(self, app, entry=None):
        """Slide the app in; its launcher object (entry) flies up into the title-bar badge."""
        now = time.monotonic()
        snap = self.fb.pages[(self.page - 1) % NPAGES].copy()          # screen we came from
        self.flight = None
        if entry is not None and app.icon_shape is not None:
            self.flight = Flight(app.icon_shape, lambda: carousel_angles(entry))
            y0, y1, x0, x1 = self.flight.rect()
            snap[y0:y1, x0:x1] = 0                                     # it leaves the carousel
        self.launcher_snap = snap
        self.app = app
        app.on_open()
        self.start_transition(snap, self.app_frame(app, now, badge=self.flight is None), True, "app",
                              overlay=self.flight.draw if self.flight else None)

    def open_settings(self):
        now = time.monotonic()
        if self.settings is None:
            self.settings = Launcher(settings_entries(), now, is_home=False)
        self.home_snap = self.fb.pages[(self.page - 1) % NPAGES].copy()
        self.launcher = self.settings; self.carousel_is_home = False
        self.launcher.invalidate()
        self.start_transition(self.home_snap, self.carousel_frame(self.settings, "\u2039 Settings", now),
                              True, "launcher", live_carousel=self.settings, live_side="front",
                              live_title="\u2039 Settings")

    def close_settings(self):
        front = self.fb.pages[(self.page - 1) % NPAGES].copy()
        if self.settings is not None:
            self.settings.reset_position()
        self.launcher = self.home; self.carousel_is_home = True
        self.launcher.invalidate()
        self.start_transition(self.home_snap, front, False, "launcher",
                              live_carousel=self.home, live_side="back",
                              live_title="Welcome, " + GREET_NAME)

    def go_home(self):
        """Jump straight to the home carousel from any app or sub-menu (Home button)."""
        now = time.monotonic()
        if self.carousel_is_home and self.app is None:
            self.launcher.on_home(now)            # already home: just re-centre
            return
        front = self.fb.pages[(self.page - 1) % NPAGES].copy()
        if self.settings is not None:
            self.settings.reset_position()
        if self.app is not None:
            self.app.on_close()
        self.app = None
        self.home.cur, self.home.off = 0, 0.0
        self.home.reset_position(); self.home.invalidate()
        self.launcher = self.home; self.carousel_is_home = True
        dest = self.carousel_frame(self.home, "Welcome, " + GREET_NAME, now)
        self.start_transition(dest, front, False, "launcher", live_carousel=self.home,
                              live_side="back", live_title="Welcome, " + GREET_NAME)

    def close_app(self):
        """Slide the app out; the badge flies back down into its place in the carousel."""
        visible = self.fb.pages[(self.page - 1) % NPAGES].copy()
        back = self.launcher_snap if self.launcher_snap is not None else np.zeros_like(visible)
        title = "Welcome, " + GREET_NAME if self.carousel_is_home else "\u2039 Settings"
        fl, self.flight = self.flight, None
        if fl is not None:
            visible[:TOP, self.BADGE_X:] = 0                           # the badge is the flyer
        self.start_transition(back, visible, False, "launcher", live_carousel=self.launcher,
                              live_side="back", live_title=title, skip_current=fl is not None,
                              overlay=fl.draw if fl else None)
        self.app.on_close()
        self.app = None

    def draw_launcher(self, buf, now, blend):
        self.clear_base(buf, "launcher")
        self.launcher.draw(buf, self.page, blend)
        if self.carousel_is_home:
            st = self.title.state(now - self.start)
            self.draw_title(buf, st, lambda: self.title.render(*st))
            self.stats.update(now, self.fps, may_render=not self.launcher.busy)
            self.stats.sync(buf, self.page)
        else:
            self.draw_title(buf, ("menu", "Settings"),
                            lambda: text_strip("\u2039 Settings", 28, ACCENT, TITLE_H, x=16))

    # ---- input ---------------------------------------------------------------------------------------
    def handle(self, ev, now):
        kind, x, y, t = ev
        self.last_input = now
        if kind == "key" and x == KEY_POWER:
            self.on_power_key(y, now)
        elif self.mode == "power":
            self.on_power_menu(kind, x, y)
        elif self.mode == "transition":
            if self.trans_target == "app" and kind in ("down", "move", "up") and y >= TOP:
                self.held_events.append((kind, x, y))     # replayed when the app is open
        elif self.mode == "app":
            self.on_app(kind, x, y)
        elif self.mode == "launcher":
            if kind == "key":
                if y == 1 and x == KEY_HOME:
                    self.go_home()
                elif y == 1 and x == KEY_BACK and not self.carousel_is_home:
                    self.close_settings()
            elif not self.carousel_is_home and kind == "up" and y < TOP:
                self.close_settings()                 # tap the "< Settings" title to go back
            else:
                en = self.launcher.on_touch(kind, x, y, t, now)
                if en is not None:
                    if en.app is not None:
                        self.open_app(en.app, en)
                    elif en.opens == "settings":
                        self.open_settings()

    def on_power_key(self, pressed, now):
        """Short press: screen off. Long press (handled in frame()): power menu."""
        if pressed:
            self.power_down_t, self.power_handled = now, False
        elif self.power_down_t is not None:
            if not self.power_handled and self.mode != "power":
                self.asleep = True
            self.power_down_t = None

    def on_app(self, kind, x, y):
        if kind == "key" and y == 1 and x == KEY_HOME:
            self.go_home()
        elif (kind == "key" and y == 1 and x == KEY_BACK) or (kind == "up" and y < TOP):
            self.close_app()
        elif kind == "key":
            self.app.on_key(x, y == 1)
        elif kind in ("down", "move", "up"):
            self.app.touch(kind, x, y)

    def open_power_menu(self):
        if self.mode in ("launcher", "app"):
            visible = self.fb.pages[(self.page - 1) % NPAGES].copy()      # what is on screen now
            if self.mode == "launcher" and self.launcher.busy:
                self.launcher.reset_position()
            self.prev_mode, self.mode = self.mode, "power"
            self.menu = power.PowerMenu(visible, time.monotonic())
            self.shown["full"] = [None] * NPAGES

    def on_power_menu(self, kind, x, y):
        now = time.monotonic()
        if kind == "key":
            if y == 1 and x in (KEY_BACK, KEY_HOME):
                self.menu.cancel(now)
        else:
            self.menu.touch(kind, x, y, now)

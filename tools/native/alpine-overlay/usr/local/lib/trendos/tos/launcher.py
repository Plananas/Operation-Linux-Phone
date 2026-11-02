"""Launcher carousel: each entry is a spinning 3D object; swipe left/right between entries,
tap an entry's object to open its app. The first entry is the home cube: it just welcomes you
(no app, no label) and continues the boot animation's spin.
"""
import math

import numpy as np

from .config import (W, BAND, NPAGES, TOP, LABEL_Y, DOTS_Y, ACCENT, GREY, PALETTE, GREEN, ORANGE,
                     CYAN, K_BOOT, K_APP, BOOT_TILT, BOOT_W, FULL_RATES, APP_SWAY, APP_TILT, SWIPE_FRACTION, SWIPE_FLICK,
                     TAP_TIME, DRAG_START)
from .gfx import canvas, crop_columns, text_strip, to_rgbx, blit
from .render import make_cube, make_plus, make_settings, make_signal, matrix
from .apps import CalculatorApp, WifiApp


class Entry:
    def __init__(self, shape, colour, app=None, opens=None, name=None, phase=(0.0, 0.0, 0.0)):
        self.shape, self.colour, self.app, self.opens = shape, colour, app, opens
        self.a, self.b, self.c = phase       # home cube: tumble angles; apps: sway wave phases
        self.t = 0.0                         # apps: sway clock
        self.label = None
        text = name or (app.name if app is not None else None)
        if text is not None:
            self.label_x, self.label = crop_columns(text_strip(text, 22, colour, 26))

    def pose(self):
        """App icon orientation: a gentle sway about facing the viewer (never sideways)."""
        (ax, wx), (ay, wy), (az, wz) = APP_SWAY
        return (ax * math.sin(wx * self.t + self.a), ay * math.sin(wy * self.t + self.b),
                az * math.sin(wz * self.t + self.c))

    @property
    def actionable(self):
        return self.app is not None or self.opens is not None


def default_entries():
    return [
        Entry(make_cube(), PALETTE[GREEN]),                                         # home: welcome
        Entry(make_plus(), PALETTE[ORANGE], CalculatorApp(), phase=(0.6, 1.1, 0.3)),
        Entry(make_settings(), PALETTE[CYAN], opens="settings", name="Settings", phase=(0.3, 0.7, 0.2)),
    ]


def settings_entries():
    return [
        Entry(make_signal(), PALETTE[GREEN], WifiApp(), phase=(0.4, 0.9, 0.2)),
    ]


def _dots(n, cur):
    im, d = canvas(12)
    gap = 18; x0 = W / 2 - gap * (n - 1) / 2
    for i in range(n):
        cx = x0 + i * gap
        if i == cur:
            d.ellipse([cx - 4, 2, cx + 4, 10], fill=ACCENT)
        else:
            d.ellipse([cx - 3, 3, cx + 3, 9], outline=GREY)
    return to_rgbx(im)


def ease_out(x):
    return 1 - (1 - x) ** 3


class Launcher:
    FULL = [(0, BAND, 0, W)]

    def __init__(self, entries, start, is_home=True):
        self.entries = entries
        self.n = len(entries)
        self.is_home = is_home               # home: entry 0 continues the boot spin + blend
        self.dots = [_dots(self.n, i) for i in range(self.n)]
        self.cur, self.off = 0, 0.0          # off: carousel offset in px (+ = dragged right)
        self.snap = None                     # (from, to, t0, duration)
        self.touch = None
        self.start = start
        if is_home:
            entries[0].b = (BOOT_W * start) % (2 * math.pi)     # continue the boot spin exactly
        self.invalidate()

    @property
    def busy(self):
        return self.touch is not None or self.snap is not None

    def invalidate(self):
        """Next draws repaint the whole band on every page."""
        self.dirty = [self.FULL] * NPAGES    # per page: rects drawn there last time
        self.dots_shown = [None] * NPAGES

    def reset_position(self):
        self.off, self.snap, self.touch = 0.0, None, None

    # ---- input ----
    def on_touch(self, ev, x, y, t, now):
        """Returns the tapped Entry if it was a tap on an actionable entry, else None."""
        if ev == "down":
            self.touch = {"x0": x, "y0": y, "t0": t, "off0": self.off, "drag": False, "hist": [(t, x)]}
            self.snap = None
        elif ev == "move" and self.touch:
            tc = self.touch
            tc["hist"] = [(tt, xx) for tt, xx in tc["hist"] if t - tt < 0.1] + [(t, x)]
            if not tc["drag"] and abs(x - tc["x0"]) > DRAG_START:
                tc["drag"] = True
            if tc["drag"]:
                self.off = tc["off0"] + (x - tc["x0"])
        elif ev == "up" and self.touch:
            tc, self.touch = self.touch, None
            if not tc["drag"]:
                en = self.entries[self.cur]
                is_tap = t - tc["t0"] < TAP_TIME and TOP <= tc["y0"] < TOP + BAND and abs(self.off) < 1
                if is_tap and en.actionable:
                    return en
                self.snap = (self.off, 0.0, now, 0.25)
            else:
                h = tc["hist"]
                v = (h[-1][1] - h[0][1]) / max(h[-1][0] - h[0][0], 1e-3) if len(h) > 1 else 0
                if self.off > W * SWIPE_FRACTION or v > SWIPE_FLICK:
                    target = float(W)
                elif self.off < -W * SWIPE_FRACTION or v < -SWIPE_FLICK:
                    target = float(-W)
                else:
                    target = 0.0
                self.snap = (self.off, target, now, 0.28)
        return None

    def on_home(self, now):
        self.snap = (self.off, 0.0, now, 0.25)

    # ---- animation ----
    def update(self, now, dt, blend):
        """blend: 0 -> 1 over the first seconds (boot spin -> full tumble for the home cube)."""
        if self.snap:
            a0, a1, ta, dur = self.snap
            k = min(1.0, (now - ta) / dur)
            self.off = a0 + (a1 - a0) * ease_out(k)
            if k >= 1.0:
                if a1 >= W:
                    self.cur = (self.cur - 1) % self.n
                elif a1 <= -W:
                    self.cur = (self.cur + 1) % self.n
                self.off, self.snap = 0.0, None
        rx, ry, rz = FULL_RATES
        for i, en in enumerate(self.entries):
            if i == 0 and self.is_home:
                en.a += dt * blend * rx
                en.b += dt * ((1 - blend) * BOOT_W + blend * ry)
                en.c += dt * blend * rz
            else:
                en.t += dt

    # ---- drawing ----
    def _render_entries(self, band, renderer, blend):
        """Render the visible entrie(s) + labels into a band array. Returns the touched rects."""
        visible = [(self.cur, self.off)]
        if self.off > 0:
            visible.append(((self.cur - 1) % self.n, self.off - W))
        elif self.off < 0:
            visible.append(((self.cur + 1) % self.n, self.off + W))
        rects = []
        for idx, dx in visible:
            en = self.entries[idx]
            home = idx == 0 and self.is_home
            if home:
                m = matrix(BOOT_TILT * (1 - blend), en.a, en.b, en.c)
                k = K_BOOT + (K_APP - K_BOOT) * blend
            else:
                m = matrix(APP_TILT, *en.pose())
                k = K_APP
            rects.append(renderer.draw(band, en.shape, m, k, dx))
            if en.label is not None:
                rects.append(blit(band, en.label, LABEL_Y, dx + en.label_x))
        return [r for r in rects if r[1] > r[0] and r[3] > r[2]]

    def draw(self, buf, page, renderer, blend):
        """Draw into framebuffer page `page` (off screen): erase what was drawn there last time,
        render the visible object(s) + labels, update the dots if needed."""
        band = buf[TOP:TOP + BAND]
        for y0, y1, x0, x1 in self.dirty[page]:
            band[y0:y1, x0:x1] = 0
        self.dirty[page] = self._render_entries(band, renderer, blend)
        if self.dots_shown[page] != self.cur:
            band[DOTS_Y:DOTS_Y + 12] = self.dots[self.cur]
            self.dots_shown[page] = self.cur

    def render_band(self, renderer, blend=1.0):
        """A fresh band image of the current frame (no page/dirty state) for slide snapshots."""
        band = np.zeros((BAND, W, 4), np.uint8)
        self._render_entries(band, renderer, blend)
        band[DOTS_Y:DOTS_Y + 12] = self.dots[self.cur]
        return band

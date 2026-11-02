"""Launcher carousel: each entry is a spinning 3D object; swipe left/right between entries,
tap an entry's object to open its app. The first entry is the home cube: it just welcomes you
(no app, no label) and continues the boot animation's spin.
"""
import math

import numpy as np

from .config import (W, BAND, NPAGES, TOP, LABEL_Y, DOTS_Y, ACCENT, GREY, PALETTE, GREEN, ORANGE,
                     K_BOOT, K_APP, BOOT_TILT, BOOT_W, FULL_RATES, SWIPE_FRACTION, SWIPE_FLICK,
                     TAP_TIME, DRAG_START)
from .gfx import canvas, crop_columns, text_strip, to_rgbx, blit
from .render import make_cube, make_plus, matrix
from .apps import CalculatorApp


class Entry:
    def __init__(self, shape, colour, app=None, phase=(0.0, 0.0, 0.0), label=True):
        self.shape, self.colour, self.app = shape, colour, app
        self.a, self.b, self.c = phase
        self.label = None
        if app is not None and label:
            self.label_x, self.label = crop_columns(text_strip(app.name, 22, colour, 26))


def default_entries():
    return [
        Entry(make_cube(), PALETTE[GREEN]),                                         # home: no app
        Entry(make_plus(), PALETTE[ORANGE], CalculatorApp(), phase=(0.6, 1.1, 0.3)),
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

    def __init__(self, entries, start):
        self.entries = entries
        self.n = len(entries)
        self.dots = [_dots(self.n, i) for i in range(self.n)]
        self.cur, self.off = 0, 0.0          # off: carousel offset in px (+ = dragged right)
        self.snap = None                     # (from, to, t0, duration)
        self.touch = None
        self.start = start
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
        """Returns the app to open (tap on an entry that has one), else None."""
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
                app = self.entries[self.cur].app
                is_tap = t - tc["t0"] < TAP_TIME and TOP <= tc["y0"] < TOP + BAND and abs(self.off) < 1
                if is_tap and app is not None:
                    return app
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
            if i == 0:
                en.a += dt * blend * rx
                en.b += dt * ((1 - blend) * BOOT_W + blend * ry)
                en.c += dt * blend * rz
            else:
                en.a += dt * rx; en.b += dt * ry; en.c += dt * rz

    # ---- drawing ----
    def draw(self, buf, page, renderer, blend):
        """Draw into framebuffer page `page` (off screen): erase what was drawn there last time,
        render the visible object(s) + labels, update the dots if needed."""
        band = buf[TOP:TOP + BAND]
        for y0, y1, x0, x1 in self.dirty[page]:
            band[y0:y1, x0:x1] = 0
        visible = [(self.cur, self.off)]
        if self.off > 0:
            visible.append(((self.cur - 1) % self.n, self.off - W))
        elif self.off < 0:
            visible.append(((self.cur + 1) % self.n, self.off + W))
        rects = []
        for idx, dx in visible:
            en = self.entries[idx]
            home = idx == 0
            tilt = BOOT_TILT * (1 - blend) if home else 0.0
            k = K_BOOT + (K_APP - K_BOOT) * blend if home else K_APP
            rects.append(renderer.draw(band, en.shape, matrix(tilt, en.a, en.b, en.c), k, dx))
            if en.label is not None:
                rects.append(blit(band, en.label, LABEL_Y, dx + en.label_x))
        self.dirty[page] = [r for r in rects if r[1] > r[0] and r[3] > r[2]]
        if self.dots_shown[page] != self.cur:
            band[DOTS_Y:DOTS_Y + 12] = self.dots[self.cur]
            self.dots_shown[page] = self.cur

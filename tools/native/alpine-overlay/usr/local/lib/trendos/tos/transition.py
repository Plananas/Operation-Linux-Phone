"""Screen transitions (opening / closing an app).

Opening: the screen behind (a snapshot) dims while the new screen fades in and slides up.
Closing: the same in reverse. Each frame is one pass of native.slide (dim the
back + fade the shifted front in), drawn straight into the framebuffer page.
"""
from . import native

OPEN_T, CLOSE_T = 0.32, 0.24
SLIDE = 48                         # px the foreground slides
DIM = 0.15                         # background brightness at the end of the transition


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


class Slide:
    def __init__(self, back, front, now, opening=True, live_fn=None, live_side=None,
                 overlay=None):
        """back: frame behind; front: frame sliding in/out. If live_fn(now) is given it re-renders
        one side each frame (live_side "front" or "back") so that side keeps animating.
        overlay(buf, e, now) draws on top of each frame; e = how far the front is in (0..1),
        e.g. the launcher object flying to the app's badge (tos/flight.py)."""
        self.back, self.front = back, front
        self.t0, self.opening = now, opening
        self.dur = OPEN_T if opening else CLOSE_T
        self.live_fn, self.live_side = live_fn, live_side
        self.overlay = overlay

    def done(self, now):
        return now - self.t0 >= self.dur

    def key(self, now):
        return round(now - self.t0, 3)

    def draw(self, buf, now):
        k = min(1.0, (now - self.t0) / self.dur)
        e = _ease(k) if self.opening else 1 - _ease(k)      # 0 = only back, 1 = only front
        back, front = self.back, self.front
        if self.live_fn is not None:
            live = self.live_fn(now)
            if self.live_side == "front":
                front = live
            else:
                back = live
        if e >= 0.99:
            buf[:] = front
        else:
            native.slide(buf, back, front, int(SLIDE * (1 - e)), 1 - (1 - DIM) * e, e)
        if self.overlay is not None:
            self.overlay(buf, e, now)

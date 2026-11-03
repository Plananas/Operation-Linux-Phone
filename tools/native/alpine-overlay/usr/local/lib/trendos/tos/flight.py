"""The launcher object flying into / out of an app's title-bar badge (every app, automatically).

Opening an app: the carousel object shrinks and arcs up to the badge spot in the top-right
corner while the app slides in, landing exactly on the badge's own spinning pose; closing plays
it in reverse. Shell.start_transition draws it over the Slide each frame (overlay).

Size changes smoothly: the 3D renderer draws ASCII character cells, so the flight steps through
a ladder of cell sizes (8x12 -> 7x10 -> 6x9 -> 5x7 px) as well as the projection scale - the
characters themselves shrink with the object instead of the object turning into a few big cells.
"""
import math

import numpy as np

from .config import W, TOP, BAND, COLS, ROWS, CW, CH, APP_TILT, K_APP
from .render import TILES, MINI, MINI_CW, MINI_CH, make_tiles, matrix


def _brighter(t, f):
    return np.minimum(255, t.astype(np.uint16) * f).astype(np.uint8)


# (cell w, cell h, atlas): brightness rises towards the small cells like the badge's MINI atlas
LADDER = [(CW, CH, TILES),
          (7, 10, _brighter(make_tiles(7, 10, 10), 1.15)),
          (6, 9, _brighter(make_tiles(6, 9, 9, offset=(0, -1)), 1.3)),
          (MINI_CW, MINI_CH, MINI)]

# the badge (keep in step with Shell.draw_badge)
BADGE_COLS, BADGE_ROWS, BADGE_K = 13, 9, 13 * 1.45
BADGE_X, BADGE_Y = W - 14 - BADGE_COLS * MINI_CW, 2


def badge_angles(now):
    """Pose angles (tilt, a, b, c) of the spinning title-bar badge at time now."""
    return (0.32, 0.0, 1.1 * now, 0.12 * math.sin(0.7 * now))


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


class Flight:
    def __init__(self, shape, carousel_pose, renderer):
        """carousel_pose() -> (tilt, a, b, c) of the object in the carousel now (it keeps
        swaying while the app slides out, so closing lands on its live pose)."""
        self.shape, self.r = shape, renderer
        self.pose0 = carousel_pose
        # sizes in px per unit of projection (K * cell width), centres in screen px
        self.s0, self.s1 = K_APP * CW, BADGE_K * MINI_CW
        self.c0 = (W / 2, TOP + ROWS * CH / 2)
        self.c1 = (BADGE_X + BADGE_COLS * MINI_CW / 2, BADGE_Y + BADGE_ROWS * MINI_CH / 2)

    def rect(self):
        """Screen rect (y0, y1, x0, x1) of the object at its carousel start (to cut it out of
        the launcher snapshot)."""
        band = np.zeros((ROWS * CH, COLS * CW, 4), np.uint8)
        y0, y1, x0, x1 = self.r.draw(band, self.shape, matrix(*self.pose0()), K_APP, 0)
        return (TOP + y0, TOP + y1, x0, x1)

    def draw(self, buf, p, now):
        """Draw the object at flight progress p (0 = carousel, 1 = badge) into buf (full frame)."""
        p = min(1.0, max(0.0, p))
        q = _smooth(p)
        # size: geometric interpolation reads as a steady shrink
        s = self.s0 * (self.s1 / self.s0) ** q
        # cell size from the ladder, by where s sits between the two ends (log scale)
        f = math.log(self.s0 / s) / math.log(self.s0 / self.s1) if self.s0 != self.s1 else 1.0
        level = min(len(LADDER) - 1, int(round(f * (len(LADDER) - 1))))
        cw, ch, atlas = LADDER[level]
        K = s / cw
        # path: a gentle arc (x leads, y follows) from the carousel centre to the badge
        cx = self.c0[0] + (self.c1[0] - self.c0[0]) * _smooth(min(1.0, p * 1.15))
        cy = self.c0[1] + (self.c1[1] - self.c0[1]) * q ** 1.25
        # pose: from the carousel pose to the badge's live pose (spin unwrapped to the nearest turn)
        a0, a1 = self.pose0(), list(badge_angles(now))
        a1[2] += 2 * math.pi * round((a0[2] - a1[2]) / (2 * math.pi))
        ang = [x0 + (x1 - x0) * q for x0, x1 in zip(a0, a1)]
        # viewport just big enough for the object (+-1.3 units at the camera distance)
        half = 0.48 * s
        cols, rows = max(2, int(2 * half / cw) + 2), max(2, int(2 * half / ch) + 2)
        # grid parity of the ends: the carousel's 60 x 44 grid is even, the 13 x 9 badge odd, so
        # the first and last frames land on exactly the same character cells (no jump)
        want = 0 if level == 0 else 1
        cols += (cols - want) % 2
        rows += (rows - want) % 2
        x, y = int(round(cx - cols * cw / 2)), int(round(cy - rows * ch / 2))
        self.r.view(buf, self.shape, matrix(*ang), K, cols, rows, x, y, atlas, cw, ch)


def carousel_angles(entry):
    """Pose angles of a launcher Entry as the carousel draws it."""
    return (APP_TILT,) + tuple(entry.pose())

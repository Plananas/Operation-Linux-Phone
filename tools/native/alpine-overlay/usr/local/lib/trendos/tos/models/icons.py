"""The launcher's 3D icons. Each one is a function returning a Shape, registered by name with
@model(name, colour). Objects should fit in about [-1.3, 1.3] on x/y to match the others; keep
them fairly flat-fronted so they read well while swaying.
"""
import math

import numpy as np

from ..config import RED, GREEN, BLUE, YELLOW, MAGENTA, CYAN, ORANGE, WHITE, SPOTIFY
from .registry import model
from .shape import Shape, arc, boxes, extrude, relief


@model("cube", GREEN)
def cube(n=36):
    """Home: unit cube (half-size 1), faces coloured PALETTE[0..5]. Same face order and sampling
    as the boot animation frames, so the boot handover is seamless: don't change it without
    rebuilding the ramdisk's bootanim."""
    u = (np.arange(n) + 0.5) / n * 2 - 1
    gu, gv = np.meshgrid(u, u)
    faces = []
    for axis in range(3):
        for sign in (-1, 1):
            p = np.zeros((n * n, 3), np.float32)
            p[:, axis] = sign
            p[:, (axis + 1) % 3] = gu.ravel()
            p[:, (axis + 2) % 3] = gv.ravel()
            nv = np.zeros(3, np.float32); nv[axis] = sign
            faces.append((p, nv, len(faces)))
    return Shape.from_faces(faces)


@model("plus", ORANGE)
def plus():
    """Calculator: two crossed bars. x faces yellow, y faces white, z faces orange."""
    return boxes([((0, 0, 0), (1.3, 0.42, 0.42)), ((0, 0, 0), (0.42, 1.3, 0.42))],
                 colour_by_axis=(YELLOW, WHITE, ORANGE))


@model("settings", CYAN)
def settings():
    """Settings: three stacked horizontal bars (like sliders)."""
    return boxes([((0, y, 0), (1.0, 0.17, 0.22)) for y in (0.62, 0.0, -0.62)],
                 colour_by_axis=(CYAN, CYAN, CYAN))


@model("signal", GREEN)
def signal():
    """Wi-Fi: four vertical bars of increasing height, bottoms aligned at y = -1.05."""
    return boxes([((x, hy - 1.05, 0), (0.18, hy, 0.20))
                  for x, hy in ((-0.93, 0.30), (-0.31, 0.55), (0.31, 0.80), (0.93, 1.05))],
                 colour_by_axis=(GREEN, GREEN, GREEN))


# Spotify logo arcs on a unit disc: (apex y, half width, sagitta, thickness), top to bottom.
# Thicker than the real logo: at this resolution the true proportions are one character tall.
_SPOTIFY_ARCS = ((0.44, 0.66, 0.22, 0.26), (0.06, 0.56, 0.17, 0.22), (-0.30, 0.46, 0.13, 0.18))
_SPOTIFY_TILT = -0.10                   # arcs droop slightly to the right, like the logo


@model("spotify", SPOTIFY)
def spotify(radius=1.2, depth=0.17, slot_walls=False):
    """Spotify: a green coin with the three arcs cut right through it, so the background shows
    through as the black arcs. Slot walls are off by default: at this resolution their dim
    shading fills the arcs in, and clean cut-outs read much better."""
    ct, st = math.cos(_SPOTIFY_TILT), math.sin(_SPOTIFY_TILT)
    arcs = []                           # (centre x, centre y, r, half-thickness, end angles lo, hi)
    for apex, w, s, t in _SPOTIFY_ARCS:
        r = (w * w + s * s) / (2 * s)
        half = math.asin(w / r)
        arcs.append((0.0, apex - r, r, t / 2, math.pi / 2 - half, math.pi / 2 + half))

    def in_slot(x, y):                  # unit logo frame
        for cx, cy, r, h, a0, a1 in arcs:
            if a0 <= math.atan2(y - cy, x - cx) <= a1 and abs(math.hypot(x - cx, y - cy) - r) < h:
                return True
            if any(math.hypot(x - cx - r * math.cos(a), y - cy - r * math.sin(a)) < h for a in (a0, a1)):
                return True             # round caps
        return False

    def inside(x, y):                   # object frame -> unit logo frame (undo scale + tilt)
        x, y = x / radius, y / radius
        return x * x + y * y <= 1 and not in_slot(ct * x + st * y, -st * x + ct * y)

    def to_object(path):
        return [((ct * x - st * y) * radius, (st * x + ct * y) * radius) for x, y in path]

    outlines = [arc(0, 0, radius, 0, 2 * math.pi)]                  # rim, counter-clockwise
    if slot_walls:
        for cx, cy, r, h, a0, a1 in arcs:                          # each slot is a hole: clockwise
            e0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
            e1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
            loop = (arc(cx, cy, r + h, a1, a0) + arc(*e0, h, a0, a0 - math.pi) +
                    arc(cx, cy, r - h, a0, a1) + arc(*e1, h, a1 + math.pi, a1))
            outlines.append(to_object(loop))
    return extrude(inside, outlines, depth, SPOTIFY, extent=radius)


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from (px, py) to the segment a-b."""
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


@model("radio", MAGENTA)
def radio(depth=0.2):
    """Radio: a broadcast mast (A-frame with one brace and a ground plate) topped by a red
    beacon, with two radio waves arcing out on each side of it."""
    top, foot, half_base = 0.38, -1.2, 0.62        # mast apex, ground, half-width at the base
    bx, by, br = 0.0, 0.6, 0.2                     # beacon ball
    waves = ((0.52, 0.11), (0.98, 0.11))           # (radius, half-thickness) around the beacon
    spread = 0.58                                  # wave half-angle (rad) either side of horizontal

    def leg_x(y):                                  # |x| of the legs at height y
        return half_base * (top - y) / (top - foot)

    def colour_at(x, y):
        if math.hypot(x - bx, y - by) < br:
            return RED                             # beacon
        r = math.hypot(x - bx, y - by)
        a = math.atan2(y - by, abs(x - bx))       # angle from horizontal, mirrored left/right
        for wr, wt in waves:
            if abs(r - wr) < wt and abs(a) < spread:
                return YELLOW
            for s in (-1, 1):                      # round caps at the wave ends
                cx, cy = wr * math.cos(spread), by + s * wr * math.sin(spread)
                if math.hypot(abs(x - bx) - cx, y - cy) < wt:
                    return YELLOW
        if foot <= y <= top + 0.04:
            if any(_seg_dist(x, y, 0, top, s * half_base, foot) < 0.095 for s in (-1, 1)):
                return MAGENTA                     # legs
            if abs(y + 0.45) < 0.07 and abs(x) < leg_x(-0.45):
                return MAGENTA                     # brace
            if abs(y - foot) < 0.06 and abs(x) < half_base + 0.12:
                return MAGENTA                     # ground plate
        if abs(x) < 0.07 and top <= y <= by - br + 0.02:
            return MAGENTA                         # neck up to the beacon
        return None

    scale, lift = 1.08, 0.05                       # fill the icon box like the others
    return relief(lambda x, y: colour_at(x / scale, (y - lift) / scale), depth, extent=1.35)

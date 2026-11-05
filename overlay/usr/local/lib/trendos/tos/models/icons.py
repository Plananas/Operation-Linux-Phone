"""The launcher's 3D icons. Each one is a function returning a Shape, registered by name with
@model(name, colour). Objects should fit in about [-1.3, 1.3] on x/y to match the others; keep
them fairly flat-fronted so they read well while swaying.
"""
import functools
import math

import numpy as np

from ..config import RED, GREEN, BLUE, YELLOW, MAGENTA, CYAN, ORANGE, WHITE, SPOTIFY
from .registry import model
from .shape import DENSITY, Shape, arc, boxes, extrude, relief


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


@model("music", MAGENTA)
def music():
    """Music: two beamed notes."""
    return boxes([((-0.95, -0.82, 0), (0.42, 0.30, 0.24)), ((0.60, -0.62, 0), (0.42, 0.30, 0.24)),
                  ((-0.65, 0.14, 0), (0.12, 0.92, 0.20)), ((0.90, 0.34, 0), (0.12, 0.92, 0.20)),
                  ((0.125, 1.02, 0), (0.895, 0.22, 0.20))],
                 colour_by_axis=(MAGENTA, WHITE, MAGENTA))


@model("folder", YELLOW)
def folder():
    """Files: an open folder, in layers so that it reads at this resolution. A darker back with its
    tab on the left, a white page with lines of text standing out of it on the right, and a bright
    front flap that leans out towards the bottom."""
    def back(x, y):
        in_body = abs(x) <= 1.12 and -0.7 <= y <= 0.5
        in_tab = -1.12 <= x <= -0.3 and 0.5 < y <= 0.86
        return ORANGE if in_body or in_tab else None

    def page(x, y):
        in_line = (0.66 <= y <= 0.8 or 0.34 <= y <= 0.48) and -0.02 <= x <= 0.72
        return None if in_line or not (-0.18 <= x <= 0.92 and -0.5 <= y <= 1.0) else WHITE

    def flap(x, y):
        half_width = 1.3 - 0.22 * (y + 0.95) / 1.1         # narrower at the top edge
        return YELLOW if abs(x) <= half_width and -0.95 <= y <= 0.15 else None

    return Shape.combine(relief(back, 0.09).transformed(t=(0, 0, 0.22)),
                         relief(page, 0.03).transformed(t=(0, 0, 0.05)),
                         relief(flap, 0.09).transformed(t=(0, 0, -0.14)))


# The world on a rough 36 x 18 grid, north at the top and the date line at the edges: # is land.
_WORLD = ("                                    ",
          "                ######  ###         ",
          "    ########    ###    #  ######### ",
          "  ###########  ##     ############# ",
          "   #########         ###############",
          "     #######        ##############  ",
          "      #####         ###############  ",
          "       ###         ##############   ",
          "        ##         ####### #### #   ",
          "         ###       #######  ## #    ",
          "          ####      ######     ##   ",
          "          #####     #####     ###   ",
          "          ####       ####    ####   ",
          "          ###        ###      ###   ",
          "          ##                     #  ",
          "          #                         ",
          "                                    ",
          "      ###########################   ")
_WORLD_FRONT = 22                       # the column that faces the viewer: Africa and Europe, not the Pacific


@model("globe", BLUE)
def globe(radius=1.25, lats=18, lons=36):
    """Web: the world, turning. One flat face per patch of the sphere, each with its own normal, so the light
    falls across it properly: green land and blue sea."""
    faces = []
    for j in range(lats):
        for i in range(lons):
            lat0, lat1 = math.pi * (0.5 - j / lats), math.pi * (0.5 - (j + 1) / lats)
            lon0, lon1 = 2 * math.pi * i / lons, 2 * math.pi * (i + 1) / lons
            mid_lat, mid_lon = (lat0 + lat1) / 2, (lon0 + lon1) / 2
            width = abs(lon1 - lon0) * math.cos(mid_lat) * radius
            nu = max(1, int(width * DENSITY * 1.2))
            nv = max(1, int(abs(lat1 - lat0) * radius * DENSITY * 1.2))
            pts = []
            for v in range(nv):
                for u in range(nu):
                    lat = lat0 + (lat1 - lat0) * (v + 0.5) / nv
                    lon = lon0 + (lon1 - lon0) * (u + 0.5) / nu
                    pts.append((radius * math.cos(lat) * math.sin(lon), radius * math.sin(lat),
                                -radius * math.cos(lat) * math.cos(lon)))
            normal = (math.cos(mid_lat) * math.sin(mid_lon), math.sin(mid_lat), -math.cos(mid_lat) * math.cos(mid_lon))
            row = _WORLD[j]
            column = (i + _WORLD_FRONT) % lons
            land = column < len(row) and row[column] == "#"
            faces.append((pts, normal, GREEN if land else BLUE))
    return Shape.from_faces(faces)


# Blip, the chat's mascot: a round head, built from real curved surfaces so that it shades like a ball and its parts
# move against each other as it turns. Only what can face the viewer is built, since it never turns far.
_BLIP_HEAD_Y = -0.16
_BLIP_EYE = (0.38, 0.28, 0.2, 0.36)                    # across, up, half width, half height, in radians around the head
_BLIP_MOUTH_UP = -0.4
_BLIP_MOUTHS = {"small": (0.3, 0.13), "mid": (0.4, 0.25), "wide": (0.48, 0.38)}   # half width, half height


@functools.lru_cache(maxsize=None)
def _ball_grid(radius, lats, lons, facing):
    """The surface points of a sphere as unit normals, the patch each belongs to, and each patch's normal. Patches turned
    further than `facing` (a z component) from the viewer are left out."""
    points, patches, normals = [], [], []
    per_unit = DENSITY * 1.25
    for j in range(lats):
        for i in range(lons):
            lat0, lat1 = math.pi * (0.5 - j / lats), math.pi * (0.5 - (j + 1) / lats)
            lon0, lon1 = 2 * math.pi * (i / lons - 0.5), 2 * math.pi * ((i + 1) / lons - 0.5)
            mid_lat, mid_lon = (lat0 + lat1) / 2, (lon0 + lon1) / 2
            normal = (math.cos(mid_lat) * math.sin(mid_lon), math.sin(mid_lat), -math.cos(mid_lat) * math.cos(mid_lon))
            if normal[2] > facing:
                continue
            nu = max(1, int((lon1 - lon0) * math.cos(mid_lat) * radius * per_unit))
            nv = max(1, int((lat0 - lat1) * radius * per_unit))
            lat, lon = np.meshgrid(lat0 + (lat1 - lat0) * (np.arange(nv) + 0.5) / nv, lon0 + (lon1 - lon0) * (np.arange(nu) + 0.5) / nu)
            points.append(np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), -np.cos(lat) * np.cos(lon)], -1).reshape(-1, 3))
            patches.append(np.full(nu * nv, len(normals)))
            normals.append(normal)
    return np.concatenate(points), np.concatenate(patches), normals


def _ball(centre, radius, colours, grid):
    """Faces of a sphere, one per patch and colour. colours(n) takes unit normals (k, 3) and gives each a palette index,
    or -1 for a hole. All at once, on a shared grid, because building these is the slow part of starting the mascot."""
    n, patch, normals = grid
    col = colours(n)
    keep = col >= 0
    n, patch, col = n[keep], patch[keep], col[keep]
    key = patch * 16 + col
    order = np.argsort(key, kind="stable")
    n, key = n[order], key[order]
    starts = np.concatenate([[0], np.flatnonzero(key[1:] != key[:-1]) + 1, [len(key)]])
    return [(n[a:b] * radius + centre, normals[key[a] // 16], int(key[a] % 16)) for a, b in zip(starts[:-1], starts[1:])]


_BLIP_HEAD_GRID = (1.0, 16, 32, 0.5)
def _around(n):
    """Unit normals as (across, up) angles from the front of the head."""
    return np.arctan2(n[:, 0], -n[:, 2]), np.arcsin(np.clip(n[:, 1], -1, 1))


def _blip_mouth(across, up, mouth):
    """Which points of the head are the mouth's opening. Shut, it's a smile: a thin curve."""
    if mouth in ("smile", "grin"):
        half_w, thick, curve = (0.5, 0.1, 0.7) if mouth == "smile" else (0.56, 0.17, 0.8)
        return (abs(across) < half_w) & (abs(up - _BLIP_MOUTH_UP - curve * across ** 2 + 0.06) < thick)
    half_w, half_h = _BLIP_MOUTHS[mouth]
    return (across / half_w) ** 2 + ((up - _BLIP_MOUTH_UP) / half_h) ** 2 < 1


def _blip_eyes(across, up, look):
    """(holes, glints) in the head: dark ovals, cut into the surface so they slide round it as the head turns, each with
    a spot of light. They're the whole of its expression, and solid shapes are what still read at a few characters."""
    eye_across, eye_up, half_w, half_h = _BLIP_EYE
    holes, glints = np.zeros(len(across), bool), np.zeros(len(across), bool)
    shift = 0.12 if look == "aside" else 0.0
    for side in (-1, 1):
        x, y = across - side * eye_across - shift, up - eye_up
        if look == "shut":
            holes |= (abs(x) < half_w * 1.25) & (abs(y) < 0.05)
        else:
            holes |= (x / half_w) ** 2 + (y / half_h) ** 2 < 1
            glints |= (x + 0.06) ** 2 + (y - 0.15) ** 2 < 0.09 ** 2
    return holes, glints


@functools.lru_cache(maxsize=None)
def _blip_head(look, mouth):
    centre = np.array((0.0, _BLIP_HEAD_Y, 0.0))

    def skin(n):
        across, up = _around(n)
        col = np.full(len(n), GREEN)
        holes, glints = _blip_eyes(across, up, look)
        col[holes | _blip_mouth(across, up, mouth)] = -1
        col[glints] = WHITE
        return col

    faces = _ball(centre, 1.0, skin, _ball_grid(*_BLIP_HEAD_GRID))
    if mouth == "wide":                                # a tongue, further in, so the mouth has depth
        def tongue(n):
            across, up = _around(n)
            half_w, half_h = _BLIP_MOUTHS[mouth]
            inside = (across / half_w) ** 2 + ((up - _BLIP_MOUTH_UP) / half_h) ** 2 < 1.3
            return np.where(inside & (up < _BLIP_MOUTH_UP - half_h * 0.45), RED, -1)
        faces += _ball(centre, 0.86, tongue, _ball_grid(*_BLIP_HEAD_GRID))
    return faces


@functools.lru_cache(maxsize=None)
def _blip_antenna():
    faces = []
    for k in range(10):                                # the stalk: a thin tube
        a = 2 * math.pi * k / 10
        n = (math.sin(a), 0.0, -math.cos(a))
        ys = np.linspace(0.8, 0.95, 4)
        faces.append((np.array([(n[0] * 0.05, y, n[2] * 0.05) for y in ys], np.float32), n, WHITE))
    faces += _ball(np.array((0.0, 1.02, 0.0)), 0.13, lambda n: np.full(len(n), YELLOW), _ball_grid(0.13, 8, 16, 0.8))
    return faces


MASCOT_POSES = []                       # in the order of TR_WEB_MASCOT_* in trend/apps/web.h


def _mascot_pose(name, look, mouth):
    model(name, GREEN)(lambda: Shape.from_faces(_blip_head(look, mouth) + _blip_antenna()))
    MASCOT_POSES.append(name)


_mascot_pose("mascot_idle", "ahead", "smile")
_mascot_pose("mascot_blink", "shut", "smile")
_mascot_pose("mascot_talk", "ahead", "small")
_mascot_pose("mascot_talk_mid", "ahead", "mid")
_mascot_pose("mascot_talk_wide", "ahead", "wide")
_mascot_pose("mascot_think", "aside", "small")
_mascot_pose("mascot_hello", "ahead", "grin")


@model("utilities", CYAN)
def utilities():
    """Utilities: three stacked horizontal bars (like sliders)."""
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


_CLOCK_R_OUT, _CLOCK_R_IN = 1.25, 1.0


def clock_face(depth=0.18):
    """Blue ring with four white hour marks and a white centre boss (no hands)."""
    def colour_at(x, y):
        r = math.hypot(x, y)
        if _CLOCK_R_IN <= r <= _CLOCK_R_OUT:
            return BLUE
        if r > _CLOCK_R_OUT:
            return None
        if r < 0.16:
            return WHITE
        a = math.atan2(y, x)
        for k in range(4):                                         # marks at 12, 3, 6, 9
            ka = k * math.pi / 2
            if _CLOCK_R_IN - 0.24 <= r < _CLOCK_R_IN and abs(math.sin(a - ka)) * r < 0.08 and math.cos(a - ka) > 0:
                return WHITE
        return None
    return relief(colour_at, depth, extent=_CLOCK_R_OUT)


def _hand(angle, length, half_w, z, colour):
    """A clock hand: a thin box from the centre to `length`, turned `angle` radians clockwise
    from 12 o'clock, sitting at depth z (negative = in front of the face)."""
    b = boxes([((0, length / 2, z), (half_w, length / 2, 0.06))], colour_by_axis=(colour, colour, colour))
    c, s = math.cos(-angle), math.sin(-angle)
    return b.transformed([[c, -s, 0], [s, c, 0], [0, 0, 1]])


CLOCK_HANDS = [(0.55, 0.10, -0.22, WHITE), (0.86, 0.07, -0.30, WHITE), (0.92, 0.035, -0.38, RED)]
                                            # hour, minute, second: (length, half width, z, colour)


def hand_angles(h, m, s=0.0):
    """Clockwise angles from 12 o'clock (radians) of the hour, minute and second hands."""
    return ((h % 12 + m / 60) / 12 * 2 * math.pi, (m + s / 60) / 60 * 2 * math.pi, s / 60 * 2 * math.pi)


def clock_hands(h, m, s=None):
    """Hour, minute (white) and optional second (red) hands for the time h:m:s (s may be
    fractional for a sweeping second hand)."""
    angles = hand_angles(h, m, s or 0.0)
    n = 3 if s is not None else 2
    return Shape.combine(*[_hand(a, *spec) for a, spec in zip(angles[:n], CLOCK_HANDS[:n])])


@model("clock", BLUE)
def clock():
    """Clock icon: the 3D clock face at ten past ten (the classic watch-advert pose). The Clock
    app builds the same face with the real time (clock_face + clock_hands)."""
    return Shape.combine(clock_face(), clock_hands(10, 10))


# Bluetooth rune: the vertical stroke plus two arrowheads (polyline vertices, unit height ~2)
_BT_RUNE = [[(-0.42, 0.40), (0.42, -0.40), (0.0, -0.82), (0.0, 0.82), (0.42, 0.40), (-0.42, -0.40)]]


@model("bluetooth", BLUE)
def bluetooth(depth=0.16):
    """Bluetooth: a blue oval with the white rune standing proud of its face, like the logo."""
    rx, ry = 0.82, 1.22

    def on_rune(x, y, w):
        return any(_seg_dist(x, y, ax, ay, bx, by) < w
                   for path in _BT_RUNE for (ax, ay), (bx, by) in zip(path, path[1:]))
    oval = relief(lambda x, y: BLUE if (x / rx) ** 2 + (y / ry) ** 2 <= 1 else None, depth, extent=1.25)
    rune = relief(lambda x, y: WHITE if on_rune(x, y, 0.11) else None, 0.07, extent=1.0)
    return Shape.combine(oval, rune.transformed(t=(0, 0, -(depth + 0.07))))


# Terminal prompt ">_": polylines in the screen's plane
_PROMPT = [[(-0.78, 0.5), (-0.1, 0.0), (-0.78, -0.5)], [(0.12, -0.52), (0.82, -0.52)]]


@model("terminal", GREEN)
def terminal(depth=0.18):
    """SSH: a green terminal screen with a ">_" prompt cut right through it, so the background
    shows through (raised glyphs get lost at this resolution; clean cut-outs read better)."""
    rx, ry, r = 1.25, 1.0, 0.2

    def on_screen(x, y):
        dx, dy = max(abs(x) - (rx - r), 0.0), max(abs(y) - (ry - r), 0.0)
        return dx * dx + dy * dy <= r * r

    def on_prompt(x, y):
        return any(_seg_dist(x, y, ax, ay, bx, by) < 0.17
                   for path in _PROMPT for (ax, ay), (bx, by) in zip(path, path[1:]))
    return relief(lambda x, y: GREEN if on_screen(x, y) and not on_prompt(x, y) else None, depth)

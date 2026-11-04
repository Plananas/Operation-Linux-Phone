"""ASCII-shaded 3D rendering (the objects themselves live in tos/models).

Every (palette colour, shade character) pair is pre-rendered once as an RGBX tile. A frame is a
ROWS x COLS grid of tile indices (0 = empty): rotate, perspective-correct back-face cull,
project, z-buffer, point-light shade. libtrend (native/libtrend/src/mesh.c) does this and copies
the tiles straight into the target buffer; this module holds the atlases and the poses.
"""
import math

import numpy as np
from PIL import Image, ImageDraw

from . import native
from .config import (CW, CH, COLS, ROWS, NS, SHADES, PALETTE, LIGHT, CAM_Z, ASPECT, K_BOOT,
                     FONT_PX, BOOT_TILT, BOOT_W)
from .gfx import art_font

# ---- tile atlas: tiles[colour * NS + shade] = CH x CW x 4 RGBX --------------------------
def make_tiles(cw=CW, ch=CH, font_px=FONT_PX, bg_rows=None, offset=(1, -1)):
    """Tile atlas [colour * NS + shade] of cw x ch RGBX character cells. bg_rows = optional
    (ch, 3) colour per pixel row drawn behind the glyphs (e.g. a card's panel + scanlines, so
    3D objects sit on cards without black boxes); cells are max(background, glyph)."""
    t = np.zeros((len(PALETTE) * NS, ch, cw, 4), np.uint8)
    f = art_font(font_px)
    for s, c in enumerate(SHADES):
        g = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(g).text(offset, c, fill=255, font=f)
        mask = np.asarray(g, np.float32)[..., None] / 255.0
        bright = 0.35 + 0.65 * (s / (NS - 1))                 # denser characters are brighter
        for col, rgb in enumerate(PALETTE):
            t[col * NS + s, :, :, :3] = (mask * np.array(rgb, np.float32) * bright).astype(np.uint8)
    if bg_rows is not None:
        bg = np.zeros((ch, cw, 4), np.uint8)
        bg[:, :, :3] = np.asarray(bg_rows, np.uint8)[:, None, :]
        t = np.maximum(t, bg[None])
    return t

TILES = make_tiles()
_atlases = {}


def card_tiles(y, panel, scan, card_y0, cw=CW, ch=CH, font_px=FONT_PX):
    """Atlas whose cell background matches a ui.card() at screen/app row y (scanlines every
    3 px from card_y0 + 4), for a viewport whose top is at y."""
    rows = [scan if (y + k - card_y0 - 4) % 3 == 0 else panel for k in range(ch)]
    key = (tuple(map(tuple, rows)), cw, ch, font_px)
    if key not in _atlases:
        _atlases[key] = make_tiles(cw, ch, font_px, rows)
    return _atlases[key]


MINI_CW, MINI_CH = 5, 7          # small cells for icon badges (title bar)
MINI = make_tiles(MINI_CW, MINI_CH, 7, offset=(0, -1))
MINI[:, :, :, :3] = np.minimum(255, MINI[:, :, :, :3].astype(np.uint16) * 3 // 2).astype(np.uint8)   # tiny glyphs: brighter


# ---- rotations ---------------------------------------------------------------------------------
def matrix(tilt, a, b, c):
    """rot_x(tilt) @ rz(c) @ ry(b) @ rx(a) as 9 floats (row-major), plain Python (no numpy
    overhead per frame)."""
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    m = [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa,
         sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa,
         -sb,     cb * sa,                cb * ca]
    if tilt:
        ct, st = math.cos(tilt), math.sin(tilt)
        m[3:] = [ct * m[3] - st * m[6], ct * m[4] - st * m[7], ct * m[5] - st * m[8],
                 st * m[3] + ct * m[6], st * m[4] + ct * m[7], st * m[5] + ct * m[8]]
    return m


def boot_matrix(t):
    """Pose of the boot loading spin at monotonic time t."""
    return matrix(BOOT_TILT, 0.0, BOOT_W * t, 0.0)


def compose(grid):
    """Full band image (ROWS*CH x COLS*CW x 4) for a grid."""
    return TILES[grid].transpose(0, 2, 1, 3, 4).reshape(ROWS * CH, COLS * CW, 4)


# ---- drawing (the work happens in native/libtrend/src/mesh.c) -------------------------------------
_TILES_ATLAS = native.atlas(TILES, CW, CH)


def draw_band(dst, shape, m9, K, x_off):
    """Render shape into dst (band-sized RGBX array, pre-cleared where it will draw), shifted
    x_off px. Returns the touched rect (y0, y1, x0, x1)."""
    v = native.view(K, ASPECT, CAM_Z, LIGHT, COLS, ROWS, NS)
    return native.mesh_draw(shape.cmesh, m9, v, _TILES_ATLAS, dst, int(round(x_off)), 0)


def draw_view(dst, shape, m9, K, cols, rows, x, y, tiles=TILES, cw=CW, ch=CH):
    """Render shape into a cols x rows cell viewport of dst (RGBX array) with its top-left at
    pixel (x, y); the object's centre maps to the viewport centre, K = projection scale in
    cells. Only non-empty cells are written (restore the background first). Returns the touched
    rect (y0, y1, x0, x1)."""
    v = native.view(K, cw / ch, CAM_Z, LIGHT, cols, rows, NS)
    return native.mesh_draw(shape.cmesh, m9, v, native.atlas(tiles, cw, ch), dst, x, y)


def shape_grid(m9, shape, K=K_BOOT):
    """Tile-index grid of a shape at launcher size (boot animation frames, model previews)."""
    return native.mesh_grid(shape.cmesh, m9, native.view(K, ASPECT, CAM_Z, LIGHT, COLS, ROWS, NS))

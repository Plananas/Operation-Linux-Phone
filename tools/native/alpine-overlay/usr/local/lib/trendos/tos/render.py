"""ASCII-shaded 3D rendering (the objects themselves live in tos/models).

Every (palette colour, shade character) pair is pre-rendered once as an RGBX tile. A frame is a
ROWS x COLS grid of tile indices (0 = empty): rotate, perspective-correct back-face cull,
project, z-buffer, point-light shade. The C core (librender.so, tools/native/render.c) does this
and copies the tiles straight into the target buffer; numpy is the fallback/reference.
"""
import ctypes, math

import numpy as np
from PIL import Image, ImageDraw

from .config import (CW, CH, COLS, ROWS, NS, SHADES, PALETTE, LIGHT, CAM_Z, ASPECT, K_BOOT,
                     FONT_PX, LIBRENDER, BOOT_TILT, BOOT_W)
from .gfx import art_font, blit

# ---- tile atlas: tiles[colour * NS + shade] = CH x CW x 4 RGBX --------------------------
def _make_tiles():
    t = np.zeros((len(PALETTE) * NS, CH, CW, 4), np.uint8)
    f = art_font(FONT_PX)
    for s, c in enumerate(SHADES):
        g = Image.new("L", (CW, CH), 0)
        ImageDraw.Draw(g).text((1, -1), c, fill=255, font=f)
        mask = np.asarray(g, np.float32)[..., None] / 255.0
        bright = 0.35 + 0.65 * (s / (NS - 1))                 # denser characters are brighter
        for col, rgb in enumerate(PALETTE):
            t[col * NS + s, :, :, :3] = (mask * np.array(rgb, np.float32) * bright).astype(np.uint8)
    return t

TILES = _make_tiles()


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


# ---- numpy reference / fallback ------------------------------------------------------------------
_LIGHT = np.array(LIGHT, np.float32)

def grid_numpy(m9, shape, K=K_BOOT):
    """ROWS x COLS tile-index grid (reference implementation; the C core matches it)."""
    R = np.array(m9, np.float32).reshape(3, 3)
    fn = shape.fnrm @ R.T
    fc = shape.fcen @ R.T
    fc[:, 2] -= CAM_Z
    vis = np.nonzero(np.einsum("ij,ij->i", fn, fc) < 0)[0]      # faces towards the camera
    if not len(vis):
        return np.zeros((ROWS, COLS), np.int32)
    idx = np.concatenate([shape.face_idx[f] for f in vis])
    p = shape.pts[idx] @ R.T
    f = shape.fid[idx]; n = fn[f]
    ooz = 1.0 / (p[:, 2] - CAM_Z)
    kz = K * ooz
    xp = np.clip((COLS / 2 + kz * p[:, 0]).astype(np.int32), 0, COLS - 1)
    yp = np.clip((ROWS / 2 - kz * p[:, 1] * ASPECT).astype(np.int32), 0, ROWS - 1)
    ld = _LIGHT - p
    lum = np.clip(np.einsum("ij,ij->i", n, ld) / np.sqrt(np.einsum("ij,ij->i", ld, ld)), 0, 1)
    shade = 1 + np.minimum((lum ** 1.3 * (NS - 1)).astype(np.int32), NS - 2)
    order = np.argsort(ooz)                                      # far -> near, nearest wins
    grid = np.zeros((ROWS, COLS), np.int32)
    grid[yp[order], xp[order]] = (shape.fcol[f] * NS + shade)[order]
    return grid


def compose(grid):
    """Full band image (ROWS*CH x COLS*CW x 4) for a grid."""
    return TILES[grid].transpose(0, 2, 1, 3, 4).reshape(ROWS * CH, COLS * CW, 4)


# ---- C core --------------------------------------------------------------------------------------
class Renderer:
    def __init__(self):
        try:
            lib = ctypes.CDLL(LIBRENDER)
            vp, f, i = ctypes.c_void_p, ctypes.c_float, ctypes.c_int
            lib.render_draw.restype = i
            lib.render_draw.argtypes = [vp, vp, vp, i, vp, vp, vp,           # shape
                                        vp, f, i, i, f, f, vp, i,           # R, K, grid, camera, light, ns
                                        vp, i, i,                           # tiles, ch, cw
                                        vp, i, i, i, i, i, vp]              # dst, stride, w, h, x, y, rect
            lib.render_shape.restype = i
            lib.render_shape.argtypes = [vp, vp, vp, i, vp, vp, vp, vp, f, i, i, f, f, vp, i, vp]
            lib.scale_bytes.restype = None
            lib.scale_bytes.argtypes = [vp, vp, i, i]
            lib.blend_rect.restype = None
            lib.blend_rect.argtypes = [vp, i, vp, i, i, i, i]
            lib.slide_frame.restype = None
            lib.slide_frame.argtypes = [vp, vp, vp, i, i, i, i, i]
            self.lib = lib
        except OSError:
            self.lib = None
        self._m9 = (ctypes.c_float * 9)()
        self._rect = (ctypes.c_int32 * 4)()
        self._light = np.ascontiguousarray(_LIGHT)

    def draw(self, dst, shape, m9, K, x_off):
        """Render shape into dst (band-sized RGBX array, pre-cleared where it will draw), shifted
        x_off px. Returns the touched rect (y0, y1, x0, x1)."""
        x_off = int(round(x_off))
        if self.lib is None:
            g = grid_numpy(m9, shape, K)
            rows, cols = np.nonzero(g.any(1))[0], np.nonzero(g.any(0))[0]
            if not len(rows):
                return (0, 0, 0, 0)
            r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
            img = TILES[g[r0:r1, c0:c1]].transpose(0, 2, 1, 3, 4).reshape((r1 - r0) * CH, (c1 - c0) * CW, 4)
            return blit(dst, img, r0 * CH, x_off + c0 * CW)
        self._m9[:] = m9
        s = shape.cptr
        self.lib.render_draw(s[0], s[1], s[2], s[3], s[4], s[5], s[6],
                             ctypes.addressof(self._m9), K, COLS, ROWS, ASPECT, CAM_Z,
                             self._light.ctypes.data, NS, TILES.ctypes.data, CH, CW,
                             dst.ctypes.data, dst.strides[0], dst.shape[1], dst.shape[0], x_off, 0,
                             ctypes.addressof(self._rect))
        return tuple(self._rect)

    # ---- 2D helpers used by overlays (power menu) ----
    def scale(self, dst, src, q):
        """dst = src * q (0..1), both contiguous arrays of equal size (dims a frame)."""
        qi = max(0, min(256, int(q * 256)))
        if self.lib is None:
            dst[:] = (src.astype(np.uint16) * qi >> 8).astype(np.uint8)
            return
        self.lib.scale_bytes(dst.ctypes.data, src.ctypes.data, src.size, qi)

    def blend(self, dst, src, a):
        """dst (a view with row stride, e.g. a rect of a page) = dst + (src - dst) * a."""
        ai = max(0, min(256, int(a * 256)))
        if self.lib is None:
            dst[:] = (dst.astype(np.int16) + ((src.astype(np.int16) - dst) * ai >> 8)).astype(np.uint8)
            return
        self.lib.blend_rect(dst.ctypes.data, dst.strides[0], src.ctypes.data, src.strides[0],
                            src.shape[1] * src.shape[2], src.shape[0], ai)

    def slide(self, dst, back, front, dy, q, a):
        """Transition frame in one pass: dst = dimmed back (q), with front shifted down dy rows
        faded in (a). All three full-screen contiguous arrays."""
        qi, ai = max(0, min(256, int(q * 256))), max(0, min(256, int(a * 256)))
        if self.lib is None:
            self.scale(dst, back, q)
            if dy < dst.shape[0]:
                self.blend(dst[dy:], front[:dst.shape[0] - dy], a)
            return
        self.lib.slide_frame(dst.ctypes.data, back.ctypes.data, front.ctypes.data,
                             dst.strides[0], dst.shape[0], dy, qi, ai)

    def grid(self, m9, shape, K=K_BOOT):
        """Tile-index grid (used to export boot animation frames)."""
        if self.lib is None:
            return grid_numpy(m9, shape, K)
        self._m9[:] = m9
        g = np.empty((ROWS, COLS), np.int32)
        s = shape.cptr
        self.lib.render_shape(s[0], s[1], s[2], s[3], s[4], s[5], s[6], ctypes.addressof(self._m9), K,
                              COLS, ROWS, ASPECT, CAM_Z, self._light.ctypes.data, NS, g.ctypes.data)
        return g

"""The boundary between Python and C: the only module that may import ctypes.

Everything here mirrors native/libtrend/include/trend/*.h. Callers pass numpy arrays and plain
numbers; they never see a pointer. Like the C underneath, these functions keep no state: each one
reads its inputs and writes only to the output array it was given.
"""
import ctypes
from ctypes import Structure, c_double, c_float, c_int, c_size_t, c_uint32, c_void_p

import numpy as np

from .config import LIBTREND


class Surface(Structure):
    _fields_ = [("px", c_void_p), ("stride", c_int), ("w", c_int), ("h", c_int)]


class Rect(Structure):
    _fields_ = [("y0", c_int), ("y1", c_int), ("x0", c_int), ("x1", c_int)]


class Mesh(Structure):
    _fields_ = [("pts", c_void_p), ("fstart", c_void_p), ("fnrm", c_void_p), ("fcen", c_void_p),
                ("fcol", c_void_p), ("nfaces", c_int)]


class View(Structure):
    _fields_ = [("k", c_float), ("aspect", c_float), ("cam_z", c_float), ("light", c_float * 3),
                ("cols", c_int), ("rows", c_int), ("shades", c_int)]


class Atlas(Structure):
    _fields_ = [("px", c_void_p), ("ch", c_int), ("cw", c_int)]


class Glyph(Structure):
    _fields_ = [("mask", c_void_p), ("w", c_int), ("h", c_int), ("dx", c_int), ("dy", c_int),
                ("advance", c_float)]


class Scope(Structure):
    _fields_ = [("samples", c_void_p), ("n_samples", c_int), ("floor", c_void_p), ("lut", c_void_p),
                ("idle_level", c_int)]


class Terrain(Structure):
    _fields_ = [("band", c_void_p), ("blend", c_void_p), ("base", c_void_p), ("amp", c_void_p),
                ("visible", c_void_p), ("colour", c_void_p), ("dim", c_void_p),
                ("ridges", c_int), ("cols", c_int), ("rows", c_int), ("shades", c_int)]


class Dial(Structure):
    _fields_ = [("mips", c_void_p), ("key", c_void_p), ("lut", c_void_p), ("offset", c_void_p),
                ("mip_of_col", c_void_p), ("tape_start", c_double), ("px_per_unit", c_double),
                ("rows", c_int), ("cols", c_int), ("tape_w", c_int)]


_vp, _i, _f = c_void_p, c_int, c_float
_SIGNATURES = {
    "tr_rgb_to_rgbx":     (None, [_vp, _vp, c_size_t]),
    "tr_scale_bytes":     (None, [_vp, _vp, c_size_t, _i]),
    "tr_blend_rect":      (None, [_vp, _i, _vp, _i, _i, _i, _i]),
    "tr_slide_frame":     (None, [_vp, _vp, _vp, _i, _i, _i, _i, _i]),
    "tr_mesh_grid":       (_i, [Mesh, _vp, View, _vp]),
    "tr_grid_blit":       (Rect, [_vp, _i, _i, Atlas, Surface, _i, _i]),
    "tr_mesh_draw":       (Rect, [Mesh, _vp, View, Atlas, Surface, _i, _i]),
    "tr_fill_rect":       (None, [Surface, Rect, c_uint32]),
    "tr_fill_stripes":    (None, [Surface, Rect, _i, c_uint32]),
    "tr_stroke_rect":     (None, [Surface, Rect, c_uint32]),
    "tr_fill_round_rect": (None, [Surface, Rect, _i, c_uint32]),
    "tr_fill_mask":       (None, [Surface, _vp, _i, _i, _i, _i, c_uint32]),
    "tr_draw_text":       (_f, [Surface, _vp, _vp, _i, _f, _i, c_uint32]),
    "tr_scope_frame":     (_f, [_vp, _i, _i, Scope, _f, Surface, _i, _i]),
    "tr_terrain_draw":    (None, [Terrain, _vp, Atlas, Surface, _i, _i]),
    "tr_dial_draw":       (None, [Dial, c_double, Surface, _i, _i]),
}


def _load(path):
    lib = ctypes.CDLL(path)
    for name, (restype, argtypes) in _SIGNATURES.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = restype, argtypes
    return lib


_lib = _load(LIBTREND)


# ---- conversions at the boundary ---------------------------------------------------------------
def ptr(a):
    """Address of a numpy array's first element, or None for no array."""
    return None if a is None else a.ctypes.data


def surface(a):
    """A Surface over an H x W x 4 (uint8) or H x W (uint32) array, which may be a slice of a page."""
    return Surface(a.ctypes.data, a.strides[0], a.shape[1], a.shape[0])


def colour(rgb):
    """An (r, g, b) tuple as a pixel in framebuffer byte order."""
    return rgb[0] | rgb[1] << 8 | rgb[2] << 16 | 0xff000000


def atlas(tiles, cw, ch):
    """An Atlas over a tile array [n][ch][cw][4]. The array must outlive the call."""
    return Atlas(tiles.ctypes.data, ch, cw)


def mesh(pts, fstart, fnrm, fcen, fcol):
    """A Mesh over contiguous arrays, which must outlive it (a Shape holds both)."""
    return Mesh(*map(ptr, (pts, fstart, fnrm, fcen, fcol)), len(fnrm))


def view(k, aspect, cam_z, light, cols, rows, shades):
    return View(k, aspect, cam_z, (c_float * 3)(*light), cols, rows, shades)


def _floats9(m9):
    return (c_float * 9)(*m9)


def _unit(v):
    """A 0..1 fraction as the 0..256 integer the C blending functions take."""
    return max(0, min(256, int(v * 256)))


# ---- pixels ------------------------------------------------------------------------------------
def rgb_to_rgbx(raw, h, w):
    """H x W x 4 RGBX array from w * h * 3 bytes of packed RGB."""
    out = np.empty((h, w, 4), np.uint8)
    _lib.tr_rgb_to_rgbx(out.ctypes.data, raw, w * h)
    return out


def scale(dst, src, q):
    """dst = src * q (0..1). Both contiguous and the same size."""
    _lib.tr_scale_bytes(dst.ctypes.data, src.ctypes.data, src.size, _unit(q))


def blend(dst, src, a):
    """dst += (src - dst) * a, where dst may be a rectangle of a page."""
    _lib.tr_blend_rect(dst.ctypes.data, dst.strides[0], src.ctypes.data, src.strides[0],
                       src.shape[1] * src.shape[2], src.shape[0], _unit(a))


def slide(dst, back, front, dy, q, a):
    """Transition frame: dst = dimmed back (q), with front shifted down dy rows faded in (a)."""
    _lib.tr_slide_frame(dst.ctypes.data, back.ctypes.data, front.ctypes.data,
                        dst.strides[0], dst.shape[0], dy, _unit(q), _unit(a))


# ---- 3D ----------------------------------------------------------------------------------------
def mesh_grid(m, m9, v):
    """The rows x cols grid of tile indices for mesh m in pose m9 under view v."""
    grid = np.empty((v.rows, v.cols), np.int32)
    _lib.tr_mesh_grid(m, _floats9(m9), v, grid.ctypes.data)
    return grid


def mesh_draw(m, m9, v, at, dst, x, y):
    """Draw mesh m into dst with its viewport's top-left at (x, y). Returns (y0, y1, x0, x1)."""
    r = _lib.tr_mesh_draw(m, _floats9(m9), v, at, surface(dst), x, y)
    return (r.y0, r.y1, r.x0, r.x1)


# ---- 2D ----------------------------------------------------------------------------------------
def fill_rect(dst, y0, y1, x0, x1, c):
    _lib.tr_fill_rect(surface(dst), Rect(y0, y1, x0, x1), colour(c))


def fill_stripes(dst, y0, y1, x0, x1, step, c):
    """Fill rows y0, y0 + step, ... within the rectangle (CRT scanlines)."""
    _lib.tr_fill_stripes(surface(dst), Rect(y0, y1, x0, x1), step, colour(c))


def stroke_rect(dst, y0, y1, x0, x1, c):
    _lib.tr_stroke_rect(surface(dst), Rect(y0, y1, x0, x1), colour(c))


def fill_round_rect(dst, y0, y1, x0, x1, radius, c):
    _lib.tr_fill_round_rect(surface(dst), Rect(y0, y1, x0, x1), radius, colour(c))


def fill_mask(dst, mask, x, y, c):
    """Colour c through an 8-bit coverage mask (contiguous H x W uint8) with its top-left at (x, y)."""
    _lib.tr_fill_mask(surface(dst), mask.ctypes.data, mask.shape[1], mask.shape[0], x, y, colour(c))


def draw_text(dst, table, text, x, y, c):
    """Latin-1 bytes through a 256-entry Glyph table. Returns the pen x after the last character."""
    return _lib.tr_draw_text(surface(dst), table, text, len(text), x, y, colour(c))


def glyph_table():
    """An empty 256-entry table for draw_text."""
    return (Glyph * 256)()


# ---- visualisers -------------------------------------------------------------------------------
def scope_frame(phos, samples, floor, lut, idle_level, peak, dst, x, y):
    """Advance the oscilloscope one frame, painting it into dst. samples None = no live audio.
    Returns the auto-gain peak to pass in next frame. phos is updated in place."""
    h, w = phos.shape
    s = Scope(ptr(samples), 0 if samples is None else len(samples), floor.ctypes.data, lut.ctypes.data, idle_level)
    return _lib.tr_scope_frame(phos.ctypes.data, h, w, s, peak, surface(dst), x, y)


def terrain(band, blend_, base, amp, visible, colour_, dim, rows, shades):
    """A Terrain over contiguous arrays (int32, float32, float32, float32, uint8, int32, float32),
    which must outlive it. rows is the height of the cell grid."""
    ridges, cols = band.shape
    return Terrain(*map(ptr, (band, blend_, base, amp, visible, colour_, dim)), ridges, cols, rows, shades)


def terrain_draw(t, history, at, dst, x, y):
    """Paint the spectrum history (ridges x cols, 0..1) as rows of shaded cells at (x, y)."""
    _lib.tr_terrain_draw(t, history.ctypes.data, at, surface(dst), x, y)


def dial(mips, key, lut, offset, mip_of_col, tape_start, px_per_unit):
    """A Dial over contiguous arrays: mips uint8 [n][rows][tape_w], key uint16 [rows][cols],
    lut uint32, offset float64 [cols], mip_of_col int32 [cols]. They must outlive it."""
    _, rows, tape_w = mips.shape
    return Dial(*map(ptr, (mips, key, lut, offset, mip_of_col)), tape_start, px_per_unit, rows, len(offset), tape_w)


def dial_draw(d, position, dst, x, y):
    """Paint the drum into dst at (x, y), turned to position."""
    _lib.tr_dial_draw(d, position, surface(dst), x, y)

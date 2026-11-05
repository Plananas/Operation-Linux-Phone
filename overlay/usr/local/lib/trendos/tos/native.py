"""The boundary between Python and C: the only module that may import ctypes.

Everything here mirrors native/libtrend/include/trend/*.h. Callers pass numpy arrays and plain
numbers; they never see a pointer. Like the C underneath, these functions keep no state: each one
reads its inputs and writes only to the output array it was given.
"""
import ctypes
import mmap
import time
from ctypes import Structure, c_char_p, c_double, c_float, c_int, c_size_t, c_uint, c_uint32, c_uint64, c_void_p

import numpy as np

from .config import LIBTREND, LIBTRENDPLAY


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


class FilesTheme(Structure):
    _fields_ = [("fonts", c_void_p * 5), ("accent", c_uint32), ("error", c_uint32),
                ("icon", Mesh), ("view", View), ("atlas", Atlas)]


class CalcTheme(Structure):
    _fields_ = [("fonts", c_void_p * 7), ("shades", c_char_p), ("n_shades", c_int),
                ("accent", c_uint32), ("error", c_uint32)]


class WebCmd(Structure):
    _fields_ = [("kind", c_int), ("arg", c_int)]


WEB_MASCOT_POSES = 7                    # TR_WEB_MASCOT_POSES


class WebTheme(Structure):
    _fields_ = [("fonts", c_void_p * 3), ("accent", c_uint32), ("error", c_uint32), ("globe", Mesh),
                ("big_view", View), ("head_view", View), ("hello_view", View), ("atlas", Atlas), ("mascot", Mesh * WEB_MASCOT_POSES)]


class MusicCmd(Structure):
    _fields_ = [("kind", c_int), ("arg", c_int)]


class MusicTheme(Structure):
    _fields_ = [("fonts", c_void_p * 4), ("accent", c_uint32), ("error", c_uint32), ("atlas", Atlas), ("shades", c_int)]


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
    "tr_expr_result":     (_i, [c_char_p, _vp, c_size_t]),
    "tr_calc_size":       (c_size_t, []),
    "tr_calc_init":       (None, [_vp]),
    "tr_calc_touch":      (None, [_vp, _vp, _i, _i, _i, c_double]),
    "tr_calc_press":      (None, [_vp, _vp, c_uint, c_double]),
    "tr_calc_frame_key":  (c_uint64, [_vp, c_double]),
    "tr_calc_render":     (None, [_vp, _vp, c_double, Surface]),
    "tr_calc_expr":       (c_char_p, [_vp]),
    "tr_files_size":        (c_size_t, []),
    "tr_files_status_size": (c_size_t, []),
    "tr_files_init":        (None, [_vp]),
    "tr_files_status_init": (None, [_vp]),
    "tr_files_feed":        (None, [_vp, c_char_p, c_size_t]),
    "tr_files_set_phase":   (None, [_vp, _i, c_char_p]),
    "tr_files_phase":       (_i, [_vp]),
    "tr_files_touch":       (_i, [_vp, _vp, _vp, _i, _i, _i]),
    "tr_files_frame_key":   (c_uint64, [_vp, _vp, c_double]),
    "tr_files_render":      (None, [_vp, _vp, _vp, c_double, Surface]),
    "tr_web_size":          (c_size_t, []),
    "tr_web_status_size":   (c_size_t, []),
    "tr_web_init":          (None, [_vp]),
    "tr_web_status_init":   (None, [_vp]),
    "tr_web_feed":          (None, [_vp, _i, c_char_p, c_size_t]),
    "tr_web_peek_open":     (c_char_p, [_vp]),
    "tr_web_clear_open":    (None, [_vp]),
    "tr_web_address":       (c_char_p, [_vp]),
    "tr_web_touch":         (WebCmd, [_vp, _vp, _vp, _i, _i, _i, c_double]),
    "tr_web_tab":           (_i, [_vp]),
    "tr_web_set_tab":       (None, [_vp, _i]),
    "tr_web_scroll_of":     (_i, [_vp, _i]),
    "tr_web_set_compose":   (None, [_vp, c_char_p, c_char_p]),
    "tr_web_advance":       (c_uint64, [_vp, _vp, c_double]),
    "tr_web_take_said":     (_i, [_vp, _vp, _i]),
    "tr_web_render":        (None, [_vp, _vp, _vp, c_double, Surface]),
    "tr_music_size":        (c_size_t, []),
    "tr_music_status_size": (c_size_t, []),
    "tr_music_library_size": (c_size_t, []),
    "tr_music_init":        (None, [_vp]),
    "tr_music_status_init": (None, [_vp, c_char_p]),
    "tr_music_touch":       (MusicCmd, [_vp, _vp, _vp, _vp, _i, _i, _i]),
    "tr_music_follow":      (None, [_vp, _vp, _vp, _vp]),
    "tr_music_frame_key":   (c_uint64, [_vp, _vp, c_double]),
    "tr_music_render":      (None, [_vp, _vp, _vp, _vp, _vp, Surface]),
    "tr_music_showing_viz": (_i, [_vp]),
    "tr_music_viz_size":    (c_size_t, []),
    "tr_music_viz_init":    (None, [_vp]),
    "tr_music_viz_advance": (None, [_vp, _vp, c_double]),
}

# libtrendplay: loaded when Music first opens, and allowed to be missing.
_PLAYER_SIGNATURES = {
    "tr_player_new":     (_vp, [c_char_p, c_char_p]),
    "tr_player_command": (None, [_vp, MusicCmd]),
    "tr_player_status":  (None, [_vp, _vp]),
    "tr_player_is_playing": (_i, [_vp]),
    "tr_player_library": (None, [_vp, _vp]),
}


def _load(path, signatures=_SIGNATURES):
    lib = ctypes.CDLL(path)
    for name, (restype, argtypes) in signatures.items():
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


# ---- the Calculator app ------------------------------------------------------------------------
TOUCH_EVENTS = {"down": 0, "move": 1, "up": 2}


def expr_result(expr):
    """The formatted value of an arithmetic expression, or None if it's invalid."""
    out = ctypes.create_string_buffer(64)
    return out.value.decode("ascii") if _lib.tr_expr_result(expr.encode("ascii"), out, 64) else None


def calc_new():
    """A fresh calculator state: opaque to Python, and aligned for the doubles inside it."""
    state = (c_double * (_lib.tr_calc_size() // ctypes.sizeof(c_double) + 1))()
    _lib.tr_calc_init(state)
    return state


def calc_theme(tables, shades, accent, error):
    """The fonts (sizes 16, 17, 22, 25, 32, 34, 54, in order) and colours. tables must outlive it."""
    fonts = (c_void_p * 7)(*map(ctypes.addressof, tables))
    return CalcTheme(fonts, shades.encode("ascii"), len(shades), colour(accent), colour(error))


def calc_touch(state, event, x, y, now):
    """Apply a touch in app-area coordinates to the state."""
    _lib.tr_calc_touch(state, state, TOUCH_EVENTS[event], x, y, now)


def calc_press(state, key, now):
    _lib.tr_calc_press(state, state, key, now)


def calc_frame_key(state, now):
    """Changes whenever the screen needs redrawing."""
    return _lib.tr_calc_frame_key(state, now)


def calc_render(state, theme, now, dst):
    """Draw the whole app area into dst."""
    _lib.tr_calc_render(state, ctypes.byref(theme), now, surface(dst))


def calc_expr(state):
    return _lib.tr_calc_expr(state).decode("latin-1")


# ---- the Web app -------------------------------------------------------------------------------
WEB_CHAT, WEB_PAGE = 0, 1                                       # trend/apps/web.h
WEB_LINK, WEB_FIELD, WEB_INPUT, WEB_NEW_CHAT, WEB_STOP_CHAT, WEB_BACK, WEB_FORWARD, WEB_RELOAD, WEB_STOP_PAGE = range(1, 10)
_WEB_F_STATUS = 5                                               # trend/apps/web_wire.h


def web_new():
    state = _aligned(_lib.tr_web_size())
    _lib.tr_web_init(state)
    return state


def web_status_new():
    """Two documents' worth of rows, about 2 MB. It comes straight from the kernel, so only the rows actually
    used take up memory."""
    memory = mmap.mmap(-1, _lib.tr_web_status_size())
    status = (ctypes.c_char * len(memory)).from_buffer(memory)
    _lib.tr_web_status_init(status)
    return status


def web_theme(tables, accent, error, globe, big, head, hello, tiles_atlas, mascot):
    """The fonts (sizes 16, 19, 25, in order), colours, the globe and its view, the mascot's two views, the tiles, and the
    mascot's meshes, one per pose. tables and what the meshes and atlas point at must outlive it."""
    return WebTheme((c_void_p * 3)(*map(ctypes.addressof, tables)), colour(accent), colour(error), globe, big, head, hello, tiles_atlas,
                    (Mesh * WEB_MASCOT_POSES)(*mascot))


def web_feed(status, which, data):
    _lib.tr_web_feed(status, which, data, len(data))


def web_feed_error(status, message):
    """Show a message in the status line, as webd itself would."""
    text = message.encode("latin-1")
    frame = bytes([_WEB_F_STATUS, len(text) + 1, 0, 0, 0]) + text
    for which in (WEB_CHAT, WEB_PAGE):
        _lib.tr_web_feed(status, which, frame, len(frame))


def web_take_open(status):
    """A URL to open in the browser, or "". Once only."""
    url = _lib.tr_web_peek_open(status)
    if not url:
        return ""
    _lib.tr_web_clear_open(status)
    return url.decode("latin-1")


def web_address(status):
    return _lib.tr_web_address(status).decode("latin-1")


def web_touch(state, status, event, x, y):
    """Apply a touch in app-area coordinates. Returns a command, with .kind and .arg."""
    return _lib.tr_web_touch(state, state, status, TOUCH_EVENTS[event], x, y, time.monotonic())


def web_tab(state):
    return _lib.tr_web_tab(state)


def web_set_tab(state, tab):
    _lib.tr_web_set_tab(state, tab)


def web_scroll_of(state, tab):
    return _lib.tr_web_scroll_of(state, tab)


def web_set_compose(state, text, label):
    _lib.tr_web_set_compose(state, None if text is None else text.encode("latin-1", "replace"),
                            None if label is None else label.encode("latin-1"))


def web_advance(state, status, now):
    return _lib.tr_web_advance(state, status, now)


_said = ctypes.create_string_buffer(64)


def web_take_said(state):
    """The letters Blip has said since the last call, for its voice."""
    n = _lib.tr_web_take_said(state, _said, len(_said))
    return _said.raw[:n] if n else b""


def web_render(state, status, theme, now, dst):
    _lib.tr_web_render(state, status, ctypes.byref(theme), now, surface(dst))


# ---- the Music app -----------------------------------------------------------------------------
FILES_OFF, FILES_STARTING = 0, 1                                # trend/apps/files.h
FILES_START, FILES_STOP = 1, 2


def files_new():
    state = _aligned(_lib.tr_files_size())
    _lib.tr_files_init(state)
    return state


def files_status_new():
    status = _aligned(_lib.tr_files_status_size())
    _lib.tr_files_status_init(status)
    return status


def files_theme(tables, accent, error, icon, view, tiles_atlas):
    """The fonts (sizes 16, 17, 22, 25, 54, in order), colours, and the folder to draw. tables and what
    the mesh and atlas point at must outlive it."""
    fonts = (c_void_p * 5)(*map(ctypes.addressof, tables))
    return FilesTheme(fonts, colour(accent), colour(error), icon, view, tiles_atlas)


def files_feed(status, data):
    _lib.tr_files_feed(status, data, len(data))


def files_set_phase(status, phase, message=None):
    _lib.tr_files_set_phase(status, phase, message.encode("latin-1") if message else None)


def files_phase(status):
    return _lib.tr_files_phase(status)


def files_touch(state, status, event, x, y):
    """Apply a touch in app-area coordinates. Returns FILES_START, FILES_STOP or 0."""
    return _lib.tr_files_touch(state, state, status, TOUCH_EVENTS[event], x, y)


def files_frame_key(state, status, now):
    return _lib.tr_files_frame_key(state, status, now)


def files_render(state, status, theme, now, dst):
    _lib.tr_files_render(state, status, ctypes.byref(theme), now, surface(dst))


MUSIC_RESCAN, MUSIC_RELEASE = MusicCmd(7, 0), MusicCmd(8, 0)    # trend/apps/music.h


def music_volume(level):
    return MusicCmd(6, level)                                   # TR_CMD_VOLUME


def _aligned(size):
    """Opaque zeroed memory for a C struct, aligned for the doubles inside it."""
    return (c_double * (size // ctypes.sizeof(c_double) + 1))()


def music_new():
    state = _aligned(_lib.tr_music_size())
    _lib.tr_music_init(state)
    return state


def music_status_new():
    status = _aligned(_lib.tr_music_status_size())
    _lib.tr_music_status_init(status, None)
    return status


def music_status_init(status, error):
    _lib.tr_music_status_init(status, error.encode("latin-1"))


def music_library_new():
    return _aligned(_lib.tr_music_library_size())


def music_theme(tables, accent, error, tiles, cw, ch, shades):
    """The fonts (sizes 16, 17, 22, 25, in order), colours, and the icons' character tiles. tables and
    tiles must outlive it."""
    fonts = (c_void_p * 4)(*map(ctypes.addressof, tables))
    return MusicTheme(fonts, colour(accent), colour(error), atlas(tiles, cw, ch), shades)


def music_touch(state, status, library, event, x, y):
    """Apply a touch in app-area coordinates. Returns a command for the player."""
    return _lib.tr_music_touch(state, state, status, library, TOUCH_EVENTS[event], x, y)


def music_frame_key(state, status, library, now):
    """Keeps the playing track and open folder in view, and changes whenever the screen needs redrawing."""
    _lib.tr_music_follow(state, state, status, library)
    return _lib.tr_music_frame_key(state, status, now)


def music_viz_new():
    viz = _aligned(_lib.tr_music_viz_size())
    _lib.tr_music_viz_init(viz)
    return viz


def music_render(state, status, library, viz, theme, now, dst):
    """Draw the whole app area, moving the visualiser on to now if it's showing."""
    if _lib.tr_music_showing_viz(state):
        _lib.tr_music_viz_advance(viz, status, now)
    _lib.tr_music_render(state, status, library, viz, ctypes.byref(theme), surface(dst))


def player_new(music_dir):
    """A running player, or None if libtrendplay or what it needs isn't installed."""
    global _player_lib
    try:
        if _player_lib is None:
            _player_lib = _load(LIBTRENDPLAY, _PLAYER_SIGNATURES)
    except OSError:
        return None
    return _player_lib.tr_player_new(music_dir.encode(), None)


_player_lib = None


def player_command(player, cmd):
    _player_lib.tr_player_command(player, cmd)


def player_status(player, status):
    _player_lib.tr_player_status(player, status)


def player_is_playing(player):
    return _player_lib.tr_player_is_playing(player)


def player_library(player, library):
    _player_lib.tr_player_library(player, library)

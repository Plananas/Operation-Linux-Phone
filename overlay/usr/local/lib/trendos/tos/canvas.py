"""Fast 2D drawing straight into RGBX arrays, through libtrend. No PIL on the drawing path.

Use this for anything redrawn often. PIL stays for one-off images (icons, tapes, atlases) and for
making the glyph masks once.

Every function writes only to dst, an H x W x 4 array that may be a slice of a larger image.
Rectangles are half-open: y0 <= y < y1, x0 <= x < x1.

    im = blank(100)
    fill_rect(im, 0, 20, 0, 480, PANEL)
    text(im, 10, 2, "hello", 20, ACCENT)
"""
from functools import lru_cache
import os, struct

import numpy as np

from . import native
from .config import GLYPH_FILE, W
from .gfx import glyph


def blank(h, w=W, bg=(0, 0, 0)):
    """A new h x w RGBX image filled with bg."""
    return np.full((h, w), native.colour(bg), np.uint32).view(np.uint8).reshape(h, w, 4)


fill_rect = native.fill_rect
stroke_rect = native.stroke_rect
fill_round_rect = native.fill_round_rect
fill_stripes = native.fill_stripes


# The glyph file: FreeType costs 2-3 ms a character, seconds across the apps' font tables, so
# tools/deploy.sh draws them once ("trendos.py --bake-glyphs", boot.bake_glyphs) and they load from
# here. Without the file, or with a damaged one, the same glyphs are just drawn when needed.
_GLYPH_HEAD = struct.Struct("<4sI")            # magic, glyph count
_GLYPH_ROW = struct.Struct("<IHHHhhd")         # code point, size, w, h, dx, dy, advance; then all masks
_GLYPH_MAGIC = b"TGL1"


def read_glyphs(path):
    """{(char, size): (mask or None, dx, dy, advance)}, or {} if there is no usable file."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        magic, n = _GLYPH_HEAD.unpack_from(data)
        rows = _GLYPH_HEAD.size + n * _GLYPH_ROW.size
        if magic != _GLYPH_MAGIC or len(data) < rows:
            return {}
        at, out = rows, {}
        for cp, size, w, h, dx, dy, adv in _GLYPH_ROW.iter_unpack(data[_GLYPH_HEAD.size:rows]):
            mask = np.frombuffer(data, np.uint8, w * h, at).reshape(h, w) if w else None
            out[chr(cp), size] = (mask, dx, dy, adv)
            at += w * h
        return out if at == len(data) else {}
    except (OSError, struct.error, ValueError):
        return {}


def write_glyphs(path, glyphs):
    """Write {(char, size): (mask or None, dx, dy, advance)} for read_glyphs, replacing any old file whole."""
    items = list(glyphs.items())
    masks = [b"" if m is None else m.tobytes() for (_, (m, _, _, _)) in items]
    rows = [_GLYPH_ROW.pack(ord(ch), size, 0 if m is None else m.shape[1], 0 if m is None else m.shape[0], dx, dy, adv)
            for ((ch, size), (m, dx, dy, adv)) in items]
    with open(path + ".tmp", "wb") as f:
        f.write(_GLYPH_HEAD.pack(_GLYPH_MAGIC, len(items)) + b"".join(rows) + b"".join(masks))
    os.replace(path + ".tmp", path)


_baked = read_glyphs(GLYPH_FILE)
_masks = {}                                    # every mask asked for: draw_text's tables point into them


def _mask(ch, size):
    """(contiguous coverage mask or None, dx, dy, advance) of one character."""
    g = _masks.get((ch, size))
    if g is None:
        g = _baked.get((ch, size))
        if g is None:
            m, dx, dy, adv = glyph(ch, size)
            g = (None if m is None else np.array(m, np.uint8), dx, dy, adv)
        _masks[ch, size] = g
    return g


def masks_seen():
    """A copy of every mask asked for so far, for baking."""
    return dict(_masks)


def ignore_baked():
    """Draw every glyph from the font from now on, even ones in the file, for baking a fresh one."""
    _baked.clear()


@lru_cache(maxsize=None)
def _font_tables(size):
    """A Latin-1 glyph table for this size, and the set of bytes loaded into it so far."""
    return native.glyph_table(), set()


def _glyph_entry(ch, size):
    """A table entry for one character. Its mask stays alive in _mask's cache."""
    m, dx, dy, adv = _mask(ch, size)
    if m is None:
        return native.Glyph(None, 0, 0, dx, dy, adv)
    return native.Glyph(m.ctypes.data, m.shape[1], m.shape[0], dx, dy, adv)


def _load(table, loaded, data, size):
    """Fill in any table entries data needs."""
    for byte in set(data) - loaded:
        table[byte] = _glyph_entry(chr(byte), size)
        loaded.add(byte)


def font_table(size, chars, extra):
    """The glyph table for a size, loaded up front for C code that draws its own text. extra maps
    spare byte values to characters outside Latin-1."""
    table, loaded = _font_tables(size)
    _load(table, loaded, chars.encode("latin-1"), size)
    for byte, ch in extra.items():
        table[byte] = _glyph_entry(ch, size)
        loaded.add(byte)
    return table


def text(dst, x, y, s, size, colour):
    """Draw s with its top-left at (x, y), in the UI font. Returns the pen x after it."""
    try:
        data = s.encode("latin-1")
    except UnicodeEncodeError:
        return _text_unicode(dst, x, y, s, size, colour)
    table, loaded = _font_tables(size)
    if not loaded.issuperset(data):
        _load(table, loaded, data, size)
    return native.draw_text(dst, table, data, x, y, colour)


def _text_unicode(dst, x, y, s, size, colour):
    """The occasional string outside Latin-1 (such as the title bar's arrow), a glyph at a time."""
    for ch in s:
        m, dx, dy, adv = _mask(ch, size)
        if m is not None:
            native.fill_mask(dst, m, int(x) + dx, y + dy, colour)
        x += adv
    return x


def text_width(s, size):
    """Width in px of s in the UI font."""
    return sum(_mask(ch, size)[3] for ch in s)


def text_strip(s, size, colour, h, x=None, w=W):
    """A strip h px tall holding one line of text, centred unless x is given."""
    im = blank(h, w)
    text(im, (im.shape[1] - text_width(s, size)) / 2 if x is None else x, 0, s, size, colour)
    return im


def card(dst, box, label, frame, panel, scan, label_colour, bg=(0, 0, 0)):
    """A framed panel with CRT scanlines and a label cut into its top edge. box = (x0, y0, x1, y1),
    half-open. The palette lives in tos/ui.py: use ui.native_card rather than calling this."""
    x0, y0, x1, y1 = box
    fill_round_rect(dst, y0, y1, x0, x1, 9, frame)
    fill_round_rect(dst, y0 + 2, y1 - 2, x0 + 2, x1 - 2, 7, panel)
    fill_stripes(dst, y0 + 4, y1 - 3, x0 + 3, x1 - 2, 3, scan)
    title = f" {label} "
    fill_rect(dst, y0 - 2, y0 + 3, x0 + 18, x0 + 19 + int(text_width(title, 16)), bg)
    text(dst, x0 + 18, y0 - 10, title, 16, label_colour)

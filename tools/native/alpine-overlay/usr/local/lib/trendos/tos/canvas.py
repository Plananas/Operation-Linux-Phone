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

import numpy as np

from . import native
from .config import W
from .gfx import glyph


def blank(h, w=W, bg=(0, 0, 0)):
    """A new h x w RGBX image filled with bg."""
    return np.full((h, w), native.colour(bg), np.uint32).view(np.uint8).reshape(h, w, 4)


fill_rect = native.fill_rect
stroke_rect = native.stroke_rect
fill_round_rect = native.fill_round_rect
fill_stripes = native.fill_stripes


@lru_cache(maxsize=None)
def _mask(ch, size):
    """(contiguous coverage mask or None, dx, dy, advance) of one character."""
    m, dx, dy, adv = glyph(ch, size)
    return (None if m is None else np.array(m, np.uint8), dx, dy, adv)


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

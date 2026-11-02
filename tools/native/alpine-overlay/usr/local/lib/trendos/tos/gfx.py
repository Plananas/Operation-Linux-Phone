"""Small 2D helpers: cached fonts, RGBX conversion, text strips, clipped copies."""
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import W, FONT_UI, FONT_UI_SCALE, FONT_ART


class _UIFont(ImageFont.FreeTypeFont):
    """VT323 at FONT_UI_SCALE x the requested size, nudged up so its capitals sit where
    DejaVu's did (VT323 has a taller ascent), so every existing layout keeps working."""

    def __init__(self, size):
        super().__init__(FONT_UI, round(size * FONT_UI_SCALE))
        self.dy = round(size * 0.112)

    def getmask2(self, *args, **kwargs):
        mask, (x, y) = super().getmask2(*args, **kwargs)
        return mask, (x, y - self.dy)

    def getbbox(self, *args, **kwargs):
        l, t, r, b = super().getbbox(*args, **kwargs)
        return l, t - self.dy, r, b - self.dy


@lru_cache(maxsize=None)
def font(size, bold=True):
    """UI font, loaded once and reused (loading a TTF costs milliseconds). VT323 has a
    single weight, so `bold` is accepted for compatibility and ignored."""
    return _UIFont(size)


@lru_cache(maxsize=None)
def art_font(size):
    """Font for the ASCII-shaded 3D glyph atlas."""
    return ImageFont.truetype(FONT_ART, size)


def to_rgbx(im):
    """PIL image -> H x W x 4 uint8 array in the framebuffer's byte order (R, G, B, X)."""
    return np.frombuffer(im.convert("RGBX").tobytes(), np.uint8).reshape(im.height, im.width, 4)


def canvas(h, w=W):
    im = Image.new("RGB", (w, h), (0, 0, 0))
    return im, ImageDraw.Draw(im)


def centre_text(d, y, txt, f, colour, w=W):
    d.text(((w - d.textlength(txt, font=f)) / 2, y), txt, fill=colour, font=f)


def text_strip(txt, size, colour, h, bold=True, x=None):
    """A screen-wide strip with one line of text, centred unless x is given."""
    im, d = canvas(h)
    f = font(size, bold)
    d.text(((W - d.textlength(txt, font=f)) / 2 if x is None else x, 0), txt, fill=colour, font=f)
    return to_rgbx(im)


def crop_columns(img):
    """Trim empty columns: returns (x offset, cropped copy). X byte forced to 0."""
    img = img.copy(); img[..., 3] = 0
    cols = np.nonzero(img.any((0, 2)))[0]
    return int(cols[0]), np.ascontiguousarray(img[:, cols[0]:cols[-1] + 1])


def blit(dst, img, y0, x0):
    """Copy img into dst at (y0, x0), clipped horizontally. Returns the touched rect."""
    x0 = int(round(x0)); h, w = img.shape[:2]
    a, b = max(0, x0), min(dst.shape[1], x0 + w)
    if b > a and h:
        dst[y0:y0 + h, a:b] = img[:, a - x0:b - x0]
        return (y0, y0 + h, a, b)
    return (0, 0, 0, 0)

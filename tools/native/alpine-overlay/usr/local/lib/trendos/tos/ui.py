"""Shared look for TREND OS apps: the green-phosphor terminal palette, framed cards with a label
cut into the top edge, and outlined keys (as in the Calculator, Radio and Clock).

    card(draw, (x0, y0, x1, y1), "label")        framed panel with CRT scanlines
    key_image(w, h, "label", kind, pressed)      cached PIL image of a key
    Keys([...]) / keys.hit(x, y)                 a row of keys with hit testing
"""
from PIL import Image, ImageDraw

from .config import ACCENT, PALETTE, RED
from .gfx import font, text_len, draw_text

BG = (0, 0, 0)
FRAME, FRAME_HI = (0, 85, 48), (0, 150, 85)     # card border / its label
PANEL, SCAN = (0, 7, 4), (0, 13, 7)             # card fill + faint scanlines
DIM, MID = (0, 60, 34), (0, 110, 62)            # unlit / secondary text
GHOST = (0, 22, 13)                             # unlit 7-segment segments
FLARE = (200, 255, 225)                         # fresh phosphor, highlights
ERR = PALETTE[RED]

KEY_STYLE = {   # kind: (fill, edge, text, pressed fill)
    "step": ((0, 10, 6), (0, 72, 42), (190, 245, 210), (150, 230, 185)),
    "jump": ((0, 14, 8), (0, 150, 85), ACCENT, ACCENT),
    "off":  ((14, 3, 3), (125, 42, 42), (255, 110, 110), (255, 110, 110)),
    "on":   (ACCENT, ACCENT, (0, 0, 0), FLARE),
    "dim":  ((0, 6, 4), (0, 45, 26), MID, (0, 110, 62)),
}


def mix(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def card(d, box, label):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0, y0, x1, y1], 9, fill=PANEL, outline=FRAME, width=2)
    for y in range(y0 + 4, y1 - 2, 3):
        d.line([(x0 + 3, y), (x1 - 3, y)], fill=SCAN)
    f = font(16)
    label = f" {label} "
    lw = d.textlength(label, font=f)
    d.rectangle([x0 + 18, y0 - 2, x0 + 18 + lw, y0 + 2], fill=BG)
    d.text((x0 + 18, y0 - 10), label, fill=FRAME_HI, font=f)


_keys = {}


def key_image(w, h, label, kind="step", pressed=False, size=30):
    """PIL RGB image (w+1 x h+1) of one outlined key; inverse video while pressed."""
    k = (w, h, label, kind, pressed, size)
    im = _keys.get(k)
    if im is None:
        im = Image.new("RGB", (w + 1, h + 1), BG); d = ImageDraw.Draw(im)
        fill, edge, text, lit = KEY_STYLE[kind]
        if pressed:
            fill, edge, text = lit, lit, (0, 0, 0)
        d.rounded_rectangle([0, 0, w, h], 7, fill=fill, outline=edge, width=2)
        if not pressed and kind != "on":
            d.line([(8, h - 5), (w - 8, h - 5)], fill=mix(fill, edge, 0.35), width=1)
        draw_text(im, (w - text_len(label, size)) / 2, (h - size * 1.12) / 2, label, size, text)
        im = _keys[k] = im
    return im


class Keys:
    """A set of keys [(id, x, y, w, h, label, kind[, size])] in app-area coordinates."""

    def __init__(self, keys):
        self.keys = [k if len(k) == 8 else k + (30,) for k in keys]

    def hit(self, x, y):
        for kid, kx, ky, w, h, *_ in self.keys:
            if kx <= x <= kx + w and ky <= y <= ky + h:
                return kid
        return None

    def draw(self, im, pressed=None):
        for kid, kx, ky, w, h, label, kind, size in self.keys:
            im.paste(key_image(w, h, label, kind, kid == pressed, size), (kx, ky))

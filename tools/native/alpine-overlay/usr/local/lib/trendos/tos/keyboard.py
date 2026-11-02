"""Reusable on-screen touch keyboard.

Three layers (letters / numbers / symbols) with Shift, Backspace, Space, Esc and Done. It manages
its own text buffer; a host app draws its own text field and calls render()/touch()/key().

Geometry is in screen coordinates: the keyboard occupies the bottom KB_H px of the screen.
The base image of each (layer, shift) is pre-rendered once; a press only overlays one key.
"""
from PIL import Image, ImageDraw

from .config import W, H, ACCENT, DIM, TEXT, PALETTE, ORANGE, RED
from .gfx import font, to_rgbx

KH, GAP = 60, 6
NROWS = 4
KB_H = NROWS * (KH + GAP) + GAP
KB_Y = H - KB_H                       # on-screen y of the keyboard's top
BG, KEY_BG, KEY_EDGE = (0, 0, 0), (22, 28, 25), (55, 70, 62)
SPECIAL = {"shift", "del", "esc", "space", "done", "123", "abc", "#+="}

# rows are lists of (label, weight); plain single-char labels have weight 1
_L = lambda s: [(c, 1) for c in s]
LAYERS = {
    "abc": [_L("qwertyuiop"), _L("asdfghjkl"),
            [("shift", 1.6)] + _L("zxcvbnm") + [("del", 1.6)],
            [("123", 1.6), ("esc", 1.4), ("space", 4.4), ("done", 2.0)]],
    "123": [_L("1234567890"), _L("-/:;()$&@\""),
            [("#+=", 1.6)] + _L(".,?!'") + [("del", 1.6)],
            [("abc", 1.6), ("esc", 1.4), ("space", 4.4), ("done", 2.0)]],
    "#+=": [_L("[]{}#%^*+="), _L("_\\|~<>'\".,"),
            [("123", 1.6)] + _L(".,?!'") + [("del", 1.6)],
            [("abc", 1.6), ("esc", 1.4), ("space", 4.4), ("done", 2.0)]],
}
LABEL = {"shift": "shift", "del": "del", "esc": "esc", "space": "space", "done": "done",
         "123": "123", "abc": "abc", "#+=": "#+="}


class Keyboard:
    def __init__(self, on_done=None, on_cancel=None, text=""):
        self.on_done, self.on_cancel = on_done, on_cancel
        self.text = text
        self.layer, self.shift = "abc", False
        self.pressed = None
        self._base = {}                  # (layer, shift) -> base RGBX image
        self._rects = {}                 # (layer, shift) -> [(id, label, x, y, w, h)]

    # ---- layout ----
    def _layout(self):
        kkey = (self.layer, self.shift)
        if kkey in self._rects:
            return self._rects[kkey]
        rects = []
        for r, row in enumerate(LAYERS[self.layer]):
            tw = sum(wt for _, wt in row)
            unit = (W - (len(row) + 1) * GAP) / tw
            x = GAP
            y = KB_Y + GAP + r * (KH + GAP)
            for label, wt in row:
                w = wt * unit
                rects.append((label, int(x), int(y), int(w), KH))
                x += w + GAP
        self._rects[kkey] = rects
        return rects

    def _disp(self, label):
        if label in SPECIAL:
            return LABEL[label]
        return label.upper() if self.shift and label.isalpha() else label

    def _key_colour(self, label):
        if label == "done":
            return (0, 165, 92), (0, 210, 120), (0, 0, 0)
        if label in ("del", "esc"):
            return (32, 14, 14), (110, 50, 50), (255, 130, 130)
        if label in ("shift", "123", "abc", "#+="):
            on = label == "shift" and self.shift
            return ((0, 70, 45) if on else KEY_BG), ACCENT, ACCENT
        return KEY_BG, KEY_EDGE, TEXT

    def _draw_key(self, d, label, x, y, w, h, pressed):
        fill, edge, txt = self._key_colour(label)
        if pressed:
            fill = tuple(min(255, c + 45) for c in fill)
        d.rounded_rectangle([x, y, x + w, y + h], 10, fill=fill, outline=edge, width=2)
        s = self._disp(label)
        f = font(26 if len(s) == 1 else 20)
        d.text((x + (w - d.textlength(s, font=f)) / 2, y + (h - 30) / 2), s, fill=txt, font=f)

    def _render_base(self):
        kkey = (self.layer, self.shift)
        if kkey in self._base:
            return self._base[kkey]
        im = Image.new("RGB", (W, KB_H), BG); d = ImageDraw.Draw(im)
        for label, x, y, w, h in self._layout():
            self._draw_key(d, label, x, y - KB_Y, w, h, False)   # image-local y
        img = to_rgbx(im)
        self._base[kkey] = img
        return img

    # ---- drawing ----
    def key(self, now):
        return (self.text, self.layer, self.shift, self.pressed)

    def render(self):
        """RGBX image of the keyboard block (KB_H x W)."""
        img = self._render_base().copy()
        if self.pressed:
            for label, x, y, w, h in self._layout():
                if label == self.pressed:
                    tile = Image.new("RGB", (w + 1, h + 1), BG)
                    self._draw_key(ImageDraw.Draw(tile), label, 0, 0, w, h, True)
                    img[y - KB_Y:y - KB_Y + h + 1, x:x + w + 1] = to_rgbx(tile)
                    break
        return img

    # ---- input ----
    def _hit(self, x, y):
        for label, kx, ky, w, h in self._layout():
            if kx <= x <= kx + w and ky <= y <= ky + h:
                return label
        return None

    def touch(self, ev, x, y):
        if ev == "down":
            self.pressed = self._hit(x, y)
        elif ev == "move":
            if self._hit(x, y) != self.pressed:
                self.pressed = None
        elif ev == "up":
            label = self._hit(x, y)
            if label is not None and label == self.pressed:
                self._activate(label)
            self.pressed = None

    def _activate(self, label):
        if label == "shift":
            self.shift = not self.shift
        elif label == "del":
            self.text = self.text[:-1]
        elif label == "space":
            self.text += " "
        elif label in ("123", "abc", "#+="):
            self.layer = label
        elif label == "esc":
            if self.on_cancel:
                self.on_cancel()
        elif label == "done":
            if self.on_done:
                self.on_done(self.text)
        else:
            self.text += label.upper() if self.shift and label.isalpha() else label

"""Reusable on-screen touch keyboard.

Three layers (letters / numbers / symbols) with Shift, Backspace, Space, Esc and Done. It manages
its own text buffer; a host app draws its own text field and calls render()/touch()/key().

Every touch on it counts: a tap in a gap goes to the nearest key, and a finger that rolls a little
still types the key it pressed. A second finger landing types the first finger's key straight away,
so fast typing keeps every letter, in order. prose=True is for writing to read: it capitalises
sentences, and types ". " for a double space. Leave it off for anything exact, like a password.

Geometry is in screen coordinates: the keyboard occupies the bottom KB_H px of the screen.
The base image of each (layer, shift) is pre-rendered once; a press only overlays one key.
"""
import re
import time

from PIL import Image, ImageDraw

from .config import W, H, ACCENT, DIM, TEXT, PALETTE, ORANGE, RED
from .gfx import font, to_rgbx

KH, GAP = 60, 6
NROWS = 4
KB_H = NROWS * (KH + GAP) + GAP
KB_Y = H - KB_H                       # on-screen y of the keyboard's top
BG, KEY_BG, KEY_EDGE = (0, 0, 0), (22, 28, 25), (55, 70, 62)
SPECIAL = {"shift", "del", "esc", "space", "done", "123", "abc", "#+="}

SLIDE = 14                            # px past a key's edge before a finger counts as on another key
LEAVE_ABOVE = 30                      # px above the keyboard at which a finger has left, typing nothing
DOUBLE_TAP = 0.4                      # s between taps of shift for caps lock
DOUBLE_SPACE = 0.6                    # s between spaces for ". "
DEL_HOLD = 0.4                        # s holding del before it repeats
DEL_EVERY = 0.08                      # s between characters as it repeats
DEL_WORDS_AFTER = 12                  # characters repeated before it goes by whole words
DEL_WORD_EVERY = 0.2                  # s between words
ESC_CONFIRM = 2.0                     # s for which a second tap of esc throws away what's typed
SENTENCE_END = re.compile(r"[.!?]\s+$")
NUMBER_PUNCTUATION = ":.,/-"          # kept on the numbers layer after a digit: 10:30, 1,000, 3.5


# rows are lists of (label, weight); plain single-char labels have weight 1
_L = lambda s: [(c, 1) for c in s]
_bottom = lambda switch: [("esc", 1.2), (switch, 1.4), (",", 1), ("space", 3.6), (".", 1), ("done", 1.8)]
LAYERS = {
    "abc": [_L("qwertyuiop"), _L("asdfghjkl"),
            [("shift", 1.6)] + _L("zxcvbnm") + [("del", 1.6)], _bottom("123")],
    "123": [_L("1234567890"), _L("-/:;()$&@\""),
            [("#+=", 1.6)] + _L(".,?!'") + [("del", 1.6)], _bottom("abc")],
    "#+=": [_L("[]{}#%^*+="), _L("_\\|~<>'\".,"),
            [("123", 1.6)] + _L(".,?!'") + [("del", 1.6)], _bottom("abc")],
}
LABEL = {"shift": "shift", "del": "del", "esc": "esc", "space": "space", "done": "done",
         "123": "123", "abc": "abc", "#+=": "#+="}


def build_rows(layer):
    """[[(label, x, y, w, h), ...] per row]"""
    rows = []
    for r, row in enumerate(LAYERS[layer]):
        unit = (W - (len(row) + 1) * GAP) / sum(wt for _, wt in row)
        x, keys = GAP, []
        y = KB_Y + GAP + r * (KH + GAP)
        for label, wt in row:
            keys.append((label, int(x), y, int(wt * unit), KH))
            x += wt * unit + GAP
        rows.append(keys)
    return rows


def nearest_key(rows, x, y):
    """The label of the key closest to a point. Each row owns the space up to halfway across its gaps."""
    r = min(max(int((y - KB_Y - GAP / 2) // (KH + GAP)), 0), len(rows) - 1)
    return min(rows[r], key=lambda k: max(k[1] - x, x - (k[1] + k[3]), 0))[0]


def is_outside(rect, x, y, margin):
    _, kx, ky, w, h = rect
    return not (kx - margin <= x <= kx + w + margin and ky - margin <= y <= ky + h + margin)


def without_last_word(text):
    return re.sub(r"\S*\s*$", "", text, count=1)


class _Finger:
    def __init__(self, label, now):
        self.label = label
        self.typed = False                  # its key has acted, so lifting does nothing
        self.repeat_at = now + DEL_HOLD if label == "del" else None
        self.repeats = 0


class Keyboard:
    def __init__(self, on_done=None, on_cancel=None, text="", on_change=None, prose=False):
        self.on_done, self.on_cancel, self.on_change = on_done, on_cancel, on_change
        self.prose = prose
        self.text = text
        self.layer = "abc"
        self.shift = "off"                  # "off", "once", "auto" (once, by itself) or "lock"
        self.fingers = {}                   # in the order they landed
        self.held_action = None             # esc or done, waiting for every finger to lift
        self.shift_at = self.space_at = -1e9
        self.esc_until = 0.0
        self._base = {}                     # (layer, capitals, lock) -> base RGBX image
        self._rows = {}                     # layer -> rows
        self._auto_capital()

    # ---- layout ----
    def _layout(self):
        if self.layer not in self._rows:
            self._rows[self.layer] = build_rows(self.layer)
        return self._rows[self.layer]

    def _rect(self, label):
        return next((k for row in self._layout() for k in row if k[0] == label), None)

    @property
    def _capitals(self):
        return self.shift != "off"

    def _disp(self, label, armed=False):
        if armed:
            return "sure?"
        if label == "shift" and self.shift == "lock":
            return "CAPS"
        if label in SPECIAL:
            return LABEL[label]
        return label.upper() if self._capitals and label.isalpha() else label

    def _key_colour(self, label, armed=False):
        if label == "done":
            return (0, 165, 92), (0, 210, 120), (0, 0, 0)
        if armed:
            return (150, 30, 30), (255, 130, 130), (255, 255, 255)
        if label in ("del", "esc"):
            return (32, 14, 14), (110, 50, 50), (255, 130, 130)
        if label in ("shift", "123", "abc", "#+="):
            if label != "shift" or not self._capitals:
                return KEY_BG, ACCENT, ACCENT
            return ((0, 110, 70) if self.shift == "lock" else (0, 70, 45)), ACCENT, ACCENT
        return KEY_BG, KEY_EDGE, TEXT

    def _draw_key(self, d, label, x, y, w, h, pressed, armed=False):
        fill, edge, txt = self._key_colour(label, armed)
        if pressed:
            fill = tuple(min(255, c + 45) for c in fill)
        d.rounded_rectangle([x, y, x + w, y + h], 10, fill=fill, outline=edge, width=2)
        s = self._disp(label, armed)
        f = font(26 if len(s) == 1 else 20)
        d.text((x + (w - d.textlength(s, font=f)) / 2, y + (h - 30) / 2), s, fill=txt, font=f)

    def _render_base(self):
        kkey = (self.layer, self._capitals, self.shift == "lock")
        if kkey in self._base:
            return self._base[kkey]
        im = Image.new("RGB", (W, KB_H), BG); d = ImageDraw.Draw(im)
        for row in self._layout():
            for label, x, y, w, h in row:
                self._draw_key(d, label, x, y - KB_Y, w, h, False)   # image-local y
        img = to_rgbx(im)
        self._base[kkey] = img
        return img

    # ---- drawing ----
    def key(self, now):
        self._repeat_delete(now)
        if self.esc_until and now >= self.esc_until:
            self.esc_until = 0.0
        return (self.text, self.layer, self.shift, tuple(f.label for f in self.fingers.values()), bool(self.esc_until))

    def _overlay(self, img, label, pressed, armed=False):
        rect = self._rect(label)
        if rect is None:
            return
        _, x, y, w, h = rect
        tile = Image.new("RGB", (w + 1, h + 1), BG)
        self._draw_key(ImageDraw.Draw(tile), label, 0, 0, w, h, pressed, armed)
        img[y - KB_Y:y - KB_Y + h + 1, x:x + w + 1] = to_rgbx(tile)

    def render(self):
        """RGBX image of the keyboard block (KB_H x W)."""
        img = self._render_base().copy()
        armed = bool(self.esc_until)
        if armed:
            self._overlay(img, "esc", False, armed)
        for f in self.fingers.values():
            self._overlay(img, f.label, True, armed and f.label == "esc")
        return img

    # ---- input ----
    def touch(self, ev, x, y, finger=0, now=None):
        now = time.monotonic() if now is None else now
        if ev == "down":
            self._land(finger, x, y, now)
            return
        if finger in self.fingers:
            self._follow(finger, x, y, now)
        if ev == "up":
            if finger in self.fingers:
                self._lift(finger, now)
            self._finish_held_action()

    def _land(self, finger, x, y, now):
        self.fingers.pop(finger, None)
        if y < KB_Y:
            return
        self._type_held_keys(now)
        self.fingers[finger] = _Finger(nearest_key(self._layout(), x, y), now)

    def _follow(self, finger, x, y, now):
        f = self.fingers[finger]
        if y < KB_Y - LEAVE_ABOVE and not f.typed:
            del self.fingers[finger]
            return
        rect = self._rect(f.label)
        if not f.typed and rect is not None and is_outside(rect, x, y, SLIDE):
            label = nearest_key(self._layout(), x, max(y, KB_Y))
            if label != f.label:
                self.fingers[finger] = _Finger(label, now)

    def _lift(self, finger, now):
        f = self.fingers.pop(finger)
        if not f.typed:
            self._act(f.label, now)

    def _type_held_keys(self, now):
        """Another finger is landing, so the ones already down have finished choosing. Esc and done wait to be
        lifted: closing the keyboard under a finger would hand the rest of its touch to the app."""
        for f in self.fingers.values():
            f.repeat_at = None
            if not f.typed and f.label not in ("esc", "done"):
                f.typed = True
                self._act(f.label, now)

    def _finish_held_action(self):
        if self.held_action is not None and not self.fingers:
            action, self.held_action = self.held_action, None
            action()

    def _repeat_delete(self, now):
        for f in self.fingers.values():
            if f.repeat_at is not None and now >= f.repeat_at:
                f.typed = True
                f.repeats += 1
                by_word = f.repeats > DEL_WORDS_AFTER
                f.repeat_at = now + (DEL_WORD_EVERY if by_word else DEL_EVERY)
                self._set_text(without_last_word(self.text) if by_word else self.text[:-1])
                if self.on_change:
                    self.on_change()

    def _act(self, label, now):
        if label != "esc":
            self.esc_until = 0.0
        if label == "shift":
            self._tap_shift(now)
        elif label == "del":
            self._set_text(self.text[:-1])
        elif label == "space":
            self._type_space(now)
        elif label in ("123", "abc", "#+="):
            self.layer = label
        elif label == "esc":
            self._tap_esc(now)
        elif label == "done":
            self._when_lifted(lambda: self.on_done(self.text) if self.on_done else None)
        else:
            self._type_character(label)

    def _when_lifted(self, action):
        self.held_action = action
        self._finish_held_action()

    def _tap_shift(self, now):
        double = now - self.shift_at <= DOUBLE_TAP
        self.shift_at = now
        if self.shift == "lock":
            self.shift = "off"
        elif double:
            self.shift = "lock"
        else:
            self.shift = "once" if self.shift == "off" else "off"

    def _tap_esc(self, now):
        if not self.text or self.esc_until:
            self.esc_until = 0.0
            self._when_lifted(lambda: self.on_cancel() if self.on_cancel else None)
        else:
            self.esc_until = now + ESC_CONFIRM

    def _type_space(self, now):
        double = self.prose and now - self.space_at <= DOUBLE_SPACE and re.search(r"\w $", self.text)
        self.space_at = -1e9 if double else now
        self._set_text(self.text[:-1] + ". " if double else self.text + " ")
        if self.prose:
            self.layer = "abc"

    def _type_character(self, label):
        capital = self._capitals and label.isalpha()
        before = self.text[-1:]
        if capital and self.shift in ("once", "auto"):
            self.shift = "off"
        self._set_text(self.text + (label.upper() if capital else label))
        keep_layer = label.isdigit() or (before.isdigit() and label in NUMBER_PUNCTUATION)
        if self.prose and self.layer != "abc" and not keep_layer:
            self.layer = "abc"

    def _set_text(self, text):
        self.text = text
        self._auto_capital()

    def _auto_capital(self):
        """A capital by itself comes and goes with where the text ends. One asked for, or caps lock, stays."""
        if self.prose and self.shift in ("off", "auto"):
            self.shift = "auto" if not self.text or SENTENCE_END.search(self.text) else "off"

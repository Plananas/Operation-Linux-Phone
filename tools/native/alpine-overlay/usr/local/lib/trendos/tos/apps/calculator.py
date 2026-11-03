"""Calculator: + - x / and brackets, live preview, history, safe evaluation.

Look: green-phosphor terminal, like the rest of TREND OS. A framed "calc" display (history,
"> expression" prompt with a block cursor, big glowing result) above a keypad of outlined keys:
dim-green digits, bright-green operators, red clear/delete and an inverse-video "=".

Motion (all short, so the app is idle between key presses apart from the cursor blink):
  * keys flash to inverse video while held and fade back after release,
  * a typed character flares bright, then settles to the prompt colour,
  * "=" decodes the result through the ASCII shading ramp (SHADES), left to right,
  * the finished line scrolls up into the history,
  * C dissolves the line back down the shading ramp, an error shakes.

The keypad is pre-rendered once; key tiles (held / fade levels) are rendered on first use and
cached, so a frame only redraws the display card and the keys that are animating. Display text
goes through a per-character glyph cache (VT323 is monospaced): rasterising a big string with
FreeType costs ~5 ms on the phone, pasting cached glyphs a fraction of that.
"""
import ast, math, operator, time

import numpy as np
from PIL import Image, ImageDraw

from ..config import W, TOP, APP_H, ACCENT, PALETTE, RED, SHADES
from ..gfx import font, to_rgbx
from .base import App

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_eval(expr):
    """Evaluate + - * / ( ) on numbers only: no names, calls or attributes are accepted."""
    def ev(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        raise ValueError("bad expression")
    return ev(ast.parse(expr, mode="eval").body)


def fmt_num(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    if isinstance(v, int) and abs(v) < 10 ** 15:
        return str(v)
    return f"{v:.10g}"


DIV, MUL, MINUS = "÷", "×", "−"
TO_ASCII = {DIV: "/", MUL: "*", MINUS: "-"}
TO_PRETTY = {"/": DIV, "*": MUL, "-": MINUS}
OPERATOR_KEYS = {DIV, MUL, MINUS, "+", "(", ")"}


def pretty(expr):
    """'12*(3-4)' -> '12 x (3 - 4)' with real symbols and spaces around operators."""
    out = []
    for ch in expr:
        if ch in "+-*/":
            out.append(f" {TO_PRETTY.get(ch, ch)} ")
        else:
            out.append(ch)
    return "".join(out).replace("( ", "(").strip()


# ---- palette (shades of the system ACCENT green) -------------------------------------------
BG = (0, 0, 0)
FRAME, FRAME_HI = (0, 85, 48), (0, 150, 85)     # display border / its "calc" label
PANEL, SCAN = (0, 7, 4), (0, 13, 7)             # display fill + faint CRT scanlines
HIST, PREVIEW, DONE_EXPR = (0, 110, 62), (0, 120, 68), (0, 150, 85)
FLARE = (200, 255, 225)                         # fresh phosphor: typed char, decoded result
ERR = PALETTE[RED]
KEY_STYLE = {   # kind: (fill, edge, text, pressed fill)
    "digit": ((0, 10, 6), (0, 72, 42), (190, 245, 210), (150, 230, 185)),
    "op":    ((0, 14, 8), (0, 150, 85), ACCENT, ACCENT),
    "clear": ((14, 3, 3), (125, 42, 42), (255, 110, 110), (255, 110, 110)),
    "eq":    (ACCENT, ACCENT, (0, 0, 0), FLARE),
}
LABELS = {"DEL": "del"}

# ---- timings (s) -----------------------------------------------------------------------------
FADE, LEVELS = 0.30, 5          # key release fade, number of pre-rendered fade steps
TYPE_T = 0.18                   # typed-character flare
SCROLL_T = 0.20                 # history scroll
SHAKE_T = 0.35                  # error shake
DECODE_STEP, DECODE_CHAR = 0.03, 0.16    # "=" decode: stagger per char, ramp time per char
CLEAR_STEP, CLEAR_CHAR = 0.018, 0.16     # "C" dissolve: stagger per char (right to left), ramp


_glyphs = {}


def _glyph(ch, size):
    """(mask cropped to the ink, x offset, y offset, advance) of one character."""
    g = _glyphs.get((ch, size))
    if g is None:
        f = font(size)
        adv, pad = f.getlength(ch), size
        m = Image.new("L", (int(adv) + size, size * 3), 0)
        ImageDraw.Draw(m).text((0, pad), ch, fill=255, font=f)
        bb = m.getbbox()
        g = (m.crop(bb), bb[0], bb[1] - pad, adv) if bb else (None, 0, 0, adv)
        _glyphs[(ch, size)] = g
    return g


def text_len(s, size):
    return sum(_glyph(ch, size)[3] for ch in s)


def draw_text(im, x, y, s, size, colour):
    if im.mode == "RGBX":
        colour = colour + (0,)
    for ch in s:
        m, dx, dy, adv = _glyph(ch, size)
        if m is not None:
            im.paste(colour, (int(x + dx), int(y + dy)), m)
        x += adv


def _kind(k):
    return "eq" if k == "=" else "op" if k in OPERATOR_KEYS else "clear" if k in ("C", "DEL") else "digit"


def _mix(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


class CalculatorApp(App):
    name = "Calculator"
    KEYS = [["C", "(", ")", DIV], ["7", "8", "9", MUL], ["4", "5", "6", MINUS],
            ["1", "2", "3", "+"], ["0", ".", "DEL", "="]]
    KX, KY, KW, KH, GX, GY = 14, 238, 108, 92, 8, 7       # keypad geometry inside the app area
    DISP = (14, 14, W - 14, 222)                          # display card
    HIST_Y, HIST_DY = 30, 24                              # history slot 0 (card-relative), spacing
    EXPR_Y, RES_Y = 82, 122                               # prompt line, result line (card-relative)
    BLINK = 0.53

    def __init__(self):
        self.expr, self.pressed, self.just_eq = "", None, False
        self.shown_expr = ""                              # expression shown after "="
        self.history = []                                 # (pretty expression, result)
        self._base = None
        self.fading = {}                                  # key -> release time
        self.anim_until = 0.0
        self.t_type = self.t_eq = self.t_err = self.t_clear = self.t_scroll = -1.0
        self.cleared = ("", "", PREVIEW, 54)              # (expr line, result, colour, size) being dissolved
        self.scroll_from = []                             # history lines before the scroll

    # ---- input ----
    def key_at(self, x, y):
        y -= TOP
        c, r = int((x - self.KX) // (self.KW + self.GX)), int((y - self.KY) // (self.KH + self.GY))
        if 0 <= r < len(self.KEYS) and 0 <= c < 4:
            x0, y0 = self._key_xy(r, c)
            if x0 <= x <= x0 + self.KW and y0 <= y <= y0 + self.KH:   # not in the gaps
                return self.KEYS[r][c]
        return None

    def touch(self, ev, x, y):
        now = time.monotonic()
        k = self.key_at(x, y)
        if ev == "down":
            self.pressed = k
        elif ev == "move" and k != self.pressed:
            self._release(now)
        elif ev == "up":
            if k is not None and k == self.pressed:
                self.press(k, now)
            self._release(now)

    def _release(self, now):
        if self.pressed is not None:
            self.fading[self.pressed] = now
        self.pressed = None

    def _anim(self, now, dur):
        self.anim_until = max(self.anim_until, now + dur)

    def press(self, k, now=None):
        now = time.monotonic() if now is None else now
        hist_before = self._hist_lines()
        if k == "C":
            line, res, col, size = self._lines(now)
            if line or res:
                self.cleared, self.t_clear = (line, res, col, size), now
                self._anim(now, CLEAR_STEP * max(len(line), len(res)) + CLEAR_CHAR + 0.05)
            self.expr, self.just_eq, self.shown_expr = "", False, ""
        elif k == "DEL":
            self.expr, self.just_eq = ("" if self.just_eq else self.expr[:-1]), False
        elif k == "=":
            e = self.expr
            if not e or self.just_eq:
                return
            try:
                result = fmt_num(safe_eval(e))
            except Exception:                            # syntax error, division by zero, ...
                result = "Error"
            self.shown_expr = pretty(e)
            if result == "Error":
                self.t_err = now; self._anim(now, SHAKE_T)
            else:
                self.history = (self.history + [(self.shown_expr, result)])[-3:]
                self.t_eq = now; self._anim(now, DECODE_STEP * len(result) + DECODE_CHAR + 0.3)
            self.expr, self.just_eq = result, True
        else:
            e = self.expr
            ch = TO_ASCII.get(k, k)
            if e == "Error" or (self.just_eq and (ch.isdigit() or ch in ".(")):
                e = ""                                   # start fresh after a result
            if ch in "+-*/" and e and e[-1] in "+-*/":
                e = e[:-1]                               # replace a trailing operator
            if len(e) < 40:
                e += ch
                self.t_type = now; self._anim(now, TYPE_T)
            self.expr, self.just_eq = e, False
        hist_after = self._hist_lines()
        if hist_after and hist_after != hist_before and hist_after[-1] not in hist_before:
            self.scroll_from, self.t_scroll = hist_before, now      # a new line joins the history
            self._anim(now, SCROLL_T)

    # ---- state -> text ----
    def _hist_lines(self):
        """History lines on screen, oldest first (the newest result stays on the prompt line
        until the next key, then scrolls up into the history)."""
        h = self.history[-3:-1] if self.just_eq else self.history[-2:]
        out = []
        for ex, res in h:
            line = f"{ex} = {res}"
            out.append(line if len(line) <= 32 else "…" + line[-31:])
        return out

    def _preview(self):
        if self.expr and self.expr != "Error":
            try:
                return fmt_num(safe_eval(self.expr))
            except Exception:
                pass
        return ""

    def _lines(self, now):
        """(prompt text without "> ", result text with "= ", result colour, result size)."""
        if self.just_eq:
            res, expr = self.expr, self.shown_expr
            col = ERR if res == "Error" else ACCENT
        else:
            res, expr, col = self._preview(), pretty(self.expr), PREVIEW
        expr = expr if len(expr) <= 23 else "…" + expr[-22:]
        text = "= " + res if res else ""
        return expr, text, col, 54 if len(text) < 13 else 34

    # ---- drawing ----
    def key(self, now):
        for k, t in list(self.fading.items()):
            if now - t >= FADE:
                del self.fading[k]
        animating = now < self.anim_until or bool(self.fading)
        return (self.expr, self.pressed, self.just_eq, len(self.history), int(now / self.BLINK) % 2,
                int(now * 60) if animating else 0)

    def _key_xy(self, r, c):
        return self.KX + c * (self.KW + self.GX), self.KY + r * (self.KH + self.GY)

    def _draw_key(self, d, k, x0, y0, level):
        """level 0 = idle, 1 = fully lit (inverse video); in between = fading back."""
        fill, edge, text, lit = KEY_STYLE[_kind(k)]
        if level > 0:
            fill, edge = _mix(fill, lit, level), _mix(edge, lit, level)
            text = _mix(text, (0, 0, 0) if k != "=" else (0, 60, 35), level ** 0.5)
        x1, y1 = x0 + self.KW, y0 + self.KH
        d.rounded_rectangle([x0, y0, x1, y1], 7, fill=fill, outline=edge, width=2)
        if level == 0 and k != "=":                                       # inner bevel line
            d.line([(x0 + 8, y1 - 5), (x1 - 8, y1 - 5)], fill=_mix(fill, edge, 0.35), width=1)
        lab = LABELS.get(k, k)
        f = font(32 if len(lab) == 1 else 22)
        d.text((x0 + (self.KW - d.textlength(lab, font=f)) / 2, y0 + (self.KH - (36 if len(lab) == 1 else 26)) / 2),
               lab, fill=text, font=f)

    def _tile(self, k, level_idx):
        """Cached RGBX tile of key k at fade step level_idx (LEVELS = held/fully lit)."""
        c = self._tiles.get((k, level_idx))
        if c is None:
            tile = Image.new("RGB", (self.KW + 1, self.KH + 1), BG)
            self._draw_key(ImageDraw.Draw(tile), k, 0, 0, level_idx / LEVELS)
            c = self._tiles[(k, level_idx)] = to_rgbx(tile)
        return c

    def _prerender(self):
        im = Image.new("RGB", (W, APP_H), BG); d = ImageDraw.Draw(im)
        self._rects, self._tiles = {}, {}
        for r, row in enumerate(self.KEYS):
            for c, k in enumerate(row):
                x0, y0 = self._key_xy(r, c)
                self._draw_key(d, k, x0, y0, 0)
                self._rects[k] = (y0, y0 + self.KH + 1, x0, x0 + self.KW + 1)
        self._base = to_rgbx(im)
        self._buf, self._dirty, self._glows = self._base.copy(), [], {}
        # display card background: frame, label cut into the top edge, scanlines
        x0, y0, x1, y1 = self.DISP
        im = Image.new("RGB", (W, y1 + 2), BG); d = ImageDraw.Draw(im)
        d.rounded_rectangle([x0, y0, x1, y1], 9, fill=PANEL, outline=FRAME, width=2)
        for y in range(y0 + 4, y1 - 2, 3):
            d.line([(x0 + 3, y), (x1 - 3, y)], fill=SCAN)
        f = font(16)
        label = " calc "
        lw = d.textlength(label, font=f)
        d.rectangle([x0 + 18, y0 - 2, x0 + 18 + lw, y0 + 2], fill=BG)
        d.text((x0 + 18, y0 - 10), label, fill=FRAME_HI, font=f)
        self._disp_bg = im.convert("RGBX")      # framebuffer byte order: no conversion per frame

    def render(self, now):
        """Draws into one persistent buffer: keys drawn over the base last frame are restored,
        then this frame's lit keys and the display card are drawn on top."""
        if self._base is None:
            self._prerender()
        buf = self._buf
        for k in self._dirty:
            y0, y1, x0, x1 = self._rects[k]
            buf[y0:y1, x0:x1] = self._base[y0:y1, x0:x1]
        self._dirty = []
        for k, t in self.fading.items():
            if k != self.pressed:
                lvl = math.ceil(LEVELS * (1 - (now - t) / FADE) ** 2)
                if lvl > 0:
                    y0, y1, x0, x1 = self._rects[k]
                    buf[y0:y1, x0:x1] = self._tile(k, min(lvl, LEVELS - 1))
                    self._dirty.append(k)
        if self.pressed:
            y0, y1, x0, x1 = self._rects[self.pressed]
            buf[y0:y1, x0:x1] = self._tile(self.pressed, LEVELS)
            self._dirty.append(self.pressed)
        h = self.DISP[3] + 2
        buf[:h] = np.frombuffer(self._display(now).tobytes(), np.uint8).reshape(h, W, 4)
        return buf

    def _display(self, now):
        x0, y0, x1, y1 = self.DISP
        im = self._disp_bg.copy()
        right = x1 - 20
        self._draw_history(im, now, right)

        expr, res, rcol, rsize = self._lines(now)
        tx, ty = x0 + 18, y0 + self.EXPR_Y

        # "C": the old line dissolves down the shading ramp, right to left
        tc = now - self.t_clear
        clearing = 0 <= tc < CLEAR_STEP * max(len(self.cleared[0]), len(self.cleared[1])) + CLEAR_CHAR
        if clearing:
            old_expr, old_res, old_col, old_size = self.cleared
            draw_text(im, tx, ty, "> ", 25, ACCENT)
            draw_text(im, tx + text_len("> ", 25), ty, self._dissolve(old_expr, tc), 25,
                      _mix(DONE_EXPR, FRAME, tc / 0.3))
            if old_res:
                draw_text(im, right - text_len(old_res, old_size), y0 + self.RES_Y + (0 if old_size == 54 else 12),
                          self._dissolve(old_res, tc), old_size, _mix(old_col, FRAME, tc / 0.3))
            return im

        # prompt line: "> expression", newest character flaring, blinking block cursor
        line = "> " + expr
        if self.just_eq:
            draw_text(im, tx, ty, line, 25, DONE_EXPR)
        else:
            tt = now - self.t_type
            flare = 0 <= tt < TYPE_T and expr
            draw_text(im, tx, ty, line[:-1] if flare else line, 25, ACCENT)
            if flare:
                draw_text(im, tx + text_len(line[:-1], 25), ty, line[-1], 25, _mix(FLARE, ACCENT, tt / TYPE_T))
            if int(now / self.BLINK) % 2 == 0 or 0 <= tt < TYPE_T:
                cx = tx + text_len(line, 25)
                ImageDraw.Draw(im).rectangle([cx + 3, ty + 3, cx + 14, ty + 29], fill=ACCENT + (0,))

        # result line: live preview (dim) while typing, decoded + glowing after "="
        if res:
            ry = y0 + self.RES_Y + (0 if rsize == 54 else 12)
            rx = right - text_len(res, rsize)
            shown, col = res, rcol
            te, ts = now - self.t_eq, now - self.t_err
            if self.just_eq and rcol == ERR and 0 <= ts < SHAKE_T:
                rx += int(11 * math.sin(ts * 60) * (1 - ts / SHAKE_T))
            elif self.just_eq and 0 <= te:
                num = res[2:]
                done = DECODE_STEP * len(num) + DECODE_CHAR
                shown = "= " + self._decode(num, te)
                col = _mix(FLARE, ACCENT, (te - done) / 0.3) if te < done + 0.3 else ACCENT
            if self.just_eq and rcol != ERR:
                gm, gx, gy = self._glow(res, rsize)
                im.paste(ACCENT + (0,), (int(rx + gx), int(ry + gy)), gm)
            draw_text(im, rx, ry, shown, rsize, col)
        return im

    def _draw_history(self, im, now, right):
        """History lines, bottom-aligned above the prompt; a new line scrolls up from the prompt
        while the oldest scrolls out through the top of the card."""
        y0 = self.DISP[1]
        lines = self._hist_lines()
        ts = now - self.t_scroll
        if 0 <= ts < SCROLL_T:
            off = self.HIST_DY * (1 - _ease(ts / SCROLL_T))
            if len(self.scroll_from) == 2:                 # its oldest line scrolls out
                lines = self.scroll_from[:1] + lines
        else:
            off, ts = 0.0, SCROLL_T
        n = len(lines)
        for i, line in enumerate(lines):
            slot = 2 - n + i                               # 1 = just above the prompt, -1 = leaving
            y = y0 + self.HIST_Y + slot * self.HIST_DY + off
            col = HIST
            if n == 3 and i == 0:                          # leaving through the top
                col = _mix(HIST, PANEL, ts / SCROLL_T)
            elif i == n - 1 and off > 0:                   # arriving from the prompt line
                col = _mix(DONE_EXPR, HIST, ts / SCROLL_T)
            draw_text(im, right - text_len(line, 17), y, line, 17, col)
        if off > 0:                                        # clip what left the card at the top
            clip = y0 + self.HIST_Y - 6
            im.paste(self._disp_bg.crop((0, 0, W, clip)), (0, 0))

    @staticmethod
    def _decode(s, t):
        """Characters build up through the shading ramp, left to right, then lock in."""
        out = []
        for i, ch in enumerate(s):
            p = (t - i * DECODE_STEP) / DECODE_CHAR
            out.append(ch if p >= 1 else " " if p <= 0 else SHADES[1 + int(p * (len(SHADES) - 1)) % (len(SHADES) - 1)])
        return "".join(out)

    @staticmethod
    def _dissolve(s, t):
        """Characters fall back down the shading ramp, right to left, then vanish."""
        out, n = [], len(s)
        for i, ch in enumerate(s):
            p = (t - (n - 1 - i) * CLEAR_STEP) / CLEAR_CHAR
            if p <= 0 or ch == " ":
                out.append(ch)
            elif p >= 1:
                out.append(" ")
            else:
                out.append(SHADES[max(1, int((1 - p) * (len(SHADES) - 1)))])
        return "".join(out)

    def _glow(self, text, size):
        """Phosphor bloom behind the result: a blurred copy of its mask (box-downscale +
        bilinear upscale, cheap), cached per text. Returns (mask, x offset, y offset)."""
        g = self._glows.get((text, size))
        if g is None:
            pad, w = 10, int(text_len(text, size)) + 20
            h = size + 2 * pad
            mask = Image.new("L", (w, h), 0)
            draw_text(mask, pad, pad, text, size, 95)
            mask = mask.resize((max(1, w // 6), max(1, h // 6)), Image.BOX).resize((w, h), Image.BILINEAR)
            if len(self._glows) > 16:
                self._glows.clear()
            g = self._glows[(text, size)] = (mask, -pad, -pad)
        return g

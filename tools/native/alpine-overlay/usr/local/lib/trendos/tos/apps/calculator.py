"""Calculator: + - x / and brackets, live preview, history, safe evaluation.

Look: a terminal-style display (history, "> expression" prompt with a blinking cursor, big
result) above a keypad of dark keys (digits), amber keys (operators), red keys (C/DEL) and a
solid green "=". The keypad is pre-rendered once with a "pressed" tile per key, so a press only
redraws the display and one key.
"""
import ast, operator

from PIL import Image, ImageDraw

from ..config import W, TOP, APP_H, ACCENT, PALETTE, ORANGE
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


# ---- palette ------------------------------------------------------------------------------
BG = (0, 0, 0)
DISP_FILL, DISP_EDGE = (6, 13, 9), (0, 80, 45)
AMBER = PALETTE[ORANGE]
KEY_STYLE = {   # kind: (fill, edge, text)
    "digit": ((18, 24, 21), (44, 62, 52), (236, 236, 236)),
    "op":    ((30, 21, 8), (115, 72, 20), AMBER),
    "clear": ((32, 12, 12), (115, 42, 42), (255, 120, 120)),
    "eq":    ((0, 165, 92), (0, 210, 120), (0, 0, 0)),
}


def _kind(k):
    return "eq" if k == "=" else "op" if k in OPERATOR_KEYS else "clear" if k in ("C", "DEL") else "digit"


def _lift(c, d):
    return tuple(min(255, v + d) for v in c)


class CalculatorApp(App):
    name = "Calculator"
    KEYS = [["C", "(", ")", DIV], ["7", "8", "9", MUL], ["4", "5", "6", MINUS],
            ["1", "2", "3", "+"], ["0", ".", "DEL", "="]]
    KX, KY, KW, KH, GX, GY = 14, 238, 108, 92, 8, 7       # keypad geometry inside the app area
    DISP = (14, 12, W - 14, 222)                          # display card
    BLINK = 0.53

    def __init__(self):
        self.expr, self.pressed, self.just_eq = "", None, False
        self.shown_expr = ""                              # expression shown after "="
        self.history = []                                 # (pretty expression, result)
        self._base = None

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
        k = self.key_at(x, y)
        if ev == "down":
            self.pressed = k
        elif ev == "move" and k != self.pressed:
            self.pressed = None
        elif ev == "up":
            if k is not None and k == self.pressed:
                self.press(k)
            self.pressed = None

    def press(self, k):
        e = self.expr
        if k == "C":
            self.expr, self.just_eq, self.shown_expr = "", False, ""
            return
        if k == "DEL":
            self.expr, self.just_eq = ("" if self.just_eq else e[:-1]), False
            return
        if k == "=":
            if not e or self.just_eq:
                return
            try:
                result = fmt_num(safe_eval(e))
            except Exception:                            # syntax error, division by zero, ...
                result = "Error"
            self.shown_expr = pretty(e)
            if result != "Error":
                self.history = (self.history + [(self.shown_expr, result)])[-2:]
            self.expr, self.just_eq = result, True
            return
        ch = TO_ASCII.get(k, k)
        if e == "Error" or (self.just_eq and (ch.isdigit() or ch in ".(")):
            e = ""                                       # start fresh after a result
        if ch in "+-*/" and e and e[-1] in "+-*/":
            e = e[:-1]                                   # replace a trailing operator
        if len(e) < 40:
            e += ch
        self.expr, self.just_eq = e, False

    # ---- drawing ----
    def key(self, now):
        return (self.expr, self.pressed, self.just_eq, len(self.history), int(now / self.BLINK) % 2)

    def _key_xy(self, r, c):
        return self.KX + c * (self.KW + self.GX), self.KY + r * (self.KH + self.GY)

    def _draw_key(self, d, k, x0, y0, pressed):
        fill, edge, text = KEY_STYLE[_kind(k)]
        if pressed:
            fill, edge = _lift(fill, 55), _lift(edge, 70)
        x1, y1 = x0 + self.KW, y0 + self.KH
        d.rounded_rectangle([x0, y0, x1, y1], 14, fill=fill, outline=edge, width=2)
        d.line([(x0 + 14, y0 + 3), (x1 - 14, y0 + 3)], fill=_lift(fill, 22), width=1)   # top highlight
        f = font(30 if k != "DEL" else 21)
        d.text((x0 + (self.KW - d.textlength(k, font=f)) / 2, y0 + (self.KH - 34) / 2), k, fill=text, font=f)

    def _prerender(self):
        im = Image.new("RGB", (W, APP_H), BG); d = ImageDraw.Draw(im)
        self._rects, self._pressed = {}, {}
        for r, row in enumerate(self.KEYS):
            for c, k in enumerate(row):
                x0, y0 = self._key_xy(r, c)
                self._draw_key(d, k, x0, y0, False)
                self._rects[k] = (y0, y0 + self.KH + 1, x0, x0 + self.KW + 1)
                tile = Image.new("RGB", (self.KW + 1, self.KH + 1), BG)
                self._draw_key(ImageDraw.Draw(tile), k, 0, 0, True)
                self._pressed[k] = to_rgbx(tile)
        self._base = to_rgbx(im)

    def render(self, now):
        if self._base is None:
            self._prerender()
        img = self._base.copy()
        if self.pressed:
            y0, y1, x0, x1 = self._rects[self.pressed]
            img[y0:y1, x0:x1] = self._pressed[self.pressed]
        x0, y0, x1, y1 = self.DISP
        img[:y1 + 2] = self._display(now)
        return img

    def _display(self, now):
        x0, y0, x1, y1 = self.DISP
        im = Image.new("RGB", (W, y1 + 2), BG); d = ImageDraw.Draw(im)
        d.rounded_rectangle([x0, y0, x1, y1], 16, fill=DISP_FILL, outline=DISP_EDGE, width=2)
        right = x1 - 18
        f_hist, f_expr = font(17, bold=False), font(25)
        # history (most recent last), right-aligned
        for i, (ex, res) in enumerate(self.history[-2:] if not self.just_eq else self.history[-3:-1]):
            line = f"{ex} = {res}"
            if len(line) > 32: line = "…" + line[-31:]
            d.text((right - d.textlength(line, font=f_hist), y0 + 14 + i * 22), line, fill=(95, 110, 100), font=f_hist)
        # expression line with prompt + cursor
        if self.just_eq:
            expr, col, cursor = self.shown_expr, (120, 170, 140), False
        else:
            expr, col, cursor = pretty(self.expr), ACCENT, int(now / self.BLINK) % 2 == 0
        expr = expr if len(expr) <= 23 else "…" + expr[-22:]
        tx, ty = x0 + 18, y0 + 72
        d.text((tx, ty), "> " + expr, fill=col, font=f_expr)
        if cursor:
            cx = tx + d.textlength("> " + expr, font=f_expr)
            d.rectangle([cx + 2, ty + 3, cx + 14, ty + 29], fill=ACCENT)
        # result: bright after "=", dimmer live preview while typing
        if self.just_eq:
            res = self.expr
            rcol = (255, 95, 95) if res == "Error" else AMBER
        else:
            res = ""
            if self.expr and self.expr != "Error":
                try:
                    res = fmt_num(safe_eval(self.expr))
                except Exception:
                    res = ""
            rcol = tuple(int(v * 0.55) for v in AMBER)
        if res:
            text = "= " + res
            big = font(54 if len(text) < 13 else 34)
            d.text((right - d.textlength(text, font=big), y0 + 118 + (0 if len(text) < 13 else 12)), text,
                   fill=rcol, font=big)
        return to_rgbx(im)

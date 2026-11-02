"""Calculator: + - x / and brackets, live preview, safe evaluation (numbers and operators only).

The keypad is pre-rendered once together with a "pressed" tile per key, so a key press only
redraws the display strip and one key (~20 ms).
"""
import ast, operator

from ..config import W, TOP, APP_H, ACCENT, DIM, PALETTE, ORANGE
from ..gfx import canvas, font, to_rgbx
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


class CalculatorApp(App):
    name = "Calculator"
    KEYS = [["C", "(", ")", DIV], ["7", "8", "9", MUL], ["4", "5", "6", MINUS],
            ["1", "2", "3", "+"], ["0", ".", "DEL", "="]]
    KX, KY, KW, KH, GAP = 14, 222, 113, 96, 4          # keypad geometry inside the app area
    DISP_H = 210                                        # display strip at the top of the app area

    def __init__(self):
        self.expr, self.pressed, self.just_eq = "", None, False
        self._base = self._pressed = None

    # ---- input ----
    def key_at(self, x, y):
        y -= TOP
        c, r = int((x - self.KX) // (self.KW + self.GAP)), int((y - self.KY) // (self.KH + self.GAP))
        return self.KEYS[r][c] if 0 <= r < len(self.KEYS) and 0 <= c < 4 else None

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
            e = ""
        elif k == "DEL":
            e = e[:-1]
        elif k == "=":
            try:
                e = fmt_num(safe_eval(e)) if e else ""
            except Exception:                            # syntax error, division by zero, ...
                e = "Error"
            self.expr, self.just_eq = e, True
            return
        else:
            ch = TO_ASCII.get(k, k)
            if e == "Error" or (self.just_eq and (ch.isdigit() or ch in ".(")):
                e = ""                                   # start fresh after a result
            if ch in "+-*/" and e and e[-1] in "+-*/":
                e = e[:-1]                               # replace a trailing operator
            if len(e) < 40:
                e += ch
        self.expr, self.just_eq = e, False

    # ---- drawing ----
    def key(self, now):
        return (self.expr, self.pressed)

    def _key_xy(self, r, c):
        return self.KX + c * (self.KW + self.GAP), self.KY + r * (self.KH + self.GAP)

    def _draw_key(self, d, k, x0, y0, pressed):
        fill = (0, 90, 50) if k == "=" else (0, 0, 0)
        if pressed:
            fill = (0, 160, 90) if k == "=" else (40, 110, 70)
        d.rounded_rectangle([x0, y0, x0 + self.KW, y0 + self.KH], 10, fill=fill,
                            outline=ACCENT if k == "=" else DIM, width=2)
        colour = (PALETTE[ORANGE] if k in OPERATOR_KEYS else (255, 110, 110) if k in ("C", "DEL")
                  else ACCENT if k == "=" else (230, 230, 230))
        f = font(30 if k != "DEL" else 22)
        d.text((x0 + (self.KW - d.textlength(k, font=f)) / 2, y0 + (self.KH - 34) / 2), k, fill=colour, font=f)

    def _prerender(self):
        im, d = canvas(APP_H)
        self._rects, self._pressed = {}, {}
        for r, row in enumerate(self.KEYS):
            for c, k in enumerate(row):
                x0, y0 = self._key_xy(r, c)
                self._draw_key(d, k, x0, y0, False)
                self._rects[k] = (y0, y0 + self.KH + 1, x0, x0 + self.KW + 1)
                tile, td = canvas(self.KH + 1, self.KW + 1)
                self._draw_key(td, k, 0, 0, True)
                self._pressed[k] = to_rgbx(tile)
        self._base = to_rgbx(im)

    def render(self, now):
        if self._base is None:
            self._prerender()
        img = self._base.copy()
        if self.pressed:
            y0, y1, x0, x1 = self._rects[self.pressed]
            img[y0:y1, x0:x1] = self._pressed[self.pressed]
        img[:self.DISP_H] = self._display()
        return img

    def _display(self):
        im, d = canvas(self.DISP_H)
        shown = "".join(TO_PRETTY.get(ch, ch) for ch in self.expr)
        preview = ""
        if self.expr and not self.just_eq and self.expr != "Error":
            try:
                preview = fmt_num(safe_eval(self.expr))
            except Exception:
                pass
        main = (self.expr if self.just_eq else preview) or ("0" if not self.expr else "")
        f_expr, big = font(24, bold=False), font(56 if len(main) < 12 else 34)
        d.rectangle([14, 16, W - 14, 196], outline=DIM)
        d.text((W - 30 - d.textlength(shown[-26:], font=f_expr), 40), shown[-26:], fill=(200, 200, 200), font=f_expr)
        colour = (255, 90, 90) if self.expr == "Error" else PALETTE[ORANGE]
        d.text((W - 30 - d.textlength(main[-14:], font=big), 110), main[-14:], fill=colour, font=big)
        return to_rgbx(im)

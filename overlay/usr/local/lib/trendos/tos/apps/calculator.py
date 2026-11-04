"""Calculator: + - x / and brackets, live preview, history.

The app itself is C: native/libtrend/src/apps/calculator.c (behaviour) and calculator_view.c
(drawing). This class connects it to the shell and hands it the fonts, which PIL rasterises once.
"""
import time

import numpy as np

from .. import canvas, native
from ..config import ACCENT, APP_H, PALETTE, RED, SHADES, TOP, W
from .base import App

MINUS_SLOT, ELLIPSIS_SLOT = 0x96, 0x85          # native/libtrend/include/trend/apps/calculator.h
DISPLAY_CHARS = "0123456789.+-*/=()> Erorinfae" + SHADES + "÷×"
EXTRA_GLYPHS = {MINUS_SLOT: "−", ELLIPSIS_SLOT: "…"}
FONT_CHARS = {                                  # size: the characters drawn at that size
    16: " calc", 17: DISPLAY_CHARS, 22: "del", 25: DISPLAY_CHARS,
    32: "C()0123456789.=+÷×", 34: DISPLAY_CHARS, 54: DISPLAY_CHARS,
}


def _theme():
    tables = [canvas.font_table(size, chars, EXTRA_GLYPHS) for size, chars in FONT_CHARS.items()]
    return native.calc_theme(tables, SHADES, ACCENT, PALETTE[RED])


class CalculatorApp(App):
    name = "Calculator"

    def __init__(self):
        self._state = native.calc_new()
        self._theme = None
        self._buf = None

    def touch(self, ev, x, y):
        native.calc_touch(self._state, ev, x, y - TOP, time.monotonic())

    def key(self, now):
        return native.calc_frame_key(self._state, now)

    def render(self, now):
        if self._buf is None:
            self._theme = _theme()
            self._buf = np.zeros((APP_H, W, 4), np.uint8)
        native.calc_render(self._state, self._theme, now, self._buf)
        return self._buf

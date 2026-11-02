"""Power menu (hold Power): Shut down / Restart / Cancel, and full-screen messages."""
from .config import W, H, TOP, APP_H, ACCENT
from .gfx import canvas, centre_text, font, to_rgbx

SHUTDOWN, RESTART, CANCEL = range(3)
BUTTONS = [("Shut down", (255, 90, 90)), ("Restart", (255, 200, 60)), ("Cancel", (170, 170, 170))]
BX, BW, BH, BY0, GAP = 60, 360, 84, 220, 24             # inside the app area (y from TOP)


def button_at(x, y):
    y -= TOP
    for i in range(len(BUTTONS)):
        y0 = BY0 + i * (BH + GAP)
        if BX <= x <= BX + BW and y0 <= y <= y0 + BH:
            return i
    return None


def render(pressed):
    im, d = canvas(APP_H)
    centre_text(d, 130, "Power", font(30), ACCENT)
    f = font(28)
    for i, (name, colour) in enumerate(BUTTONS):
        y0 = BY0 + i * (BH + GAP)
        d.rounded_rectangle([BX, y0, BX + BW, y0 + BH], 14,
                            fill=(45, 45, 45) if i == pressed else (0, 0, 0), outline=colour, width=3)
        centre_text(d, y0 + (BH - 32) / 2, name, f, colour)
    return to_rgbx(im)


def message(text):
    im, d = canvas(H)
    centre_text(d, H / 2 - 20, text, font(30), ACCENT)
    return to_rgbx(im)

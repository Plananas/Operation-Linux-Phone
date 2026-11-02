"""Power menu (hold Power), in the TREND OS terminal style.

The screen behind is frozen and dims smoothly; a card fades/slides in, options appear one after
another and the title types itself ("> power"). Cancel reverses the animation; Shut down /
Restart type a status line, fade the whole screen to black and then run the command.

PowerMenu.frame(now) returns (key, draw): the shell calls draw(page) only when the key changed for
that page, so the menu costs nothing once its animation has settled. Dimming and fading use the
C helpers in librender.so (Renderer.scale / Renderer.blend) and draw straight into the page.
"""
import numpy as np
from PIL import Image, ImageDraw

from .config import W, H, ACCENT, GREY, DIM
from .gfx import canvas, font, to_rgbx

SHUTDOWN, RESTART, CANCEL = range(3)
ITEMS = [("shut down", (255, 90, 90)), ("restart", (255, 200, 60)), ("cancel", (170, 170, 170))]

# card geometry (screen coordinates)
CX0, CY0, CWD, CHT = 40, 236, 400, 400
TITLE_DY, RULE_DY, ITEM_DY, ITEM_H, ITEM_GAP, ITEM_X = 26, 80, 112, 66, 16, 28
OPEN_T, CLOSE_T, FADE_T = 0.30, 0.20, 0.45
DIM_TO = 0.30                         # background brightness when the menu is open
TYPE_DT, BLINK = 0.045, 0.53


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _scale(c, a):
    return tuple(int(v * a) for v in c)


class PowerMenu:
    def __init__(self, snapshot, now, renderer):
        """snapshot: the screen currently visible (H x W x 4), shown dimmed behind the card."""
        self.snap, self.r = snapshot, renderer
        self._card_cache = (None, None)
        self.phase, self.t0 = "open", now        # open -> idle -> close | halting -> fading
        self.pressed = None
        self.action = None                       # SHUTDOWN / RESTART once chosen
        self.status = ""

    # ---- state ----
    def done_closing(self, now):
        return self.phase == "close" and now - self.t0 >= CLOSE_T

    def ready_to_halt(self, now):
        return self.phase == "fading" and now - self.t0 >= FADE_T

    def item_at(self, x, y):
        for i in range(len(ITEMS)):
            y0 = CY0 + ITEM_DY + i * (ITEM_H + ITEM_GAP)
            if CX0 + 16 <= x <= CX0 + CWD - 16 and y0 <= y <= y0 + ITEM_H:
                return i
        return None

    def cancel(self, now):
        if self.phase in ("open", "idle"):
            # reverse from wherever the opening animation got to
            k = min(1.0, (now - self.t0) / OPEN_T) if self.phase == "open" else 1.0
            self.phase, self.t0 = "close", now - (1 - k) * CLOSE_T

    def touch(self, kind, x, y, now):
        if self.phase not in ("open", "idle"):
            return
        i = self.item_at(x, y)
        if kind == "down":
            self.pressed = i
        elif kind == "move" and i != self.pressed:
            self.pressed = None
        elif kind == "up":
            if i is not None and i == self.pressed:
                if i == CANCEL:
                    self.cancel(now)
                else:
                    self.action = i
                    self.status = "shutting down" if i == SHUTDOWN else "restarting"
                    self.phase, self.t0 = "halting", now
            self.pressed = None

    # ---- animation parameters at time `now` ----
    def _params(self, now):
        t = now - self.t0
        if self.phase == "open":
            if t >= OPEN_T + 7 * TYPE_DT:        # opening animation and title typing finished
                self.phase, self.t0 = "idle", now - OPEN_T
            k = min(1.0, t / OPEN_T)
            return _ease(k), k, t
        if self.phase == "idle":
            return 1.0, 1.0, t
        if self.phase == "close":
            k = max(0.0, 1 - t / CLOSE_T)
            return _ease(k), 1.0, 99.0
        if self.phase == "halting":
            if t >= len(self.status) * TYPE_DT + 0.6:
                self.phase, self.t0 = "fading", now
            return 1.0, 1.0, 99.0
        return 1.0, 1.0, 99.0                    # fading

    def frame(self, now):
        """(key, render callable) for the current frame."""
        e, k, t = self._params(now)
        t_phase = now - self.t0
        if self.phase == "open":
            key = ("open", round(t_phase, 3))
        elif self.phase == "idle":
            key = ("idle", self.pressed, int(t_phase / BLINK) % 2)
        elif self.phase == "close":
            key = ("close", round(t_phase, 3))
        elif self.phase == "halting":
            key = ("halt", int(t_phase / TYPE_DT), int(t_phase / BLINK) % 2)
        else:
            key = ("fade", round(t_phase, 3))
        return key, lambda buf: self._draw(buf, now, e, k, t)

    # ---- drawing ----
    # The card is composed every frame from layers that are drawn once with PIL: the box, one
    # image per option (normal + pressed), the footer, and title strips (cached per text).
    # Fading/sliding the layers uses the C blend, so an animation frame costs a few ms.
    CARD_BG, ITEM_BG = (4, 10, 7), (10, 16, 13)

    def _layers(self):
        if hasattr(self, "_base"):
            return
        im, d = canvas(CHT, CWD)
        d.rounded_rectangle([0, 0, CWD - 1, CHT - 1], 16, fill=self.CARD_BG, outline=_scale(ACCENT, 0.55), width=2)
        d.line([(ITEM_X, RULE_DY), (CWD - ITEM_X, RULE_DY)], fill=DIM, width=1)
        self._base = to_rgbx(im)
        iw, f_item = CWD - 32, font(26)
        self._items = []
        for name, colour in ITEMS:
            pair = []
            for pressed in (False, True):
                im = Image.new("RGB", (iw, ITEM_H + 1), self.CARD_BG); d = ImageDraw.Draw(im)
                if pressed:
                    d.rounded_rectangle([0, 0, iw - 1, ITEM_H], 10, fill=_scale(colour, 0.9))
                    d.text((32, (ITEM_H - 30) / 2), name, fill=(0, 0, 0), font=f_item)
                else:
                    d.rounded_rectangle([0, 0, iw - 1, ITEM_H], 10, fill=self.ITEM_BG, outline=DIM, width=1)
                    d.rectangle([10, 14, 15, ITEM_H - 14], fill=colour)
                    d.text((32, (ITEM_H - 30) / 2), name, fill=colour, font=f_item)
                pair.append(to_rgbx(im))
            self._items.append(pair)
        im = Image.new("RGB", (CWD - 40, 20), self.CARD_BG); d = ImageDraw.Draw(im)
        foot, f = "back or home to cancel", font(15, bold=False)
        d.text(((CWD - 40 - d.textlength(foot, font=f)) / 2, 0), foot, fill=GREY, font=f)
        self._foot = to_rgbx(im)
        self._titles = {}

    def _title(self, text, cursor):
        k = (text, cursor)
        if k not in self._titles:
            f = font(28)
            im = Image.new("RGB", (CWD - 2 * ITEM_X, 40), self.CARD_BG); d = ImageDraw.Draw(im)
            d.text((0, 2), text, fill=ACCENT, font=f)
            if cursor:
                x = d.textlength(text, font=f)
                d.rectangle([x + 2, 6, x + 15, 34], fill=ACCENT)
            self._titles[k] = to_rgbx(im)
        return self._titles[k]

    def _card(self, k, t, now):
        """Card (CHT x CWD x 4). k: opening progress (item stagger), t: time for typing."""
        self._layers()
        card = self._base.copy()
        if self.phase in ("halting", "fading"):
            th = now - self.t0 if self.phase == "halting" else 99
            n = min(len(self.status), int(th / TYPE_DT))
            dots = min(3, int(max(0.0, th - len(self.status) * TYPE_DT) / 0.15))
            title = self._title("> " + self.status[:n] + "." * dots, True)
        else:
            n = min(5, int(max(0.0, t - OPEN_T * 0.4) / TYPE_DT))
            title = self._title("> " + "power"[:n], n < 5 or int(t / BLINK) % 2 == 0)
        card[TITLE_DY - 2:TITLE_DY + 38, ITEM_X:CWD - ITEM_X] = title
        if self.phase in ("halting", "fading"):
            return card
        for i in range(len(ITEMS)):
            a = _ease((k - 0.25 - 0.12 * i) / 0.45)            # staggered fade + slide in
            if a <= 0.01:
                continue
            img = self._items[i][i == self.pressed]
            y0 = ITEM_DY + i * (ITEM_H + ITEM_GAP) + int(10 * (1 - a))
            region = card[y0:y0 + img.shape[0], 16:16 + img.shape[1]]
            if a >= 0.99:
                region[:] = img
            else:
                self.r.blend(region, img, a)
        fa = _ease((k - 0.6) / 0.4)
        if fa > 0.01:
            self.r.blend(card[CHT - 40:CHT - 20, 20:CWD - 20], self._foot, fa)
        return card

    def _card_cached(self, k, t, now):
        """Reuse the card while idle (cursor blink and pressed state are part of the key)."""
        if self.phase == "idle":
            key = (self.pressed, int(t / BLINK) % 2)
            if self._card_cache[0] != key:
                self._card_cache = (key, self._card(k, t, now))
            return self._card_cache[1]
        return self._card(k, t, now)

    def _draw(self, buf, now, e, k, t):
        """Draw the frame into page buf: dimmed snapshot + card faded in by e (slides up)."""
        fading = self.phase == "fading"
        f = _ease((now - self.t0) / FADE_T) if fading else 0.0
        q = DIM_TO * (1 - f) if fading else 1 - (1 - DIM_TO) * e
        self.r.scale(buf, self.snap, q)
        card_a = 1 - f if fading else e
        if card_a > 0.01:
            card = self._card_cached(k, t, now)
            y0 = CY0 + int(24 * (1 - e)) if self.phase in ("open", "close") else CY0
            region = buf[y0:y0 + CHT, CX0:CX0 + CWD]
            if card_a >= 0.99:
                region[:] = card
            else:
                self.r.blend(region, card, card_a)


def message(text):
    """Plain full-screen message (fallback)."""
    im, d = canvas(H)
    f = font(30)
    d.text(((W - d.textlength(text, font=f)) / 2, H / 2 - 20), text, fill=ACCENT, font=f)
    return to_rgbx(im)

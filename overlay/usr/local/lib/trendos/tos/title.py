"""Title line typewriter: "TREND OS" is backspaced in place, then the greeting is typed from
the point where the finished text will be centred (letters never shift); the cursor blinks
before, stays solid while typing and disappears after."""
import random

from .config import W, TITLE_H, ACCENT
from .gfx import canvas, font, to_rgbx


class TitleAnim:
    BLINK = 0.53

    def __init__(self, text_from, text_to):
        self.font = font(28)
        _, d = canvas(1, 1)
        self.x0 = (W - d.textlength(text_from, font=self.font)) / 2
        self.x1 = (W - d.textlength(text_to, font=self.font)) / 2
        self.cw = d.textlength("M", font=self.font)
        t, ev = 0.9, []
        for i in range(len(text_from), -1, -1):                    # backspace
            ev.append((t, text_from[:i])); t += 0.055 + random.uniform(0, 0.035)
        self.t_erased = t
        self.t_type = t + 0.45
        t = self.t_type
        for i, ch in enumerate(text_to, 1):                         # type
            t += 0.055 + random.uniform(0, 0.075) + (0.12 if ch in " ,." else 0)
            ev.append((t, text_to[:i]))
        self.events, self.t_first, self.t_last = ev, ev[0][0], ev[-1][0]
        self.final = (text_to, False, self.x1)

    def state(self, t):
        """(text, cursor visible, x) at time t since the animation started."""
        if t > self.t_last + 0.5:
            return self.final                                       # done: no more scanning
        if self.t_erased < t < self.t_type:                         # cursor hops to the new start
            frac = (t - self.t_erased) / (self.t_type - self.t_erased)
            return "", frac < 0.3 or frac > 0.6, self.x0 if frac < 0.5 else self.x1
        text = self.events[0][1]
        for te, tx in self.events:
            if te > t:
                break
            text = tx
        x = self.x0 if t <= self.t_erased else self.x1
        typing = self.t_first <= t <= self.t_last + 0.5
        return text, typing or int(t / self.BLINK) % 2 == 0, x

    def render(self, text, cursor, x0):
        im, d = canvas(TITLE_H)
        d.text((x0, 0), text, fill=ACCENT, font=self.font)
        if cursor:
            x = x0 + d.textlength(text, font=self.font)
            d.rectangle([x + 1, 4, x + self.cw - 2, 33], fill=ACCENT)
        return to_rgbx(im)

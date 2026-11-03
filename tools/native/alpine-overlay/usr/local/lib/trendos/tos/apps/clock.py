"""Clock: glowing seven-segment time, date, internet-sync status, and up to four alarms.

Screens (self.mode):
  main  "clock" card: HH:MM in phosphor 7-segment digits (unlit segments faintly visible, like a
        real VFD), a 60-tick seconds bar, the date and whether the time is synced (busybox ntpd,
        OpenRC service "timesync"). "alarms" card: the next alarm, then one row per alarm
        (time, repeat days, on/off switch) and "+ new alarm". Tap a row to edit it.
  edit  the alarm's time (- / + under hours and minutes, hold to repeat), repeat days
        (none = one-off, switched off after it rings), delete / cancel / save.
  ring  the alarm is going off: flashing time, snooze 5 min / stop. Volume keys snooze.

Alarms ring even when the Clock isn't open or the screen is off: the shell calls background()
about once a second (every few seconds while asleep) and brings the app to the front, waking
the screen, when it returns True. The tone is generated on first use and played through the
loudspeaker, getting louder over the first 20 s; it stops by itself after 10 minutes.
Alarms are kept in ALARMS_FILE.
"""
import json, math, os, subprocess, threading, time, wave

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..config import W, TOP, APP_H, ACCENT, CW, CH
from ..gfx import font, to_rgbx, text_len, draw_text
from ..models import Shape
from ..models.icons import CLOCK_HANDS, _hand, clock_face, hand_angles
from ..render import TILES, card_tiles, matrix
from ..ui import BG, PANEL, SCAN, DIM, MID, GHOST, FLARE, ERR, Keys, card, mix
from .base import App

ALARMS_FILE = "/var/lib/trendos/alarms.json"
SYNC_FILE = "/tmp/ntp-last-sync"              # written by /usr/local/sbin/ntp-synced
TONE_RAMP, TONE_LOOP = "/tmp/trendos-alarm-ramp.wav", "/tmp/trendos-alarm-loop.wav"
PLAY = ["aplay", "-q", "-D", "hw:CARD=sprdphone,DEV=0"]
MAX_ALARMS, SNOOZE, RING_MAX = 4, 5 * 60, 10 * 60
KEY_VOLDOWN, KEY_VOLUP = 114, 115
DAYS = "MTWTFSS"                               # Monday first (time.struct_time.tm_wday)
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
REPEAT_DELAY, REPEAT_EVERY = 0.45, 0.08

# ---- layout (app-area coordinates) ------------------------------------------------------------
CLOCK = (14, 12, W - 14, 300)
ALARMS = (14, 316, W - 14, APP_H - 14)
DW, DH, DT = 84, 150, 17                       # 7-segment digit size + segment thickness
DIG_Y = 58
COLON_W, GAP = 30, 12
ROW_Y0, ROW_H = 448, 67
VIS_FPS = 15
FACE_COLS, FACE_ROWS = 13, 9                   # 3D clock in the alarms card header (104 x 108 px)
FACE_X, FACE_Y = W - 30 - FACE_COLS * CW, ALARMS[1] + 14
RING_COLS, RING_ROWS = 30, 16                  # big 3D clock on the ringing screen (240 x 192 px)
RING_X, RING_Y, BOUNCE = (W - RING_COLS * CW) // 2, 304, 10
class Clock3D:
    """The 3D clock as one Shape built once (face + hands at 12 o'clock); setting the time just
    rotates the hands' points, normals and face centres in place (the renderer keeps pointers
    to these arrays), so a frame costs microseconds instead of rebuilding the model."""

    def __init__(self):
        face = clock_face()
        hands = [_hand(0.0, *spec) for spec in CLOCK_HANDS]
        self.shape = Shape.combine(face, *hands)
        self.parts = []                        # (point slice, face slice, original pts, nrm, cen)
        p0, f0 = len(face.pts), len(face.fnrm)
        for hnd in hands:
            ps, fs = slice(p0, p0 + len(hnd.pts)), slice(f0, f0 + len(hnd.fnrm))
            s = self.shape
            self.parts.append((ps, fs, s.pts[ps].copy(), s.fnrm[fs].copy(), s.fcen[fs].copy()))
            p0, f0 = ps.stop, fs.stop

    def at(self, t):
        lt = time.localtime(t)
        s = self.shape
        for (ps, fs, pts, nrm, cen), a in zip(self.parts, hand_angles(lt.tm_hour, lt.tm_min, lt.tm_sec + t % 1)):
            c, sn = math.cos(a), math.sin(a)             # clockwise by a about z
            R = np.array([[c, sn, 0], [-sn, c, 0], [0, 0, 1]], np.float32)
            s.pts[ps] = pts @ R.T
            s.fnrm[fs] = nrm @ R.T
            s.fcen[fs] = cen @ R.T
        return s


_clock3d = None


def clock_shape(t):
    """The 3D clock showing the local time at epoch t, with a sweeping second hand."""
    global _clock3d
    if _clock3d is None:
        _clock3d = Clock3D()
    return _clock3d.at(t)


def _digit_x():
    total = 4 * DW + 2 * GAP + COLON_W + 2 * GAP
    x0 = (W - total) // 2
    return [x0, x0 + DW + GAP, x0 + 2 * DW + 3 * GAP + COLON_W, x0 + 3 * DW + 4 * GAP + COLON_W], \
        x0 + 2 * DW + 2 * GAP


DIG_XS, COLON_X = _digit_x()

# ---- seven-segment glyphs ------------------------------------------------------------------------
SEGS = {0: "abcdef", 1: "bc", 2: "abged", 3: "abgcd", 4: "fgbc", 5: "afgcd", 6: "afgedc",
        7: "abc", 8: "abcdefg", 9: "abcdfg", None: ""}
PAD = 12                                       # room for the glow around a tile


def _seg_polys(w, h, t, gap=3):
    """Hexagonal segments a..g of a w x h digit (origin top-left)."""
    def hor(yc):
        x0, x1 = t / 2 + gap, w - t / 2 - gap
        return [(x0, yc), (x0 + t / 2, yc - t / 2), (x1 - t / 2, yc - t / 2), (x1, yc),
                (x1 - t / 2, yc + t / 2), (x0 + t / 2, yc + t / 2)]

    def ver(xc, y0, y1):
        y0, y1 = y0 + gap, y1 - gap
        return [(xc, y0), (xc + t / 2, y0 + t / 2), (xc + t / 2, y1 - t / 2), (xc, y1),
                (xc - t / 2, y1 - t / 2), (xc - t / 2, y0 + t / 2)]
    l, r, top, mid, bot = t / 2, w - t / 2, t / 2, h / 2, h - t / 2
    return {"a": hor(top), "g": hor(mid), "d": hor(bot),
            "f": ver(l, top, mid), "b": ver(r, top, mid), "e": ver(l, mid, bot), "c": ver(r, mid, bot)}


_tiles = {}


def _glow_tile(polys, size, colour):
    """Black PIL tile: ghost shapes everywhere, lit ones in `colour` with a soft phosphor glow.
    polys = [(points, lit)] in tile coordinates (already offset by PAD)."""
    im = Image.new("RGB", size, BG); d = ImageDraw.Draw(im)
    mask = Image.new("L", size, 0); dm = ImageDraw.Draw(mask)
    for pts, lit in polys:
        d.polygon(pts, fill=GHOST)
        if lit:
            dm.polygon(pts, fill=255)
    glow = mask.filter(ImageFilter.GaussianBlur(7))
    tint = Image.new("RGB", size, mix(BG, colour, 0.55))
    im = ImageChops.lighter(im, Image.composite(tint, im, glow))
    im.paste(colour, (0, 0), mask)
    return im


def digit_tile(n, colour):
    k = ("d", n, colour)
    if k not in _tiles:
        polys = _seg_polys(DW, DH, DT)
        on = SEGS[n]
        _tiles[k] = _glow_tile([([(x + PAD, y + PAD) for x, y in p], s in on) for s, p in polys.items()],
                               (DW + 2 * PAD, DH + 2 * PAD), colour)
    return _tiles[k]


def colon_tile(lit, colour):
    k = ("c", lit, colour)
    if k not in _tiles:
        s, cx = 9, COLON_W / 2 + PAD
        dots = [[(cx - s, y - s), (cx + s, y - s), (cx + s, y + s), (cx - s, y + s)]
                for y in (PAD + DH * 0.3, PAD + DH * 0.7)]
        _tiles[k] = _glow_tile([(p, lit) for p in dots], (COLON_W + 2 * PAD, DH + 2 * PAD), colour)
    return _tiles[k]


def paste_glow(im, tile, x, y):
    """Lighten a glow tile onto im at (x, y) (tile includes PAD on every side)."""
    box = (x - PAD, y - PAD, x - PAD + tile.width, y - PAD + tile.height)
    im.paste(ImageChops.lighter(im.crop(box), tile), box[:2])


def draw_hhmm(im, h, m, colon, colour):
    for x, n in zip(DIG_XS, (h // 10, h % 10, m // 10, m % 10)):
        paste_glow(im, digit_tile(n, colour), x, DIG_Y)
    paste_glow(im, colon_tile(colon, colour), COLON_X, DIG_Y)


# ---- alarm tone ------------------------------------------------------------------------------
def _make_tones():
    """Retro triple beep (C6 with a little 3rd harmonic so it carries on a small speaker)."""
    sr = 44100

    def beeps(amp):
        t = np.arange(int(sr * 0.09)) / sr
        b = (np.sin(2 * np.pi * 1046.5 * t) + 0.3 * np.sin(2 * np.pi * 3139.5 * t)) / 1.3
        b *= np.minimum(1, np.minimum(t, t[-1] - t) / 0.005)          # 5 ms fades: no clicks
        gap, rest = np.zeros(int(sr * 0.07)), np.zeros(int(sr * 0.55))
        return np.concatenate([b, gap, b, gap, b, rest]) * amp

    def save(path, x):
        x = (np.clip(x, -1, 1) * 32000).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(np.repeat(x, 2).tobytes())
    save(TONE_RAMP, np.concatenate([beeps(0.25 + 0.75 * i / 19) for i in range(20)]))   # ~20 s
    save(TONE_LOOP, np.concatenate([beeps(1.0)] * 5))


class ClockApp(App):
    name = "Clock"

    def __init__(self):
        self.alarms = []                       # [{"h", "m", "days": [0..6], "on"}]
        try:
            with open(ALARMS_FILE) as f:
                self.alarms = [a for a in json.load(f) if {"h", "m", "days", "on"} <= set(a)][:MAX_ALARMS]
        except Exception:
            pass
        self.mode = "main"
        self.fired = {}                        # alarm index -> minute it last rang
        self.snooze_until = None               # epoch seconds
        self.ring_t0, self.ring_label = 0.0, ""
        self.edit = None                       # alarm being edited: dict + "index" (None = new)
        self.pressed, self.repeat_t = None, 0.0
        self._stop, self._player = threading.Event(), None
        self._base = None
        self._slow_shown, self._img, self._buf = None, None, None

    keep_awake = property(lambda self: self.mode == "ring")

    # ---- persistence ------------------------------------------------------------------------
    def _save(self):
        try:
            os.makedirs(os.path.dirname(ALARMS_FILE), exist_ok=True)
            with open(ALARMS_FILE, "w") as f:
                json.dump(self.alarms, f)
        except OSError:
            pass

    # ---- alarms -----------------------------------------------------------------------------
    @staticmethod
    def _next_time(a, now_epoch):
        """Epoch seconds of alarm a's next ring after now (None if it never rings)."""
        lt = time.localtime(now_epoch)
        for dd in range(8):
            t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + dd, a["h"], a["m"], 0, 0, 0, -1))
            if t > now_epoch and (not a["days"] or time.localtime(t).tm_wday in a["days"]):
                return t
        return None

    def next_alarm(self):
        now = time.time()
        times = [t for a in self.alarms if a["on"] for t in [self._next_time(a, now)] if t]
        if self.snooze_until:
            times.append(self.snooze_until)
        return min(times) if times else None

    def background(self, now):
        """Called by the shell ~1/s (even while asleep): True = bring me to the front."""
        if self.mode == "ring":
            if time.monotonic() - self.ring_t0 > RING_MAX:
                self._stop_ring()
            return False
        if self.snooze_until and time.time() >= self.snooze_until:
            self.snooze_until = None
            self._start_ring("snoozed alarm")
            return True
        lt = time.localtime()
        minute = (lt.tm_year, lt.tm_yday, lt.tm_hour, lt.tm_min)
        for i, a in enumerate(self.alarms):
            if a["on"] and a["h"] == lt.tm_hour and a["m"] == lt.tm_min and \
                    (not a["days"] or lt.tm_wday in a["days"]) and self.fired.get(i) != minute:
                self.fired[i] = minute
                if not a["days"]:
                    a["on"] = False            # one-off alarm: done
                    self._save()
                self._start_ring(f"alarm {a['h']:02d}:{a['m']:02d}")
                return True
        return False

    def _start_ring(self, label):
        self.mode, self.ring_label, self.ring_t0 = "ring", label, time.monotonic()
        self.edit, self.pressed = None, None
        self._stop.clear()
        threading.Thread(target=self._sound, daemon=True).start()

    def _sound(self):
        try:
            if not (os.path.exists(TONE_RAMP) and os.path.exists(TONE_LOOP)):
                _make_tones()
            subprocess.run(["/usr/local/sbin/audio-speaker"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception:
            return
        t0 = time.monotonic()
        while not self._stop.is_set():
            f = TONE_RAMP if time.monotonic() - t0 < 1 else TONE_LOOP
            try:
                self._player = subprocess.Popen(PLAY + [f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._player.wait()
            except OSError:
                time.sleep(1)

    def _stop_ring(self):
        self._stop.set()
        p = self._player
        if p is not None and p.poll() is None:
            p.kill()
        self.mode, self.pressed = "main", None

    # ---- lifecycle / input ------------------------------------------------------------------------
    def on_close(self):
        if self.mode == "ring":
            self._stop_ring()                   # leaving the alarm screen = dismiss
        self.mode, self.edit, self.pressed = "main", None, None

    def on_key(self, code, pressed):
        if self.mode == "ring" and code in (KEY_VOLDOWN, KEY_VOLUP):
            if pressed:
                self._snooze()
            return True
        return False

    def _snooze(self):
        self._stop_ring()
        self.snooze_until = time.time() + SNOOZE

    def _keys(self):
        if self.mode == "ring":
            return Keys([("snooze", 14, 530, 220, 120, "snooze 5", "step", 34),
                         ("stop", 246, 530, 220, 120, "stop", "on", 40)])
        if self.mode == "edit":
            hx = DIG_XS[0] + DW + GAP // 2 - 92        # centre of the hour digits - half the pair
            mx = DIG_XS[2] + DW + GAP // 2 - 92
            ks = [("h-", hx, 316, 88, 78, "-", "jump", 40), ("h+", hx + 96, 316, 88, 78, "+", "jump", 40),
                  ("m-", mx, 316, 88, 78, "-", "jump", 40), ("m+", mx + 96, 316, 88, 78, "+", "jump", 40)]
            for i, c in enumerate(DAYS):
                ks.append((f"d{i}", 16 + i * 65, 452, 58, 70, c, "on" if i in self.edit["days"] else "dim", 30))
            new = self.edit.get("index") is None
            ks += [("delete", 14, 626, 140, 90, "cancel" if new else "delete", "step" if new else "off"),
                   ("save", 166, 626, 300, 90, "save", "on", 34)]
            return Keys(ks)
        ks = []
        for i, a in enumerate(self.alarms):
            y = ROW_Y0 + i * ROW_H
            ks.append((f"t{i}", 370, y + 6, 80, 48, "on" if a["on"] else "off", "on" if a["on"] else "off", 28))
        if len(self.alarms) < MAX_ALARMS:
            y = ROW_Y0 + len(self.alarms) * ROW_H
            ks.append(("new", 30, y + 4, 420, 52, "+ new alarm", "dim", 26))
        return Keys(ks)

    def touch(self, ev, x, y):
        y -= TOP
        keys = self._keys()
        k = keys.hit(x, y)
        if ev == "down":
            self.pressed = k
            if self.mode == "main" and k is None:
                i = (y - ROW_Y0) // ROW_H
                if 0 <= i < len(self.alarms) and ALARMS[1] < y < ALARMS[3] and x < 360:
                    self.pressed = f"row{i}"
            self.repeat_t = time.monotonic() + REPEAT_DELAY
            if self.pressed in ("h-", "h+", "m-", "m+"):
                self._adjust(self.pressed)
        elif ev == "move":
            if self.pressed and not self.pressed.startswith("row") and k != self.pressed:
                self.pressed = None
        elif ev == "up":
            p, self.pressed = self.pressed, None
            if p is not None and (p == k or p.startswith("row")):
                self._press(p)

    def _adjust(self, kid):
        e = self.edit
        if kid[0] == "h":
            e["h"] = (e["h"] + (1 if kid[1] == "+" else -1)) % 24
        else:
            e["m"] = (e["m"] + (1 if kid[1] == "+" else -1)) % 60

    def _press(self, kid):
        if self.mode == "ring":
            if kid == "stop":
                self._stop_ring()
            elif kid == "snooze":
                self._snooze()
        elif self.mode == "edit":
            e = self.edit
            if kid.startswith("d"):
                d = int(kid[1:])
                e["days"] = sorted(set(e["days"]) ^ {d})
            elif kid == "save":
                a = {"h": e["h"], "m": e["m"], "days": e["days"], "on": True}
                if e.get("index") is None:
                    self.alarms.append(a)
                else:
                    self.alarms[e["index"]] = a
                self.fired = {}
                self._save()
                self.mode, self.edit = "main", None
            elif kid == "delete":
                if e.get("index") is not None:
                    del self.alarms[e["index"]]
                    self.fired = {}
                    self._save()
                self.mode, self.edit = "main", None
        else:
            if kid == "new":
                self.edit = {"h": 7, "m": 0, "days": [0, 1, 2, 3, 4], "index": None}
                self.mode = "edit"
            elif kid.startswith("t"):
                a = self.alarms[int(kid[1:])]
                a["on"] = not a["on"]
                self.fired = {}
                self._save()
            elif kid.startswith("row"):
                i = int(kid[3:])
                self.edit = dict(self.alarms[i], days=list(self.alarms[i]["days"]), index=i)
                self.mode = "edit"

    # ---- drawing ------------------------------------------------------------------------------
    def _slow_key(self):
        """What the 2D layer shows (redrawn with PIL only when this changes)."""
        t = time.time()
        lt = time.localtime(t)
        base = (self.mode, self.pressed, json.dumps(self.alarms), json.dumps(self.edit), self.snooze_until)
        if self.mode == "ring":
            return base + (int(t * 2),)                        # flash twice a second
        if self.mode == "edit":
            return base
        return base + (lt.tm_min, lt.tm_sec, int(t * 2) % 2)   # colon blinks

    def key(self, now):
        if self.pressed in ("h-", "h+", "m-", "m+") and time.monotonic() >= self.repeat_t:
            self._adjust(self.pressed)
            self.repeat_t = time.monotonic() + REPEAT_EVERY
        if self.mode == "edit":
            return self._slow_key()
        return self._slow_key() + (int(now * VIS_FPS),)        # the 3D clock moves

    def _background_image(self, which):
        if self._base is None:
            self._base = {}
        if which not in self._base:
            im = Image.new("RGB", (W, APP_H), BG); d = ImageDraw.Draw(im)
            if which == "main":
                card(d, CLOCK, "clock"); card(d, ALARMS, "alarms")
            elif which == "edit":
                card(d, CLOCK, "set alarm")
            else:
                card(d, CLOCK, "alarm")
            self._base[which] = im
        return self._base[which].copy()

    def render(self, now):
        slow = self._slow_key()
        if slow != self._slow_shown:                           # 2D layer: PIL, a few times/s
            im = self._background_image(self.mode)
            d = ImageDraw.Draw(im)
            t = time.time()
            lt = time.localtime(t)
            if self.mode == "edit":
                self._render_edit(im, d)
            elif self.mode == "ring":
                self._render_ring(im, d, t, lt)
            else:
                self._render_main(im, d, t, lt)
            self._keys().draw(im, self.pressed)
            self._img = to_rgbx(im)
            self._buf = self._img.copy()
            self._slow_shown = slow
        self._draw_3d(now)
        return self._buf

    def _draw_3d(self, now):
        """The 3D clock over the 2D layer (restored first): swaying gently on the main screen,
        shaking and bouncing while an alarm rings."""
        t = time.time()
        if self.mode == "main":
            x, y, cols, rows = FACE_X, FACE_Y, FACE_COLS, FACE_ROWS
            self._buf[y:y + rows * CH, x:x + cols * CW] = self._img[y:y + rows * CH, x:x + cols * CW]
            m9 = matrix(0.22, 0.12 * math.sin(0.8 * now), 0.45 * math.sin(0.5 * now), 0.0)
            self.renderer.view(self._buf, clock_shape(t), m9, cols * 1.55, cols, rows, x, y,
                               card_tiles(y, PANEL, SCAN, ALARMS[1]))
        elif self.mode == "ring":
            x, y, cols, rows = RING_X, RING_Y, RING_COLS, RING_ROWS
            h = rows * CH + BOUNCE
            self._buf[y - BOUNCE:y + h, x:x + cols * CW] = self._img[y - BOUNCE:y + h, x:x + cols * CW]
            dy = -int(BOUNCE * abs(math.sin(7 * now)))
            m9 = matrix(0.18, 0.0, 0.35 * math.sin(2.5 * now), 0.30 * math.sin(34 * now))
            self.renderer.view(self._buf, clock_shape(t), m9, cols * 1.2, cols, rows, x, y + dy, TILES)

    def _sync_text(self):
        try:
            ago = time.time() - int(open(SYNC_FILE).read().split()[0])
            if ago < 3600 * 6:
                return "> synced " + (f"{int(ago // 60)} min ago" if ago >= 60 else "just now"), MID
            return f"> last synced {int(ago // 3600)} h ago", MID
        except (OSError, ValueError, IndexError):
            return "> time not synced yet (needs Wi-Fi)", ERR

    def _render_main(self, im, d, t, lt):
        txt, col = self._sync_text()
        draw_text(im, 30, CLOCK[1] + 14, txt, 17, col)
        tz = time.strftime("%Z", lt)
        draw_text(im, CLOCK[2] - 16 - text_len(tz, 17), CLOCK[1] + 14, tz, 17, MID)
        draw_hhmm(im, lt.tm_hour, lt.tm_min, int(t * 2) % 2 == 0, ACCENT)
        # seconds: 60 ticks, lit up to the current second
        x0, x1, y = 40, W - 40, CLOCK[1] + 232
        for s in range(60):
            x = x0 + (x1 - x0) * s / 59
            ln = 10 if s % 5 == 0 else 5
            d.line([(x, y - ln), (x, y)], fill=ACCENT if s <= lt.tm_sec else DIM, width=2)
        date = f"{time.strftime('%A', lt)} {lt.tm_mday} {time.strftime('%B %Y', lt)}".upper()
        draw_text(im, (W - text_len(date, 22)) / 2, CLOCK[1] + 248, date, 22, MID)
        # alarms
        nxt = self.next_alarm()
        y0 = ALARMS[1] + 16
        if nxt:
            mins = int((nxt - t) // 60) + 1
            snoozed = self.snooze_until and nxt == self.snooze_until
            draw_text(im, 30, y0, "> snoozed until" if snoozed else "> next alarm", 17, MID)
            draw_text(im, 30, y0 + 26, time.strftime("%a %H:%M", time.localtime(nxt)), 40, ACCENT)
            left = f"in {mins // 60} h {mins % 60} min" if mins >= 60 else f"in {mins} min"
            draw_text(im, 30, y0 + 76, left, 20, MID)
        else:
            draw_text(im, 30, y0, "> no alarms on", 17, MID)
            draw_text(im, 30, y0 + 30, "tap + new alarm", 22, DIM)
        d.line([(30, ROW_Y0 - 6), (W - 30, ROW_Y0 - 6)], fill=(0, 28, 16))
        for i, a in enumerate(self.alarms):
            y = ROW_Y0 + i * ROW_H
            col = ACCENT if a["on"] else MID
            if self.pressed == f"row{i}":
                d.rounded_rectangle([24, y + 2, 360, y + ROW_H - 6], 7, fill=(0, 30, 17))
            draw_text(im, 34, y + 10, f"{a['h']:02d}:{a['m']:02d}", 40, col)
            if a["days"]:
                for k, c in enumerate(DAYS):
                    draw_text(im, 168 + k * 24, y + 22, c, 22, (col if k in a["days"] else DIM))
            else:
                draw_text(im, 168, y + 22, "once", 22, col)
            if i < len(self.alarms) - 1 or len(self.alarms) < MAX_ALARMS:
                d.line([(30, y + ROW_H - 2), (W - 30, y + ROW_H - 2)], fill=(0, 28, 16))

    def _render_edit(self, im, d):
        e = self.edit
        draw_hhmm(im, e["h"], e["m"], True, ACCENT)
        for x, lab in ((DIG_XS[0], "hour"), (DIG_XS[2], "minute")):
            draw_text(im, x + DW + GAP / 2 - text_len(lab, 17) / 2, CLOCK[1] + 240, lab, 17, MID)
        rep = "repeats " + " ".join(DAY_NAMES[i] for i in e["days"]) if e["days"] else "rings once (no days picked)"
        if len(e["days"]) == 7:
            rep = "repeats every day"
        draw_text(im, 18, 418, rep, 17, MID)

    def _render_ring(self, im, d, t, lt):
        flash = int(t * 2) % 2 == 0
        col = FLARE if flash else ACCENT
        draw_hhmm(im, lt.tm_hour, lt.tm_min, True, col)
        draw_text(im, 30, CLOCK[1] + 14, "> " + self.ring_label, 17, ACCENT)
        if flash:
            draw_text(im, CLOCK[2] - 16 - text_len("WAKE UP", 17), CLOCK[1] + 14, "WAKE UP", 17, FLARE)
        draw_text(im, (W - text_len("volume key = snooze", 17)) / 2, 502, "volume key = snooze", 17, MID)

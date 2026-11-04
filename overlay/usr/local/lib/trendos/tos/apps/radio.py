"""FM radio: tuning drum dial, live oscilloscope + ASCII spectrum of the radio's audio.

Look: the same green-phosphor terminal as the Calculator: framed cards with a label cut into
the top edge, CRT scanlines, outlined keys.
  * "fm" card: big frequency readout, status line, volume blocks, band position bar.
  * "scope" card: oscilloscope trace with phosphor persistence (it fades over a few frames)
    above a 3D waterfall terrain: the live spectrum is the front ridge and scrolls back to the
    horizon in perspective, nearer ridges hiding farther ones, in the 3D renderer's ASCII
    characters (radio off: a flat perspective grid).
  * "tune" card: a drum dial: ticks wrap round a cylinder (they bunch up and dim towards the
    edges). Drag or fling it; it snaps to 0.1 MHz. Tap a number on it to jump there.
  * keys: << -1 MHz, < -0.1, on/off, > +0.1, >> +1 (hold < > to repeat). Volume keys work.

Hardware: tos/hw/fm.py (Broadcom FM core over the BT UART), driven by one worker thread so the UI
never waits on it (power-up takes ~4 s). The visualiser reads the same audio from the codec's
line-in with `arecord` (16 kHz mono). Opening the app turns the radio on, closing turns it off.
Wired headphones are the antenna. Last frequency + volume are kept in STATE_FILE.
"""
import json, math, os, subprocess, threading, time

import numpy as np
from PIL import Image, ImageDraw

from ..config import W, TOP, APP_H, ACCENT, SHADES, NS, CW, CH, GREEN, DIMGREEN
from ..render import card_tiles
from ..gfx import font, to_rgbx, text_len, draw_text
from .. import canvas, native
from ..hw import audio, fm
from ..ui import BG, FRAME, FRAME_HI, PANEL, SCAN, DIM, MID, FLARE, ERR, KEY_STYLE, mix as _mix, card as _card
from .base import App

STATE_FILE = "/var/lib/trendos/radio.json"
CAPTURE = ["arecord", "-q", "-D", f"hw:CARD={fm.CARD},DEV=0", "-f", "S16_LE", "-c", "1", "-r", "16000", "-t", "raw"]
# with a Bluetooth speaker/headphones connected: CD-quality capture, streamed to it as well
CAPTURE_BT = ["arecord", "-q", "-D", f"hw:CARD={fm.CARD},DEV=0", "-f", "S16_LE", "-c", "2", "-r", "44100", "-t", "raw"]
KEY_VOLDOWN, KEY_VOLUP = 114, 115

# ---- palette: the shared TREND OS look (tos/ui.py) --------------------------------------------
GRID = (0, 34, 19)

# ---- layout (app-area coordinates; touch y is screen y, i.e. + TOP) -------------------------
DISP = (14, 12, W - 14, 172)
SCOPE = (14, 188, W - 14, 452)
SX0, SY0, SX1, SY1 = 24, 204, W - 24, 294          # oscilloscope
TY0, T_ROWS = 300, 12                               # 3D waterfall terrain: 12 rows of 12 px cells
T_COLS = (SX1 - SX0) // CW                          # 54 columns (one spectrum band each)
T_LINES, T_EVERY = 14, 2                            # history ridges, frames per new ridge
T_AMP, T_HORIZON = 7.0, 0.6                         # peak height (rows, front ridge), horizon row
DIAL = (14, 468, W - 14, 604)
KX, KY, KW, KH, GX = 14, 620, 84, 96, 8
KEYS = [("<<", -1.0), ("<", -0.1), ("pwr", None), (">", 0.1), (">>", 1.0)]

# ---- dial ------------------------------------------------------------------------------------
CX, R = W // 2, 220                 # drum axis on screen, drum radius (px)
DX0, DX1 = 22, W - 22                # dial window columns (inside the card border)
DEG_PER_MHZ = 14.0                  # drum rotation per MHz
PX_PER_MHZ = R * math.radians(DEG_PER_MHZ)      # at the centre line: ~52 px
TICK_BASE = 584                     # app y of the tick bottoms
TICK_I = {"major": 255, "half": 185, "minor": 120}    # tick intensities on the tape
REPEAT_DELAY, REPEAT_EVERY = 0.45, 0.09

# ---- visualiser --------------------------------------------------------------------------------
GRID_I = 30                         # graticule dots (phosphor intensity)
SPIN = "|/-\\"
VIS_FPS = 20                        # visualiser frame rate (30 costs ~46 % of a core, 20 ~1/3)


def _lut32(colour_of):
    """256-entry intensity -> RGBX lookup table as uint32 (one gather colours a whole image)."""
    lut = np.zeros((256, 4), np.uint8)
    for i in range(256):
        lut[i, :3] = colour_of(i / 255)
    return lut.view(np.uint32).ravel()


def _phosphor(v):
    """Scope tube: dark panel, up to ACCENT, white-hot at the trace core."""
    return _mix(PANEL, ACCENT, v / 0.75) if v < 0.75 else _mix(ACCENT, FLARE, (v - 0.75) / 0.25)


class RadioApp(App):
    name = "Radio"

    def __init__(self):
        self.freq, self.vol = 100.0, 10
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            self.freq, self.vol = fm.clamp(float(st["freq"])), int(st["vol"])
        except Exception:
            pass
        self.disp_f = self.freq             # dial position (float MHz, animates)
        self.snap = None                    # MHz the dial is easing to
        self.fling = 0.0                    # MHz/s while coasting after a flick
        self.drag, self.moved = None, False # (x0, f0) while dragging the dial; dragged > 6 px?
        self.trail = []                     # recent (t, x) of the drag, for flick speed
        self.pressed, self.repeat_t = None, 0.0
        # hardware side (written by the worker thread)
        self.state, self.msg = "off", ""    # off | starting | on | error
        self.rssi, self.tuned, self.hw_vol = None, None, None
        self.want_on, self.closing = False, False
        self.fm = fm.FM()
        self._lock, self._wake = threading.Lock(), threading.Event()
        self._worker = None
        self._cap = None                    # arecord process
        self._bt_play = None                # aplay to the Bluetooth device, while one is connected
        self.bt_out, self._bt_check = None, 0.0
        self.samples = np.zeros(4096, np.int16)
        self.anim_until = 0.0
        self.last_t = time.monotonic()
        # visualiser state
        self.phos = np.zeros((SY1 - SY0, SX1 - SX0), np.uint8)
        self.peak = 2000.0
        self.bands = np.zeros(T_COLS, np.float32)            # live spectrum (front ridge)
        self.hist = np.zeros((T_LINES, T_COLS), np.float32)  # [0] = front (newest)
        self.band_ref = -1e9
        self.t_frames = 0
        self._buf = None                    # persistent app-area image (built on first render)

    # ---- lifecycle -----------------------------------------------------------------------
    def on_open(self):
        with self._lock:
            self.want_on, self.closing = True, False
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
        self._wake.set()

    def on_close(self):
        with self._lock:
            self.want_on, self.closing = False, True
        self.drag, self.pressed = None, None
        self._wake.set()
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump({"freq": round(self.target(), 1), "vol": self.vol}, f)
        except OSError:
            pass

    def target(self):
        """The 0.1 MHz channel the dial points at (what the chip is tuned to)."""
        return fm.clamp(self.snap if self.snap is not None else self.disp_f)

    # ---- worker thread: all hardware access ---------------------------------------------------
    def _run(self):
        next_rssi = 0.0
        while True:
            self._wake.wait(0.25)
            self._wake.clear()
            with self._lock:
                if self.closing and not self.want_on and not self.fm.is_on:
                    self._worker = None
                    return
                want = self.want_on
            try:
                if want and not self.fm.is_on:
                    self.state, self.msg = "starting", ""
                    t = self.target()
                    self.fm.on(t, self.vol)
                    self.tuned, self.hw_vol = t, self.vol
                    self._start_capture()
                    self.state, next_rssi = "on", 0.0
                elif not want and self.fm.is_on:
                    self._stop_capture()
                    self.fm.off()
                    self.state, self.rssi, self.tuned = "off", None, None
                    self.anim_until = time.monotonic() + 0.8      # let the trace fade out
                if self.fm.is_on:
                    t = self.target()
                    if t != self.tuned:
                        self.fm.tune(t); self.tuned = t
                        next_rssi = time.monotonic() + 0.15
                    want = 0 if self.bt_out else self.vol      # wired headphones muted on Bluetooth
                    if want != self.hw_vol:
                        fm.set_volume(want); self.hw_vol = want
                    if time.monotonic() >= self._bt_check:       # Bluetooth audio came / went?
                        self._bt_check = time.monotonic() + 2.0
                        if audio.bt_sink() != self.bt_out:
                            self._start_capture()
                    if time.monotonic() >= next_rssi:
                        self.rssi = self.fm.rssi()
                        next_rssi = time.monotonic() + 0.5
            except Exception as e:                      # UART timeout, missing patch file, ...
                self._stop_capture()
                try:
                    self.fm.off()
                except Exception:
                    pass
                with self._lock:
                    self.want_on = False
                self.state, self.msg, self.rssi, self.tuned = "error", str(e)[:28], None, None

    def _start_capture(self):
        """Line-in capture for the visualiser; with Bluetooth audio connected it is CD quality
        and also streamed to the speaker/headphones (wired headphones muted: they are only
        the antenna then)."""
        self._stop_capture()
        mac = audio.bt_sink()
        try:
            if mac:
                self._bt_play = subprocess.Popen(["aplay", "-q", "-D", audio.bt_device(mac), "-f", "S16_LE",
                                                  "-c", "2", "-r", "44100", "-t", "raw"],
                                                 stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p = subprocess.Popen(CAPTURE_BT if mac else CAPTURE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, bufsize=0)
        except OSError:
            self._stop_capture()
            return
        self.bt_out = mac
        self._cap = p
        threading.Thread(target=self._read_capture, args=(p, self._bt_play), daemon=True).start()

    def _read_capture(self, p, out=None):
        fd, ring, carry = p.stdout.fileno(), np.zeros(4096, np.int16), b""
        stereo = out is not None
        while True:
            try:
                b = os.read(fd, 4096)
            except OSError:
                break
            if not b:
                break
            b, carry = carry + b, b""
            n = len(b) - len(b) % (4 if stereo else 2)
            b, carry = b[:n], b[n:]
            if out is not None:
                try:
                    out.stdin.write(b)
                except (BrokenPipeError, OSError):
                    out = None                           # device went away: the worker notices
            a = np.frombuffer(b, np.int16)
            if stereo:
                a = a[::6]                               # left channel, 44.1 -> ~14.7 kHz for the visuals
            a = a[-len(ring):]
            ring = np.concatenate((ring[len(a):], a))
            self.samples = ring                          # swapped whole: no lock needed

    def _stop_capture(self):
        p, self._cap = self._cap, None
        if p is not None:
            p.kill()
            p.wait()
        b, self._bt_play = self._bt_play, None
        if b is not None:
            b.kill()
            b.wait()
        self.bt_out = None
        self.samples = np.zeros(4096, np.int16)

    # ---- input --------------------------------------------------------------------------------
    def on_key(self, code, pressed):
        if code in (KEY_VOLDOWN, KEY_VOLUP):
            if pressed:
                self.vol = max(0, min(fm.HP_VOL_MAX, self.vol + (1 if code == KEY_VOLUP else -1)))
                self._wake.set()
            return True
        return False

    def _key_at(self, x, y):
        if KY <= y <= KY + KH:
            i = int((x - KX) // (KW + GX))
            if 0 <= i < len(KEYS) and x - KX - i * (KW + GX) <= KW:
                return i
        return None

    def touch(self, ev, x, y):
        now = time.monotonic()
        y -= TOP
        if ev == "down":
            if DIAL[1] <= y <= DIAL[3]:
                self.drag, self.trail = (x, self.disp_f), [(now, x)]
                self.snap, self.fling, self.moved = None, 0.0, False
            else:
                self.pressed = self._key_at(x, y)
                if self.pressed is not None:
                    self.repeat_t = now + REPEAT_DELAY
                    if KEYS[self.pressed][1] is not None:
                        self._step(KEYS[self.pressed][1])
        elif ev == "move":
            if self.drag is not None:
                x0, f0 = self.drag
                if abs(x - x0) > 6:
                    self.moved = True
                self.disp_f = min(fm.BAND[1], max(fm.BAND[0], f0 - (x - x0) / PX_PER_MHZ))
                self.trail = (self.trail + [(now, x)])[-6:]
                self._wake.set()
            elif self.pressed is not None and self._key_at(x, y) != self.pressed:
                self.pressed = None
        elif ev == "up":
            if self.drag is not None:
                if not self.moved:                       # a tap on the dial: jump there
                    s = max(-0.99, min(0.99, (x - CX) / R))
                    self.snap = fm.clamp(self.disp_f + math.degrees(math.asin(s)) / DEG_PER_MHZ)
                else:
                    t0, x0 = self.trail[0]
                    v = -(x - x0) / PX_PER_MHZ / max(now - t0, 1e-3)
                    if now - t0 < 0.15 and abs(v) > 3:
                        self.fling = max(-40.0, min(40.0, v))
                    else:
                        self.snap = fm.clamp(self.disp_f)
                self.drag = None
                self._wake.set()
            elif self.pressed is not None:
                if KEYS[self.pressed][1] is None and self._key_at(x, y) == self.pressed:
                    with self._lock:
                        self.want_on = self.state not in ("on", "starting")
                    self._wake.set()
                self.pressed = None
            self.anim_until = now + 0.3

    def _step(self, mhz):
        self.fling = 0.0
        self.snap = fm.clamp(self.target() + mhz)
        self._wake.set()

    # ---- motion --------------------------------------------------------------------------------
    def _update(self, now):
        dt, self.last_t = min(0.1, now - self.last_t), now
        if self.pressed is not None and KEYS[self.pressed][1] is not None and abs(KEYS[self.pressed][1]) < 1 \
                and now >= self.repeat_t:
            self._step(KEYS[self.pressed][1]); self.repeat_t = now + REPEAT_EVERY
        if self.fling:
            self.disp_f += self.fling * dt
            self.fling *= math.exp(-3.5 * dt)
            if self.disp_f <= fm.BAND[0] or self.disp_f >= fm.BAND[1] or abs(self.fling) < 0.8:
                self.disp_f = min(fm.BAND[1], max(fm.BAND[0], self.disp_f))
                self.fling, self.snap = 0.0, fm.clamp(self.disp_f)
            self._wake.set()
        elif self.snap is not None and self.drag is None:
            d = self.snap - self.disp_f
            if abs(d) < 0.003:
                self.disp_f, self.snap = self.snap, None
            else:
                self.disp_f += d * (1 - math.exp(-14 * dt))

    @property
    def moving(self):
        return self.drag is not None or self.fling != 0.0 or self.snap is not None

    def key(self, now):
        self._update(now)
        if self.moving or self.pressed is not None or now < self.anim_until:
            return ("live", int(now * 30))                  # dial in motion: full frame rate
        if self.state in ("on", "starting"):
            return ("live", int(now * VIS_FPS))
        return ("idle", self.state, self.msg, round(self.disp_f, 3), self.vol)

    # ---- drawing ---------------------------------------------------------------------------------
    # Everything static is pre-rendered once; each frame is a few whole-array numpy operations
    # (per-pixel Python or PIL work is far too slow on the Cortex-A7).
    def _prerender(self):
        im = Image.new("RGB", (W, APP_H), BG); d = ImageDraw.Draw(im)
        _card(d, DISP, "fm"); _card(d, SCOPE, "scope"); _card(d, DIAL, "tune")
        self._base = to_rgbx(im)                                    # the empty cards, for restoring regions
        self._buf = self._base.copy()
        self._shown = {}
        # scope: plain tube (no scanlines) with a dotted graticule as a phosphor floor
        h, w = self.phos.shape
        self._floor = np.zeros((h, w), np.uint8)
        for gx in range(0, w + 1, w // 8):
            self._floor[::4, min(gx, w - 1)] = GRID_I
        for gy in (0, h // 2, h - 1):
            self._floor[gy, ::4] = GRID_I
        self._scope_lut = _lut32(_phosphor)
        # 3D terrain: the 3D renderer's ASCII tiles, on the card background
        atlas = card_tiles(TY0, PANEL, SCAN, SCOPE[1])
        self._t_atlas = native.atlas(atlas, CW, CH)
        self._t_tiles = atlas                                       # keeps the pointer above alive
        cols = np.arange(T_COLS)
        cx = (T_COLS - 1) / 2
        # per ridge i (rows) and screen column (cols): which band it shows (linear interpolation
        # between i0 and i0 + 1), whether it is inside the ridge's width, its baseline + scale
        sc = 1 / (1 + 0.16 * np.arange(T_LINES))[:, None]           # perspective scale
        u = cx + (cols[None, :] - cx) / sc
        t_ok = (u >= 0) & (u <= T_COLS - 1)
        u = np.clip(u, 0, T_COLS - 1.001)
        i0 = np.floor(u)
        depth = np.arange(T_LINES)
        self._t_tables = (                                          # geometry, fixed for the app's life
            i0.astype(np.int32),
            (u - i0).astype(np.float32),
            np.broadcast_to(T_HORIZON + (T_ROWS - 1.15 - T_HORIZON) * sc, u.shape).astype(np.float32),
            np.broadcast_to(T_AMP * sc, u.shape).astype(np.float32),
            t_ok.astype(np.uint8),
            (np.where(depth < T_LINES // 2, GREEN, DIMGREEN) * NS).astype(np.int32),
            (1.15 - 0.5 * depth / T_LINES).astype(np.float32),
        )
        self._terrain = native.terrain(*self._t_tables, T_ROWS, NS)
        self.t_floor = None
        self._win = np.hanning(1024).astype(np.float32)
        e = np.round(np.geomspace(3, 512, T_COLS + 1)).astype(int)
        for k in range(1, len(e)):
            e[k] = max(e[k], e[k - 1] + 1)
        self._edges, self._widths = e[:-1], np.diff(e).astype(np.float32)
        self._prerender_dial()
        self._key_tiles = {}

    def _prerender_dial(self):
        """A flat tape of the whole band at the drum's centre-line scale, projected onto the
        drum each frame. How much tape lies behind a screen column depends only on the column
        (it grows towards the edges), so the tape is pre-max-filtered at each width ("mips")
        and every column reads its own width: the bunched-up edge ticks blend instead of
        flickering. Brightness falloff and the card's scanlines are baked into a lookup table
        indexed by (scanline row?, column shade, tape intensity): a frame is two gathers."""
        top = TICK_BASE - 36 - 40                                # highest ink: major labels
        self._dy0, self._dy1 = top, TICK_BASE + 1
        pad = 90 / DEG_PER_MHZ + 0.5
        self._tape_f0 = fm.BAND[0] - pad
        tw = int(math.ceil((fm.BAND[1] - fm.BAND[0] + 2 * pad) * PX_PER_MHZ)) + 2
        tape = Image.new("L", (tw, self._dy1 - self._dy0), 0)
        d = ImageDraw.Draw(tape)
        base = TICK_BASE - self._dy0
        for k in range(int(fm.BAND[0] * 10), int(fm.BAND[1] * 10) + 1):
            x = round((k / 10 - self._tape_f0) * PX_PER_MHZ)
            kind = "major" if k % 10 == 0 else "half" if k % 5 == 0 else "minor"
            ln, wd = {"major": (36, 3), "half": (24, 2), "minor": (13, 1)}[kind]
            d.rectangle([x - wd // 2, base - ln, x - wd // 2 + wd - 1, base], fill=TICK_I[kind])
            if kind == "major":
                lab = str(k // 10)
                draw_text(tape, x - text_len(lab, 24) / 2, base - ln - 34, lab, 24, 255)
        tape = np.asarray(tape)
        # per screen column: tape offset (MHz) at its left edge, tape width behind it, shade
        xb = np.arange(DX0, DX1 + 1) - 0.5
        off = np.degrees(np.arcsin(np.clip((xb - CX) / R, -1, 1))) / DEG_PER_MHZ
        width = np.maximum(1, np.ceil(np.diff(off) * PX_PER_MHZ)).astype(np.intp)
        mips = [tape]
        for k in range(2, int(width.max()) + 1):                # mips[k-1][:, x] = max(tape[:, x:x+k])
            m = mips[-1].copy()
            m[:, :-(k - 1)] = np.maximum(m[:, :-(k - 1)], tape[:, k - 1:])
            mips.append(m)
        # lookup table: [scanline?][shade 0..15][intensity] -> RGBX (max of background, ink)
        xc = np.arange(DX0, DX1) - CX
        shade = np.cos(np.arcsin(np.clip(xc / R, -1, 1))) ** 1.6
        sq = np.minimum(15, np.round(shade * 15)).astype(np.uint16)
        bgrow = self._buf[self._dy0:self._dy1, DX0 + 40, :3]
        scan = np.array([tuple(c) == SCAN for c in bgrow], np.uint16)
        lut = np.zeros((2, 16, 256, 4), np.uint8)
        for r, bgc in enumerate((PANEL, SCAN)):
            for q in range(16):
                for i in range(256):
                    ink = _mix(BG, ACCENT, i / 255 * q / 15)
                    lut[r, q, i, :3] = tuple(max(a, b) for a, b in zip(ink, bgc))
        self._dial_tables = (                                       # geometry, fixed for the app's life
            np.stack(mips),
            (scan[:, None] << 12) | (sq[None, :] << 8),                 # per pixel: lut row
            lut.view(np.uint32).reshape(-1),
            off[:-1],
            (width - 1).astype(np.int32),
        )
        self._dial = native.dial(*self._dial_tables, self._tape_f0, PX_PER_MHZ)
        # needle with a phosphor glow: a narrow strip composited with max()
        nh = DIAL[3] - 8 - (DIAL[1] + 6)
        nd = Image.new("RGB", (9, nh), BG); dd = ImageDraw.Draw(nd)
        for dx, c in ((1, DIM), (7, DIM), (2, FRAME_HI), (6, FRAME_HI)):
            dd.line([(dx, 12), (dx, nh - 1)], fill=c)
        for dx in (3, 4, 5):
            dd.line([(dx, 9), (dx, nh - 1)], fill=FLARE)
        dd.polygon([(0, 0), (8, 0), (4, 9)], fill=FLARE)
        self._needle = to_rgbx(nd)
        self._needle_y = DIAL[1] + 6

    def render(self, now):
        if self._buf is None:
            self._prerender()
        buf = self._buf
        on = self.state == "on"
        k = (self.state, self.msg, self.rssi, int(now * 8) % 4 if self.state == "starting" else 0, self.vol, self.bt_out)
        if self._shown.get("status") != k:
            self._region(DISP[1] + 6, DISP[1] + 42, self._draw_status, now)
            self._shown["status"] = k
        k = (f"{self.target():.1f}", on)
        if self._shown.get("freq") != k:
            self._region(DISP[1] + 42, DISP[3] - 32, self._draw_freq, now)
            self._shown["freq"] = k
        k = (round(self.disp_f, 2), on)
        if self._shown.get("bar") != k:
            self._region(DISP[3] - 32, DISP[3] - 4, self._draw_bar, now)
            self._shown["bar"] = k
        k = round(self.disp_f, 4)
        if self._shown.get("dial") != k:
            self._draw_dial(buf)
            self._shown["dial"] = k
        k = (self.pressed, self.state in ("on", "starting"))
        if self._shown.get("keys") != k:
            self._draw_keys(buf)
            self._shown["keys"] = k
        self._draw_scope()
        self._draw_terrain()
        return buf

    def _region(self, y0, y1, paint, now):
        """Redraw rows y0..y1 of the app area: restore the empty card, then paint over it."""
        self._buf[y0:y1] = self._base[y0:y1]
        paint(self._buf, now)

    def _draw_status(self, buf, now):
        if self.state == "starting":
            status, scol = "> powering up " + SPIN[int(now * 8) % 4], ACCENT
        elif self.state == "error":
            status, scol = "> error: " + self.msg, ERR
        elif self.state == "on":
            where = "bluetooth" if self.bt_out else "tuned"
            status, scol = f"> {where}    rssi {self.rssi if self.rssi is not None else '--'}", MID
        else:
            status, scol = "> off   (headphones = antenna)", MID
        y = DISP[1] + 14
        canvas.text(buf, 30, y, status, 17, scol)
        vx = DISP[2] - 16 - fm.HP_VOL_MAX * 8
        canvas.text(buf, vx - 34, y, "vol", 17, MID)
        for i in range(fm.HP_VOL_MAX):
            x = vx + i * 8
            canvas.fill_rect(buf, y + 4, y + 17, x, x + 6, ACCENT if i < self.vol else DIM)

    def _draw_freq(self, buf, now):
        txt = f"{self.target():.1f}"
        col = ACCENT if self.state == "on" else MID
        right = 360
        canvas.text(buf, right - canvas.text_width(txt, 84), DISP[1] + 44, txt, 84, col)
        canvas.text(buf, right + 12, DISP[1] + 92, "MHz", 26, col)

    def _draw_bar(self, buf, now):
        y, x0, x1 = DISP[3] - 20, 40, W - 40
        span = fm.BAND[1] - fm.BAND[0]
        canvas.fill_rect(buf, y, y + 1, x0, x1 + 1, FRAME)
        for mhz in range(88, 109, 2):
            x = int(x0 + (mhz - fm.BAND[0]) / span * (x1 - x0))
            canvas.fill_rect(buf, y - 3, y + 4, x, x + 1, FRAME)
        x = int(x0 + (self.disp_f - fm.BAND[0]) / span * (x1 - x0))
        canvas.fill_rect(buf, y - 7, y + 8, x - 2, x + 3, FLARE if self.state == "on" else MID)

    def _draw_dial(self, buf):
        native.dial_draw(self._dial, self.disp_f, buf, DX0, self._dy0)
        y0, n0 = self._needle_y, CX - 4
        strip = buf[y0:y0 + self._needle.shape[0], n0:n0 + 9]
        np.maximum(strip, self._needle, out=strip)

    def _key_tile(self, i, lab, kind, pressed):
        k = (i, lab, kind, pressed)
        t = self._key_tiles.get(k)
        if t is None:
            im = Image.new("RGB", (KW + 1, KH + 1), BG); d = ImageDraw.Draw(im)
            fill, edge, text, lit = KEY_STYLE[kind]
            if pressed:
                fill, edge, text = lit, lit, (0, 0, 0)
            d.rounded_rectangle([0, 0, KW, KH], 7, fill=fill, outline=edge, width=2)
            if not pressed and kind != "on":
                d.line([(8, KH - 5), (KW - 8, KH - 5)], fill=_mix(fill, edge, 0.35), width=1)
            draw_text(im, (KW - text_len(lab, 30)) / 2, (KH - 34) / 2, lab, 30, text)
            t = self._key_tiles[k] = to_rgbx(im)
        return t

    def _draw_keys(self, buf):
        on = self.state in ("on", "starting")
        for i, (lab, step) in enumerate(KEYS):
            if step is None:
                kind = lab = "on" if on else "off"
            else:
                kind = "jump" if abs(step) >= 1 else "step"
            x0 = KX + i * (KW + GX)
            buf[KY:KY + KH + 1, x0:x0 + KW + 1] = self._key_tile(i, lab, kind, i == self.pressed)

    def _draw_scope(self):
        live = self.state == "on" and self._cap is not None
        idle = 115 if self.state in ("off", "error") else 180
        self.peak = native.scope_frame(self.phos, self.samples if live else None, self._floor,
                                       self._scope_lut, idle, self.peak, self._buf, SX0, SY0)

    def _draw_terrain(self):
        """Waterfall terrain: the live spectrum is the front ridge; every T_EVERY frames it moves
        one step back towards the horizon, shrinking in perspective and fading. Drawn front to
        back with per-column occlusion (a ridge hides what is behind it), one ASCII character
        per column whose density follows the level. Radio off: a flat perspective grid."""
        if self.state == "on" and self._cap is not None:
            s = self.samples[-1024:].astype(np.float32) * self._win
            mag = np.abs(np.fft.rfft(s))[1:]                                 # 15.6 Hz bins
            bands = np.add.reduceat(mag, self._edges)[:T_COLS] / self._widths
            db = 20 * np.log10(bands + 1.0)
            # level relative to the noise floor (radio static is loud everywhere): floor = a
            # slowly tracked low percentile, top = slowly decaying peak
            fl = float(np.percentile(db, 35))
            self.t_floor = fl if self.t_floor is None else 0.9 * self.t_floor + 0.1 * fl
            self.band_ref = max(float(db.max()), self.band_ref - 0.3)
            v = np.clip((db - self.t_floor) / max(6.0, self.band_ref - self.t_floor), 0, 1) ** 1.3
        else:
            v = np.zeros(T_COLS, np.float32)
        self.bands = np.maximum(v, self.bands * 0.75).astype(np.float32)  # fast attack, slow fall
        self.t_frames += 1
        if self.t_frames % T_EVERY == 0:
            self.hist[1:] = self.hist[:-1]
        self.hist[0] = self.bands
        if self.state != "on":
            self.hist *= 0.8
        if self._shown.get("terrain_flat") and not self.hist.any():
            return
        native.terrain_draw(self._terrain, self.hist, self._t_atlas, self._buf, SX0, TY0)
        self.hist[self.hist < 0.005] = 0
        self._shown["terrain_flat"] = not self.hist.any()

"""SSH (home screen): who is connected to this phone over SSH, live.

  "sshd" card         is the server up, which links it answers on, how many are connected
  "connections" card  each connection: address, link, how long, user, terminal, the key that
                      logged in, what it is running, and an activity trace. Connections still
                      logging in show in yellow.
  "log" card          recent logins and logouts (IN/OUT), rejected logins (FAIL) and connections
                      dropped before logging in (DROP), newest first, from sshd's log

View only. Data comes from tos/sshmon.py, sampled once a second by a thread while the app is open.
The screen stays on while it's open, since it's something you watch.
"""
import threading, time, traceback

from PIL import Image, ImageDraw

from ..config import W, APP_H, ACCENT, PALETTE, YELLOW
from ..gfx import to_rgbx, text_len, draw_text
from ..sshmon import SshMon
from ..ui import BG, DIM, MID, ERR, FLARE, card
from .base import App

WARN = PALETTE[YELLOW]
STATUS = (14, 12, W - 14, 128)
CONNS = (14, 144, W - 14, 460)
LOG = (14, 476, W - 14, APP_H - 14)
ROW_H, MAX_ROWS = 100, 3
LOG_ROW, LOG_SIZE = 26, 22
LOG_COLOURS = {"IN": ACCENT, "OUT": MID, "FAIL": ERR, "DROP": WARN}
SPARK_X0, SPARK_Y, SPARK_H, SPARK_BAR = 336, 36, 34, 4
SAMPLE = 1.0                    # s between samples
PAUSE_AFTER = 3.0               # s without the shell asking for frames: screen off, stop sampling


def fit(s, size, width):
    """Cut s to fit width px (the UI font is monospaced)."""
    n = int(width / max(1, text_len("M", size)))
    return s if len(s) <= n else s[:max(0, n - 2)] + ".."


def span(sec):
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s"
    if sec < 86400:
        return f"{sec // 3600}h {sec % 3600 // 60:02d}m"
    return f"{sec // 86400}d {sec % 86400 // 3600}h"


class SshApp(App):
    name = "SSH"
    keep_awake = True

    def __init__(self):
        self.mon = None
        self.snap = None
        self.version = 0
        self.sig = None
        self.seen = 0.0
        self.stop = None

    def on_open(self):
        if self.mon is None:
            self.mon = SshMon()
        self._publish(self.mon.sample())
        self.seen = time.monotonic()
        self.stop = threading.Event()
        threading.Thread(target=self._run, args=(self.stop,), daemon=True).start()

    def on_close(self):
        if self.stop is not None:
            self.stop.set()
            self.stop = None
        self.snap = None                # next open starts from fresh data, not a stale frame

    def _run(self, stop):
        while not stop.wait(SAMPLE):
            if time.monotonic() - self.seen > PAUSE_AFTER:
                continue
            try:
                snap = self.mon.sample()
                if not stop.is_set():
                    self._publish(snap)
            except Exception:           # a bad sample must not end the live view
                traceback.print_exc()

    def _publish(self, snap):
        sig = self._signature(snap)
        self.snap = snap
        if sig != self.sig:
            self.sig = sig
            self.version += 1

    @staticmethod
    def _signature(s):
        """Everything render() shows, so nothing is redrawn while nothing changes."""
        return (s.running, tuple(s.ports), s.failed, len(s.events),
                tuple((e.time, e.kind, e.who, e.ip) for e in s.events[:8]),
                tuple((c.ip, c.port, c.link, c.user, c.tty, c.key, c.command, int(c.age), int(c.idle),
                       tuple(c.spark), c.fresh) for c in s.sessions))

    def key(self, now):
        self.seen = time.monotonic()
        return self.version

    # ---- drawing -------------------------------------------------------------------------------
    def render(self, now):
        snap = self.snap
        if snap is None:                # pre-render before opening: look, but don't keep it
            if self.mon is None:
                self.mon = SshMon()
            snap = self.mon.sample()
        im = Image.new("RGB", (W, APP_H), BG)
        d = ImageDraw.Draw(im)
        self._draw_status(im, d, snap)
        self._draw_conns(im, d, snap)
        self._draw_log(im, d, snap)
        return to_rgbx(im)

    def _draw_status(self, im, d, s):
        x0, y0, x1, _ = STATUS
        card(d, STATUS, "sshd")
        col = ACCENT if s.running else ERR
        d.ellipse([x0 + 18, y0 + 20, x0 + 32, y0 + 34], fill=col)
        draw_text(im, x0 + 42, y0 + 12, "listening" if s.running else "NOT RUNNING", 30, col)
        y = y0 + 46
        for link, ip, port in s.ports[:3]:
            text = f"{link:<6}{ip}"
            draw_text(im, x0 + 18, y, text, 20, MID)
            state = f":{port} open" if port else " closed"
            draw_text(im, x0 + 18 + text_len(text, 20), y, state, 20, ACCENT if port else MID)
            y += 21
        n = str(len(s.sessions))
        draw_text(im, x1 - 46 - text_len(n, 60) / 2, y0 + 12, n, 60, FLARE if s.sessions else DIM)
        draw_text(im, x1 - 46 - text_len("live", 20) / 2, y0 + 78, "live", 20, MID if s.sessions else DIM)

    def _draw_conns(self, im, d, s):
        x0, y0, x1, y1 = CONNS
        card(d, CONNS, "connections")
        if not s.sessions:
            for text, size, col, dy in (("no connections", 30, MID, 110), ("waiting for logins", 20, DIM, 146)):
                draw_text(im, (W - text_len(text, size)) / 2, y0 + dy, text, size, col)
            return
        y = y0 + 14
        for i, c in enumerate(s.sessions[:MAX_ROWS]):
            if i:
                d.line([(x0 + 14, y - 6), (x1 - 14, y - 6)], fill=DIM)
            self._draw_row(im, d, c, x0 + 16, x1 - 16, y)
            y += ROW_H
        extra = len(s.sessions) - MAX_ROWS
        if extra > 0:
            text = f"+{extra} more"
            draw_text(im, x1 - 16 - text_len(text, 20), y1 - 22, text, 20, WARN)

    def _draw_row(self, im, d, c, x0, x1, y):
        authed = c.user is not None
        col = FLARE if c.fresh else (ACCENT if authed else WARN)
        age = span(c.age)
        draw_text(im, x1 - text_len(age, 26), y, age, 26, MID)
        ipw = x1 - x0 - text_len(age, 26) - 70
        ip = fit(c.ip, 30, ipw)
        draw_text(im, x0, y - 2, ip, 30, col)
        draw_text(im, x0 + text_len(ip, 30) + 10, y + 5, c.link, 20, MID)
        left = SPARK_X0 - x0 - 10
        if not authed:
            draw_text(im, x0, y + 32, "logging in...", 22, WARN)
            return
        who = c.user + (f" {c.tty}" if c.tty else "") + (f" {c.key}" if c.key else "")
        draw_text(im, x0, y + 30, fit(who, 20, left), 20, MID)
        cmd = "$ " + c.command if c.command else "no command"
        draw_text(im, x0, y + 50, fit(cmd, 20, left), 20, ACCENT if c.command else MID)
        idle = "active" if c.idle < 2 else "idle " + span(c.idle)
        draw_text(im, x0, y + 70, idle, 20, ACCENT if c.idle < 2 else MID)
        self._draw_spark(d, c.spark, y + SPARK_Y)

    @staticmethod
    def _draw_spark(d, spark, y):
        peak = max(max(spark), 4)
        base = y + SPARK_H
        d.line([(SPARK_X0, base), (SPARK_X0 + len(spark) * SPARK_BAR, base)], fill=DIM)
        for i, v in enumerate(spark):
            if v > 0:
                x = SPARK_X0 + i * SPARK_BAR
                d.rectangle([x, base - max(2, int(SPARK_H * v / peak)), x + SPARK_BAR - 2, base],
                            fill=ACCENT)

    def _draw_log(self, im, d, s):
        x0, y0, x1, y1 = LOG
        label = f"log - {s.failed} rejected" if s.failed else "log"
        card(d, LOG, label)
        if not s.events:
            draw_text(im, x0 + 18, y0 + 18, "nothing logged yet", LOG_SIZE, DIM)
            return
        y = y0 + 12
        for e in s.events[:(y1 - y0 - 14) // LOG_ROW]:
            col = LOG_COLOURS[e.kind]
            draw_text(im, x0 + 16, y, e.time, LOG_SIZE, MID)
            draw_text(im, x0 + 84, y, e.kind, LOG_SIZE, col)
            draw_text(im, x0 + 146, y, fit(f"{e.who} {e.ip}", LOG_SIZE, x1 - x0 - 158), LOG_SIZE, col)
            y += LOG_ROW

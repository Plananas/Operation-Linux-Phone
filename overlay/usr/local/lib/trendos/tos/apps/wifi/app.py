"""Wi-Fi app: shows the current connection and nearby networks, and lets you join a network by
tapping it and typing the password on the on-screen keyboard.

Status/scan run in short background threads so the UI never stalls on the slow `iw scan`.
Connecting shells out to /usr/local/sbin/wifi-connect (writes the saved config and associates).
"""
import re, subprocess, threading, time

import math

from ...config import W, H, TOP, APP_H, ACCENT, GREY, DIM, TEXT, PALETTE, GREEN, DIMGREEN, CW, CH
from ...gfx import canvas, font, to_rgbx
from ...keyboard import Keyboard, KB_Y
from ...models import boxes
from ...render import card_tiles, draw_view, matrix
from ... import ui
from ..base import App

STATUS_EVERY, SCAN_EVERY = 2.0, 15.0
ROW_Y0, ROW_H = TOP + 196, 42          # network list rows (screen coords)
STATUS = (14, 12, W - 14, 158)          # "wi-fi" status card (app coords)
VCOLS, VROWS = 15, 11                   # 3D signal-bars viewport (8 x 12 px cells): 120 x 132 px
VX, VY = W - 24 - VCOLS * CW, STATUS[1] + 10
VIS_FPS = 15
BAR_X, BAR_H = (-0.93, -0.31, 0.31, 0.93), (0.30, 0.55, 0.80, 1.05)   # as the "signal" icon


def _level(dbm):
    """Signal 0..4 bars, continuous: -90 dBm = 0, -50 dBm = 4."""
    return 0.0 if dbm is None else max(0.0, min(4.0, (dbm + 90) / 10))


_bar_shapes = {}


def bars_shape(level):
    """The signal icon in 3D with the bottom of each bar lit up to `level` (0..4): lit part
    green, the rest of the bar dim green. Cached per 1/20 bar."""
    q = round(level * 20) / 20
    if q not in _bar_shapes:
        lit, dim = [], []
        for i, (x, hy) in enumerate(zip(BAR_X, BAR_H)):
            f = max(0.0, min(1.0, q - i))            # how much of bar i is lit
            full = 2 * hy
            if f > 0.02:
                h = full * f
                lit.append(((x, -1.05 + h / 2, 0), (0.18, h / 2, 0.20)))
            if f < 0.98:
                h = full * (1 - f)
                dim.append(((x, -1.05 + full - h / 2, 0), (0.18, h / 2, 0.20)))
        parts = []
        if lit:
            parts.append(boxes(lit, colour_by_axis=(GREEN, GREEN, GREEN)))
        if dim:
            parts.append(boxes(dim, colour_by_axis=(DIMGREEN, DIMGREEN, DIMGREEN)))
        from ...models import Shape
        _bar_shapes[q] = parts[0] if len(parts) == 1 else Shape.combine(*parts)
    return _bar_shapes[q]



def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _bars(dbm):
    if dbm is None:
        return 0
    return 4 if dbm >= -55 else 3 if dbm >= -67 else 2 if dbm >= -78 else 1


class WifiApp(App):
    name = "Wi-Fi"

    def __init__(self):
        self.status = {"connected": False}
        self.networks = []                 # [(ssid, dbm, secured)]
        self.version = 0
        self.next_status = self.next_scan = 0.0
        self._busy = False
        self.mode = "list"                 # list | connect | busy | result
        self.level = 0.0                   # displayed signal level (eases to the real one)
        self.last_t = time.monotonic()
        self._list_key, self._buf = None, None
        self.kb = None
        self.sel = None                    # SSID being connected to
        self.msg = ""

    # ---- background data ----
    def _refresh(self, do_scan):
        try:
            r = _run(["iw", "dev", "wlan0", "link"], 3)
            link = r.stdout if r else ""
            st = {"connected": "Connected to" in link}
            if st["connected"]:
                m = re.search(r"SSID: (.+)", link); st["ssid"] = m.group(1).strip() if m else "?"
                m = re.search(r"signal: (-?\d+)", link); st["dbm"] = int(m.group(1)) if m else None
                r = _run(["ip", "-4", "addr", "show", "wlan0"], 2)
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout if r else "")
                st["ip"] = m.group(1) if m else "?"
            if st != self.status:
                self.status = st; self.version += 1
            if do_scan:
                r = _run(["iw", "dev", "wlan0", "scan"], 8)
                if r:
                    nets = self._parse_scan(r.stdout)
                    if nets != self.networks:
                        self.networks = nets; self.version += 1
        finally:
            self._busy = False

    @staticmethod
    def _parse_scan(out):
        best = {}                          # ssid -> [dbm, secured]
        sig = ssid = None; sec = False
        def flush():
            if ssid and sig is not None and ssid.isprintable() and "\\x00" not in ssid:
                cur = best.get(ssid)
                if cur is None or sig > cur[0]:
                    best[ssid] = [sig, sec]
        for line in out.splitlines():
            if line.startswith("BSS "):
                flush(); sig = ssid = None; sec = False
            else:
                s = line.strip()
                if s.startswith("signal:"):
                    sig = int(float(s.split()[1]))
                elif s.startswith("SSID:"):
                    ssid = s[5:].strip()
                elif s.startswith("RSN:") or s.startswith("WPA:"):
                    sec = True
        flush()
        return [(k, v[0], v[1]) for k, v in sorted(best.items(), key=lambda kv: -kv[1][0])[:7]]

    def key(self, now):
        if self.mode == "list" and not self._busy and now >= self.next_status:
            do_scan = now >= self.next_scan
            self.next_status = now + STATUS_EVERY
            if do_scan:
                self.next_scan = now + SCAN_EVERY
            self._busy = True
            threading.Thread(target=self._refresh, args=(do_scan,), daemon=True).start()
        if self.mode == "connect":
            return ("connect", self.sel, self.kb.key(now))
        if self.mode == "list":
            return (self.mode, self.version, self.msg, int(now * VIS_FPS))   # 3D bars animate
        return (self.mode, self.version, self.msg)

    # ---- input ----
    def _row_at(self, y):
        i = int((y - ROW_Y0) // ROW_H)
        return i if 0 <= i < len(self.networks) else None

    def touch(self, ev, x, y):
        if self.mode == "list":
            if ev != "up":
                return
            i = self._row_at(y)
            if i is not None:
                ssid, _, secured = self.networks[i]
                if secured:
                    self.sel = ssid
                    self.kb = Keyboard(on_done=self._do_connect, on_cancel=self._to_list)
                    self.mode = "connect"
                else:
                    self._do_connect("")            # open network
                    self.sel = ssid
            elif y > ROW_Y0 - 40:
                self.next_scan = 0.0                 # tap empty area to rescan
        elif self.mode == "connect":
            self.kb.touch(ev, x, y)
        elif self.mode == "result":
            if ev == "up":
                self._to_list()

    def second_finger(self, ev, x, y):
        if self.mode == "connect":
            self.kb.touch(ev, x, y, finger=1)

    def _to_list(self):
        self.mode, self.kb = "list", None
        self.next_status = self.next_scan = 0.0

    def _do_connect(self, password):
        if self.mode == "list" and self.sel is None:
            return
        ssid = self.sel
        self.mode, self.msg = "busy", f"connecting to {ssid}…"
        self.kb = None
        threading.Thread(target=self._connect_thread, args=(ssid, password), daemon=True).start()

    def _connect_thread(self, ssid, password):
        r = _run(["/usr/local/sbin/wifi-connect", ssid, password], 40)
        ok = r is not None and r.returncode == 0
        if ok:
            self._to_list()
        else:
            self.mode = "result"
            self.msg = f"could not connect to {ssid}\n(wrong password or out of range)"

    # ---- drawing ----
    def render(self, now):
        if self.mode == "connect":
            return self._render_connect()
        if self.mode in ("busy", "result"):
            return self._render_message()
        k = (self.version, repr(self.status), repr(self.networks))
        if k != self._list_key:                      # the list itself: only when it changes
            self._list_key, self._base = k, self._render_list()
            self._buf = self._base.copy()
        self._draw_bars(now)
        return self._buf

    def _draw_bars(self, now):
        """3D signal bars in the status card, swaying gently, easing to the real signal."""
        dt, self.last_t = min(0.2, now - self.last_t), now
        target = _level(self.status.get("dbm")) if self.status.get("connected") else 0.0
        self.level += (target - self.level) * (1 - math.exp(-4 * dt))
        h, w = VROWS * CH, VCOLS * CW
        self._buf[VY:VY + h, VX:VX + w] = self._base[VY:VY + h, VX:VX + w]
        m9 = matrix(0.28, 0.10 * math.sin(0.9 * now), 0.55 * math.sin(0.6 * now), 0.0)
        draw_view(self._buf, bars_shape(self.level), m9, VCOLS * 1.9, VCOLS, VROWS, VX, VY,
                           card_tiles(VY, ui.PANEL, ui.SCAN, STATUS[1]))

    def _render_list(self):
        im, d = canvas(APP_H)
        f_big, f_mid, f_small = font(34), font(20), font(16, bold=False)
        st = self.status
        ui.card(d, STATUS, "wi-fi")
        if st.get("connected"):
            name = st.get("ssid", "?")
            name = name if len(name) <= 14 else name[:13] + "…"
            d.text((30, 32), name, fill=ACCENT, font=f_big)
            d.text((30, 82), st.get("ip", "?"), fill=TEXT, font=f_small)
            d.text((30, 108), f"{st.get('dbm', '?')} dBm", fill=ui.MID, font=f_small)
        else:
            d.text((30, 50), "not connected", fill=GREY, font=f_big)
        d.text((22, 168), "nearby networks  (tap to join)", fill=GREY, font=f_small)
        if not self.networks:
            d.text((30, ROW_Y0 - TOP), "scanning…", fill=DIM, font=f_mid)
        for i, (ssid, dbm, secured) in enumerate(self.networks):
            y = ROW_Y0 - TOP + i * ROW_H
            here = st.get("connected") and ssid == st.get("ssid")
            name = ssid if len(ssid) <= 24 else ssid[:23] + "…"
            d.text((30, y), name, fill=PALETTE[GREEN] if here else TEXT, font=f_mid)
            if not secured:
                d.text((30 + d.textlength(name, font=f_mid) + 10, y + 4), "open", fill=DIM, font=f_small)
            self._signal(d, W - 90, y + 2, _bars(dbm))
        return to_rgbx(im)

    def _render_connect(self):
        im, d = canvas(APP_H)
        d.text((24, 24), "Connect to", fill=GREY, font=font(18, bold=False))
        d.text((24, 48), self.sel or "", fill=ACCENT, font=font(30))
        fld_y = 110
        d.rounded_rectangle([20, fld_y, W - 20, fld_y + 52], 10, fill=(10, 16, 13), outline=DIM, width=2)
        txt = self.kb.text or "password"
        col = TEXT if self.kb.text else DIM
        d.text((34, fld_y + 12), txt, fill=col, font=font(24, bold=False))
        d.text((24, fld_y + 68), "esc to cancel · done to connect", fill=DIM, font=font(15, bold=False))
        img = to_rgbx(im).copy()          # writable: we overlay the keyboard
        kb_img = self.kb.render()
        img[KB_Y - TOP:KB_Y - TOP + kb_img.shape[0]] = kb_img
        return img

    def _render_message(self):
        im, d = canvas(APP_H)
        lines = self.msg.split("\n")
        y = APP_H // 2 - 20 * len(lines)
        for ln in lines:
            d.text(((W - d.textlength(ln, font=font(22))) / 2, y), ln, fill=ACCENT, font=font(22))
            y += 40
        if self.mode == "result":
            tip = "tap to go back"
            d.text(((W - d.textlength(tip, font=font(16, bold=False))) / 2, y + 20), tip, fill=DIM, font=font(16, bold=False))
        return to_rgbx(im)

    @staticmethod
    def _signal(d, x, y, bars):
        for i in range(4):
            h = 6 + i * 7
            col = (0, 200, 110) if i < bars else (40, 50, 45)
            d.rectangle([x + i * 12, y + 28 - h, x + i * 12 + 8, y + 28], fill=col)

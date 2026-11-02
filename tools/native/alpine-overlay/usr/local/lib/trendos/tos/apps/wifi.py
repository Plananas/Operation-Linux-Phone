"""Wi-Fi app: shows the current connection and nearby networks, and lets you join a network by
tapping it and typing the password on the on-screen keyboard.

Status/scan run in short background threads so the UI never stalls on the slow `iw scan`.
Connecting shells out to /usr/local/sbin/wifi-connect (writes the saved config and associates).
"""
import re, subprocess, threading, time

from ..config import W, H, TOP, APP_H, ACCENT, GREY, DIM, TEXT, PALETTE, GREEN
from ..gfx import canvas, font, to_rgbx
from ..keyboard import Keyboard, KB_Y
from .base import App

STATUS_EVERY, SCAN_EVERY = 2.0, 15.0
ROW_Y0, ROW_H = TOP + 168, 42          # network list rows (screen coords)


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
        return self._render_list()

    def _render_list(self):
        im, d = canvas(APP_H)
        f_big, f_mid, f_small = font(34), font(20), font(16, bold=False)
        st = self.status
        d.rounded_rectangle([14, 14, W - 14, 118], 14, fill=(6, 13, 9), outline=(0, 80, 45), width=2)
        if st.get("connected"):
            d.text((30, 26), st.get("ssid", "?"), fill=ACCENT, font=f_big)
            self._signal(d, W - 150, 34, _bars(st.get("dbm")))
            d.text((30, 74), f"{st.get('ip','?')}   {st.get('dbm','?')} dBm", fill=TEXT, font=f_small)
        else:
            d.text((30, 40), "not connected", fill=GREY, font=f_big)
        d.text((22, 140), "nearby networks  (tap to join)", fill=GREY, font=f_small)
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

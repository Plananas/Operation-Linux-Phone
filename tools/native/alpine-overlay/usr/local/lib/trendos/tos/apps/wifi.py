"""Wi-Fi status app: shows the current connection and nearby networks.

Read-only for now (connecting to a new secured network needs an on-screen keyboard, which comes
later; new networks are added over SSH with `wifi-connect`). Status and scan run in short
background threads so the UI never stalls on the slow `iw scan`.
"""
import re, subprocess, threading, time

from ..config import W, APP_H, ACCENT, GREY, DIM, TEXT, PALETTE, GREEN, RED
from ..gfx import canvas, font, to_rgbx
from .base import App

STATUS_EVERY, SCAN_EVERY = 2.0, 15.0


def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _bars(dbm):
    if dbm is None:
        return 0
    return 4 if dbm >= -55 else 3 if dbm >= -67 else 2 if dbm >= -78 else 1


class WifiApp(App):
    name = "Wi-Fi"

    def __init__(self):
        self.status = {"connected": False}
        self.networks = []                 # [(ssid, dbm)]
        self.version = 0                   # bumps when data changes
        self.next_status = self.next_scan = 0.0
        self._busy = False

    # ---- background data ----
    def _refresh(self, do_scan):
        try:
            link = _run(["iw", "dev", "wlan0", "link"], 3)
            st = {"connected": "Connected to" in link}
            if st["connected"]:
                m = re.search(r"SSID: (.+)", link); st["ssid"] = m.group(1).strip() if m else "?"
                m = re.search(r"signal: (-?\d+)", link); st["dbm"] = int(m.group(1)) if m else None
                ipo = _run(["ip", "-4", "addr", "show", "wlan0"], 2)
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ipo); st["ip"] = m.group(1) if m else "?"
            if st != self.status:
                self.status = st; self.version += 1
            if do_scan:
                out = _run(["iw", "dev", "wlan0", "scan"], 8)
                best = {}
                cur = None
                for line in out.splitlines():
                    s = line.strip()
                    if s.startswith("signal:"):
                        cur = int(float(s.split()[1]))
                    elif s.startswith("SSID:"):
                        ssid = s[5:].strip()
                        if ssid and cur is not None and ssid.isprintable() and "\\x00" not in ssid:
                            best[ssid] = max(best.get(ssid, -999), cur)
                nets = sorted(best.items(), key=lambda kv: -kv[1])[:8]
                if nets and nets != self.networks:
                    self.networks = nets; self.version += 1
        finally:
            self._busy = False

    def key(self, now):
        if not self._busy and now >= self.next_status:
            do_scan = now >= self.next_scan
            self.next_status = now + STATUS_EVERY
            if do_scan:
                self.next_scan = now + SCAN_EVERY
            self._busy = True
            threading.Thread(target=self._refresh, args=(do_scan,), daemon=True).start()
        return self.version

    def touch(self, ev, x, y):
        if ev == "up":
            self.next_scan = 0.0           # tap anywhere to rescan now

    # ---- drawing ----
    def render(self, now):
        im, d = canvas(APP_H)
        f_big, f_mid, f_small = font(34), font(20), font(16, bold=False)
        st = self.status
        # status card
        d.rounded_rectangle([14, 14, W - 14, 118], 14, fill=(6, 13, 9), outline=(0, 80, 45), width=2)
        if st.get("connected"):
            d.text((30, 26), st.get("ssid", "?"), fill=ACCENT, font=f_big)
            self._signal(d, W - 150, 34, _bars(st.get("dbm")))
            d.text((30, 74), f"{st.get('ip','?')}   {st.get('dbm','?')} dBm", fill=TEXT, font=f_small)
        else:
            d.text((30, 40), "not connected", fill=GREY, font=f_big)
        # nearby list
        d.text((22, 140), "nearby networks", fill=GREY, font=f_small)
        y = 170
        if not self.networks:
            d.text((30, y), "scanning...", fill=DIM, font=f_mid)
        for ssid, dbm in self.networks:
            here = st.get("connected") and ssid == st.get("ssid")
            col = PALETTE[GREEN] if here else TEXT
            name = ssid if len(ssid) <= 26 else ssid[:25] + "…"
            d.text((30, y), name, fill=col, font=f_mid)
            self._signal(d, W - 110, y + 2, _bars(dbm))
            y += 42
        d.text((22, APP_H - 70), "tap to rescan", fill=DIM, font=f_small)
        d.text((22, APP_H - 46), "add a network over SSH: wifi-connect", fill=DIM, font=f_small)
        return to_rgbx(im)

    @staticmethod
    def _signal(d, x, y, bars):
        for i in range(4):
            h = 6 + i * 7
            col = (0, 200, 110) if i < bars else (40, 50, 45)
            d.rectangle([x + i * 12, y + 28 - h, x + i * 12 + 8, y + 28], fill=col)

"""Bluetooth (Settings > Bluetooth): switch Bluetooth on/off, find, pair and connect devices.

  "bluetooth" card  the phone's Bluetooth name + address, status, and the 3D Bluetooth rune
                    (spins faster while scanning)
  keys              on/off, scan (finds devices for 20 s)
  "my devices"      paired devices: kind and state; tap the key to connect / disconnect, x to
                    forget. A connected speaker or headphones become the Radio's audio output.
  "nearby"          devices found by the scan (named ones, strongest first); tap to pair and
                    connect.

Driven by tos/hw/bluetooth.py (a bluetoothctl that is also the pairing agent), started when the
app opens; connections stay up after it closes (bluetoothd keeps them).
"""
import math, time

from PIL import Image, ImageDraw

from ..config import W, TOP, APP_H, ACCENT, CW, CH
from ..gfx import to_rgbx, text_len, draw_text
from ..hw.bluetooth import BtCtl, SCAN_TIME
from ..models import get as get_model
from ..render import card_tiles, draw_view, matrix
from ..ui import BG, PANEL, SCAN, DIM, MID, ERR, Keys, card
from .base import App

STATUS = (14, 12, W - 14, 150)
MINE = (14, 238, W - 14, 482)
NEARBY = (14, 498, W - 14, APP_H - 14)
ROW_H, MINE_ROWS, NEAR_ROWS = 54, 4, 3
VCOLS, VROWS = 12, 10                          # 3D rune: 96 x 120 px
VX, VY = W - 26 - VCOLS * CW, STATUS[1] + 8
VIS_FPS = 15
KIND_TEXT = {"headset": "headset", "headphones": "headphones", "speaker": "speaker",
             "phone": "phone", "computer": "computer", "keyboard": "keyboard", "mouse": "mouse",
             "gamepad": "gamepad", "tv": "tv"}


class BluetoothApp(App):
    name = "Bluetooth"

    def __init__(self):
        self.bt = BtCtl()
        self.pressed = None
        self.spin, self.last_t = 0.0, time.monotonic()
        self._slow_shown, self._img, self._buf = None, None, None

    def on_open(self):
        self.bt.start()

    def on_close(self):
        if self.bt.discovering:
            self.bt.scan(False)
        self.bt.stop()
        self.pressed = None

    # ---- lists -----------------------------------------------------------------------------------
    def _mine(self):
        devs = [d for d in self.bt.devices.values() if d.paired]
        return sorted(devs, key=lambda d: (not d.connected, d.label.lower()))[:MINE_ROWS]

    def _nearby(self):
        devs = [d for d in self.bt.devices.values() if not d.paired and d.named]
        return sorted(devs, key=lambda d: -(d.rssi if d.rssi is not None else -200))[:NEAR_ROWS]

    def _unnamed(self):
        return sum(1 for d in self.bt.devices.values() if not d.paired and not d.named)

    def _keys(self):
        bt = self.bt
        ks = [("power", 14, 160, 134, 62, "on" if bt.powered else "off", "on" if bt.powered else "off", 30)]
        if bt.powered:
            ks.append(("scan", 158, 160, 134, 62, "stop" if bt.discovering else "scan", "jump", 30))
            for i, d in enumerate(self._mine()):
                y = MINE[1] + 40 + i * ROW_H
                busy = bt.busy and bt.busy[1] == d.mac
                lab = "..." if busy else ("disconn." if d.connected else "connect")
                ks.append((f"c{d.mac}", 300, y + 4, 112, 42, lab, "on" if d.connected else "step", 22))
                ks.append((f"x{d.mac}", 418, y + 4, 40, 42, "x", "off", 24))
        return Keys(ks)

    # ---- input -------------------------------------------------------------------------------------
    def touch(self, ev, x, y):
        y -= TOP
        k = self._keys().hit(x, y)
        if k is None and ev == "down" and self.bt.powered and NEARBY[1] + 36 <= y < NEARBY[3]:
            i = int((y - NEARBY[1] - 36) // ROW_H)
            near = self._nearby()
            if 0 <= i < len(near):
                k = f"p{near[i].mac}"
        if ev == "down":
            self.pressed = k
        elif ev == "move" and self.pressed and not self.pressed.startswith("p") and k != self.pressed:
            self.pressed = None
        elif ev == "up":
            p, self.pressed = self.pressed, None
            if p is not None and (p == k or p.startswith("p")):
                self._press(p)

    def _press(self, k):
        bt = self.bt
        if k == "power":
            bt.power(not bt.powered)
        elif k == "scan":
            bt.scan(not bt.discovering)
        elif k[0] == "c":
            d = bt.devices.get(k[1:])
            if d is not None and not bt.busy:
                (bt.disconnect if d.connected else bt.connect)(d.mac)
        elif k[0] == "x":
            bt.forget(k[1:])
        elif k[0] == "p" and not bt.busy:
            bt.pair_and_connect(k[1:])

    # ---- drawing ------------------------------------------------------------------------------------
    def key(self, now):
        self.bt.tick()
        return self._slow_key() + (int(now * VIS_FPS),)

    def _slow_key(self):
        bt = self.bt
        left = int(bt._scan_until - time.monotonic()) if bt.discovering else 0
        return (bt.version, self.pressed, bt.powered, bt.discovering, left, bt.msg, repr(bt.busy))

    def render(self, now):
        slow = self._slow_key()
        if slow != self._slow_shown:
            self._img = to_rgbx(self._render_2d())
            self._buf = self._img.copy()
            self._slow_shown = slow
        self._draw_rune(now)
        return self._buf

    def _draw_rune(self, now):
        dt, self.last_t = min(0.2, now - self.last_t), now
        rate = 3.5 if self.bt.discovering else (0.8 if self.bt.powered else 0.0)
        self.spin += rate * dt
        h, w = VROWS * CH, VCOLS * CW
        self._buf[VY:VY + h, VX:VX + w] = self._img[VY:VY + h, VX:VX + w]
        yaw = self.spin if self.bt.discovering else 0.6 * math.sin(self.spin)
        m9 = matrix(0.22, 0.0, yaw, 0.0)
        draw_view(self._buf, get_model("bluetooth"), m9, VCOLS * 1.55, VCOLS, VROWS, VX, VY,
                           card_tiles(VY, PANEL, SCAN, STATUS[1]))

    def _row_status(self, d):
        bt = self.bt
        if bt.busy and bt.busy[1] == d.mac:
            return bt.busy[0] + " ...", ACCENT
        kind = KIND_TEXT.get(d.kind, "device")
        return (f"{kind}  -  connected", ACCENT) if d.connected else (kind, MID)

    def _render_2d(self):
        bt = self.bt
        im = Image.new("RGB", (W, APP_H), BG); d = ImageDraw.Draw(im)
        card(d, STATUS, "bluetooth")
        name = bt.alias or "TREND OS"
        draw_text(im, 30, STATUS[1] + 20, name, 34, ACCENT if bt.powered else MID)
        draw_text(im, 30, STATUS[1] + 66, bt.address or "starting ...", 17, MID)
        if not bt.powered:
            state = "> off"
        elif bt.discovering:
            left = max(0, int(bt._scan_until - time.monotonic()))
            state = f"> scanning ... {left} s"
        else:
            state = "> on  -  others see it as " + name
        draw_text(im, 30, STATUS[1] + 98, state[:34], 17, ACCENT if bt.discovering else MID)
        if bt.msg:
            col = ERR if bt.msg.startswith("failed") or "not in range" in bt.msg else MID
            lines = [bt.msg[:16], bt.msg[16:32]] if len(bt.msg) > 16 else [bt.msg]
            for i, ln in enumerate(lines):
                draw_text(im, 304, 166 + i * 22, ln, 18, col)
        card(d, MINE, "my devices")
        card(d, NEARBY, "nearby")
        if not bt.powered:
            draw_text(im, 30, MINE[1] + 40, "bluetooth is off", 22, DIM)
        else:
            mine = self._mine()
            if not mine:
                draw_text(im, 30, MINE[1] + 34, "nothing paired yet:", 20, MID)
                draw_text(im, 30, MINE[1] + 60, "put your headphones or speaker", 18, DIM)
                draw_text(im, 30, MINE[1] + 82, "in pairing mode, tap scan, then", 18, DIM)
                draw_text(im, 30, MINE[1] + 104, "tap it under nearby", 18, DIM)
            for i, dv in enumerate(mine):
                y = MINE[1] + 40 + i * ROW_H
                draw_text(im, 30, y, dv.label[:16], 26, ACCENT if dv.connected else (190, 245, 210))
                st, col = self._row_status(dv)
                draw_text(im, 30, y + 28, st, 16, col)
            near = self._nearby()
            for i, dv in enumerate(near):
                y = NEARBY[1] + 36 + i * ROW_H
                if self.pressed == f"p{dv.mac}":
                    d.rounded_rectangle([24, y - 4, W - 24, y + ROW_H - 10], 7, fill=(0, 30, 17))
                busy = bt.busy and bt.busy[1] == dv.mac
                draw_text(im, 30, y, dv.label[:22], 26, ACCENT if busy else (190, 245, 210))
                sig = f"{dv.rssi} dBm" if dv.rssi is not None else ""
                info = (bt.busy[0] + " ...") if busy else f"{KIND_TEXT.get(dv.kind, 'device')}   {sig}   tap to pair"
                draw_text(im, 30, y + 28, info, 16, ACCENT if busy else MID)
            n = self._unnamed()
            if not near:
                draw_text(im, 30, NEARBY[1] + 40, "tap scan to look for devices" if not bt.discovering
                          else "looking ...", 20, DIM)
            if n:
                draw_text(im, 30, NEARBY[3] - 30, f"+ {n} unnamed (beacons, etc.)", 16, DIM)
        self._keys().draw(im, self.pressed)
        return im

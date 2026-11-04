"""Touchscreen + keys, read raw from evdev (non-blocking).

Events: ("down"|"move"|"up", x, y, t) for the first finger (MT protocol B, slot 0) and
("key", code, 1 press / 0 release, t). Touch coordinates are screen pixels.
"""
import os, struct, time

from ..config import TOUCH_DEV, KEYS_DEV

EV_FMT = "llHHi"                         # struct input_event on 32-bit ARM (16 bytes)
EV_SZ = struct.calcsize(EV_FMT)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_MT_SLOT, ABS_MT_X, ABS_MT_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39


class Input:
    def __init__(self):
        self.fds = []
        for dev in (TOUCH_DEV, KEYS_DEV):
            try:
                self.fds.append(os.open(dev, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.slot, self.x, self.y = 0, 0, 0
        self.down, self.pending = False, None

    def poll(self):
        out = []
        for fd in self.fds:
            while True:
                try:
                    data = os.read(fd, EV_SZ * 64)
                except BlockingIOError:
                    break
                if not data:
                    break
                for _, _, typ, code, val in struct.iter_unpack(EV_FMT, data[:len(data) - len(data) % EV_SZ]):
                    if typ == EV_ABS:
                        if code == ABS_MT_SLOT:
                            self.slot = val
                        elif self.slot == 0:
                            if code == ABS_MT_TRACKING_ID:
                                self.pending = "down" if val >= 0 else "up"
                            elif code == ABS_MT_X:
                                self.x = val
                            elif code == ABS_MT_Y:
                                self.y = val
                    elif typ == EV_SYN and code == 0:
                        t = time.monotonic()
                        if self.pending == "down" and not self.down:
                            self.down = True; out.append(("down", self.x, self.y, t))
                        elif self.pending == "up" and self.down:
                            self.down = False; out.append(("up", self.x, self.y, t))
                        elif self.down:
                            out.append(("move", self.x, self.y, t))
                        self.pending = None
                    elif typ == EV_KEY and val in (0, 1):
                        out.append(("key", code, val, time.monotonic()))
        return out

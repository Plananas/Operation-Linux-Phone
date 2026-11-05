"""Touchscreen + keys, read raw from evdev (non-blocking).

Events: ("down"|"move"|"up", x, y, t) for the first finger (MT protocol B, slot 0),
("down2"|"move2"|"up2", x, y, t) for the second (slot 1), and ("key", code, 1 press / 0 release, t).
Touch coordinates are screen pixels.
"""
import os, struct, time

from ..config import TOUCH_DEV, KEYS_DEV

EV_FMT = "llHHi"                         # struct input_event on 32-bit ARM (16 bytes)
EV_SZ = struct.calcsize(EV_FMT)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_MT_SLOT, ABS_MT_X, ABS_MT_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
FINGER_KINDS = (("down", "move", "up"), ("down2", "move2", "up2"))


class _Finger:
    def __init__(self):
        self.id = -1                     # the contact in this slot, or -1
        self.x = self.y = 0
        self.sent_x = self.sent_y = 0    # where the last event said it was
        self.down, self.moved, self.pending = False, False, None

    def on_abs(self, code, val):
        if code == ABS_MT_TRACKING_ID:
            if val != self.id:
                self.id, self.pending = val, "down" if val >= 0 else "up"
        elif code == ABS_MT_X:
            self.x, self.moved = val, True
        elif code == ABS_MT_Y:
            self.y, self.moved = val, True

    def report(self, kinds, t):
        """This finger's events for one SYN, as (lifts, presses, moves)."""
        down, move, up = kinds
        lifts, presses, moves = [], [], []
        if self.pending == "down":
            if self.down:                # a new contact replaced the old one with no lift between
                lifts.append((up, self.sent_x, self.sent_y, t))
            self.down = True
            presses.append((down, self.x, self.y, t))
        elif self.pending == "up":
            if self.down:
                lifts.append((up, self.x, self.y, t))
            self.down = False
        elif self.down and (self.moved or move == "move"):
            moves.append((move, self.x, self.y, t))
        self.pending, self.moved = None, False
        self.sent_x, self.sent_y = self.x, self.y
        return lifts, presses, moves


class Input:
    def __init__(self):
        self.fds = []
        for dev in (TOUCH_DEV, KEYS_DEV):
            try:
                self.fds.append(os.open(dev, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.slot = 0
        self.fingers = (_Finger(), _Finger())

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
                        elif self.slot < len(self.fingers):
                            self.fingers[self.slot].on_abs(code, val)
                    elif typ == EV_SYN and code == 0:
                        out += self._report(time.monotonic())
                    elif typ == EV_KEY and val in (0, 1):
                        out.append(("key", code, val, time.monotonic()))
        return out

    def _report(self, t):
        """Lifts come first, so that a finger leaving and another landing in one SYN stay in order."""
        reports = [f.report(kinds, t) for f, kinds in zip(self.fingers, FINGER_KINDS)]
        return [ev for part in zip(*reports) for events in part for ev in events]

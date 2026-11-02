"""Framebuffer pages, page flipping with vsync, and screen sleep/wake.

sprdfb notes (Samsung SC8830 kernel 3.10):
- FBIOPAN_DISPLAY returns immediately; the switch happens at the next refresh, so we wait with
  FBIO_WAITFORVSYNC after every flip (sleeps, no CPU) and draw into the page shown 2 flips ago.
- Screen off/on is Android's earlysuspend: "mem" / "on" in /sys/power/state. A wake lock keeps
  the phone itself running (it's a server), so only panel, backlight and touch switch off.
"""
import fcntl, mmap, os, struct, threading

import numpy as np

from .config import W, H, NPAGES, FB_DEV, BACKLIGHT, BRIGHTNESS

FBIOGET_VSCREENINFO, FBIOPAN_DISPLAY, FBIO_WAITFORVSYNC = 0x4600, 0x4606, 0x40044620
_YOFFSET = slice(20, 24)           # fb_var_screeninfo.yoffset


def sysfs_write(path, value):
    try:
        with open(path, "w") as f:
            f.write(value)
    except OSError:
        pass


class Framebuffer:
    def __init__(self):
        self.fd = os.open(FB_DEV, os.O_RDWR)
        self._var = bytearray(fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, bytes(160)))
        self._mm = mmap.mmap(self.fd, W * H * 4 * NPAGES, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.pages = np.frombuffer(self._mm, np.uint8).reshape(NPAGES, H, W, 4)
        self._vsync_arg = struct.pack("I", 0)

    def show(self, page):
        """Flip to `page`, then wait for the refresh so the previous page is really off screen."""
        self._var[_YOFFSET] = (page * H).to_bytes(4, "little")
        try:
            fcntl.ioctl(self.fd, FBIOPAN_DISPLAY, bytes(self._var))
            fcntl.ioctl(self.fd, FBIO_WAITFORVSYNC, self._vsync_arg)
        except OSError:
            pass                           # EPERM while the display is suspended: harmless

    @staticmethod
    def screen_off():
        sysfs_write("/sys/power/wake_lock", "alpine-keepawake")   # never really suspend
        sysfs_write("/sys/power/state", "mem")

    def screen_on(self, page):
        for _ in range(2):                                        # retry once if needed
            sysfs_write("/sys/power/state", "on")
            t = threading.Thread(target=lambda: open("/sys/power/wait_for_fb_wake").read(), daemon=True)
            t.start(); t.join(2.0)
            if not t.is_alive():
                break
        self.show(page)                    # make the controller scan out our page again
        sysfs_write(BACKLIGHT, str(BRIGHTNESS))

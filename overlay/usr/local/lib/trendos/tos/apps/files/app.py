"""Files: add and fetch files from a browser on the home network.

The server is its own program, native/filesd/, which gives up root and can only touch the shared
folders. The screen is C: native/libtrend/src/apps/files/. This class starts and stops the server and
passes its status lines across. Sharing carries on when the app closes, and stops by itself after 30
idle minutes, or when the shell stops.
"""
import fcntl
import os
import subprocess

import numpy as np

from ... import canvas, native
from ...config import (ACCENT, APP_H, CAM_Z, CH, CW, FILES_DIR, FILES_TMP, FILESD, FILESD_FONT, FILESD_PAGE,
                       FILESD_USER, LIGHT, MUSIC_DIR, NS, PALETTE, RED, TOP, W)
from ...render import card_tiles
from ...ui import PANEL, SCAN
from ..base import App

ELLIPSIS_SLOT = 0x85                            # native/libtrend/include/trend/apps/files.h
CARD_Y0, ICON_Y, ICON_COLS, ICON_ROWS = 16, 124, 19, 12
ICON_K = 30.0
LATIN1 = bytes([*range(0x20, 0x7f), *range(0xa0, 0x100)]).decode("latin-1")
NOT_INSTALLED = "not installed: run tools/deploy.sh"


class FilesApp(App):
    name = "Files"

    def __init__(self):
        self._state = native.files_new()
        self._status = native.files_status_new()
        self._proc = None
        self._theme = None
        self._buf = None

    @property
    def keep_awake(self):
        """The PIN has to stay readable while someone types it in."""
        return native.files_phase(self._status) != native.FILES_OFF

    def _start(self):
        native.files_set_phase(self._status, native.FILES_STARTING)
        try:
            self._proc = subprocess.Popen(
                [FILESD, "-u", FILESD_USER, "-w", FILESD_PAGE, "-f", FILESD_FONT, "-t", FILES_TMP,
                 f"music={MUSIC_DIR}", f"files={FILES_DIR}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            native.files_set_phase(self._status, native.FILES_OFF, NOT_INSTALLED)
            return
        fd = self._proc.stdout.fileno()
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    def _pump(self):
        """Pass on what the server has said. Never waits, unless the server has just gone."""
        if self._proc is None:
            return
        try:
            data = os.read(self._proc.stdout.fileno(), 8192)
        except BlockingIOError:
            return
        if data:
            native.files_feed(self._status, data)
            return
        self._proc.stdout.close()
        self._proc.wait()
        self._proc = None
        native.files_set_phase(self._status, native.FILES_OFF)

    def background(self, now):
        self._pump()
        return False

    def touch(self, ev, x, y):
        cmd = native.files_touch(self._state, self._status, ev, x, y - TOP)
        if cmd == native.FILES_START:
            self._start()
        elif cmd == native.FILES_STOP and self._proc is not None:
            self._proc.terminate()

    def key(self, now):
        self._pump()
        return native.files_frame_key(self._state, self._status, now)

    def _make_theme(self):
        tables = [canvas.font_table(size, LATIN1, {ELLIPSIS_SLOT: "…"}) for size in (16, 17, 22, 25)]
        tables.append(canvas.font_table(54, "0123456789 ", {}))
        self._tiles = card_tiles(ICON_Y, PANEL, SCAN, CARD_Y0)
        view = native.view(ICON_K, CW / CH, CAM_Z, LIGHT, ICON_COLS, ICON_ROWS, NS)
        return native.files_theme(tables, ACCENT, PALETTE[RED], self.icon_shape.cmesh, view,
                                  native.atlas(self._tiles, CW, CH))

    def render(self, now):
        if self._buf is None:
            self._theme = self._make_theme()
            self._buf = np.zeros((APP_H, W, 4), np.uint8)
        native.files_render(self._state, self._status, self._theme, now, self._buf)
        return self._buf

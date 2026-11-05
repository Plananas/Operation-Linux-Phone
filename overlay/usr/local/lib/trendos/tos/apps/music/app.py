"""Music: plays files from /data/music, and carries on when the app is closed.

The app is C: native/libtrend/src/apps/music/ (touch, drawing, the visualiser) and native/player/
(finding, decoding and playing, on its own thread). This class connects them to the shell and hands
over the fonts, which PIL rasterises once.
"""
import numpy as np

from ... import canvas, native
from ...config import ACCENT, APP_H, CH, CW, MUSIC_DIR, NS, PALETTE, RED, TOP, W
from ...hw import audio, volume
from ...render import TILES
from ..base import App

ELLIPSIS_SLOT = 0x85                            # native/libtrend/include/trend/apps/music.h
LATIN1 = bytes([*range(0x20, 0x7f), *range(0xa0, 0x100)]).decode("latin-1")
FONT_SIZES = (16, 17, 22, 25)
NOT_INSTALLED = "Player not installed: run tools/deploy.sh"


def _theme():
    tables = [canvas.font_table(size, LATIN1, {ELLIPSIS_SLOT: "…"}) for size in FONT_SIZES]
    return native.music_theme(tables, ACCENT, PALETTE[RED], TILES, CW, CH, NS)


class MusicApp(App):
    name = "Music"

    def __init__(self):
        self._state = native.music_new()
        self._status = native.music_status_new()
        self._library = native.music_library_new()
        self._player = None
        self._theme = None
        self._buf = None
        self._viz = native.music_viz_new()

    def on_open(self):
        if self._player is None:
            self._player = native.player_new(MUSIC_DIR)     # it scans as it starts
            if self._player is None:
                native.music_status_init(self._status, NOT_INSTALLED)
            else:
                audio.on_take_output(self._release)
                volume.on_change(self._set_volume)
                self._set_volume(volume.level())
        else:
            native.player_command(self._player, native.MUSIC_RESCAN)

    def _set_volume(self, level):
        native.player_command(self._player, native.music_volume(level))

    def _release(self):
        native.player_command(self._player, native.MUSIC_RELEASE)

    def _send(self, cmd):
        if self._player is not None:
            native.player_command(self._player, cmd)

    def touch(self, ev, x, y):
        self._send(native.music_touch(self._state, self._status, ev, x, y - TOP))

    def key(self, now):
        if self._player is not None:
            native.player_status(self._player, self._status)
            native.player_library(self._player, self._library)
        return native.music_frame_key(self._state, self._status, now)

    def render(self, now):
        if self._buf is None:
            self._theme = _theme()
            self._buf = np.zeros((APP_H, W, 4), np.uint8)
        native.music_render(self._state, self._status, self._library, self._viz, self._theme, now, self._buf)
        return self._buf

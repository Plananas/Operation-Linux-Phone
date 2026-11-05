"""Web: a chat with an AI agent, with a browser one tab behind it.

The network and everything it brings in are handled by native/webd/, an unprivileged program, started twice: one
is the agent and one is the browser, so each can work while the other waits. The screen is C:
native/libtrend/src/apps/web/. This class starts the two, carries bytes and commands between them and the screen,
and looks after the on-screen keyboard. The conversation goes on existing when the app is closed, until the shell
stops.
"""
import fcntl
import os
import re
import subprocess
import threading

import numpy as np

from ... import canvas, native
from ...config import (ACCENT, APP_H, CAM_Z, CH, CW, LIGHT, NS, PALETTE, RED, TOP, W, WEB_API_BASE, WEB_KEY_FILE,
                       WEB_MODEL, WEB_USER, WEBD)
from ...keyboard import KB_Y, Keyboard
from ...models import MASCOT_POSES, get
from ...render import TILES
from ..base import App

LATIN1 = bytes([*range(0x20, 0x7f), *range(0xa0, 0x100)]).decode("latin-1")
HEAD_COLS, HEAD_ROWS, HEAD_K = 28, 14, 38.0
BIG_COLS, BIG_ROWS, BIG_K = 40, 22, 50.0
BLIP_LIGHT = (-1.5, 2.0, -7.0)          # nearer the front than the usual light, or its mouth would be in the dark
TEXT_MAX = 1000
READ_PER_FRAME = 8                      # reads of up to 64 KB each, so that a big page can't stall a frame
LOOKS_LIKE_ADDRESS = re.compile(r"^(https?://\S+|[\w-]+(\.[\w-]+)*\.[a-zA-Z]{2,}(:\d+)?(/\S*)?|\d+\.\d+\.\d+\.\d+(:\d+)?(/\S*)?)$")


def is_address(text):
    return bool(LOOKS_LIKE_ADDRESS.match(text.strip()))


def one_line(text):
    """The commands are lines: nothing typed or fetched can be allowed to start another."""
    return re.sub(r"[\r\n\x00-\x1f]+", " ", text)


class _Webd:
    """One running webd: bytes from it go to the screen, command lines go to it."""

    def __init__(self, status, which, args):
        self.status, self.which, self.args = status, which, args
        self.proc = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.alive():
            return True
        try:
            self.proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, bufsize=0)
        except OSError:
            self.proc = None
            return False
        for pipe in (self.proc.stdout, self.proc.stdin):
            flags = fcntl.fcntl(pipe.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(pipe.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return True

    def pump(self):
        """Pass on what it has said. Never waits."""
        if self.proc is None:
            return
        for _ in range(READ_PER_FRAME):
            try:
                data = os.read(self.proc.stdout.fileno(), 65536)
            except BlockingIOError:
                return
            except OSError:
                data = b""
            if not data:
                self.proc.stdout.close()
                self.proc.stdin.close()
                self.proc.wait()
                self.proc = None
                return
            native.web_feed(self.status, self.which, data)

    def send(self, line):
        if not self.start():
            return
        try:
            os.write(self.proc.stdin.fileno(), one_line(line).encode("utf-8", "replace") + b"\n")
        except (BlockingIOError, BrokenPipeError):
            pass


class WebApp(App):
    name = "Web"

    def __init__(self):
        self._state = native.web_new()
        self._status = native.web_status_new()
        self._agent = _Webd(self._status, native.WEB_CHAT, [WEBD, "agent", "-u", WEB_USER, "-k", WEB_KEY_FILE,
                                                            "-a", WEB_API_BASE, "-m", WEB_MODEL])
        self._browser = _Webd(self._status, native.WEB_PAGE, [WEBD, "web", "-u", WEB_USER])
        # The shell pre-renders every app while it starts, and the mascot takes a couple of seconds to build. That
        # mustn't freeze the home screen, so it's built on the side and the screen stays blank if it's opened sooner.
        self._mascot = threading.Thread(target=lambda: [get(name) for name in MASCOT_POSES], daemon=True)
        self._mascot.start()
        self._kb = None
        self._field = None                  # the form field being typed into; None means the input box
        self._theme = None
        self._buf = None

    def on_open(self):
        if not self._agent.start() or not self._browser.start():
            native.web_feed_error(self._status, "not installed: run tools/deploy.sh")

    def background(self, now):
        self._pump()
        return False

    def _pump(self):
        self._agent.pump()
        self._browser.pump()
        url = native.web_take_open(self._status)
        if url:
            self._open_in_browser(url)

    def _scroll(self, tab):
        return native.web_scroll_of(self._state, tab)

    def _open_in_browser(self, address):
        native.web_set_tab(self._state, native.WEB_PAGE)
        self._browser.send(f"G {self._scroll(native.WEB_PAGE)} {address}")

    # ---- typing ----
    def _open_keyboard(self, field=None):
        self._field = field
        self._kb = Keyboard(on_done=self._typed, on_cancel=self._close_keyboard)
        self._show_compose()

    def _show_compose(self):
        text = self._kb.text[-TEXT_MAX:]
        if self._field is not None:
            label = "form box: esc to cancel"
        else:
            label = "ask or type an address: esc to cancel"
        native.web_set_compose(self._state, text, label)

    def _close_keyboard(self):
        self._kb, self._field = None, None
        native.web_set_compose(self._state, None, None)

    def _typed(self, text):
        field = self._field
        self._close_keyboard()
        if field is not None:
            self._browser.send(f"I {field} {text}")
        elif not text.strip():
            pass
        elif is_address(text):
            self._open_in_browser(text.strip())
        else:
            self._ask(text.strip())

    def _ask(self, text):
        if native.web_tab(self._state) == native.WEB_PAGE:
            address = native.web_address(self._status)
            if address:
                self._agent.send(f"P {address}")
        native.web_set_tab(self._state, native.WEB_CHAT)
        self._agent.send(f"S {text}")

    # ---- the shell's calls ----
    def touch(self, ev, x, y):
        if self._kb is not None:
            if y >= KB_Y:
                self._kb.touch(ev, x, y)
                if self._kb is not None:
                    self._show_compose()
            return
        cmd = native.web_touch(self._state, self._status, ev, x, y - TOP)
        on_page = native.web_tab(self._state) == native.WEB_PAGE
        scroll = self._scroll(native.WEB_PAGE)
        if cmd.kind == native.WEB_LINK:
            if on_page:
                self._browser.send(f"F {scroll} {cmd.arg}")
            else:
                self._agent.send(f"F {cmd.arg}")
        elif cmd.kind == native.WEB_FIELD:
            self._open_keyboard(cmd.arg)
        elif cmd.kind == native.WEB_INPUT:
            self._open_keyboard()
        elif cmd.kind == native.WEB_NEW_CHAT:
            self._agent.send("N x")
        elif cmd.kind == native.WEB_STOP_CHAT:
            self._agent.send("C x")
        elif cmd.kind == native.WEB_BACK:
            self._browser.send(f"B {scroll}")
        elif cmd.kind == native.WEB_FORWARD:
            self._browser.send(f"W {scroll}")
        elif cmd.kind == native.WEB_RELOAD:
            self._browser.send("R")
        elif cmd.kind == native.WEB_STOP_PAGE:
            self._browser.send("X")

    def key(self, now):
        self._pump()
        frame = native.web_advance(self._state, self._status, now)
        return (frame, self._kb.key(now)) if self._kb is not None else frame

    def _make_theme(self):
        tables = [canvas.font_table(size, LATIN1, {}) for size in (16, 19, 25)]
        head = native.view(HEAD_K, CW / CH, CAM_Z, BLIP_LIGHT, HEAD_COLS, HEAD_ROWS, NS)
        hello = native.view(BIG_K, CW / CH, CAM_Z, BLIP_LIGHT, BIG_COLS, BIG_ROWS, NS)
        big = native.view(BIG_K, CW / CH, CAM_Z, LIGHT, BIG_COLS, BIG_ROWS, NS)
        return native.web_theme(tables, ACCENT, PALETTE[RED], self.icon_shape.cmesh, big, head, hello, native.atlas(TILES, CW, CH),
                                [get(name).cmesh for name in MASCOT_POSES])

    def render(self, now):
        if self._buf is None:
            self._buf = np.zeros((APP_H, W, 4), np.uint8)
        if self._theme is None:
            if self._mascot.is_alive():
                return self._buf
            self._theme = self._make_theme()
        native.web_render(self._state, self._status, self._theme, now, self._buf)
        if self._kb is not None:
            kb = self._kb.render()
            self._buf[KB_Y - TOP:KB_Y - TOP + kb.shape[0]] = kb
        return self._buf

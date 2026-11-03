"""Base class for apps."""
from ..render import shared_renderer


class App:
    name = "App"
    keep_awake = False          # True: the screen doesn't auto-sleep while this app is open
    icon_shape = None           # set by its launcher Entry: shown spinning in the title bar

    @property
    def renderer(self):
        """The shared 3D renderer: self.renderer.view(buf, shape, m9, K, cols, rows, x, y, tiles)."""
        return shared_renderer()

    def background(self, now):
        """Called by the shell about once a second, even when the app is closed or the screen
        is off (then every few seconds). Return True to be brought to the front (the screen is
        woken and any other app closed): e.g. an alarm going off."""
        return False

    def on_open(self):
        """The app is being opened (start hardware, threads, ...). render() may already have
        been called before this, to pre-render the first frame, so render must not need it."""

    def on_close(self):
        """The app was closed (Back, Home or title tap). Stop what on_open started."""

    def on_key(self, code, pressed):
        """Hardware key other than Home/Back/Power (e.g. volume: 114 down, 115 up).
        Return True if handled."""
        return False

    def touch(self, ev, x, y):
        """Touch event inside the app area: ev is "down", "move" or "up" (screen coordinates)."""

    def key(self, now):
        """A value that changes whenever the screen must be redrawn (compared per page)."""
        return "static"

    def render(self, now):
        """RGBX image of the app area: APP_H x W x 4."""
        raise NotImplementedError

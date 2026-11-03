"""Base class for apps."""


class App:
    name = "App"

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

"""Base class for apps."""


class App:
    name = "App"

    def touch(self, ev, x, y):
        """Touch event inside the app area: ev is "down", "move" or "up" (screen coordinates)."""

    def key(self, now):
        """A value that changes whenever the screen must be redrawn (compared per page)."""
        return "static"

    def render(self, now):
        """RGBX image of the app area: APP_H x W x 4."""
        raise NotImplementedError

"""The volume bar: shows over the title bar for a moment when the volume changes, and can be dragged
while it's there. It only draws and remembers what it covers; tos/hw/volume.py holds the level.
"""
import numpy as np

from . import canvas
from .config import ACCENT, DIM, NPAGES, TOP, W
from .hw import volume

SHOW_FOR = 2.0
X0, STEP = 64, 24                  # the blocks: one per level
BLOCK_Y0, BLOCK_Y1 = 20, 46
FONT = 28


def level_at(x):
    """The level for a touch at x: everything left of a block's middle is below it."""
    return max(0, min(volume.MAX, round((x - X0) / STEP)))


def _image(level):
    im = np.zeros((TOP, W, 4), np.uint8)
    canvas.text(im, 14, 18, "VOL", FONT, ACCENT)
    for i in range(volume.MAX):
        x = X0 + i * STEP
        canvas.fill_rect(im, BLOCK_Y0, BLOCK_Y1, x + 3, x + STEP - 3, ACCENT if i < level else DIM)
    canvas.text(im, X0 + volume.MAX * STEP + 8, 18, str(level), FONT, ACCENT)
    return im


class VolumeBar:
    def __init__(self):
        self.until = 0.0
        self.dragging = False
        self.under = None              # what the bar covers, for pictures of the screen
        self.on_pages = set()          # pages it has been drawn on and not yet cleaned off
        self._image = (None, None)     # (level, image)

    def visible(self, now):
        return self.dragging or now < self.until

    def show(self, now, screen):
        """screen: the page being displayed."""
        if not self.visible(now):
            self.under = screen[:TOP].copy()
        self.until = now + SHOW_FOR

    def hide(self, picture):
        """Take the bar down at once, and out of a copy of the screen."""
        if self.on_pages:
            picture[:TOP] = self.under
        self.until, self.dragging = 0.0, False

    def draw(self, buf, page, now):
        if self.visible(now):
            level = volume.level()
            if self._image[0] != level:
                self._image = (level, _image(level))
            buf[:TOP] = self._image[1]
            self.on_pages = set(range(NPAGES))

    def leaves(self, page, now):
        """True once for each page the bar has to be cleaned off, now that it's gone."""
        if self.visible(now) or page not in self.on_pages:
            return False
        self.on_pages.discard(page)
        return True

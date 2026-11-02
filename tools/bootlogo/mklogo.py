#!/usr/bin/env python3
"""Render the TREND OS boot logo (480x800 baseline JPEG, 4:4:4) using the cube renderer.
Run on the phone (needs /usr/local/bin/cube.py): python3 mklogo.py out.jpg"""
import sys
sys.path.insert(0, "/usr/local/bin")
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import cube

W, H = cube.W, cube.H
img = np.zeros((H, W, 3), np.uint8)
cube.LIGHT = np.array([1.0, 2.5, -7.0], np.float32)       # frontal light: all 3 faces visible
grid = cube.cells(-0.6, -0.75, 0.0)                     # corner view: top + two sides
pix = cube.tiles[grid].transpose(0, 2, 1, 3, 4).reshape(cube.ROWS * cube.CH, W, 4)[..., :3]
img[cube.TOP:cube.TOP + cube.ROWS * cube.CH] = np.clip(pix.astype(np.float32) * 1.5, 0, 255).astype(np.uint8)
im = Image.fromarray(img); d = ImageDraw.Draw(im)
big = ImageFont.truetype(cube.FONT, 28)
d.text(((W - d.textlength(cube.TITLE, font=big)) / 2, cube.TITLE_Y), cube.TITLE, fill=cube.ACCENT, font=big)
small = ImageFont.truetype(cube.FONT_REG, 16)
for y, txt, col in ((680, "powered by", (110, 110, 110)), (702, "alpine linux", (200, 200, 200))):
    f = small if y == 680 else ImageFont.truetype(cube.FONT, 24)
    d.text(((W - d.textlength(txt, font=f)) / 2, y), txt, fill=col, font=f)
im.save(sys.argv[1], "JPEG", quality=88, subsampling=0, optimize=False, progressive=False)
print("saved", sys.argv[1])

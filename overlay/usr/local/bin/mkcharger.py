#!/usr/bin/env python3
"""Pre-render the assets for the ramdisk charging screen (/bin/charger) -> charger.bin.

Layout (little endian u32 unless noted):
  "CHGR", version=1
  tiles:  ntiles, ns, ch, cw, then ntiles*ch*cw*4 RGBX        (same ASCII shade tiles as trendos)
  big:    count, w, h, chars[count] (bytes), masks[count][h][w] (u8 alpha)
  small:  first, count, w, h, masks[count][h][w]               (ASCII first..first+count-1)
  title:  w, h, RGBX[h][w][4]
Usage: mkcharger.py out.bin
"""
import struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REG = "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"
SHADES = " .,-~:;=!*#$@"
PALETTE = [(255, 70, 70), (70, 255, 110), (80, 140, 255), (255, 215, 50),
           (255, 80, 255), (50, 230, 230), (255, 150, 40), (230, 230, 230)]
NS, CW, CH = len(SHADES), 8, 12

def tiles():
    font = ImageFont.truetype(FONT, 12)
    t = np.zeros((len(PALETTE) * NS, CH, CW, 4), np.uint8)
    for s, c in enumerate(SHADES):
        g = Image.new("L", (CW, CH), 0); ImageDraw.Draw(g).text((1, -1), c, fill=255, font=font)
        mask = np.asarray(g, np.float32)[..., None] / 255.0
        bright = 0.35 + 0.65 * (s / (NS - 1))
        for f, rgb in enumerate(PALETTE):
            t[f * NS + s, :, :, :3] = (mask * np.array(rgb, np.float32) * bright).astype(np.uint8)
    return t

def masks(chars, font_path, size):
    f = ImageFont.truetype(font_path, size)
    w = int(round(f.getlength("M"))); asc, desc = f.getmetrics(); h = asc + desc
    out = []
    for ch in chars:
        g = Image.new("L", (w, h), 0); ImageDraw.Draw(g).text((0, 0), ch, fill=255, font=f)
        out.append(np.asarray(g, np.uint8))
    return w, h, np.stack(out)

def main():
    out = [b"CHGR", struct.pack("<I", 1)]
    t = tiles()
    out += [struct.pack("<4I", len(t), NS, CH, CW), t.tobytes()]
    big = "0123456789%"
    w, h, m = masks(big, FONT, 84)
    out += [struct.pack("<3I", len(big), w, h), big.encode(), m.tobytes()]
    first, count = 32, 95
    w, h, m = masks([chr(c) for c in range(first, first + count)], FONT_REG, 18)
    out += [struct.pack("<4I", first, count, w, h), m.tobytes()]
    f = ImageFont.truetype(FONT, 28)
    im = Image.new("RGB", (480, 36), (0, 0, 0)); d = ImageDraw.Draw(im)
    d.text(((480 - d.textlength("TREND OS", font=f)) / 2, 0), "TREND OS", fill=(0, 255, 140), font=f)
    title = np.zeros((36, 480, 4), np.uint8); title[..., :3] = np.asarray(im)
    out += [struct.pack("<2I", 480, 36), title.tobytes()]
    open(sys.argv[1], "wb").write(b"".join(out))
    print("wrote", sys.argv[1], sum(len(x) for x in out), "bytes")

if __name__ == "__main__":
    main()

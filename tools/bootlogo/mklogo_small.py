#!/usr/bin/env python3
"""Compact TREND OS boot logo for the bootloader slot (must be <= 23761 bytes).
Baseline JPEG, 480x800, 4:4:4 like Samsung's original. Usage: mklogo_small.py out.jpg [quality]"""
import sys, math, io
from PIL import Image, ImageDraw, ImageFont
W, H = 480, 800
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)

# isometric cube, flat shaded faces in the startup-screen colours
cx, cy, s = W // 2, 328, 104
top   = [(cx, cy - s), (cx + s * 0.866, cy - s / 2), (cx, cy), (cx - s * 0.866, cy - s / 2)]
left  = [(cx - s * 0.866, cy - s / 2), (cx, cy), (cx, cy + s), (cx - s * 0.866, cy + s / 2)]
right = [(cx, cy), (cx + s * 0.866, cy - s / 2), (cx + s * 0.866, cy + s / 2), (cx, cy + s)]
d.polygon(top, fill=(255, 215, 50)); d.polygon(left, fill=(200, 50, 50)); d.polygon(right, fill=(170, 60, 200))

big = ImageFont.truetype(BOLD, 56)
t = "TREND OS"; d.text(((W - d.textlength(t, font=big)) / 2, 488), t, fill=(0, 255, 140), font=big)
small = ImageFont.truetype(REG, 16); mid = ImageFont.truetype(BOLD, 24)
d.text(((W - d.textlength("powered by", font=small)) / 2, 680), "powered by", fill=(110, 110, 110), font=small)
d.text(((W - d.textlength("alpine linux", font=mid)) / 2, 704), "alpine linux", fill=(200, 200, 200), font=mid)

LIMIT = 23761
q = int(sys.argv[2]) if len(sys.argv) > 2 else 95
while True:
    b = io.BytesIO(); im.save(b, "JPEG", quality=q, subsampling=0, progressive=False, optimize=False)
    if b.tell() <= LIMIT or q <= 40: break
    q -= 3
open(sys.argv[1], "wb").write(b.getvalue()); print(f"{sys.argv[1]}: {b.tell()} bytes (limit {LIMIT}), quality {q}")

# ---- restructure to the segment layout this bootloader's decoder is proven to handle ----
# Download screen (in sboot): SOI APP0 [COM] DQT DHT(all 4 tables) SOF0 SOS
# Samsung logo  (in sboot):   ... DQT(both tables in one segment) SOF0 DHT(all 4) SOS
def segments(j):
    i, segs = 2, []
    while True:
        m = j[i + 1]; L = int.from_bytes(j[i + 2:i + 4], "big")
        segs.append((m, j[i + 4:i + 2 + L]))
        if m == 0xDA:
            return segs, j[i + 2 + L:]          # entropy-coded data + EOI
        i += 2 + L

def seg(m, body):
    return bytes([0xFF, m]) + (len(body) + 2).to_bytes(2, "big") + body

j = open(sys.argv[1], "rb").read()
segs, scan = segments(j)
get = lambda m: [b for mm, b in segs if mm == m]
out = b"\xff\xd8" + seg(0xE0, get(0xE0)[0]) + seg(0xDB, b"".join(get(0xDB))) \
      + seg(0xC4, b"".join(get(0xC4))) + seg(0xC0, get(0xC0)[0]) + seg(0xDA, get(0xDA)[0]) + scan
assert len(out) <= LIMIT
open(sys.argv[1], "wb").write(out)
print(f"restructured: {len(out)} bytes, segments: SOI APP0 DQT(x{len(get(0xDB))} merged) DHT(x{len(get(0xC4))} merged) SOF0 SOS")

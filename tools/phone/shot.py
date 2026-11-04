"""Save what the panel is showing right now as a PNG."""
import sys
from PIL import Image
pan_y = int(open("/sys/class/graphics/fb0/pan").read().split(",")[1])
with open("/dev/fb0", "rb") as f:
    f.seek(pan_y * 480 * 4)
    raw = f.read(480 * 800 * 4)
Image.frombytes("RGBX", (480, 800), raw).convert("RGB").save(sys.argv[1])

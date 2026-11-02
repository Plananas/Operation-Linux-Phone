# Replace the two embedded Trend 2 Lite logos in SBOOT (phone build G318HXCU0APF1) in place.
# Layout (compiled-in blobs): [JPEG][zero pad to 4][u32 size] ... the size field FOLLOWS the JPEG.
# New JPEG is written at the same offset, the rest of the slot zero-filled, size set to its length.
# Usage: python3 patch_sboot.py <SBOOT-original.bin> <logo.jpg> <out.bin>
import sys, hashlib
src, logo, out = sys.argv[1:]
d = bytearray(open(src, "rb").read())
assert hashlib.sha256(d).hexdigest() == "518b6c2865d2933de038b14b5e69133f0bc1a5584ab6ea218ff7f56fd6d7fe48", "unexpected SBOOT"
LEN = 23761
SLOTS = [(0x76214, 0x7bee8), (0x7beec, 0x81bc0)]     # (jpeg offset, size-field offset)
j = open(logo, "rb").read()
assert j[:3] == b"\xff\xd8\xff" and j[-2:] == b"\xff\xd9" and len(j) <= LEN, len(j)
for o, sz in SLOTS:
    assert d[o:o+3] == b"\xff\xd8\xff" and d[o+LEN-2:o+LEN] == b"\xff\xd9"
    assert int.from_bytes(d[sz:sz+4], "little") == LEN and d[o+LEN:sz] == b"\0" * (sz - o - LEN)
    d[o:sz] = j + b"\0" * (sz - o - len(j))            # jpeg + zeros up to the size field
    d[sz:sz+4] = len(j).to_bytes(4, "little")
open(out, "wb").write(d)
print("patched", out, hashlib.sha256(d).hexdigest())

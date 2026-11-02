# Rebuild the PARAM partition image (a GNU tar, padded to 2 MiB) with replaced files.
# Usage: python3 mkparam.py <original PARAM.bin> <out.bin> name=file [name=file ...]
import sys, tarfile, io
src, out, *repl = sys.argv[1:]
repl = dict(r.split("=", 1) for r in repl)
SIZE = 2 * 1024 * 1024
with tarfile.open(src) as t:
    members = [(m, t.extractfile(m).read()) for m in t.getmembers()]
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as o:
    for m, data in members:                     # same order + metadata as stock
        if m.name in repl:
            data = open(repl.pop(m.name), "rb").read()
        m.size = len(data)
        o.addfile(m, io.BytesIO(data))
assert not repl, f"not found in PARAM: {list(repl)}"
img = buf.getvalue()
assert len(img) <= SIZE, len(img)
open(out, "wb").write(img + b"\0" * (SIZE - len(img)))
print(f"{out}: {len(img)} bytes used of {SIZE}")

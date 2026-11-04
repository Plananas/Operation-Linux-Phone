# Build a root-owned newc cpio (gzip) for the native-boot ramdisk, no root needed.
# Usage: python3 mkramdisk.py <ramdisk dir> <busybox.static> <out.cpio.gz> [name=path ...]
#   extra files: e.g. logo.rgbx=... bin/fbpan=... bin/bootanim=... bootanim.bin=...
#   (files under bin/ get mode 0755, others 0644)
import os, sys, gzip, stat
src, bb, out = sys.argv[1:4]
extras = [a.split("=", 1) for a in sys.argv[4:]]
entries = []  # (name, mode, data, rdevmajor, rdevminor)
for d in ['bin', 'dev', 'proc', 'sys', 'mnt', 'mnt/data', 'newroot', 'tmp']:
    entries.append((d, stat.S_IFDIR | 0o755, b'', 0, 0))
entries.append(('dev/console', stat.S_IFCHR | 0o600, b'', 5, 1))
entries.append(('init', stat.S_IFREG | 0o755, open(os.path.join(src, 'init'), 'rb').read(), 0, 0))
entries.append(('bin/busybox', stat.S_IFREG | 0o755, open(bb, 'rb').read(), 0, 0))
for name, path in extras:
    mode = 0o755 if name.startswith('bin/') else 0o644
    entries.append((name, stat.S_IFREG | mode, open(path, 'rb').read(), 0, 0))
o = bytearray(); ino = 300000
def add(name, mode, data, ma, mi):
    global ino; ino += 1
    nm = name.encode() + b'\0'
    h = b'070701' + b''.join(b'%08X' % v for v in
        (ino, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0, len(data), 0, 0, ma, mi, len(nm), 0))
    o.extend(h + nm); o.extend(b'\0' * ((-len(o)) % 4))
    o.extend(data); o.extend(b'\0' * ((-len(o)) % 4))
for e in entries: add(*e)
add('TRAILER!!!', 0, b'', 0, 0)
o.extend(b'\0' * ((-len(o)) % 512))
open(out, 'wb').write(gzip.compress(bytes(o), 9, mtime=0)); print('ramdisk', len(o), '->', os.path.getsize(out))

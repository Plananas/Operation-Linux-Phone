#!/usr/bin/env python3
"""TREND OS shell (480x800 sprdfb framebuffer, RGBX bytes, 2 pages double-buffered).

- Takes over from the ramdisk's loading spin (bootanim) at exactly the same pose, blends into
  the full tumble, plays the startup sound, types the greeting.
- Launcher: each app is a spinning ASCII-shaded 3D object. Swipe left/right to move between
  apps (follows the finger, snaps with easing), tap the object to open the app.
  Back (touch key) or Home (button), or tapping the title, returns to the launcher.
- Stats panel on the launcher.

Rendering fast path: every (palette colour, shade character) pair is pre-rendered once as an
RGBX tile; each frame computes only a grid of tile indices with numpy (rotate, cull, project,
z-buffer, light) and copies tiles straight into the mmap'd framebuffer page (C: librender.so).
"""
import ast, ctypes, fcntl, math, mmap, operator, os, random, select, struct, subprocess, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 480, 800
FB = "/dev/fb0"
FONT = "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REG = "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"
SHADES = " .,-~:;=!*#$@"          # index 0 = empty cell
NS = len(SHADES)
PALETTE = [(255, 70, 70), (70, 255, 110), (80, 140, 255), (255, 215, 50),
           (255, 80, 255), (50, 230, 230), (255, 150, 40), (230, 230, 230)]
TITLE = "TREND OS"
GREET_NAME = "Robin"
MAX_FPS = 30
SLEEP_AFTER = 120                  # s without input -> screen off
LONG_PRESS = 0.9                   # s holding Power -> power menu
ACCENT, GREY, DIM = (0, 255, 140), (130, 130, 130), (60, 60, 60)

# Boot animation ("loading" spin, played by /bin/bootanim from the ramdisk until this program
# takes over): spin about the vertical axis, view tilted so the top face shows. Frame k is
# shown at CLOCK_MONOTONIC time t with k = floor(t * BOOT_FPS) % BOOT_N, so the spin angle is
# always 2*pi * t / BOOT_PERIOD and this program can continue from exactly the same pose.
BOOT_TILT = 0.45
BOOT_PERIOD = 4.0
BOOT_FPS = 30
BOOT_N = int(BOOT_PERIOD * BOOT_FPS)
BOOT_W = 2 * math.pi / BOOT_PERIOD
BLEND = 2.5                        # s to ease from the loading spin into the full tumble
FULL_RATES = (0.9, 0.62, 0.35)     # rad/s about x, y, z in the full tumble
BOOTANIM_PID = "/dev/.bootanim.pid"
SOUND = "/usr/local/share/trendos/startup.wav"
SOUND_PLAYED = "/run/trendos-sound-played"

# ---- layout ------------------------------------------------------------------
FONT_PX, CW, CH = 12, 8, 12        # 60 x 44 cells, rows exactly screen-wide
COLS, ROWS = W // CW, 44
TITLE_Y = 22
TOP = 66                           # object band: 66 .. 594
BAND = ROWS * CH
LABEL_Y = BAND - 50                # inside the band, below the (launcher-sized) object
DOTS_Y = BAND - 16
STATS_Y, STATS_H = 600, 196        # stats panel: 600 .. 796
APP_H = H - TOP                    # app screens use 66 .. 800

# ---- tile atlas: tile[colour * NS + shade] = CH x CW x 4 RGBX ----------------
font = ImageFont.truetype(FONT, FONT_PX)
tiles = np.zeros((len(PALETTE) * NS, CH, CW, 4), np.uint8)
for s, c in enumerate(SHADES):
    g = Image.new("L", (CW, CH), 0)
    ImageDraw.Draw(g).text((1, -1), c, fill=255, font=font)
    mask = np.asarray(g, np.float32)[..., None] / 255.0
    bright = 0.35 + 0.65 * (s / (NS - 1))
    for f, rgb in enumerate(PALETTE):
        tiles[f * NS + s, :, :, :3] = (mask * np.array(rgb, np.float32) * bright).astype(np.uint8)

# ---- shapes ------------------------------------------------------------------
class Shape:
    """Sampled surface points of a convex solid: PTS (N,3), FID face per point, FNRM outward
    normal per face, FCOL palette index per face."""
    def __init__(self, pts, fid, fnrm, fcol, convex=True):
        self.convex = convex
        self.PTS, self.FID = np.asarray(pts, np.float32), np.asarray(fid, np.int32)
        self.FNRM, self.FCOL = np.asarray(fnrm, np.float32), np.asarray(fcol, np.int32)
        starts = np.searchsorted(self.FID, np.arange(len(self.FNRM) + 1))
        self.face_idx = [np.arange(starts[i], starts[i + 1]) for i in range(len(self.FNRM))]
        self.FCEN = np.array([self.PTS[ix].mean(0) for ix in self.face_idx], np.float32)
        self.FSTART = np.ascontiguousarray(starts, np.int32)
        for a in ("PTS", "FID", "FNRM", "FCEN", "FCOL"):
            setattr(self, a, np.ascontiguousarray(getattr(self, a)))

def make_cube(n=36):
    # identical sampling/face order to the boot animation, so the handover is seamless
    u = (np.arange(n) + 0.5) / n * 2 - 1
    A_, B_ = np.meshgrid(u, u)
    pts, nrm, fid = [], [], []
    for axis in range(3):
        for sign in (-1, 1):
            p = np.zeros((n * n, 3), np.float32)
            p[:, axis] = sign
            p[:, (axis + 1) % 3] = A_.ravel()
            p[:, (axis + 2) % 3] = B_.ravel()
            nv = np.zeros(3, np.float32); nv[axis] = sign
            pts.append(p); nrm.append(nv); fid.append(np.full(n * n, len(fid), np.int32))
    return Shape(np.concatenate(pts), np.concatenate(fid), nrm, range(6))

def tri_points(a, b, c, n):
    """Evenly spread points over triangle abc (two points per grid cell)."""
    out = []
    for i in range(n):
        for j in range(n - i):
            out.append(((i + 1 / 3) / n, (j + 1 / 3) / n))
            if i + j < n - 1:
                out.append(((i + 2 / 3) / n, (j + 2 / 3) / n))
    uv = np.array(out, np.float32)
    a, b, c = (np.asarray(v, np.float32) for v in (a, b, c))
    return a + uv[:, :1] * (b - a) + uv[:, 1:] * (c - a)

def make_octahedron(r=1.45, n=30):
    pts, fid, nrm, col = [], [], [], []
    k = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                p = tri_points((sx * r, 0, 0), (0, sy * r, 0), (0, 0, sz * r), n)
                pts.append(p); fid.append(np.full(len(p), k, np.int32))
                nv = np.array([sx, sy, sz], np.float32); nrm.append(nv / np.linalg.norm(nv))
                col.append(k); k += 1
    return Shape(np.concatenate(pts), np.concatenate(fid), nrm, col)

def make_boxes(boxes, colour_by_axis, density=17):
    """Union of axis-aligned boxes [(centre, half_sizes)], drawn with a z-buffer.
    Face colour depends on the face's axis: colour_by_axis = (x, y, z) palette indices."""
    pts, fid, nrm, col = [], [], [], []
    for centre, half in boxes:
        c, h = np.asarray(centre, np.float32), np.asarray(half, np.float32)
        for axis in range(3):
            u, v = (axis + 1) % 3, (axis + 2) % 3
            nu, nv = max(2, int(2 * h[u] * density)), max(2, int(2 * h[v] * density))
            gu = ((np.arange(nu) + 0.5) / nu * 2 - 1) * h[u]
            gv = ((np.arange(nv) + 0.5) / nv * 2 - 1) * h[v]
            GU, GV = np.meshgrid(gu, gv)
            for sign in (-1, 1):
                p = np.zeros((nu * nv, 3), np.float32)
                p[:, axis] = sign * h[axis]; p[:, u] = GU.ravel(); p[:, v] = GV.ravel()
                p += c
                k = len(nrm)
                pts.append(p); fid.append(np.full(len(p), k, np.int32))
                nvec = np.zeros(3, np.float32); nvec[axis] = sign; nrm.append(nvec)
                col.append(colour_by_axis[axis])
    return Shape(np.concatenate(pts), np.concatenate(fid), nrm, col, convex=False)

def make_plus():
    return make_boxes([((0, 0, 0), (1.3, 0.42, 0.42)), ((0, 0, 0), (0.42, 1.3, 0.42))],
                      colour_by_axis=(3, 7, 6))          # x: yellow, y: white, z: orange

LIGHT = np.array([-2.5, 3.0, -5.0], np.float32)
CAM_Z = -4.5                       # camera position (0, 0, CAM_Z); points project with 1/(z - CAM_Z)
K_BOOT = COLS * 1.03               # projection scale of the boot animation
K_APP = COLS * 0.93                # launcher size (leaves room for label + dots)
ASPECT = CW / CH

def rot_x(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)

def rotation(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], np.float32)
    ry = np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]], np.float32)
    rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]], np.float32)
    return rz @ ry @ rx

def boot_R(t):
    return rot_x(BOOT_TILT) @ rotation(0.0, BOOT_W * t, 0.0)

def cells_R_np(R, shape, K=K_BOOT):
    """numpy reference/fallback: ROWS x COLS grid of tile indices for rotation matrix R."""
    fn = shape.FNRM @ R.T
    fc = shape.FCEN @ R.T
    fc[:, 2] -= CAM_Z                                   # vector camera -> face centre
    vis = np.nonzero(np.einsum("ij,ij->i", fn, fc) < 0)[0]   # perspective-correct back-face cull
    idx = np.concatenate([shape.face_idx[f] for f in vis])
    p = shape.PTS[idx] @ R.T
    f = shape.FID[idx]; n = fn[f]
    ooz = 1.0 / (p[:, 2] - CAM_Z)
    kz = K * ooz
    xp = np.clip((COLS / 2 + kz * p[:, 0]).astype(np.int32), 0, COLS - 1)
    yp = np.clip((ROWS / 2 - kz * p[:, 1] * ASPECT).astype(np.int32), 0, ROWS - 1)
    ld = LIGHT - p
    lum = np.einsum("ij,ij->i", n, ld) / np.sqrt(np.einsum("ij,ij->i", ld, ld))
    np.clip(lum, 0, 1, out=lum)
    shade = 1 + np.minimum((lum ** 1.3 * (NS - 1)).astype(np.int32), NS - 2)
    # depth order: far -> near, nearest written last wins (stable edges where faces meet,
    # correct overlap for non-convex shapes)
    order = np.argsort(ooz)
    grid = np.zeros((ROWS, COLS), np.int32)
    grid[yp[order], xp[order]] = (shape.FCOL[f] * NS + shade)[order]
    return grid

# ---- C renderer (librender.so); falls back to numpy if missing ---------------
LIBRENDER = "/usr/local/lib/trendos/librender.so"
_P = lambda a, t: a.ctypes.data_as(ctypes.POINTER(t))
try:
    _lib = ctypes.CDLL(LIBRENDER)
    _f, _i, _u8 = ctypes.c_float, ctypes.c_int, ctypes.c_uint8
    _lib.render_shape.restype = _i
    _lib.render_shape.argtypes = [ctypes.POINTER(_f), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32), _i,
                                  ctypes.POINTER(_f), ctypes.POINTER(_f), ctypes.POINTER(ctypes.c_int32),
                                  ctypes.POINTER(_f), _f, _i, _i, _f, _f, ctypes.POINTER(_f), _i,
                                  ctypes.POINTER(ctypes.c_int32)]
    _lib.render_draw.restype = _i
    _lib.render_draw.argtypes = [ctypes.c_void_p] * 7 + [ctypes.c_void_p, _f, _i, _i, _f, _f, ctypes.c_void_p, _i,
                                 ctypes.c_void_p, _i, _i, ctypes.c_void_p, _i, _i, _i, _i, _i, ctypes.c_void_p]
    _lib.blit_grid.restype = None
    _lib.blit_grid.argtypes = [ctypes.POINTER(ctypes.c_int32), _i, _i, ctypes.POINTER(_u8), _i, _i,
                               ctypes.POINTER(_u8), _i, _i, _i, _i, _i]
except OSError:
    _lib = None
_LIGHT_C = np.ascontiguousarray(LIGHT, np.float32)
_LIGHT_PTR = _LIGHT_C.ctypes.data
_TILES_PTR = tiles.ctypes.data

def cells_R(R, shape, K=K_BOOT):
    """ROWS x COLS grid of tile indices for rotation matrix R (C if available)."""
    if _lib is None:
        return cells_R_np(R, shape, K)
    R = np.ascontiguousarray(R, np.float32)
    grid = np.empty((ROWS, COLS), np.int32)
    _lib.render_shape(_P(shape.PTS, ctypes.c_float), _P(shape.FID, ctypes.c_int32), _P(shape.FSTART, ctypes.c_int32),
                      len(shape.FNRM), _P(shape.FNRM, ctypes.c_float), _P(shape.FCEN, ctypes.c_float),
                      _P(shape.FCOL, ctypes.c_int32), _P(R, ctypes.c_float), K, COLS, ROWS, ASPECT, CAM_Z,
                      _P(_LIGHT_C, ctypes.c_float), NS, _P(grid, ctypes.c_int32))
    return grid

_R9 = (ctypes.c_float * 9)()
_RECT = (ctypes.c_int32 * 4)()

def mat_py(tilt, a, b, c):
    """rot_x(tilt) @ rz(c) @ ry(b) @ rx(a) as 9 floats (row-major), without numpy overhead."""
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    # M = rz @ ry @ rx
    m = [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa,
         sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa,
         -sb,     cb * sa,                cb * ca]
    if tilt:
        ct, st = math.cos(tilt), math.sin(tilt)
        m = [m[0], m[1], m[2],
             ct * m[3] - st * m[6], ct * m[4] - st * m[7], ct * m[5] - st * m[8],
             st * m[3] + ct * m[6], st * m[4] + ct * m[7], st * m[5] + ct * m[8]]
    return m

def shape_ptrs(shape):
    if not hasattr(shape, "_cptr"):
        shape._cptr = (shape.PTS.ctypes.data, shape.FID.ctypes.data, shape.FSTART.ctypes.data, len(shape.FNRM),
                       shape.FNRM.ctypes.data, shape.FCEN.ctypes.data, shape.FCOL.ctypes.data)
    return shape._cptr

def render_into(dst, shape, m9, K, x_off):
    """Render shape straight into dst (H x W x 4 view, e.g. the band of a framebuffer page).
    Returns the touched rect (y0, y1, x0, x1)."""
    if _lib is None:
        R = np.array(m9, np.float32).reshape(3, 3)
        g = cells_R_np(R, shape, K); y0, x0, img = compose_bbox(g)
        blit(dst, img, y0, x_off + x0)
        h, w = img.shape[:2]; x0 += int(round(x_off))
        return (y0, y0 + h, max(0, x0), min(W, x0 + w)) if h else (0, 0, 0, 0)
    _R9[:] = m9
    p = shape_ptrs(shape)
    _lib.render_draw(p[0], p[1], p[2], p[3], p[4], p[5], p[6], ctypes.addressof(_R9), K, COLS, ROWS, ASPECT,
                     CAM_Z, _LIGHT_PTR, NS, _TILES_PTR, CH, CW, dst.ctypes.data, dst.strides[0], dst.shape[1],
                     dst.shape[0], int(round(x_off)), 0, ctypes.addressof(_RECT))
    return tuple(_RECT)

def draw_grid(band, grid, x_off, y_off=0):
    """Copy the tiles of non-empty cells into band (pre-cleared) at pixel offset, clipped."""
    if _lib is None:
        y0, x0, img = compose_bbox(grid)
        blit(band, img, y_off + y0, x_off + x0)
        return
    _lib.blit_grid(_P(grid, ctypes.c_int32), ROWS, COLS, _P(tiles, ctypes.c_uint8), CH, CW,
                   _P(band, ctypes.c_uint8), band.strides[0], band.shape[1], band.shape[0], int(round(x_off)), y_off)

def compose(grid):
    return tiles[grid].transpose(0, 2, 1, 3, 4).reshape(ROWS * CH, W, 4)

def compose_bbox(grid):
    """Pixels of just the occupied cells: (y0, x0, img) relative to the band."""
    rows = np.nonzero(grid.any(1))[0]; cols = np.nonzero(grid.any(0))[0]
    if not len(rows): return 0, 0, np.zeros((0, 0, 4), np.uint8)
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    g = grid[r0:r1, c0:c1]
    img = tiles[g].transpose(0, 2, 1, 3, 4).reshape((r1 - r0) * CH, (c1 - c0) * CW, 4)
    return r0 * CH, c0 * CW, img

def blit(band, img, y0, x0):
    """Copy img into band at (y0, x0), clipped horizontally to the screen."""
    x0 = int(round(x0)); h, w = img.shape[:2]
    a, b = max(0, x0), min(W, x0 + w)
    if b > a and h:
        band[y0:y0 + h, a:b] = img[:, a - x0:b - x0]

CUBE = make_cube()

# ---- framebuffer -------------------------------------------------------------
fd = os.open(FB, os.O_RDWR)
var = bytearray(fcntl.ioctl(fd, 0x4600, bytes(160)))   # FBIOGET_VSCREENINFO
NPAGES = 3                         # triple buffering: we draw into the page shown 2 flips ago
mm = mmap.mmap(fd, W * H * 4 * NPAGES, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
fbmem = np.frombuffer(mm, np.uint8).reshape(NPAGES, H, W, 4)

_VSYNC_ARG = struct.pack("I", 0)

def pan(page):
    """Show `page`, then wait for the next vertical refresh so the page that was on screen is
    really off screen before we start drawing into it (pan returns immediately on sprdfb)."""
    var[20:24] = (page * H).to_bytes(4, "little")
    fcntl.ioctl(fd, 0x4606, bytes(var))                 # FBIOPAN_DISPLAY
    try:
        fcntl.ioctl(fd, 0x40044620, _VSYNC_ARG)         # FBIO_WAITFORVSYNC (sleeps, no CPU)
    except OSError:
        pass

def to_rgbx(im):
    return np.frombuffer(im.convert("RGBX").tobytes(), np.uint8).reshape(im.height, im.width, 4)

def text_strip(txt, size, colour, h, bold=True, x=None):
    im = Image.new("RGB", (W, h), (0, 0, 0)); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT if bold else FONT_REG, size)
    d.text(((W - d.textlength(txt, font=f)) / 2 if x is None else x, 0), txt, fill=colour, font=f)
    return to_rgbx(im)

# ---- stats -------------------------------------------------------------------
def rd(path, default=""):
    try:
        with open(path) as f: return f.read().strip()
    except OSError: return default

class Stats:
    def __init__(self):
        self.prev_cpu = self._cpu(); self.prev_net = self._net(); self.prev_t = time.time()
        self.cpu = 0.0; self.cores = 1; self.rx = self.tx = 0.0

    @staticmethod
    def _cpu():
        """Per-core (total, idle) ticks. Per core, because this kernel hot-plugs core 1 on and off
        (e.g. on touch boost) and the aggregate "cpu" line then jumps -> nonsense percentages."""
        out = {}
        for line in rd("/proc/stat").splitlines():
            if line.startswith("cpu") and line[3:4].isdigit():
                f = line.split(); v = list(map(int, f[1:]))
                out[f[0]] = (sum(v), v[3] + v[4])
        return out

    @staticmethod
    def _net():
        b = "/sys/class/net/rndis0/statistics/"
        return int(rd(b + "rx_bytes", "0")), int(rd(b + "tx_bytes", "0"))

    def sample(self):
        now = time.time(); dt = max(now - self.prev_t, 1e-3)
        cur = self._cpu(); dtot = dbusy = 0
        for core, (tot, idle) in cur.items():           # cores online at both samples only
            if core in self.prev_cpu:
                t_, i_ = tot - self.prev_cpu[core][0], idle - self.prev_cpu[core][1]
                if t_ > 0 and 0 <= i_ <= t_:
                    dtot += t_; dbusy += t_ - i_
        self.cpu = 100.0 * dbusy / dtot if dtot else 0.0
        self.cores = len(cur)
        rx, tx = self._net(); prx, ptx = self.prev_net
        self.rx, self.tx = (rx - prx) / dt, (tx - ptx) / dt
        self.prev_cpu, self.prev_net, self.prev_t = cur, (rx, tx), now
        mem = {l.split(":")[0]: int(l.split()[1]) for l in rd("/proc/meminfo").splitlines()}
        avail = mem.get("MemAvailable", mem["MemFree"] + mem.get("Buffers", 0) + mem.get("Cached", 0))
        st = os.statvfs("/")
        return {
            "cpu": self.cpu, "cores": self.cores,
            "freq": int(rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "0")) / 1e6,
            "ctemp": rd("/sys/class/thermal/thermal_zone1/temp", "?"),
            "mem_used": (mem["MemTotal"] - avail) / 1024, "mem_total": mem["MemTotal"] / 1024,
            "bat": int(rd("/sys/class/power_supply/battery/capacity", "0")),
            "bat_status": rd("/sys/class/power_supply/battery/status", "?"),
            "btemp": int(rd("/sys/class/power_supply/battery/temp", "0")) / 10,
            "bvolt": int(rd("/sys/class/power_supply/battery/voltage_now", "0")) / 1e6,
            "disk_used": (st.f_blocks - st.f_bfree) * st.f_frsize / 2**30,
            "disk_total": st.f_blocks * st.f_frsize / 2**30,
            "link": rd("/sys/class/net/rndis0/operstate", "down"),
            "rx": self.rx, "tx": self.tx,
            "load": rd("/proc/loadavg").split()[0],
            "uptime": float(rd("/proc/uptime", "0").split()[0]),
        }

def human_rate(b):
    for unit in ("B", "K", "M"):
        if b < 1024: return f"{b:5.0f}{unit}/s"
        b /= 1024
    return f"{b:5.1f}G/s"

f_lbl = ImageFont.truetype(FONT, 15)
f_val = ImageFont.truetype(FONT_REG, 15)

def bar_colour(frac, invert=False):
    frac = 1 - frac if invert else frac
    return (70, 220, 110) if frac < 0.6 else (255, 200, 50) if frac < 0.85 else (255, 70, 70)

STAT_ROWS = 6

def stats_row(i, s, fps):
    """Render stats row i -> (y offset in panel, RGBX image). Row 0 includes the divider."""
    y0, h = (0, 38) if i == 0 else (12 + 26 * i, 26)
    im = Image.new("RGB", (W, h), (0, 0, 0)); d = ImageDraw.Draw(im)
    if i == 0: d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    LX, BX, BW, VX = 18, 70, 150, 232
    y = 12 + 26 * i - y0
    def row(label, frac, colour, text):
        d.text((LX, y), label, fill=ACCENT, font=f_lbl)
        if frac is not None:
            d.rectangle([BX, y + 3, BX + BW, y + 15], outline=DIM)
            d.rectangle([BX + 1, y + 4, BX + 1 + int((BW - 2) * max(0, min(1, frac))), y + 14], fill=colour)
            d.text((VX, y), text, fill=(220, 220, 220), font=f_val)
        else:
            d.text((BX, y), text, fill=(220, 220, 220), font=f_val)
    if i == 0:
        row("CPU", s["cpu"] / 100, bar_colour(s["cpu"] / 100),
            f"{s['cpu']:3.0f}% {s['cores']}c {s['freq']:.2f}GHz {s['ctemp']}\u00b0C")
    elif i == 1:
        mf = s["mem_used"] / s["mem_total"]
        row("RAM", mf, bar_colour(mf), f"{s['mem_used']:3.0f} / {s['mem_total']:.0f} MB")
    elif i == 2:
        bf = s["bat"] / 100; chg = "+" if s["bat_status"] == "Charging" else ""
        row("BAT", bf, bar_colour(bf, invert=True), f"{s['bat']:3d}%{chg} {s['bvolt']:.2f}V {s['btemp']:.1f}\u00b0C")
    elif i == 3:
        df = s["disk_used"] / s["disk_total"]
        row("DISK", df, bar_colour(df), f"{s['disk_used']:.2f} / {s['disk_total']:.1f} GB")
    elif i == 4:
        net = "192.168.42.129" if s["link"] == "up" else "usb link down"
        row("NET", None, None, f"{net}  \u2193{human_rate(s['rx'])} \u2191{human_rate(s['tx'])}")
    else:
        up = int(s["uptime"])
        row("UP", None, None, f"{up // 86400}d {up // 3600 % 24:02d}:{up // 60 % 60:02d}:{up % 60:02d}  load {s['load']}  {fps:4.1f}fps")
    return y0, to_rgbx(im)

# ---- boot frame (also used as the early logo by the ramdisk init) -----------
def boot_frame():
    img = np.zeros((H, W, 4), np.uint8)
    img[TITLE_Y:TITLE_Y + 36] = text_strip(TITLE, 28, ACCENT, 36)
    img[TOP:TOP + BAND] = compose(cells_R(boot_R(0.0), CUBE))
    bi = Image.new("RGB", (W, STATS_H), (0, 0, 0)); d = ImageDraw.Draw(bi)
    d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    msg = "booting..."; d.text(((W - d.textlength(msg, font=f_lbl)) / 2, 80), msg, fill=GREY, font=f_lbl)
    img[STATS_Y:STATS_Y + STATS_H] = to_rgbx(bi)
    return img

# ---- title: "TREND OS" backspaced, greeting typed (ends centred) -------------
class TitleAnim:
    BLINK = 0.53

    def __init__(self, text_from, text_to):
        self.font = ImageFont.truetype(FONT, 28)
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.x0 = (W - tmp.textlength(text_from, font=self.font)) / 2
        self.x1 = (W - tmp.textlength(text_to, font=self.font)) / 2
        self.cw = tmp.textlength("M", font=self.font)
        t, ev = 0.9, []
        for i in range(len(text_from), -1, -1):
            ev.append((t, text_from[:i])); t += 0.055 + random.uniform(0, 0.035)
        self.t_erased = t
        t += 0.45
        self.t_type = t
        for i in range(1, len(text_to) + 1):
            ch = text_to[i - 1]
            t += 0.055 + random.uniform(0, 0.075) + (0.12 if ch in " ,." else 0)
            ev.append((t, text_to[:i]))
        self.events, self.t_first, self.t_last = ev, ev[0][0], ev[-1][0]

    def state(self, t):
        text = self.events[0][1]
        for te, tx in self.events:
            if te > t: break
            text = tx
        if self.t_erased < t < self.t_type:
            frac = (t - self.t_erased) / (self.t_type - self.t_erased)
            return "", frac < 0.3 or frac > 0.6, self.x0 if frac < 0.5 else self.x1
        x = self.x0 if t <= self.t_erased else self.x1
        if t > self.t_last + 0.5:
            return text, False, x
        typing = self.t_first <= t <= self.t_last + 0.5
        return text, typing or int(t / self.BLINK) % 2 == 0, x

    def render(self, text, cursor, x0):
        im = Image.new("RGB", (W, 36), (0, 0, 0)); d = ImageDraw.Draw(im)
        d.text((x0, 0), text, fill=ACCENT, font=self.font)
        if cursor:
            x = x0 + d.textlength(text, font=self.font)
            d.rectangle([x + 1, 4, x + self.cw - 2, 33], fill=ACCENT)
        return to_rgbx(im)

# ---- input: touchscreen (protocol B, slot 0) + keys ---------------------------
EV_FMT = "llHHi"; EV_SZ = struct.calcsize(EV_FMT)
KEY_HOME, KEY_BACK, KEY_POWER = 102, 158, 116

class Input:
    def __init__(self):
        self.fds = []
        for dev in ("/dev/input/event1", "/dev/input/event0"):
            try: self.fds.append(os.open(dev, os.O_RDONLY | os.O_NONBLOCK))
            except OSError: pass
        self.slot, self.x, self.y = 0, 0, 0
        self.down = False; self.pending = None

    def poll(self):
        out = []
        for fdi in self.fds:
            while True:
                try: data = os.read(fdi, EV_SZ * 64)
                except BlockingIOError: break
                if not data: break
                for i in range(0, len(data) - EV_SZ + 1, EV_SZ):
                    _, _, typ, code, val = struct.unpack_from(EV_FMT, data, i)
                    if typ == 3:                                   # EV_ABS
                        if code == 0x2F: self.slot = val
                        elif self.slot == 0:
                            if code == 0x39: self.pending = "down" if val >= 0 else "up"
                            elif code == 0x35: self.x = val
                            elif code == 0x36: self.y = val
                    elif typ == 0 and code == 0:                   # SYN_REPORT
                        t = time.monotonic()
                        if self.pending == "down" and not self.down:
                            self.down = True; out.append(("down", self.x, self.y, t))
                        elif self.pending == "up" and self.down:
                            self.down = False; out.append(("up", self.x, self.y, t))
                        elif self.down:
                            out.append(("move", self.x, self.y, t))
                        self.pending = None
                    elif typ == 1 and val in (0, 1):               # key press (1) / release (0)
                        out.append(("key", code, val, time.monotonic()))
        return out

# ---- apps ----------------------------------------------------------------------
class App:
    name = "App"
    def touch(self, ev, x, y): pass
    def key(self, now): return "static"
    def render(self, now): raise NotImplementedError

class CubeApp(App):
    name = "Cube"
    def render(self, now):
        im = Image.new("RGB", (W, APP_H), (0, 0, 0)); d = ImageDraw.Draw(im)
        big = ImageFont.truetype(FONT, 40); small = ImageFont.truetype(FONT_REG, 18)
        for y, txt, f, col in ((250, "Cube", big, PALETTE[1]), (320, "This app is empty.", small, (200, 200, 200)),
                               (640, "Back or Home to return", small, GREY)):
            d.text(((W - d.textlength(txt, font=f)) / 2, y), txt, fill=col, font=f)
        return to_rgbx(im)

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

def safe_eval(expr):
    """Evaluate + - * / ( ) on numbers only (no names, calls or attributes)."""
    def ev(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS: return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand); return -v if isinstance(n.op, ast.USub) else v
        raise ValueError("bad expression")
    return ev(ast.parse(expr, mode="eval").body)

def fmt_num(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15: v = int(v)
    if isinstance(v, int) and abs(v) < 10 ** 15: return str(v)
    return f"{v:.10g}"

class CalculatorApp(App):
    name = "Calculator"
    KEYS = [["C", "(", ")", "\u00f7"], ["7", "8", "9", "\u00d7"], ["4", "5", "6", "\u2212"],
            ["1", "2", "3", "+"], ["0", ".", "DEL", "="]]
    SYM = {"\u00f7": "/", "\u00d7": "*", "\u2212": "-"}
    KX, KY, KW, KH, GAP = 14, 222, 113, 96, 4        # keypad geometry inside the app area

    def __init__(self):
        self.expr, self.pressed, self.just_eq = "", None, False

    def key_at(self, x, y):
        y -= TOP
        c, r = int((x - self.KX) // (self.KW + self.GAP)), int((y - self.KY) // (self.KH + self.GAP))
        if 0 <= r < len(self.KEYS) and 0 <= c < 4:
            return self.KEYS[r][c]
        return None

    def press(self, k):
        e = self.expr
        if k == "C": e = ""
        elif k == "DEL": e = e[:-1]
        elif k == "=":
            try: e = fmt_num(safe_eval(e)) if e else ""
            except ZeroDivisionError: e = "Error"
            except Exception: e = "Error"
            self.expr, self.just_eq = e, True; return
        else:
            ch = self.SYM.get(k, k)
            if e == "Error" or (self.just_eq and (ch.isdigit() or ch in ".(")): e = ""
            if ch in "+-*/" and e and e[-1] in "+-*/": e = e[:-1]   # replace trailing operator
            if len(e) < 40: e += ch
        self.expr, self.just_eq = e, False

    def touch(self, ev, x, y):
        k = self.key_at(x, y)
        if ev == "down": self.pressed = k
        elif ev == "move" and k != self.pressed: self.pressed = None
        elif ev == "up":
            if k is not None and k == self.pressed: self.press(k)
            self.pressed = None

    def key(self, now): return (self.expr, self.pressed)

    DISP_H = 210                                   # display strip height (top of app area)

    def _draw_key(self, d, k, x0, y0, pressed):
        op = k in ("\u00f7", "\u00d7", "\u2212", "+", "(", ")")
        fill = (0, 90, 50) if k == "=" else (0, 0, 0)
        if pressed: fill = (0, 160, 90) if k == "=" else (40, 110, 70)
        d.rounded_rectangle([x0, y0, x0 + self.KW, y0 + self.KH], 10, fill=fill,
                            outline=ACCENT if k == "=" else DIM, width=2)
        tc = PALETTE[6] if op else (255, 110, 110) if k in ("C", "DEL") else ACCENT if k == "=" else (230, 230, 230)
        f = ImageFont.truetype(FONT, 30 if k != "DEL" else 22)
        d.text((x0 + (self.KW - d.textlength(k, font=f)) / 2, y0 + (self.KH - 34) / 2), k, fill=tc, font=f)

    def _keypad(self, pressed_key):
        """Full app image with the keypad drawn (display area left blank)."""
        im = Image.new("RGB", (W, APP_H), (0, 0, 0)); d = ImageDraw.Draw(im)
        for r, row in enumerate(self.KEYS):
            for c, k in enumerate(row):
                self._draw_key(d, k, self.KX + c * (self.KW + self.GAP), self.KY + r * (self.KH + self.GAP),
                               k == pressed_key)
        return to_rgbx(im)

    def _pressed_tile(self, k):
        im = Image.new("RGB", (self.KW + 1, self.KH + 1), (0, 0, 0))
        self._draw_key(ImageDraw.Draw(im), k, 0, 0, True)
        return to_rgbx(im)

    def _key_rect(self, k):
        for r, row in enumerate(self.KEYS):
            if k in row:
                c = row.index(k)
                x0 = self.KX + c * (self.KW + self.GAP); y0 = self.KY + r * (self.KH + self.GAP)
                return y0, y0 + self.KH + 1, x0, x0 + self.KW + 1

    def render(self, now):
        if not hasattr(self, "_base"):                      # pre-render once
            self._base = self._keypad(None)
            self._pressed_imgs = {k: self._pressed_tile(k) for row in self.KEYS for k in row}
        img = self._base.copy()
        if self.pressed:
            y0, y1, x0, x1 = self._key_rect(self.pressed)
            img[y0:y1, x0:x1] = self._pressed_imgs[self.pressed]
        # display strip
        im = Image.new("RGB", (W, self.DISP_H), (0, 0, 0)); d = ImageDraw.Draw(im)
        shown = self.expr.replace("/", "\u00f7").replace("*", "\u00d7").replace("-", "\u2212")
        preview = ""
        if self.expr and not self.just_eq and self.expr != "Error":
            try: preview = fmt_num(safe_eval(self.expr))
            except Exception: preview = ""
        f_expr = ImageFont.truetype(FONT_REG, 24)
        main = (self.expr if self.just_eq else preview) or ("0" if not self.expr else "")
        big = ImageFont.truetype(FONT, 56 if len(main) < 12 else 34)
        d.rectangle([14, 16, W - 14, 196], outline=DIM)
        d.text((W - 30 - d.textlength(shown[-26:], font=f_expr), 40), shown[-26:], fill=(200, 200, 200), font=f_expr)
        col = (255, 90, 90) if self.expr == "Error" else PALETTE[6]
        d.text((W - 30 - d.textlength(main[-14:], font=big), 110), main[-14:], fill=col, font=big)
        img[:self.DISP_H] = to_rgbx(im)
        return img

class Entry:
    """A launcher entry: the spinning object that represents an app."""
    def __init__(self, app, shape, colour, phase=(0.0, 0.0, 0.0), label=True):
        self.app, self.shape, self.colour = app, shape, colour
        self.a, self.b, self.c = phase
        self.label = None
        if label:
            lab = np.ascontiguousarray(text_strip(app.name, 22, colour, 26)[..., :3])
            lab = np.concatenate([lab, np.zeros(lab.shape[:2] + (1,), np.uint8)], 2)   # X byte = 0
            cols = np.nonzero(lab.any((0, 2)))[0]
            self.label_x, self.label = int(cols[0]), lab[:, cols[0]:cols[-1] + 1].copy()

ENTRIES = [
    Entry(CubeApp(), CUBE, PALETTE[1], label=False),          # home object: no label
    Entry(CalculatorApp(), make_plus(), PALETTE[6], phase=(0.6, 1.1, 0.3)),
]

def dots(n, cur):
    im = Image.new("RGB", (W, 12), (0, 0, 0)); d = ImageDraw.Draw(im)
    gap = 18; x0 = W / 2 - gap * (n - 1) / 2
    for i in range(n):
        cx = x0 + i * gap
        if i == cur: d.ellipse([cx - 4, 2, cx + 4, 10], fill=ACCENT)
        else: d.ellipse([cx - 3, 3, cx + 3, 9], outline=GREY)
    return to_rgbx(im)
DOTS = [dots(len(ENTRIES), i) for i in range(len(ENTRIES))]

# ---- screen sleep / wake (earlysuspend; the wake lock keeps the phone itself running) ---
def _sysw(path, val):
    try:
        with open(path, "w") as f: f.write(val)
    except OSError:
        pass

def screen_off():
    _sysw("/sys/power/wake_lock", "alpine-keepawake")   # never really suspend: stay a server
    _sysw("/sys/power/state", "mem")                    # early suspend: panel, backlight, touch off

def screen_on(page):
    for attempt in range(2):                            # retry once if the display didn't come back
        _sysw("/sys/power/state", "on")                 # late resume
        t = threading.Thread(target=lambda: open("/sys/power/wait_for_fb_wake").read(), daemon=True)
        t.start(); t.join(2.0)                          # wait (max 2 s) until the display is back
        if not t.is_alive():
            break
    pan(page)                                           # make the controller scan out our page
    _sysw("/sys/class/backlight/panel/brightness", "160")

# ---- power menu ----------------------------------------------------------------
POWER_BTNS = [("Shut down", (255, 90, 90)), ("Restart", (255, 200, 60)), ("Cancel", (170, 170, 170))]
PB_X, PB_W, PB_H, PB_Y0, PB_GAP = 60, 360, 84, 220, 24      # inside the app area (y from TOP)

def power_btn_at(x, y):
    y -= TOP
    for i in range(len(POWER_BTNS)):
        y0 = PB_Y0 + i * (PB_H + PB_GAP)
        if PB_X <= x <= PB_X + PB_W and y0 <= y <= y0 + PB_H:
            return i
    return None

def power_menu(pressed):
    im = Image.new("RGB", (W, APP_H), (0, 0, 0)); d = ImageDraw.Draw(im)
    big = ImageFont.truetype(FONT, 30); f = ImageFont.truetype(FONT, 28)
    t = "Power"; d.text(((W - d.textlength(t, font=big)) / 2, 130), t, fill=ACCENT, font=big)
    for i, (name, col) in enumerate(POWER_BTNS):
        y0 = PB_Y0 + i * (PB_H + PB_GAP)
        d.rounded_rectangle([PB_X, y0, PB_X + PB_W, y0 + PB_H], 14,
                            fill=(45, 45, 45) if i == pressed else (0, 0, 0), outline=col, width=3)
        d.text(((W - d.textlength(name, font=f)) / 2, y0 + (PB_H - 32) / 2), name, fill=col, font=f)
    return to_rgbx(im)

def message_screen(text):
    im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 30)
    d.text(((W - d.textlength(text, font=f)) / 2, H / 2 - 20), text, fill=ACCENT, font=f)
    return to_rgbx(im)

# ---- boot handover -------------------------------------------------------------
def greeting():
    return f"Welcome, {GREET_NAME}"

def stop_bootanim():
    try:
        pid = int(open(BOOTANIM_PID).read())
        os.kill(pid, 15)
    except (OSError, ValueError):
        return
    for _ in range(100):
        try:
            os.kill(pid, 0); time.sleep(0.005)
        except OSError:
            break

def play_startup_sound():
    if not os.path.exists(SOUND) or os.path.exists(SOUND_PLAYED):
        return
    try:
        subprocess.Popen(["aplay", "-q", "-D", "hw:0,0", SOUND],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(SOUND_PLAYED, "w").close()
    except OSError:
        pass

def ease_out(x):
    return 1 - (1 - x) ** 3

# ---- main loop -----------------------------------------------------------------
def main():
    bf = boot_frame()
    for pg in range(NPAGES):                      # title + 'booting...'; leave the band alone
        fbmem[pg][:TOP] = bf[:TOP]
        fbmem[pg][TOP + BAND:] = bf[TOP + BAND:]
    stop_bootanim()
    play_startup_sound()
    stats, inp = Stats(), Input()
    start = time.monotonic()
    ENTRIES[0].b = (BOOT_W * start) % (2 * math.pi)        # continue the loading spin exactly
    title = TitleAnim(TITLE, greeting())
    FULL = [(0, BAND, 0, W)]
    dirty = [FULL] * NPAGES                       # per page: rects drawn there last time
    stat_img = [None] * STAT_ROWS                 # rendered stats rows (off-screen) ...
    stat_ver = [0] * STAT_ROWS                    # ... their versions, and what each page has:
    page_stat_ver = [[-1] * STAT_ROWS for _ in range(NPAGES)]

    mode, cur, off = "launcher", 0, 0.0          # off: carousel offset in px (+ = dragged right)
    anim = None                                   # (from, to, t0, dur) snap animation
    touch = None                                  # dict for the current touch
    open_app = None
    shown = {k: [None] * NPAGES for k in ("title", "app", "dots")}
    last = start
    page, frames, t0, fps, next_stats = 1, 0, start, 0.0, 0.0
    sdata, srow = None, STAT_ROWS
    asleep, last_input = False, start
    power_down_t, power_handled, pmenu_pressed, prev_mode = None, False, None, "launcher"

    def redraw_all():
        nonlocal dirty, page_stat_ver, next_stats
        for k in shown: shown[k] = [None] * NPAGES
        dirty = [FULL] * NPAGES
        page_stat_ver = [[-1] * STAT_ROWS for _ in range(NPAGES)]
        next_stats = 0.0

    while True:
        if asleep:                                   # screen off: no drawing, just wait for a key
            select.select(inp.fds, [], [], 5.0)
            for ev, x, y, t in inp.poll():
                if ev == "key" and y == 1 and x in (KEY_POWER, KEY_HOME):
                    screen_on((page - 1) % NPAGES)
                    asleep, last_input, last = False, time.monotonic(), time.monotonic()
                    power_down_t, power_handled = None, True     # ignore this press's release
                    redraw_all()
                    break
            continue

        now = time.monotonic()
        dt, last = now - last, now
        n = len(ENTRIES)

        # -- input --
        for ev, x, y, t in inp.poll():
            last_input = now
            if ev == "key" and x == KEY_POWER:
                if y == 1:
                    power_down_t, power_handled = now, False
                elif power_down_t is not None:
                    if not power_handled and mode != "power":
                        asleep = True                         # short press: screen off
                    power_down_t = None
                continue
            if mode == "power":
                if ev == "key" and y == 1 and x in (KEY_BACK, KEY_HOME):
                    mode = prev_mode; redraw_all()
                elif ev in ("down", "move"):
                    pmenu_pressed = power_btn_at(x, y) if ev == "down" or pmenu_pressed is not None else None
                    if ev == "move" and power_btn_at(x, y) != pmenu_pressed: pmenu_pressed = None
                elif ev == "up":
                    b = power_btn_at(x, y)
                    if b is not None and b == pmenu_pressed:
                        if b == 2:
                            mode = prev_mode; redraw_all()
                        else:
                            msg = message_screen("Shutting down..." if b == 0 else "Restarting...")
                            for pg in range(NPAGES): fbmem[pg][:] = msg
                            pan(page)
                            subprocess.Popen(["poweroff" if b == 0 else "reboot"])
                            mode = "halt"
                    pmenu_pressed = None
                continue
            if mode == "halt":
                continue
            if mode == "app":
                if (ev == "key" and y == 1 and x in (KEY_BACK, KEY_HOME)) or (ev == "up" and y < TOP):
                    mode, open_app = "launcher", None
                    shown["title"] = [None] * NPAGES; shown["dots"] = [None] * NPAGES; next_stats = 0.0
                    dirty = [FULL] * NPAGES
                    page_stat_ver = [[-1] * STAT_ROWS for _ in range(NPAGES)]
                elif ev in ("down", "move", "up"):
                    open_app.touch(ev, x, y)
                continue
            if ev == "down":
                touch = {"x0": x, "y0": y, "t0": t, "off0": off, "drag": False, "hist": [(t, x)]}
                anim = None
            elif ev == "move" and touch:
                touch["hist"] = [(tt, xx) for tt, xx in touch["hist"] if t - tt < 0.1] + [(t, x)]
                if not touch["drag"] and abs(x - touch["x0"]) > 12:
                    touch["drag"] = True
                if touch["drag"]:
                    off = touch["off0"] + (x - touch["x0"])
            elif ev == "up" and touch:
                if not touch["drag"]:
                    if t - touch["t0"] < 0.5 and TOP <= touch["y0"] < TOP + BAND and abs(off) < 1:
                        mode, open_app = "app", ENTRIES[cur].app       # tap: open the app
                        shown["app"] = [None] * NPAGES; shown["title"] = [None] * NPAGES
                    else:
                        anim = (off, 0.0, now, 0.25)
                else:
                    h = touch["hist"]
                    v = (h[-1][1] - h[0][1]) / max(h[-1][0] - h[0][0], 1e-3) if len(h) > 1 else 0
                    target = W if (off > W * 0.25 or v > 700) else -W if (off < -W * 0.25 or v < -700) else 0.0
                    anim = (off, float(target), now, 0.28)
                touch = None
            elif ev == "key" and y == 1 and x == KEY_HOME:
                anim = (off, 0.0, now, 0.25)

        # -- power key held -> power menu; inactivity -> sleep --
        if power_down_t is not None and not power_handled and now - power_down_t >= LONG_PRESS:
            power_handled = True
            if mode in ("launcher", "app"):
                prev_mode, mode, pmenu_pressed, touch, anim = mode, "power", None, None, None
                if prev_mode == "launcher": off = 0.0
        if mode in ("launcher", "app") and now - last_input > SLEEP_AFTER:
            asleep = True
        if asleep:
            screen_off()
            continue
        if mode == "halt":
            time.sleep(0.5); continue

        # -- carousel snap animation --
        if anim:
            a0, a1, ta, dur = anim
            k = min(1.0, (now - ta) / dur)
            off = a0 + (a1 - a0) * ease_out(k)
            if k >= 1.0:
                if a1 >= W: cur = (cur - 1) % n
                elif a1 <= -W: cur = (cur + 1) % n
                off, anim = 0.0, None

        # -- spin every object (first one continues the boot spin, blending in) --
        x_ = min(1.0, (now - start) / BLEND); e = x_ * x_ * (3 - 2 * x_)
        for i, en in enumerate(ENTRIES):
            if i == 0:
                en.a += dt * e * FULL_RATES[0]
                en.b += dt * ((1 - e) * BOOT_W + e * FULL_RATES[1])
                en.c += dt * e * FULL_RATES[2]
            else:
                en.a += dt * FULL_RATES[0]; en.b += dt * FULL_RATES[1]; en.c += dt * FULL_RATES[2]

        buf = fbmem[page]
        if mode == "launcher":
            fband = buf[TOP:TOP + BAND]               # draw straight into this (off-screen) page
            for y0, y1, x0, x1 in dirty[page]:        # erase only what we drew here last time
                fband[y0:y1, x0:x1] = 0
            rects = []
            visible = [(cur, off)]
            if off > 0: visible.append(((cur - 1) % n, off - W))
            if off < 0: visible.append(((cur + 1) % n, off + W))
            for idx, dx in visible:
                en = ENTRIES[idx]
                tilt = BOOT_TILT * (1 - e) if idx == 0 else 0.0
                kk = K_BOOT + (K_APP - K_BOOT) * e if idx == 0 else K_APP
                rects.append(render_into(fband, en.shape, mat_py(tilt, en.a, en.b, en.c), kk, dx))
                if en.label is not None:
                    lx = int(round(dx + en.label_x))
                    blit(fband, en.label, LABEL_Y, lx)
                    rects.append((LABEL_Y, LABEL_Y + en.label.shape[0], max(0, lx), min(W, lx + en.label.shape[1])))
            dirty[page] = [r for r in rects if r[1] > r[0] and r[3] > r[2]]
            if shown["dots"][page] != cur:
                fband[DOTS_Y:DOTS_Y + 12] = DOTS[cur]; shown["dots"][page] = cur

            st = title.state(now - start)
            if st != shown["title"][page]:
                buf[TITLE_Y:TITLE_Y + 36] = title.render(*st)
                shown["title"][page] = st
            if now >= next_stats:                 # sample once a second ...
                sdata, srow, next_stats = stats.sample(), 0, now + 1.0
            if srow < STAT_ROWS and not touch and not anim:   # render one row per frame, off-screen
                stat_img[srow] = stats_row(srow, sdata, fps); stat_ver[srow] += 1
                srow += 1
            for r in range(STAT_ROWS):            # copy rows this page is missing (never the visible page)
                if stat_img[r] is not None and page_stat_ver[page][r] != stat_ver[r]:
                    yo, img = stat_img[r]
                    buf[STATS_Y + yo:STATS_Y + yo + img.shape[0]] = img
                    page_stat_ver[page][r] = stat_ver[r]
        elif mode == "power":
            if shown["app"][page] != ("power", pmenu_pressed):
                buf[TOP:H] = power_menu(pmenu_pressed)
                shown["app"][page] = ("power", pmenu_pressed)
            if shown["title"][page] != ("power",):
                buf[TITLE_Y:TITLE_Y + 36] = text_strip("TREND OS", 28, ACCENT, 36)
                shown["title"][page] = ("power",)
        else:
            k = open_app.key(now)
            if k != shown["app"][page]:
                buf[TOP:H] = open_app.render(now)
                shown["app"][page] = k
            st = ("app", open_app.name)
            if st != shown["title"][page]:
                buf[TITLE_Y:TITLE_Y + 36] = text_strip("‹ " + open_app.name, 28, ACCENT, 36, x=16)
                shown["title"][page] = st

        pan(page)
        page = (page + 1) % NPAGES
        frames += 1
        if frames % 15 == 0:
            tn = time.monotonic(); fps = 15 / (tn - t0); t0 = tn
        spare = 1.0 / MAX_FPS - (time.monotonic() - now)
        if spare > 0:
            time.sleep(spare)

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--boot-anim":
        grids = np.stack([cells_R(boot_R(k / BOOT_FPS), CUBE) for k in range(BOOT_N)]).astype(np.uint8)
        hdr = struct.pack("<4s8I", b"BANM", BOOT_N, ROWS, COLS, CH, CW, TOP, BOOT_FPS, len(tiles))
        open(sys.argv[2], "wb").write(hdr + tiles.tobytes() + grids.tobytes())
    elif len(sys.argv) == 3 and sys.argv[1] == "--boot-frame":
        open(sys.argv[2], "wb").write(boot_frame().tobytes())
    else:
        main()

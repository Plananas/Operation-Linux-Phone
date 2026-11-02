#!/usr/bin/env python3
"""Startup screen: spinning ASCII-shaded 3D cube + live system stats.
Phone framebuffer: 480x800 sprdfb, RGBX byte order, 2 pages used for double buffering.

Fast path: every (face colour, shade character) combination is pre-rendered once as a
ready-to-blit RGBX tile. Each frame only computes a grid of tile indices with numpy
(rotate, cull, project, z-buffer, light) and gathers tiles straight into the mmap'd
framebuffer, then page-flips with FBIOPAN_DISPLAY. Stats panel redraws once a second.
"""
import fcntl, math, mmap, os, random, subprocess, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 480, 800
FB = "/dev/fb0"
FONT = "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REG = "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"
SHADES = " .,-~:;=!*#$@"          # index 0 = empty cell
NS = len(SHADES)
FACE_COLOURS = [(255, 70, 70), (70, 255, 110), (80, 140, 255),
                (255, 215, 50), (255, 80, 255), (50, 230, 230)]
TITLE = "TREND OS"
MAX_FPS = 30
# Boot animation ("loading" spin, played by /bin/bootanim from the ramdisk until this program
# takes over): spin about the vertical axis, view tilted so the top face shows. Frame k is
# shown at CLOCK_MONOTONIC time t with k = floor(t * BOOT_FPS) % BOOT_N, so the spin angle is
# always 2*pi * t / BOOT_PERIOD and this program can continue from exactly the same pose.
BOOT_TILT = 0.45                   # rad, view tilt during the loading spin
BOOT_PERIOD = 4.0                  # s per revolution
BOOT_FPS = 30
BOOT_N = int(BOOT_PERIOD * BOOT_FPS)
BOOT_W = 2 * math.pi / BOOT_PERIOD
BLEND = 2.5                        # s to ease from the loading spin into the full tumble
FULL_RATES = (0.9, 0.62, 0.35)     # rad/s about x, y, z in the full tumble
BOOTANIM_PID = "/dev/.bootanim.pid"
SOUND = "/usr/local/share/trendos/startup.wav"   # made by mksound.py; chime lands at 2.6 s
SOUND_PLAYED = "/run/trendos-sound-played"       # once per boot (not on respawn)

# ---- layout ------------------------------------------------------------------
FONT_PX, CW, CH = 12, 8, 12        # 60 x 44 cells, rows exactly screen-wide (contiguous)
COLS, ROWS = W // CW, 44
TITLE_Y = 22
TOP = 66                           # cube area: 66 .. 594
STATS_Y, STATS_H = 600, 196        # stats panel: 600 .. 796

# ---- tile atlas: tile[face * NS + shade] = CH x CW x 4 RGBX ------------------
font = ImageFont.truetype(FONT, FONT_PX)
tiles = np.zeros((len(FACE_COLOURS) * NS, CH, CW, 4), np.uint8)
for s, c in enumerate(SHADES):
    g = Image.new("L", (CW, CH), 0)
    ImageDraw.Draw(g).text((1, -1), c, fill=255, font=font)
    mask = np.asarray(g, np.float32)[..., None] / 255.0
    bright = 0.35 + 0.65 * (s / (NS - 1))
    for f, rgb in enumerate(FACE_COLOURS):
        tiles[f * NS + s, :, :, :3] = (mask * np.array(rgb, np.float32) * bright).astype(np.uint8)

# ---- cube geometry -----------------------------------------------------------
N = 40
u = (np.arange(N) + 0.5) / N * 2 - 1
A_, B_ = np.meshgrid(u, u)
pts, nrm, fid = [], [], []
for axis in range(3):
    for sign in (-1, 1):
        p = np.zeros((N * N, 3), np.float32)
        p[:, axis] = sign
        p[:, (axis + 1) % 3] = A_.ravel()
        p[:, (axis + 2) % 3] = B_.ravel()
        n = np.zeros(3, np.float32); n[axis] = sign
        pts.append(p); nrm.append(n); fid.append(np.full(N * N, len(fid), np.int32))
PTS, FID = np.concatenate(pts), np.concatenate(fid)
FNRM = np.array(nrm, np.float32)
LIGHT = np.array([-2.5, 3.0, -5.0], np.float32)

# ---- framebuffer -------------------------------------------------------------
fd = os.open(FB, os.O_RDWR)
var = bytearray(fcntl.ioctl(fd, 0x4600, bytes(160)))   # FBIOGET_VSCREENINFO
mm = mmap.mmap(fd, W * H * 4 * 2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
fbmem = np.frombuffer(mm, np.uint8).reshape(2, H, W, 4)

def pan(page):
    var[20:24] = (page * H).to_bytes(4, "little")
    fcntl.ioctl(fd, 0x4606, bytes(var))                 # FBIOPAN_DISPLAY

def to_rgbx(im):
    a = np.zeros((im.height, im.width, 4), np.uint8); a[..., :3] = np.asarray(im); return a

def rot_x(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)

def boot_R(t):
    """Pose of the loading spin at monotonic time t."""
    return rot_x(BOOT_TILT) @ rotation(0.0, BOOT_W * t, 0.0)

def rotation(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], np.float32)
    ry = np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]], np.float32)
    rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]], np.float32)
    return rz @ ry @ rx

K = COLS * 1.03
ASPECT = CW / CH

def cells(a, b, c):
    return cells_R(rotation(a, b, c))

def cells_R(R):
    """ROWS x COLS grid of tile indices for rotation matrix R."""
    fn = FNRM @ R.T
    visf = np.nonzero(fn[:, 2] < 0)[0]
    sel = np.isin(FID, visf)
    p = PTS[sel] @ R.T; f = FID[sel]; n = fn[f]
    ooz = 1.0 / (p[:, 2] + 4.5)
    xp = np.clip((COLS / 2 + K * ooz * p[:, 0]).astype(np.int32), 0, COLS - 1)
    yp = np.clip((ROWS / 2 - K * ooz * p[:, 1] * ASPECT).astype(np.int32), 0, ROWS - 1)
    ld = LIGHT - p; ld /= np.linalg.norm(ld, axis=1, keepdims=True)
    lum = np.clip((n * ld).sum(1), 0, 1) ** 1.3
    shade = 1 + np.minimum((lum * (NS - 1)).astype(np.int32), NS - 2)
    order = np.argsort(ooz)
    grid = np.zeros((ROWS, COLS), np.int32)
    grid[yp[order], xp[order]] = (f * NS + shade)[order]
    return grid

# ---- stats -------------------------------------------------------------------
def rd(path, default=""):
    try:
        with open(path) as f: return f.read().strip()
    except OSError: return default

class Stats:
    def __init__(self):
        self.prev_cpu = self._cpu(); self.prev_net = self._net(); self.prev_t = time.time()
        self.cpu = 0.0; self.rx = self.tx = 0.0

    @staticmethod
    def _cpu():
        v = list(map(int, rd("/proc/stat").splitlines()[0].split()[1:]))
        idle = v[3] + v[4]; return sum(v), idle

    @staticmethod
    def _net():
        b = "/sys/class/net/rndis0/statistics/"
        return int(rd(b + "rx_bytes", "0")), int(rd(b + "tx_bytes", "0"))

    def sample(self):
        now = time.time(); dt = max(now - self.prev_t, 1e-3)
        tot, idle = self._cpu(); pt, pi = self.prev_cpu
        self.cpu = 100.0 * (1 - (idle - pi) / max(tot - pt, 1))
        rx, tx = self._net(); prx, ptx = self.prev_net
        self.rx, self.tx = (rx - prx) / dt, (tx - ptx) / dt
        self.prev_cpu, self.prev_net, self.prev_t = (tot, idle), (rx, tx), now
        mem = {l.split(":")[0]: int(l.split()[1]) for l in rd("/proc/meminfo").splitlines()}
        avail = mem.get("MemAvailable", mem["MemFree"] + mem.get("Buffers", 0) + mem.get("Cached", 0))
        st = os.statvfs("/")
        return {
            "cpu": self.cpu,
            "freq": int(rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "0")) / 1e6,
            "cores": rd("/sys/devices/system/cpu/online", "?"),
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
GREY, DIM, ACCENT = (130, 130, 130), (60, 60, 60), (0, 255, 140)

def bar_colour(frac, invert=False):
    frac = 1 - frac if invert else frac
    return (70, 220, 110) if frac < 0.6 else (255, 200, 50) if frac < 0.85 else (255, 70, 70)

def stats_panel(s, fps):
    im = Image.new("RGB", (W, STATS_H), (0, 0, 0)); d = ImageDraw.Draw(im)
    d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    LX, BX, BW, VX = 18, 70, 150, 232
    def row(y, label, frac, colour, text):
        d.text((LX, y), label, fill=ACCENT, font=f_lbl)
        if frac is not None:
            d.rectangle([BX, y + 3, BX + BW, y + 15], outline=DIM)
            d.rectangle([BX + 1, y + 4, BX + 1 + int((BW - 2) * max(0, min(1, frac))), y + 14], fill=colour)
            d.text((VX, y), text, fill=(220, 220, 220), font=f_val)
        else:
            d.text((BX, y), text, fill=(220, 220, 220), font=f_val)
    y = 12
    row(y, "CPU", s["cpu"] / 100, bar_colour(s["cpu"] / 100),
        f"{s['cpu']:3.0f}%  {s['freq']:.2f}GHz  {s['ctemp']}°C"); y += 26
    mf = s["mem_used"] / s["mem_total"]
    row(y, "RAM", mf, bar_colour(mf), f"{s['mem_used']:3.0f} / {s['mem_total']:.0f} MB"); y += 26
    bf = s["bat"] / 100
    chg = "+" if s["bat_status"] == "Charging" else ""
    row(y, "BAT", bf, bar_colour(bf, invert=True),
        f"{s['bat']:3d}%{chg} {s['bvolt']:.2f}V {s['btemp']:.1f}°C"); y += 26
    df = s["disk_used"] / s["disk_total"]
    row(y, "DISK", df, bar_colour(df), f"{s['disk_used']:.2f} / {s['disk_total']:.1f} GB"); y += 26
    net = "192.168.42.129" if s["link"] == "up" else "usb link down"
    row(y, "NET", None, None, f"{net}  ↓{human_rate(s['rx'])} ↑{human_rate(s['tx'])}"); y += 26
    up = int(s["uptime"])
    row(y, "UP", None, None,
        f"{up // 86400}d {up // 3600 % 24:02d}:{up // 60 % 60:02d}:{up % 60:02d}  load {s['load']}  {fps:4.1f}fps")
    return to_rgbx(im)

# ---- boot frame (also used as the early logo by the ramdisk init) -----------
def boot_frame():
    """Full-screen RGBX image: title + cube at T0 + 'booting...' where the stats go."""
    img = np.zeros((H, W, 4), np.uint8)
    ti = Image.new("RGB", (W, 36), (0, 0, 0)); d = ImageDraw.Draw(ti)
    tf = ImageFont.truetype(FONT, 28)
    d.text(((W - d.textlength(TITLE, font=tf)) / 2, 0), TITLE, fill=ACCENT, font=tf)
    img[TITLE_Y:TITLE_Y + 36] = to_rgbx(ti)
    g = cells_R(boot_R(0.0))
    img[TOP:TOP + ROWS * CH] = tiles[g].transpose(0, 2, 1, 3, 4).reshape(ROWS * CH, W, 4)
    bi = Image.new("RGB", (W, STATS_H), (0, 0, 0)); d = ImageDraw.Draw(bi)
    d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    msg = "booting..."; d.text(((W - d.textlength(msg, font=f_lbl)) / 2, 80), msg, fill=GREY, font=f_lbl)
    img[STATS_Y:STATS_Y + STATS_H] = to_rgbx(bi)
    return img

# ---- main loop ---------------------------------------------------------------
# ---- title: "TREND OS" is backspaced away and a greeting typed in, terminal style --------
GREET_NAME = "Robin"

def greeting():
    return f"Welcome, {GREET_NAME}"

class TitleAnim:
    """Typewriter transition for the title line: backspace in place, then type the new text
    from the point where the finished text will be centred (letters never shift)."""
    BLINK = 0.53

    def __init__(self, text_from, text_to):
        self.font = ImageFont.truetype(FONT, 28)
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.x0 = (W - tmp.textlength(text_from, font=self.font)) / 2   # same as boot_frame()
        self.x1 = (W - tmp.textlength(text_to, font=self.font)) / 2     # finished text centred
        self.cw = tmp.textlength("M", font=self.font)
        t, ev = 0.9, []                                    # cursor blinks a little first
        for i in range(len(text_from), -1, -1):            # backspace
            ev.append((t, text_from[:i])); t += 0.055 + random.uniform(0, 0.035)
        self.t_erased = t
        t += 0.45
        self.t_type = t
        for i in range(1, len(text_to) + 1):               # type
            ch = text_to[i - 1]
            t += 0.055 + random.uniform(0, 0.075) + (0.12 if ch in " ,." else 0)
            ev.append((t, text_to[:i]))
        self.events, self.t_first, self.t_last = ev, ev[0][0], ev[-1][0]

    def state(self, t):
        text = self.events[0][1]
        for te, tx in self.events:
            if te > t: break
            text = tx
        if self.t_erased < t < self.t_type:               # pause: cursor hops to the new start
            frac = (t - self.t_erased) / (self.t_type - self.t_erased)
            x = self.x0 if frac < 0.5 else self.x1
            return "", frac < 0.3 or frac > 0.6, x
        x = self.x0 if t <= self.t_erased else self.x1
        if t > self.t_last + 0.5:                          # message typed: cursor gone
            return text, False, x
        typing = self.t_first <= t <= self.t_last + 0.5
        cursor = typing or int(t / self.BLINK) % 2 == 0
        return text, cursor, x

    def render(self, text, cursor, x0):
        im = Image.new("RGB", (W, 36), (0, 0, 0)); d = ImageDraw.Draw(im)
        d.text((x0, 0), text, fill=ACCENT, font=self.font)
        if cursor:
            x = x0 + d.textlength(text, font=self.font)
            d.rectangle([x + 1, 4, x + self.cw - 2, 33], fill=ACCENT)
        return to_rgbx(im)

def stop_bootanim():
    """Stop the ramdisk's loading animation (if running) so only we draw from now on."""
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

def main():
    bf = boot_frame()
    for pg in (0, 1):                             # title + 'booting...'; leave the cube area alone
        fbmem[pg][:TOP] = bf[:TOP]
        fbmem[pg][TOP + ROWS * CH:] = bf[TOP + ROWS * CH:]
    stop_bootanim()
    play_startup_sound()                          # swell matches the blend, chime at full tumble
    stats = Stats()
    start = time.monotonic()
    a, b, c = 0.0, (BOOT_W * start) % (2 * math.pi), 0.0   # continue the loading spin exactly
    last = start
    page, frames, t0, fps, next_stats = 1, 0, start, 0.0, 0.0
    dirty = [(0, ROWS), (0, ROWS)]
    title = TitleAnim(TITLE, greeting())
    title_shown = [None, None]                    # what each page's title line currently shows
    while True:
        tf0 = time.monotonic()
        dt, last = tf0 - last, tf0
        st = title.state(tf0 - start)
        if st != title_shown[page]:
            fbmem[page][TITLE_Y:TITLE_Y + 36] = title.render(*st)
            title_shown[page] = st
        x = min(1.0, (tf0 - start) / BLEND); e = x * x * (3 - 2 * x)   # smoothstep 0 -> 1
        a += dt * e * FULL_RATES[0]
        b += dt * ((1 - e) * BOOT_W + e * FULL_RATES[1])
        c += dt * e * FULL_RATES[2]
        grid = cells_R(rot_x(BOOT_TILT * (1 - e)) @ rotation(a, b, c))
        used = np.nonzero(grid.any(1))[0]
        r0, r1 = (used[0], used[-1] + 1) if len(used) else (0, 0)
        d0, d1 = min(r0, dirty[page][0]), max(r1, dirty[page][1])
        dirty[page] = (r0, r1)
        if d1 > d0:
            img = tiles[grid[d0:d1]].transpose(0, 2, 1, 3, 4).reshape((d1 - d0) * CH, W, 4)
            fbmem[page][TOP + d0 * CH:TOP + d1 * CH] = img
        if tf0 >= next_stats:
            panel = stats_panel(stats.sample(), fps)
            fbmem[0][STATS_Y:STATS_Y + STATS_H] = panel
            fbmem[1][STATS_Y:STATS_Y + STATS_H] = panel
            next_stats = tf0 + 1.0
        pan(page)
        page ^= 1
        frames += 1
        if frames % 15 == 0:
            now = time.monotonic(); fps = 15 / (now - t0); t0 = now
        spare = 1.0 / MAX_FPS - (time.monotonic() - tf0)
        if spare > 0:
            time.sleep(spare)

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--boot-anim":
        import struct
        grids = np.stack([cells_R(boot_R(k / BOOT_FPS)) for k in range(BOOT_N)]).astype(np.uint8)
        hdr = struct.pack("<4s8I", b"BANM", BOOT_N, ROWS, COLS, CH, CW, TOP, BOOT_FPS, len(tiles))
        open(sys.argv[2], "wb").write(hdr + tiles.tobytes() + grids.tobytes())
    elif len(sys.argv) == 3 and sys.argv[1] == "--boot-frame":
        open(sys.argv[2], "wb").write(boot_frame().tobytes())   # raw 480x800 RGBX for the ramdisk
    else:
        main()

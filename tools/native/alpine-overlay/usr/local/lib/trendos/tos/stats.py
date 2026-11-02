"""System stats sampling and the stats panel at the bottom of the launcher.

Rendering a row with PIL costs ~6 ms, so rows are rendered one per frame (off-screen) and each
framebuffer page copies the rows it is missing when that page is drawn - never touching the page
that is on screen.
"""
import os, time

from .config import W, NPAGES, STATS_Y, ACCENT, DIM, TEXT
from .gfx import canvas, font, to_rgbx

ROWS = 6


def rd(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


class Stats:
    """Samples CPU, memory, battery, disk, network once per call."""

    def __init__(self):
        self.prev_cpu, self.prev_net, self.prev_t = self._cpu(), self._net(), time.time()

    @staticmethod
    def _cpu():
        """Per-core (total, idle) ticks. Per core, because the kernel hot-plugs core 1 (e.g. on
        touch boost) and the aggregate "cpu" line then jumps -> nonsense percentages."""
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
        for core, (tot, idle) in cur.items():                 # cores online at both samples only
            if core in self.prev_cpu:
                t_, i_ = tot - self.prev_cpu[core][0], idle - self.prev_cpu[core][1]
                if t_ > 0 and 0 <= i_ <= t_:
                    dtot += t_; dbusy += t_ - i_
        rx, tx = self._net(); prx, ptx = self.prev_net
        self.prev_cpu, self.prev_net, self.prev_t = cur, (rx, tx), now
        mem = {l.split(":")[0]: int(l.split()[1]) for l in rd("/proc/meminfo").splitlines()}
        avail = mem.get("MemAvailable", mem["MemFree"] + mem.get("Buffers", 0) + mem.get("Cached", 0))
        st = os.statvfs("/")
        bat = "/sys/class/power_supply/battery/"
        return {
            "cpu": 100.0 * dbusy / dtot if dtot else 0.0, "cores": len(cur),
            "freq": int(rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "0")) / 1e6,
            "ctemp": rd("/sys/class/thermal/thermal_zone1/temp", "?"),
            "mem_used": (mem["MemTotal"] - avail) / 1024, "mem_total": mem["MemTotal"] / 1024,
            "bat": int(rd(bat + "capacity", "0")), "bat_status": rd(bat + "status", "?"),
            "btemp": int(rd(bat + "temp", "0")) / 10, "bvolt": int(rd(bat + "voltage_now", "0")) / 1e6,
            "disk_used": (st.f_blocks - st.f_bfree) * st.f_frsize / 2**30,
            "disk_total": st.f_blocks * st.f_frsize / 2**30,
            "link": rd("/sys/class/net/rndis0/operstate", "down"),
            "rx": (rx - prx) / dt, "tx": (tx - ptx) / dt,
            "load": rd("/proc/loadavg").split()[0],
            "uptime": float(rd("/proc/uptime", "0").split()[0]),
        }


def human_rate(b):
    for unit in ("B", "K", "M"):
        if b < 1024:
            return f"{b:5.0f}{unit}/s"
        b /= 1024
    return f"{b:5.1f}G/s"


def bar_colour(frac, invert=False):
    frac = 1 - frac if invert else frac
    return (70, 220, 110) if frac < 0.6 else (255, 200, 50) if frac < 0.85 else (255, 70, 70)


def row_spec(i, s, fps):
    """What stats row i shows: (label, bar fraction or None, bar colour, text). Cheap to compute;
    the panel only re-renders a row with PIL when its spec changed."""
    if i == 0:
        f = s["cpu"] / 100
        return "CPU", round(f, 2), bar_colour(f), f"{s['cpu']:3.0f}% {s['cores']}c {s['freq']:.2f}GHz {s['ctemp']}\u00b0C"
    if i == 1:
        f = s["mem_used"] / s["mem_total"]
        return "RAM", round(f, 2), bar_colour(f), f"{s['mem_used']:3.0f} / {s['mem_total']:.0f} MB"
    if i == 2:
        f = s["bat"] / 100; chg = "+" if s["bat_status"] == "Charging" else ""
        return "BAT", round(f, 2), bar_colour(f, invert=True), f"{s['bat']:3d}%{chg} {s['bvolt']:.2f}V {s['btemp']:.1f}\u00b0C"
    if i == 3:
        f = s["disk_used"] / s["disk_total"]
        return "DISK", round(f, 2), bar_colour(f), f"{s['disk_used']:.2f} / {s['disk_total']:.1f} GB"
    if i == 4:
        net = "192.168.42.129" if s["link"] == "up" else "usb link down"
        return "NET", None, None, f"{net}  \u2193{human_rate(s['rx'])} \u2191{human_rate(s['tx'])}"
    up = int(s["uptime"])
    return "UP", None, None, (f"{up // 86400}d {up // 3600 % 24:02d}:{up // 60 % 60:02d}:{up % 60:02d}"
                              f"  load {s['load']}  {fps:4.1f}fps")


def render_row(i, spec):
    """Stats row i -> (y offset in panel, RGBX image). Row 0 includes the divider line."""
    label, frac, colour, text = spec
    y0, h = (0, 38) if i == 0 else (12 + 26 * i, 26)
    im, d = canvas(h)
    if i == 0:
        d.line([(16, 2), (W - 16, 2)], fill=DIM, width=1)
    LX, BX, BW, VX = 18, 70, 150, 232
    y = 12 + 26 * i - y0
    d.text((LX, y), label, fill=ACCENT, font=font(15))
    if frac is None:
        d.text((BX, y), text, fill=TEXT, font=font(15, bold=False))
    else:
        d.rectangle([BX, y + 3, BX + BW, y + 15], outline=DIM)
        d.rectangle([BX + 1, y + 4, BX + 1 + int((BW - 2) * max(0, min(1, frac))), y + 14], fill=colour)
        d.text((VX, y), text, fill=TEXT, font=font(15, bold=False))
    return y0, to_rgbx(im)


class StatsPanel:
    """Samples once a second; re-renders (one per frame) only rows whose content changed;
    syncs rows into each page lazily."""

    def __init__(self):
        self.stats = Stats()
        self.data, self.next_sample, self.pending = None, 0.0, ROWS
        self.rows = [None] * ROWS          # (y offset, image) per row
        self.specs = [None] * ROWS         # what each rendered row shows
        self.ver = [0] * ROWS              # version of each rendered row ...
        self.invalidate()

    def invalidate(self):
        """Force every page to re-copy all rows (e.g. after an app screen covered the panel)."""
        self.page_ver = [[-1] * ROWS for _ in range(NPAGES)]   # ... and what each page holds
        self.next_sample = 0.0

    def update(self, now, fps, may_render=True):
        if now >= self.next_sample:
            self.data, self.pending, self.next_sample = self.stats.sample(), 0, now + 1.0
        while may_render and self.pending < ROWS:      # at most one PIL render per frame
            i = self.pending
            self.pending += 1
            spec = row_spec(i, self.data, fps)
            if spec != self.specs[i]:
                self.rows[i], self.specs[i] = render_row(i, spec), spec
                self.ver[i] += 1
                break

    def sync(self, buf, page):
        """Copy rows this page doesn't have yet (buf is that page, never the visible one)."""
        pv = self.page_ver[page]
        for i in range(ROWS):
            if self.rows[i] is not None and pv[i] != self.ver[i]:
                yo, img = self.rows[i]
                buf[STATS_Y + yo:STATS_Y + yo + img.shape[0]] = img
                pv[i] = self.ver[i]

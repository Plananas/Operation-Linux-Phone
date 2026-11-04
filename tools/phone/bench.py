"""Whole-frame costs of the installed tree, plus the running shell's real CPU. Works on old and new."""
import os, struct, sys, time
sys.path.insert(0, "/usr/local/lib/trendos")
t0 = time.perf_counter()
import numpy as np
from tos.apps.radio import RadioApp
from tos.apps.calculator import CalculatorApp
from tos.apps.clock import ClockApp
print(f"import apps: {(time.perf_counter()-t0)*1000:.0f} ms")

def per_frame(fn, n):
    c0 = time.process_time(); t = time.perf_counter()
    for i in range(n):
        fn(i)
    return (time.perf_counter() - t) * 1000 / n, (time.process_time() - c0) * 1000 / n

r = RadioApp()
r.state, r._cap = "on", object()
r.render(0.0)
rng = np.random.default_rng(3)
def radio(i):
    t = np.arange(4096) + i * 800
    r.samples = ((np.sin(t * 0.03) * 6000 + np.sin(t * 0.17) * 2500 + rng.normal(0, 600, 4096)) * 0.6).astype(np.int16)
    r.render(i / 20)
wall, cpu = per_frame(radio, 100)
print(f"radio live frame (incl. ~1 ms test audio): {wall:.2f} ms wall, {cpu:.2f} ms cpu")
r2 = RadioApp()
r2.state, r2._cap = "on", object()
r2.render(0.0)
def radio_tune(i):
    r2.samples = r.samples
    r2.disp_f = 90 + i * 0.13
    r2.render(i / 20)
print("radio while tuning: %.2f ms wall, %.2f ms cpu" % per_frame(radio_tune, 60))

c = CalculatorApp()
c.render(0.0)
print("calculator redraw: %.2f ms wall, %.2f ms cpu" % per_frame(lambda i: c.render(1.0 + i * 3), 10))
k = ClockApp()
print("clock redraw: %.2f ms wall, %.2f ms cpu" % per_frame(lambda i: k.render(time.time() + i), 20))

# ---- the running shell -------------------------------------------------------------------------
def key(code):
    with open("/dev/input/event0", "wb", buffering=0) as f:
        for v in (1, 0):
            f.write(struct.pack("llHHi", 0, 0, 1, code, v))
            f.write(struct.pack("llHHi", 0, 0, 0, 0, 0))

def shell_pid():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                cmd = open(f"/proc/{p}/cmdline").read().split("\0")
            except OSError:
                continue
            if len(cmd) > 1 and cmd[0].endswith("python3") and cmd[1].endswith("trendos.py"):
                return int(p)

pid = shell_pid()
def cpu_ticks():
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])

key(102)        # Home: wakes the screen, returns to the home carousel
time.sleep(2)
a = cpu_ticks(); time.sleep(20); b = cpu_ticks()
rss = [l for l in open(f"/proc/{pid}/status") if l.startswith("VmRSS")][0].split()[1]
print(f"shell on home screen: {(b-a)/20:.1f}% of one core, rss {rss} kB")

"""Drive the live UI with injected input and take screenshots."""
import struct, subprocess, sys, time

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SLOT, TRACK, X, Y = 0x2f, 0x39, 0x35, 0x36
tid = int(time.time()) % 100000 * 10


def ev(f, t, c, v):
    f.write(struct.pack("llHHi", 0, 0, t, c, v))


def key(code):
    with open("/dev/input/event0", "wb", buffering=0) as f:
        for v in (1, 0):
            ev(f, EV_KEY, code, v); ev(f, EV_SYN, 0, 0)
            time.sleep(0.05)


def stroke(points, dt=0.03):
    global tid
    tid += 1
    with open("/dev/input/event1", "wb", buffering=0) as f:
        ev(f, EV_ABS, SLOT, 0); ev(f, EV_ABS, TRACK, tid)
        # The kernel drops a repeated value. A shell that restarted since the last gesture would
        # never see the Y, and would take every touch to be at y = 0, so vary it per gesture.
        for x, y in points:
            ev(f, EV_ABS, X, x); ev(f, EV_ABS, Y, y + tid % 7); ev(f, EV_SYN, 0, 0)
            time.sleep(dt)
        ev(f, EV_ABS, TRACK, -1); ev(f, EV_SYN, 0, 0)


def swipe_left():
    stroke([(x, 300) for x in range(420, 60, -40)], 0.02)
    time.sleep(1.0)


def tap(x, y):
    stroke([(x, y), (x, y)], 0.06)


def shot(name):
    subprocess.check_call(["python3", "-I", "/tmp/shot.py", f"/tmp/shot-{name}.png"])
    print("shot", name, flush=True)


key(102); time.sleep(1.5)
shot("home")
# name:swipes[:swipes inside the sub-carousel]. Home always returns to the first carousel item.
for spec in sys.argv[1:]:
    name, *steps = spec.split(":")
    for depth, n in enumerate(steps):
        for _ in range(int(n)):
            swipe_left()
        if depth + 1 == len(steps):
            shot(f"{name}-carousel")
        tap(240, 300)
        time.sleep(1.0 if depth + 1 < len(steps) else 0.12)
    shot(f"{name}-transition")
    time.sleep(7 if name == "radio" else 1.5)
    shot(name)
    key(102)
    time.sleep(1.2)
    key(102)
    time.sleep(1.0)
print("done")

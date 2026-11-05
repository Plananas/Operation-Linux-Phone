"""What's using the CPU right now: per-thread use over a few seconds, per-core load, and processes that came and went
too fast for top. Changes nothing, so run it before restarting anything:
    ssh root@192.168.42.129 python3 -I - < tools/phone/cpuwho.py
"""
import os, time

SECONDS, HZ = 5.0, 100


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def threads():
    out = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            tids = os.listdir(f"/proc/{pid}/task")
        except OSError:
            continue
        for tid in tids:
            stat = read(f"/proc/{pid}/task/{tid}/stat")
            if stat:
                end = stat.rfind(")")
                fields = stat[end + 2:].split()
                out[int(tid)] = (int(pid), stat[stat.find("(") + 1:end], int(fields[11]), int(fields[12]))
    return out


def cores():
    return {l.split()[0]: list(map(int, l.split()[1:])) for l in read("/proc/stat").splitlines()
            if l.startswith("cpu") and l[3:4].isdigit()}


def last_pid():
    return int(read("/proc/loadavg").split()[4])


before, cores0, pid0, seen, t0 = threads(), cores(), last_pid(), {}, time.monotonic()
while time.monotonic() - t0 < SECONDS:           # catch the short-lived ones by name
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) not in before and int(pid) not in seen:
            seen[int(pid)] = read(f"/proc/{pid}/cmdline").replace("\0", " ").strip()[:70]
    time.sleep(0.01)
after, cores1, pid1, took = threads(), cores(), last_pid(), time.monotonic() - t0

print(f"new processes: {(pid1 - pid0) / took:.1f}/s    load: {read('/proc/loadavg').strip()}")
for name, v1 in cores1.items():
    if name in cores0:
        total = sum(v1) - sum(cores0[name])
        idle = v1[3] + v1[4] - cores0[name][3] - cores0[name][4]
        print(f"{name}: {100 * (total - idle) / max(1, total):3.0f}% busy")
    else:
        print(f"{name}: came online during the sample")
print("\n %cpu  usr  sys   pid   tid  name  (100 = one whole core)")
rows = []
for tid, (pid, name, u, s) in after.items():
    _, _, u0, s0 = before.get(tid, (0, "", 0, 0))
    if (u - u0) + (s - s0) > 0:
        rows.append(((u - u0) + (s - s0), u - u0, s - s0, pid, tid, name))
for ticks, u, s, pid, tid, name in sorted(rows, reverse=True)[:12]:
    cmd = read(f"/proc/{pid}/cmdline").replace("\0", " ").strip()[:44]
    print(f"{100 * ticks / HZ / took:5.1f} {u:4d} {s:4d} {pid:5d} {tid:5d}  {name}  {cmd}")
print("\nstarted during the sample:")
counts = {}
for cmd in seen.values():
    counts[cmd] = counts.get(cmd, 0) + 1
for cmd, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12]:
    print(f"{n:5d}  {cmd or '(gone before its name could be read)'}")

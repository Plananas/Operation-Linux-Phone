"""Live view of the SSH server, from the kernel and sshd's own log (no helper programs):

  /proc/net/tcp[6]      established connections and listening sockets
  /proc/PID             sshd processes: socket inodes, user@tty (cmdline), CPU, what runs under them
  /var/log/messages     Accepted / Failed / Disconnected lines, and which key logged in
  ~/.ssh/authorized_keys  names for those keys (the comment field)

This kernel has no per-socket byte counters and no /proc/PID/io, so "activity" is the CPU time of
the session's sshd process plus, for terminals, the pts timestamps. It shows when a session is
busy, not how many bytes it moved.
"""
import base64, collections, fcntl, hashlib, os, re, socket, struct, time

LOG = "/var/log/messages"
LOG_TAIL = 64 * 1024            # read this much history when the viewer opens
MAX_EVENTS = 40
SPARK_LEN = 30                  # samples of activity kept per connection
LINKS = {"rndis0": "USB", "wlan0": "WIFI", "lo": "LOCAL"}
SIOCGIFADDR = 0x8915
HZ = os.sysconf("SC_CLK_TCK")
EST, LISTEN = 0x01, 0x0A

_LINE = re.compile(r"^\w+\s+\d+ (\d\d:\d\d):\d\d \S+ \S+ sshd[-\w]*\[\d+\]: (.*)$")
_ACCEPTED = re.compile(r"^Accepted (\S+) for (\S+) from (\S+) port (\d+) ssh2(?:: (\S+) (\S+))?")
_FAILED = re.compile(r"^Failed (\S+) for (\S+) from (\S+) port (\d+)")
_INVALID = re.compile(r"^Invalid user (\S*) from (\S+) port (\d+)")
_DISC_USER = re.compile(r"^Disconnected from user (\S+) (\S+) port (\d+)")
_CLOSED = re.compile(r"^(?:Connection (?:closed|reset) by|Disconnected from)"
                     r"(?: (?:authenticating|invalid) user (\S*))? (\S+) port \d+.*\[preauth\]|"
                     r"^(?:Connection (?:closed|reset) by|Disconnected from)"
                     r" (?:authenticating|invalid) user (\S*) (\S+) port \d+|"
                     r"^Timeout before authentication for (?:connection from )?(\S+)")
_CMD_USER = re.compile(r"sshd[-\w]*: (\S+?)@(\S+)")
_CMD_PRIV = re.compile(r"sshd[-\w]*: (\S+) \[priv\]")


def clean(s):
    """Text that came from the network (usernames in the log): printable ASCII only."""
    return "".join(c if " " <= c <= "~" else " " if c in "\t\r\n" else "?" for c in s)


def _addr(h):
    if len(h) == 8:
        return socket.inet_ntoa(struct.pack("<I", int(h, 16)))
    raw = struct.pack("<4I", *(int(h[i:i + 8], 16) for i in range(0, 32, 8)))
    if raw[:12] == b"\0" * 10 + b"\xff\xff":        # IPv4-mapped
        return socket.inet_ntoa(raw[12:])
    return socket.inet_ntop(socket.AF_INET6, raw)


def read_tcp():
    """[(state, local ip, local port, remote ip, remote port, inode, queued bytes)]"""
    out = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                next(f)
                for line in f:
                    p = line.split()
                    lip, lport = p[1].split(":")
                    rip, rport = p[2].split(":")
                    tx, rx = p[4].split(":")
                    out.append((int(p[3], 16), _addr(lip), int(lport, 16), _addr(rip), int(rport, 16),
                                p[9], int(tx, 16) + int(rx, 16)))
        except (OSError, StopIteration, ValueError, IndexError):
            pass
    return out


def interfaces():
    """{interface name: IPv4 address} for the interfaces that have one."""
    out = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in os.listdir("/sys/class/net"):
            try:
                r = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()[:15]))
                out[name] = socket.inet_ntoa(r[20:24])
            except OSError:
                pass
    finally:
        s.close()
    return out


def read_procs():
    """{pid: (comm, ppid, cpu ticks, start ticks)} for every process."""
    procs = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                s = f.read().decode("latin1")
            head, tail = s.rsplit(")", 1)
            p = tail.split()
            procs[int(name)] = (head.split("(", 1)[1], int(p[1]), int(p[11]) + int(p[12]), int(p[19]))
        except (OSError, IndexError, ValueError):
            pass                # the process just went away
    return procs


def _socket_inodes(pid):
    out = set()
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                t = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if t.startswith("socket:["):
                out.add(t[8:-1])
    except OSError:
        pass
    return out


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return clean(f.read().replace(b"\0", b" ").decode("latin1").strip())
    except OSError:
        return ""


def _uptime():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def key_names(path="/root/.ssh/authorized_keys"):
    """{"SHA256:..." fingerprint: the key's comment}"""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.search(r"(?:^|\s)(?:ssh-\S+|ecdsa-\S+|sk-\S+) (\S+)(?: (.*))?$", line.strip())
                if m:
                    try:
                        d = hashlib.sha256(base64.b64decode(m.group(1))).digest()
                    except ValueError:
                        continue
                    fp = "SHA256:" + base64.b64encode(d).decode().rstrip("=")
                    out[fp] = clean(m.group(2) or "")
    except OSError:
        pass
    return out


class Event:
    __slots__ = ("time", "kind", "who", "ip")

    def __init__(self, time_, kind, who, ip):
        self.time, self.kind, self.who, self.ip = time_, kind, clean(who), clean(ip)


class Session:
    """One established connection to sshd."""
    __slots__ = ("ip", "port", "link", "user", "tty", "key", "command", "age", "idle", "spark", "fresh")


class Snapshot:
    __slots__ = ("running", "ports", "sessions", "events", "failed")


class _Track:
    """What's remembered about a connection between samples."""
    __slots__ = ("ticks", "pts", "active", "spark")

    def __init__(self, now):
        self.ticks = self.pts = None
        self.active = now
        self.spark = collections.deque([0] * SPARK_LEN, SPARK_LEN)


class SshMon:
    def __init__(self):
        self.keys = key_names()
        self.tracks = {}                                  # socket inode -> _Track
        self.events = collections.deque(maxlen=MAX_EVENTS)
        self.logins = {}                                  # (ip, port) -> (user, key label)
        self.failed = 0
        self.pos = None                                   # how far LOG has been read
        self.partial = b""

    # ---- log ---------------------------------------------------------------------------------
    def _read_log(self):
        try:
            size = os.path.getsize(LOG)
            if self.pos is None:
                self.pos = max(0, size - LOG_TAIL)
                skip_first = self.pos > 0
            else:
                skip_first = False
            if size < self.pos:                           # rotated
                self.pos, self.partial = 0, b""
            if size == self.pos:
                return
            with open(LOG, "rb") as f:
                f.seek(self.pos)
                data = f.read()
            self.pos += len(data)
        except OSError:
            return
        lines = (self.partial + data).split(b"\n")
        self.partial = lines.pop()                        # an unfinished last line waits for more
        if skip_first and lines:
            lines.pop(0)                                  # the tail started mid-line
        for line in lines:
            self._parse(line.decode("latin1"))

    def _parse(self, line):
        m = _LINE.match(line)
        if not m:
            return
        t, msg = m.groups()
        a = _ACCEPTED.match(msg)
        if a:
            method, user, ip, port, _ktype, fp = a.groups()
            label = self.keys.get(fp) or (fp[:15] if fp else method)
            self.logins[(ip, int(port))] = (user, clean(label))
            if len(self.logins) > 200:
                self.logins.pop(next(iter(self.logins)))
            self.events.appendleft(Event(t, "IN", user, ip))
            return
        a = _DISC_USER.match(msg)
        if a:
            self.events.appendleft(Event(t, "OUT", a.group(1), a.group(2)))
            return
        a = _INVALID.match(msg)
        if a:                                             # "Failed ... invalid user" repeats this
            self.failed += 1
            self.events.appendleft(Event(t, "FAIL", a.group(1) or "?", a.group(2)))
            return
        a = _FAILED.match(msg)
        if a:
            if a.group(2) != "invalid":
                self.failed += 1
                self.events.appendleft(Event(t, "FAIL", a.group(2), a.group(3)))
            return
        a = _CLOSED.match(msg)
        if a:
            self.events.appendleft(Event(t, "DROP", a.group(1) or a.group(3) or "?",
                                         a.group(2) or a.group(4) or a.group(5) or "?"))

    # ---- sampling ------------------------------------------------------------------------------
    def sample(self):
        now = time.monotonic()
        self._read_log()
        procs = read_procs()
        children = collections.defaultdict(list)
        for pid, p in procs.items():
            children[p[1]].append(pid)
        listeners = [pid for pid, p in procs.items() if p[0] == "sshd"]
        sessions = [pid for pid, p in procs.items() if p[0].startswith("sshd-")]
        by_inode = collections.defaultdict(list)
        for pid in sessions:
            for ino in _socket_inodes(pid):
                by_inode[ino].append(pid)
        listen_inodes = set()
        for pid in listeners:
            listen_inodes |= _socket_inodes(pid)

        tcp = read_tcp()
        ifs = interfaces()
        snap = Snapshot()
        snap.running = bool(listeners)
        lsocks = [t for t in tcp if t[0] == LISTEN and t[5] in listen_inodes]
        ports = {t[2] for t in lsocks} or {22}
        snap.ports = []                                   # (link, ip, port or None if closed)
        for name, ip in sorted(ifs.items(), key=lambda kv: list(LINKS).index(kv[0]) if kv[0] in LINKS else 9):
            if name not in LINKS:
                continue
            hit = next((t[2] for t in lsocks if t[1] in (ip, "0.0.0.0", "::")), None)
            snap.ports.append((LINKS[name], ip, hit))

        up = _uptime()
        out, seen = [], set()
        for st, lip, lport, rip, rport, ino, queued in tcp:
            if st != EST or lport not in ports:
                continue
            seen.add(ino)
            s = Session()
            s.ip, s.port = rip, rport
            s.link = next((LINKS.get(n, n.upper()) for n, ip in ifs.items() if ip == lip), "?")
            pids = by_inode.get(ino, [])
            user, tty, top, keylabel = None, None, None, ""
            for pid in pids:
                cmd = _cmdline(pid)
                m = _CMD_USER.search(cmd)
                if m:
                    user, tty, top = m.group(1), m.group(2), pid
                else:
                    m = _CMD_PRIV.search(cmd)
                    if m and m.group(1) != "unknown" and user is None:
                        user = m.group(1)
            login = self.logins.get((rip, rport))
            if login:
                keylabel = login[1]
                user = user or login[0]
            s.user, s.tty, s.key = user, tty, keylabel
            s.command = self._command(top, procs, children) if top else ""
            start = min((procs[p][3] for p in pids if p in procs), default=None)
            s.age = max(0, up - start / HZ) if start is not None else 0

            tr = self.tracks.get(ino)
            if tr is None:
                tr = self.tracks[ino] = _Track(now)
            ticks = sum(procs[p][2] for p in pids if p in procs)
            delta = ticks - tr.ticks if tr.ticks is not None else 0
            tr.ticks = ticks
            pts = self._pts_time(tty)
            pts_moved = tr.pts is not None and pts != tr.pts
            tr.pts = pts
            if delta > 0 or queued or pts_moved:
                tr.active = now
            tr.spark.append(max(0, delta) + (1 if (queued or pts_moved) else 0))
            s.spark = list(tr.spark)
            s.idle = now - tr.active
            s.fresh = s.age < 3
            out.append(s)
        for ino in list(self.tracks):
            if ino not in seen:
                del self.tracks[ino]
        out.sort(key=lambda s: (s.user is None, s.age))   # logged-in first, newest first
        snap.sessions = out
        snap.events = list(self.events)
        snap.failed = self.failed
        return snap

    @staticmethod
    def _pts_time(tty):
        if not tty or not tty.startswith("pts/"):
            return None
        try:
            st = os.stat("/dev/" + tty)
            return max(st.st_atime, st.st_mtime)
        except OSError:
            return None

    @staticmethod
    def _command(top, procs, children):
        """What the session is running: the newest process at the bottom of its tree."""
        pid, best = top, None
        stack = list(children.get(top, []))
        while stack:
            p = stack.pop()
            kids = children.get(p, [])
            stack.extend(kids)
            if not kids and p in procs and (best is None or procs[p][3] >= procs[best][3]):
                best = p
        if best is None:
            return ""
        return _cmdline(best) or procs[best][0]

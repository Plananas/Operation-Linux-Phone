"""Bluetooth control for TREND OS apps: one long-lived `bluetoothctl` (BlueZ) driven through a
pipe. It is also the pairing agent (NoInputNoOutput: "just works" pairing, passkeys confirmed
automatically - headphones and speakers have no screen to compare them on anyway).

    bt = BtCtl(); bt.start()
    bt.power(True); bt.scan(True)        # discovery stops by itself after SCAN_TIME
    bt.devices -> {mac: Device}          # live: names, paired/connected, RSSI, kind
    bt.pair_and_connect(mac); bt.connect(mac); bt.disconnect(mac); bt.forget(mac)
    bt.version                           # bumps whenever anything changes (for App.key())

The services underneath: btuart (chip -> hci0), bluetooth (bluetoothd), btaudio (bluealsa).
"""
import re, subprocess, threading, time

SCAN_TIME = 20
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02|\r")
PROMPT = re.compile(r"^(\s*\[[^\]]*\][>#]\s*)+")    # "[bluetoothctl]> " / "[TREND OS]# ", repeated
EVENT = re.compile(r"^\[(NEW|CHG|DEL)\] (Device|Controller) ([0-9A-F:]{17}) ?(.*)$")
MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")

# BlueZ "Icon" -> what TREND OS calls it
KINDS = {"audio-headset": "headset", "audio-headphones": "headphones", "audio-card": "speaker",
         "phone": "phone", "computer": "computer", "input-keyboard": "keyboard",
         "input-mouse": "mouse", "input-gaming": "gamepad", "video-display": "tv"}


class Device:
    def __init__(self, mac, name=""):
        self.mac, self.name = mac, name
        self.paired = self.connected = self.trusted = False
        self.rssi, self.kind, self.seen = None, "", 0.0

    @property
    def label(self):
        """Display name; unnamed devices (mostly BLE beacons) show their address."""
        return self.name if self.name and self.name.replace("-", ":") != self.mac else self.mac

    @property
    def named(self):
        return self.label != self.mac


class BtCtl:
    def __init__(self):
        self.devices, self.powered, self.discovering = {}, False, False
        self.address, self.alias = "", ""
        self.version = 0
        self.busy, self.msg = None, ""            # current operation ("pairing", ...), status text
        self.passkey = None
        self._p, self._lock = None, threading.Lock()
        self._scan_until = 0.0
        self._info_for = None                     # mac whose `info` block is being read

    # ---- process ----------------------------------------------------------------------------
    def start(self):
        if self._p is not None and self._p.poll() is None:
            return
        try:
            self._p = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as e:
            self._set_msg(f"bluetoothctl failed: {e}")
            return
        threading.Thread(target=self._reader, daemon=True).start()
        for c in ("agent NoInputNoOutput", "default-agent", "pairable on", "show", "devices"):
            self._send(c)

    def stop(self):
        p, self._p = self._p, None
        if p is not None and p.poll() is None:
            try:
                if self.discovering:
                    p.stdin.write("scan off\n")
                p.stdin.write("quit\n"); p.stdin.flush()
                p.wait(timeout=2)
            except Exception:
                p.kill()

    def _send(self, cmd):
        p = self._p
        if p is None or p.poll() is not None:
            return
        try:
            p.stdin.write(cmd + "\n"); p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _changed(self):
        self.version += 1

    def _set_msg(self, msg):
        self.msg = msg
        self._changed()

    # ---- commands -------------------------------------------------------------------------------
    def power(self, on):
        self._send("power on" if on else "power off")

    def scan(self, on):
        if on:
            self._scan_until = time.monotonic() + SCAN_TIME
            self._send("scan on")
        else:
            self._scan_until = 0.0
            self._send("scan off")

    def tick(self):
        """Call regularly (from App.key()): stops discovery after SCAN_TIME."""
        if self._scan_until and time.monotonic() > self._scan_until:
            self.scan(False)

    def pair_and_connect(self, mac):
        self.busy = ("pairing", mac); self._set_msg("pairing ...")
        self._send(f"pair {mac}")                 # on success: trust + connect (see _line)

    def connect(self, mac):
        self.busy = ("connecting", mac); self._set_msg("connecting ...")
        self._send(f"connect {mac}")

    def disconnect(self, mac):
        self.busy = ("disconnecting", mac); self._set_msg("disconnecting ...")
        self._send(f"disconnect {mac}")

    def forget(self, mac):
        self._send(f"remove {mac}")

    # ---- output parsing -----------------------------------------------------------------------
    def _dev(self, mac):
        d = self.devices.get(mac)
        if d is None:
            d = self.devices[mac] = Device(mac)
            self._send(f"info {mac}")             # paired? connected? kind?
        return d

    def _reader(self):
        p = self._p
        for raw in p.stdout:
            for line in ANSI.sub("", raw).split("\n"):
                line = PROMPT.sub("", line).strip()
                if line:
                    with self._lock:
                        try:
                            self._line(line)
                        except Exception:
                            pass
        self.powered = False
        self._set_msg("bluetooth stopped")

    def _line(self, line):
        m = EVENT.match(line)
        if m:
            kind, what, mac, rest = m.groups()
            if what == "Controller":
                self._prop(None, rest)
            elif kind == "DEL":
                self.devices.pop(mac, None)
            else:
                d = self._dev(mac)
                if kind == "NEW":
                    d.name, d.seen = rest.strip(), time.monotonic()
                else:
                    self._prop(d, rest)
            self._changed()
            return
        if line.startswith("Device ") and MAC.match(line[7:24]):    # "devices" list / info header
            mac = line[7:24]
            d = self._dev(mac)
            rest = line[25:].strip()
            if rest and not rest.startswith("("):
                d.name = rest
            self._info_for = mac
            self._changed()
            return
        if line.startswith("Controller ") and MAC.match(line[11:28]):
            self.address, self._info_for = line[11:28], "controller"
            return
        if ":" in line and self._info_for:                          # "Name: ...", "Paired: yes"
            d = None if self._info_for == "controller" else self.devices.get(self._info_for)
            self._prop(d, line)
            self._changed()
            return
        self._result(line)

    def _prop(self, d, text):
        k, _, v = text.partition(": ")
        k, v = k.strip(), v.strip()
        yes = v == "yes"
        if d is None:                                                # the controller
            if k == "Powered":
                self.powered = yes
            elif k == "Discovering":
                self.discovering = yes
            elif k == "Alias":
                self.alias = v
            return
        if k in ("Name", "Alias") and v:
            if k == "Name" or not d.name:
                d.name = v
        elif k == "Paired":
            d.paired = yes
        elif k == "Bonded" and yes:
            d.paired = True
        elif k == "Trusted":
            d.trusted = yes
        elif k == "Connected":
            d.connected = yes
            if self.busy and self.busy[1] == d.mac and self.busy[0] in ("connecting", "disconnecting"):
                self.busy = None
                self.msg = f"{d.label}: {'connected' if yes else 'disconnected'}"
        elif k == "Icon":
            d.kind = KINDS.get(v, "")
        elif k == "RSSI":
            n = re.search(r"-?\d+(?=\)?$)", v)
            d.rssi = int(n.group()) if n else None
            d.seen = time.monotonic()

    def _result(self, line):
        """Replies to our commands and agent prompts."""
        low = line.lower()
        if "confirm passkey" in low or "request confirmation" in low:
            n = re.search(r"\d{6}", line)
            self.passkey = n.group() if n else None
            self._send("yes")
        elif "authorize service" in low or "accept pairing" in low:
            self._send("yes")
        elif "enter pin code" in low:
            self._send("0000")
        elif low.startswith("pairing successful"):
            mac = self.busy[1] if self.busy else None
            if mac:
                self._send(f"trust {mac}")
                self.busy = ("connecting", mac)
                self._send(f"connect {mac}")
            self._set_msg("paired, connecting ...")
        elif low.startswith("failed to pair") or low.startswith("failed to connect") or \
                low.startswith("failed to disconnect"):
            self.busy = None
            reason = line.split(":", 1)[-1].strip().replace("org.bluez.Error.", "")
            self._set_msg(f"failed: {reason}"[:40])
        elif low.startswith("connection successful"):
            self.busy = None
            self._set_msg("connected")
        elif low.startswith("successful disconnected"):
            self.busy = None
            self._set_msg("disconnected")
        elif "not available" in low and self.busy:
            self.busy = None
            self._set_msg("device not in range")

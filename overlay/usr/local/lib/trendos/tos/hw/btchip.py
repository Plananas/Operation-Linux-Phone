"""The Broadcom BCM43430A1 Bluetooth/FM chip on the UART /dev/ttyS0: power, firmware patch,
UART speed, and vendor HCI commands - shared by the FM radio (tos/hw/fm.py) and Bluetooth
(/usr/local/sbin/bt-up).

Two ways to talk to it:
  RawUart   the UART directly (no BlueZ): power on via rfkill, load the patch, send commands.
  HciSocket through the kernel's Bluetooth stack once BlueZ owns the UART (hci0 attached by
            bt-up): raw HCI commands on an HCI socket, as `hcitool cmd` does.
open_chip() picks HciSocket when hci0 exists, else powers the chip up on RawUart.
"""
import os, select, socket, struct, subprocess, termios, time

UART = "/dev/ttyS0"
PATCH = "/data/bt/BCM43430A1.hcd"     # copied once from Android's /system (see patch_file())
PATCH_SRC = "/mnt/system/vendor/firmware/BCM43430A1_001.002.009.0018.0033_ORC.hcd"
ADDR = "/data/bt/bt_addr"            # the phone's own Bluetooth address, copied from Samsung's efs
FAST_BAUD = 3000000                   # after the patch (Android's Broadcom vendor lib does the same)
HCI_DEV = "/sys/class/bluetooth/hci0"


def bt_rfkill():
    """sysfs dir of the chip's power switch (bcm bt rfkill; not the hci0 soft switch)."""
    for d in sorted(os.listdir("/sys/class/rfkill")):
        p = f"/sys/class/rfkill/{d}"
        try:
            name = open(p + "/name").read().strip()
        except OSError:
            continue
        if not name.startswith("hci"):
            return p
    raise IOError("no Bluetooth rfkill switch")


def power(on):
    with open(bt_rfkill() + "/state", "w") as f:
        f.write("1" if on else "0")


def patch_file():
    if not os.path.exists(PATCH):
        os.makedirs(os.path.dirname(PATCH), exist_ok=True)
        os.makedirs("/mnt/system", exist_ok=True)
        if subprocess.run(["mountpoint", "-q", "/mnt/system"]).returncode != 0:
            subprocess.run(["mount", "-o", "ro", "/dev/mmcblk0p24", "/mnt/system"], check=True)
        with open(PATCH_SRC, "rb") as s, open(PATCH, "wb") as d:
            d.write(s.read())
    return PATCH


def bd_addr():
    """This phone's Bluetooth address ("D0:87:..."), from efs (p17, mounted read-only once).
    None if not found (the chip then keeps Broadcom's placeholder 43:43:A1:...)."""
    if not os.path.exists(ADDR):
        os.makedirs("/mnt/efs", exist_ok=True)
        try:
            subprocess.run(["mount", "-o", "ro", "/dev/mmcblk0p17", "/mnt/efs"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with open("/mnt/efs/bluetooth/bt_addr") as f, open(ADDR, "w") as o:
                    o.write(f.read().strip())
            finally:
                subprocess.run(["umount", "/mnt/efs"])
        except (OSError, subprocess.CalledProcessError):
            return None
    a = open(ADDR).read().strip()
    return a if len(a.split(":")) == 6 else None


def _baud_const(baud):
    return getattr(termios, f"B{baud}")


class RawUart:
    def __init__(self, baud=115200):
        fd = os.open(UART, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.fd = fd
        self.set_baud(baud)
        termios.tcflush(fd, termios.TCIOFLUSH)

    def set_baud(self, baud):
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | termios.CRTSCTS
        a[4] = a[5] = _baud_const(baud)
        a[6][termios.VMIN] = a[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)

    def close(self):
        termios.tcflush(self.fd, termios.TCIOFLUSH)   # never block in close() on unsent bytes
        os.close(self.fd)

    def cmd(self, opcode, params=b"", timeout=1.5):
        """Send an HCI command, return the event packet (bytes after the 0x04 type byte)."""
        os.write(self.fd, struct.pack("<BHB", 1, opcode, len(params)) + params)
        buf, end = b"", time.time() + timeout
        while time.time() < end:
            if select.select([self.fd], [], [], max(0, end - time.time()))[0]:
                try:
                    buf += os.read(self.fd, 300)
                except BlockingIOError:                 # spurious wake-up
                    continue
                if len(buf) >= 3 and buf[0] == 4 and len(buf) >= 3 + buf[2]:
                    return buf[1:3 + buf[2]]
        raise IOError(f"no HCI reply to 0x{opcode:04x}")


class HciSocket:
    """Raw HCI commands through the kernel (hci0 attached to the UART by bt-up)."""
    HCI_FILTER = 2

    def __init__(self, dev=0):
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        s.bind((dev,))
        # filter: HCI event packets, Command Complete (0x0e) + Command Status (0x0f)
        s.setsockopt(socket.SOL_HCI, self.HCI_FILTER,
                     struct.pack("<IIIh2x", 1 << 4, (1 << 0x0e) | (1 << 0x0f), 0, 0))
        self.s = s

    def close(self):
        self.s.close()

    def cmd(self, opcode, params=b"", timeout=1.5):
        self.s.send(struct.pack("<BHB", 1, opcode, len(params)) + params)
        end = time.time() + timeout
        while time.time() < end:
            if select.select([self.s], [], [], max(0, end - time.time()))[0]:
                p = self.s.recv(300)
                # p = 04 | evt | len | (ncmd | opcode LE | status ...) for Command Complete
                if len(p) >= 6 and p[1] == 0x0e and struct.unpack_from("<H", p, 4)[0] == opcode:
                    return p[1:]
        raise IOError(f"no HCI reply to 0x{opcode:04x}")


def boot_raw(baud=None, addr=None):
    """Power the chip (rfkill off->on: the UART gives EIO until then), load the firmware patch,
    switch off chip sleep, optionally set the Bluetooth address and switch the UART to `baud`.
    Returns an open RawUart."""
    patch = patch_file()
    power(False); time.sleep(0.3)
    power(True); time.sleep(0.6)
    u = RawUart(115200)
    try:
        u.cmd(0x0C03)                                   # HCI reset
        u.cmd(0xFC2E); time.sleep(0.05)                 # download minidriver
        d, i = open(patch, "rb").read(), 0
        while i < len(d):                               # .hcd = a list of HCI commands
            op, ln = struct.unpack_from("<HB", d, i)
            u.cmd(op, d[i + 3:i + 3 + ln]); i += 3 + ln
        time.sleep(0.25)
        u.cmd(0x0C03, timeout=2)                        # reset -> run the patched firmware
        u.cmd(0xFC27, bytes(12))                        # sleep mode off (else CTS stalls the UART)
        if addr:
            u.cmd(0xFC01, bytes(int(b, 16) for b in reversed(addr.split(":"))))   # vendor: write BD_ADDR
        if baud and baud != 115200:
            u.cmd(0xFC18, b"\0\0" + struct.pack("<I", baud))   # vendor: update UART baud rate
            time.sleep(0.05)
            u.set_baud(baud)
            u.cmd(0x1001)                               # read local version: checks the new speed
    except Exception:
        u.close()
        raise
    return u


def bluez_attached():
    return os.path.exists(HCI_DEV)

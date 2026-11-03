"""FM radio driver: Broadcom BCM43430A1 FM core, analog out -> codec line-in -> headphones.

Raw HCI over the Bluetooth UART (no BlueZ); wired headphones are the antenna. Blocking calls:
use it from one background thread (the Radio app does). Command line: /usr/local/sbin/fmctl.
See PLAN.md "FM radio" for how this was worked out and what NOT to do (digital FM reboots).
"""
import os, select, struct, subprocess, termios, time

UART, RFKILL = "/dev/ttyS0", "/sys/class/rfkill/rfkill0/state"
PATCH = "/data/bt/BCM43430A1.hcd"     # copied once from Android's /system (see _patch())
PATCH_SRC = "/mnt/system/vendor/firmware/BCM43430A1_001.002.009.0018.0033_ORC.hcd"
CARD = "sprdphone"
BAND = (87.5, 108.0)                  # MHz, Europe/US
STEP = 0.1

# FM core registers (vendor HCI 0xFC15: [reg, 0=write/1=read, data...])
REG_POWER, REG_CTRL, REG_AUDIO0, REG_TUNE_MODE, REG_FREQ0, REG_FREQ1, REG_RSSI = 0x00, 0x01, 0x05, 0x09, 0x0A, 0x0B, 0x0F
CTRL_STEREO = 0x04                    # band Europe/US 87.5-108, manual blend, stereo
AUDIO_DAC_LR = 0x1C                   # DAC left + right on, route to analog DAC (0x20 = I2S, 0x02 = mute)
AUDIO_MUTE = 0x02
HP_VOL_MAX = 15                       # codec "HPx Playback Volume" range 0..15 (3 dB steps)


def clamp(mhz):
    return round(min(BAND[1], max(BAND[0], mhz)) / STEP) * STEP


# ---- raw HCI --------------------------------------------------------------------------------
def _open():
    fd = os.open(UART, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | termios.CRTSCTS
    a[4] = a[5] = termios.B115200
    a[6][termios.VMIN] = a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def _close(fd):
    termios.tcflush(fd, termios.TCIOFLUSH)   # never block in close() on unsent bytes
    os.close(fd)


def _cmd(fd, opcode, params=b"", timeout=1.5):
    os.write(fd, struct.pack("<BHB", 1, opcode, len(params)) + params)
    buf, end = b"", time.time() + timeout
    while time.time() < end:
        if select.select([fd], [], [], max(0, end - time.time()))[0]:
            buf += os.read(fd, 300)
            if len(buf) >= 3 and buf[0] == 4 and len(buf) >= 3 + buf[2]:
                return buf[:3 + buf[2]]
    raise IOError(f"no HCI reply to 0x{opcode:04x}")


def _w(fd, reg, *vals):
    _cmd(fd, 0xFC15, bytes([reg, 0] + list(vals)))


def _r(fd, reg, n=1):
    e = _cmd(fd, 0xFC15, bytes([reg, 1, n]))
    return int.from_bytes(e[9:9 + n], "little")


def _patch():
    """Path of the chip's firmware patch, copied from Android's /system on first use."""
    if not os.path.exists(PATCH):
        os.makedirs(os.path.dirname(PATCH), exist_ok=True)
        os.makedirs("/mnt/system", exist_ok=True)
        if subprocess.run(["mountpoint", "-q", "/mnt/system"]).returncode != 0:
            subprocess.run(["mount", "-o", "ro", "/dev/mmcblk0p24", "/mnt/system"], check=True)
        with open(PATCH_SRC, "rb") as s, open(PATCH, "wb") as d:
            d.write(s.read())
    return PATCH


# ---- codec (analog line-in -> headphones) -------------------------------------------------------
def _mix(name, val):
    subprocess.run(["amixer", "-q", "-c", CARD, "cset", f"name={name}", str(val)], check=False)


def codec_on(volume=12):
    for name, val in [("VBC Switch", "ap"), ("Line Function", 1), ("Linein Boost", 3),
                      ("Linein Mute Switch", 0), ("Linein Headphone Mute Switch", 0),
                      ("ADCL Mixer AILADCL Switch", 1), ("ADCR Mixer AIRADCR Switch", 1),
                      ("HPL Mixer ADCLHPL Switch", 1), ("HPR Mixer ADCRHPR Switch", 1),
                      ("HeadPhone Mute", 0), ("HeadPhone Function", 1)]:
        _mix(name, val)
    set_volume(volume)


def codec_off():
    for name, val in [("HeadPhone Function", 0), ("HPL Mixer ADCLHPL Switch", 0), ("HPR Mixer ADCRHPR Switch", 0),
                      ("ADCL Mixer AILADCL Switch", 0), ("ADCR Mixer AIRADCR Switch", 0),
                      ("Line Function", 0), ("Linein Boost", 0), ("HeadPhone Mute", 1)]:
        _mix(name, val)


def set_volume(v):
    """Headphone volume 0..HP_VOL_MAX (0 = codec mute)."""
    v = max(0, min(HP_VOL_MAX, int(v)))
    _mix("HPL Playback Volume", v); _mix("HPR Playback Volume", v)


# ---- the radio ----------------------------------------------------------------------------------
class FM:
    """Power, tune, read signal. Keeps the UART open while on (retuning is then ~10 ms)."""

    def __init__(self):
        self.fd = None

    @property
    def is_on(self):
        return self.fd is not None

    def on(self, mhz, volume=12):
        """Power up (~4 s: rfkill cycle + firmware patch download) and tune."""
        patch = _patch()
        if self.fd is not None:
            self.off()
        # The UART only works after an rfkill off->on (EIO before); that toggle also powers the chip.
        with open(RFKILL, "w") as f: f.write("0")
        time.sleep(0.3)
        with open(RFKILL, "w") as f: f.write("1")
        time.sleep(0.6)
        fd = _open()
        try:
            _cmd(fd, 0x0C03)                                   # HCI reset
            _cmd(fd, 0xFC2E); time.sleep(0.05)                 # download minidriver
            d, i = open(patch, "rb").read(), 0
            while i < len(d):                                  # .hcd = a list of HCI commands
                op, ln = struct.unpack_from("<HB", d, i)
                _cmd(fd, op, d[i + 3:i + 3 + ln]); i += 3 + ln
            time.sleep(0.25)
            _cmd(fd, 0x0C03, timeout=2)                        # reset -> run the patched firmware
            _cmd(fd, 0xFC27, bytes(12))                        # sleep mode off (else it dozes, CTS stalls the UART)
            _w(fd, REG_POWER, 0x01); time.sleep(0.1)           # FM on (0x03 = FM + RDS)
            _w(fd, REG_CTRL, CTRL_STEREO)
            _w(fd, REG_AUDIO0, AUDIO_DAC_LR, 0x00)
        except Exception:
            _close(fd)
            raise
        self.fd = fd
        self.tune(mhz)
        codec_on(volume)

    def tune(self, mhz):
        f = int(round(clamp(mhz) * 1000)) - 64000
        _w(self.fd, REG_FREQ0, f & 0xFF); _w(self.fd, REG_FREQ1, f >> 8); _w(self.fd, REG_TUNE_MODE, 0x01)

    def freq(self):
        return (_r(self.fd, REG_FREQ0, 2) + 64000) / 1000

    def rssi(self):
        return _r(self.fd, REG_RSSI)

    def off(self):
        codec_off()
        try:
            fd = self.fd if self.fd is not None else _open()
            try:
                _w(fd, REG_AUDIO0, AUDIO_MUTE, 0x00); _w(fd, REG_POWER, 0x00)
            finally:
                _close(fd)
        except (OSError, IOError):
            pass                                               # chip already off
        self.fd = None
        with open(RFKILL, "w") as f: f.write("0")


def main(argv):
    """fmctl on [MHz] | tune MHz | off   (tune reopens the UART of a radio left on by `on`)."""
    cmd = argv[0] if argv else ""
    fm = FM()
    if cmd == "on":
        fm.on(float(argv[1]) if len(argv) > 1 else 100.0)
        print(f"on {fm.freq():.1f} MHz  rssi {fm.rssi()}")
        _close(fm.fd)                                          # leave the chip running
    elif cmd == "tune" and len(argv) > 1:
        fm.fd = _open()
        try:
            fm.tune(float(argv[1])); time.sleep(0.15)
            print(f"tuned {fm.freq():.1f} MHz  rssi {fm.rssi()}")
        finally:
            _close(fm.fd)
    elif cmd == "off":
        fm.off()
    else:
        raise SystemExit("usage: fmctl on [MHz] | tune MHz | off")

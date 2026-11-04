"""FM radio driver: Broadcom BCM43430A1 FM core, analog out -> codec line-in -> headphones.

Vendor HCI commands to the Bluetooth/FM chip (tos/hw/btchip.py): straight over the UART when
Bluetooth is off, or through BlueZ's hci0 when bt-up has attached it (the chip then stays
powered for Bluetooth). Wired headphones are the antenna. Blocking calls: use it from one
background thread (the Radio app does). Command line: /usr/local/sbin/fmctl.
See PLAN.md "FM radio" for how this was worked out and what NOT to do (digital FM reboots).
"""
import subprocess, time

from . import btchip

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


def _w(t, reg, *vals):
    t.cmd(0xFC15, bytes([reg, 0] + list(vals)))


def _r(t, reg, n=1):
    e = t.cmd(0xFC15, bytes([reg, 1, n]))     # 0e len ncmd opcode(2) status reg ... data
    return int.from_bytes(e[8:8 + n], "little")


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
def _link():
    """A link to a chip that is already running."""
    return btchip.HciSocket() if btchip.bluez_attached() else btchip.RawUart()


class FM:
    """Power, tune, read signal. Keeps the chip link open while on (retuning is then ~10 ms)."""

    def __init__(self):
        self.t = None              # btchip.RawUart or btchip.HciSocket

    @property
    def is_on(self):
        return self.t is not None

    def on(self, mhz, volume=12):
        """Power up and tune (~4 s from cold: rfkill cycle + firmware patch download; instant
        when Bluetooth already has the chip running)."""
        if self.t is not None:
            self.off()
        self.t = btchip.HciSocket() if btchip.bluez_attached() else btchip.boot_raw()
        try:
            _w(self.t, REG_POWER, 0x01); time.sleep(0.1)           # FM on (0x03 = FM + RDS)
            _w(self.t, REG_CTRL, CTRL_STEREO)
            _w(self.t, REG_AUDIO0, AUDIO_DAC_LR, 0x00)
        except Exception:
            self.off()
            raise
        self.tune(mhz)
        codec_on(volume)

    def tune(self, mhz):
        f = int(round(clamp(mhz) * 1000)) - 64000
        _w(self.t, REG_FREQ0, f & 0xFF); _w(self.t, REG_FREQ1, f >> 8); _w(self.t, REG_TUNE_MODE, 0x01)

    def freq(self):
        return (_r(self.t, REG_FREQ0, 2) + 64000) / 1000

    def rssi(self):
        return _r(self.t, REG_RSSI)

    def off(self):
        codec_off()
        t, self.t = self.t, None
        try:
            if t is None:
                t = _link()
            try:
                _w(t, REG_AUDIO0, AUDIO_MUTE, 0x00); _w(t, REG_POWER, 0x00)
            finally:
                t.close()
        except (OSError, IOError):
            pass                                               # chip already off
        if not btchip.bluez_attached():
            try:
                btchip.power(False)                            # nobody else needs the chip
            except (OSError, IOError):
                pass


def main(argv):
    """fmctl on [MHz] | tune MHz | off   (tune reopens the link to a radio left on by `on`)."""
    cmd = argv[0] if argv else ""
    fm = FM()
    if cmd == "on":
        fm.on(float(argv[1]) if len(argv) > 1 else 100.0)
        print(f"on {fm.freq():.1f} MHz  rssi {fm.rssi()}")
        fm.t.close()                                           # leave the chip running
    elif cmd == "tune" and len(argv) > 1:
        fm.t = _link()
        try:
            fm.tune(float(argv[1])); time.sleep(0.15)
            print(f"tuned {fm.freq():.1f} MHz  rssi {fm.rssi()}")
        finally:
            fm.t.close()
    elif cmd == "off":
        fm.off()
    else:
        raise SystemExit("usage: fmctl on [MHz] | tune MHz | off")

#!/usr/bin/env python3
"""FM radio control for the SM-G318H (Broadcom BCM43430A1 FM core, analog out -> codec line-in).

Raw HCI over /dev/ttyS0 (no BlueZ). Run on the phone as root:
    fmctl.py on [FREQ_MHZ]     power up, load the patch, route analog FM to the headphones
    fmctl.py tune FREQ_MHZ     retune (chip must be on)
    fmctl.py off               mute, power down FM + Bluetooth core, restore the codec
See PLAN.md "FM radio" for how this was worked out and what NOT to do (Digital FM crashes).
"""
import os, select, struct, subprocess, sys, termios, time

UART, RFKILL = "/dev/ttyS0", "/sys/class/rfkill/rfkill0/state"
PATCH = "/root/bt/BCM43430A1.hcd"     # copy of /system/vendor/firmware/BCM43430A1_*.hcd
CARD = "sprdphone"

# FM core registers (vendor HCI 0xFC15: [reg, 0=write/1=read, data...])
REG_POWER, REG_CTRL, REG_AUDIO0, REG_TUNE_MODE, REG_FREQ0, REG_FREQ1, REG_RSSI = 0x00, 0x01, 0x05, 0x09, 0x0A, 0x0B, 0x0F
CTRL_STEREO = 0x04                    # band Europe/US 87.5-108, manual blend, stereo
AUDIO_DAC_LR = 0x1C                   # DAC left + right on, route to analog DAC (0x20 = I2S, 0x02 = mute)
AUDIO_MUTE = 0x02


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


# ---- codec (analog line-in -> headphones) -------------------------------------------------------
def _mix(name, val):
    subprocess.run(["amixer", "-q", "-c", CARD, "cset", f"name={name}", str(val)], check=False)


def codec_on():
    for name, val in [("VBC Switch", "ap"), ("Line Function", 1), ("Linein Boost", 3),
                      ("Linein Mute Switch", 0), ("Linein Headphone Mute Switch", 0),
                      ("ADCL Mixer AILADCL Switch", 1), ("ADCR Mixer AIRADCR Switch", 1),
                      ("HPL Mixer ADCLHPL Switch", 1), ("HPR Mixer ADCRHPR Switch", 1),
                      ("HPL Playback Volume", 12), ("HPR Playback Volume", 12),
                      ("HeadPhone Mute", 0), ("HeadPhone Function", 1)]:
        _mix(name, val)


def codec_off():
    for name, val in [("HeadPhone Function", 0), ("HPL Mixer ADCLHPL Switch", 0), ("HPR Mixer ADCRHPR Switch", 0),
                      ("ADCL Mixer AILADCL Switch", 0), ("ADCR Mixer AIRADCR Switch", 0),
                      ("Line Function", 0), ("Linein Boost", 0), ("HeadPhone Mute", 1)]:
        _mix(name, val)


# ---- commands -------------------------------------------------------------------------------------
def tune(fd, mhz):
    f = int(round(mhz * 1000)) - 64000
    _w(fd, REG_FREQ0, f & 0xFF); _w(fd, REG_FREQ1, f >> 8); _w(fd, REG_TUNE_MODE, 0x01)
    time.sleep(0.15)
    got = (_r(fd, REG_FREQ0, 2) + 64000) / 1000
    print(f"tuned {got:.1f} MHz  rssi {_r(fd, REG_RSSI)}")


def on(mhz):
    # The UART only works after an rfkill off->on (EIO before); that toggle also powers the chip.
    open(RFKILL, "w").write("0"); time.sleep(0.3)
    open(RFKILL, "w").write("1"); time.sleep(0.6)
    fd = _open()
    try:
        _cmd(fd, 0x0C03)                                   # HCI reset
        _cmd(fd, 0xFC2E); time.sleep(0.05)                 # download minidriver
        d, i = open(PATCH, "rb").read(), 0
        while i < len(d):                                  # .hcd = a list of HCI commands
            op, ln = struct.unpack_from("<HB", d, i)
            _cmd(fd, op, d[i + 3:i + 3 + ln]); i += 3 + ln
        time.sleep(0.25)
        _cmd(fd, 0x0C03, timeout=2)                        # reset -> run the patched firmware
        _cmd(fd, 0xFC27, bytes(12))                        # sleep mode off (else it dozes, CTS stalls the UART)
        _w(fd, REG_POWER, 0x01); time.sleep(0.1)           # FM on (0x03 = FM + RDS)
        _w(fd, REG_CTRL, CTRL_STEREO)
        _w(fd, REG_AUDIO0, AUDIO_DAC_LR, 0x00)
        tune(fd, mhz)
    finally:
        _close(fd)
    codec_on()


def off():
    try:
        fd = _open()
        try:
            _w(fd, REG_AUDIO0, AUDIO_MUTE, 0x00); _w(fd, REG_POWER, 0x00)
        finally:
            _close(fd)
    except (OSError, IOError):
        pass                                               # chip already off
    codec_off()
    open(RFKILL, "w").write("0")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "on":
        on(float(sys.argv[2]) if len(sys.argv) > 2 else 100.0)
    elif cmd == "tune":
        fd = _open()
        try:
            tune(fd, float(sys.argv[2]))
        finally:
            _close(fd)
    elif cmd == "off":
        off()
    else:
        sys.exit(__doc__)

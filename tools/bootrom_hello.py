#!/usr/bin/env python3
"""Read-only handshake with a Spreadtrum BootROM (USB 1782:4d00).

Sends only the "check baud" probe and prints the BootROM's version reply.
Nothing is uploaded, written or executed on the phone; afterwards the BootROM
times out and the phone boots normally.

Protocol (from spreadtrum_flash/spd_dump.c, reimplemented here):
  1. control transfer bmRequestType=0x21 bRequest=34 wValue=0x601 wIndex=0
  2. bulk OUT a single 0x7E byte (BSL_CMD_CHECK_BAUD)
  3. bulk IN one HDLC frame: 7E | type(2,BE)=0x0081 | len(2,BE) | data | crc16(2,BE) | 7E
     (0x7D escapes the next byte XOR 0x20)
  Reply data "SPRD3\\0" = BootROM without secure boot (per spd_dump.c line ~1279).

Usage: sudo python3 bootrom_hello.py   (then plug the phone in holding Volume Up)
"""
import fcntl, glob, os, struct, sys, time

VID, PID = "1782", "4d00"
USBDEVFS_CONTROL = 0xC0185500          # _IOWR('U', 0, struct usbdevfs_ctrltransfer) (64-bit)
USBDEVFS_BULK = 0xC0185502             # _IOWR('U', 2, struct usbdevfs_bulktransfer) (64-bit)
USBDEVFS_CLAIMINTERFACE = 0x8004550F   # _IOR('U', 15, unsigned int)
USBDEVFS_RELEASEINTERFACE = 0x80045510
import ctypes

def find_device(timeout=180):
    t0 = time.time(); said = False
    while time.time() - t0 < timeout:
        for d in glob.glob("/sys/bus/usb/devices/*"):
            try:
                if open(d + "/idVendor").read().strip() == VID and open(d + "/idProduct").read().strip() == PID:
                    return d
            except OSError:
                pass
        if not said:
            print("Waiting for 1782:4d00 ... (hold Volume Up and plug in USB)"); said = True
        time.sleep(0.05)
    sys.exit("timed out waiting for the BootROM device")

def endpoints(sysdev):
    eps_in, eps_out = [], []
    for ep in glob.glob(sysdev + "/*:1.0/ep_*"):
        if open(ep + "/type").read().strip() == "Bulk":
            addr = int(open(ep + "/bEndpointAddress").read(), 16)
            (eps_in if addr & 0x80 else eps_out).append(addr)
    return eps_in[0], eps_out[0]

def control(fd, rtype, req, value, index):
    s = struct.pack("BBHHHI4xQ", rtype, req, value, index, 0, 1000, 0)
    return fcntl.ioctl(fd, USBDEVFS_CONTROL, bytearray(s))

def bulk(fd, ep, data=None, length=512, timeout=1000):
    buf = ctypes.create_string_buffer(data, len(data)) if data is not None else ctypes.create_string_buffer(length)
    s = bytearray(struct.pack("III4xQ", ep, len(buf), timeout, ctypes.addressof(buf)))
    n = fcntl.ioctl(fd, USBDEVFS_BULK, s, True)
    return n, buf.raw

def crc16(data):  # spd_crc16: CRC-16/XMODEM-style as used by the SPRD BootROM
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def unframe(raw):
    out, esc, started = bytearray(), False, False
    for b in raw:
        if b == 0x7E:
            if started and out: break
            started = True; continue
        if not started: continue
        if b == 0x7D: esc = True; continue
        out.append(b ^ 0x20 if esc else b); esc = False
    return bytes(out)

def main():
    sysdev = find_device()
    busnum = int(open(sysdev + "/busnum").read()); devnum = int(open(sysdev + "/devnum").read())
    ep_in, ep_out = endpoints(sysdev)
    path = f"/dev/bus/usb/{busnum:03d}/{devnum:03d}"
    print(f"found {path}  bulk IN {ep_in:#04x}  OUT {ep_out:#04x}")
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, struct.pack("I", 0))
        control(fd, 0x21, 34, 0x601, 0)
        bulk(fd, ep_out, b"\x7e")
        raw = b""
        for _ in range(10):
            try:
                n, data = bulk(fd, ep_in, length=512)
                raw += data[:n]
                if raw.count(b"\x7e") >= 2: break
            except OSError:
                bulk(fd, ep_out, b"\x7e")
        frame = unframe(raw)
        print("raw reply:", raw.hex(" "))
        if len(frame) < 6:
            sys.exit("no/short reply")
        typ, ln = struct.unpack(">HH", frame[:4]); payload = frame[4:4 + ln]
        chk = struct.unpack(">H", frame[4 + ln:6 + ln])[0]
        print(f"type {typ:#06x} ({'BSL_REP_VER' if typ == 0x81 else '?'}), len {ln}, "
              f"crc {'OK' if crc16(frame[:4 + ln]) == chk else 'mismatch'}")
        print("BootROM version string:", payload)
        if payload == b"SPRD3\0":
            print("=> 'SPRD3': BootROM reports NO secure boot (unsigned loaders accepted)")
        else:
            print("=> not 'SPRD3': spd_dump would treat this as SECURE BOOT")
        fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, struct.pack("I", 0))
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()

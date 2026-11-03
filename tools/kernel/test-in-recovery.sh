#!/bin/sh
# Boot a test boot image ONCE, without touching the real KERNEL partition:
# write it to RECOVERY (p21, stock recovery is in firmware/extracted/recovery.img) and
# `reboot recovery`.
# The bootloader's recovery flag is STICKY: power-cycles keep booting RECOVERY until a normal
# reboot clears it. To go back to KERNEL (TREND OS), from the test kernel over SSH:
#   python3 -c 'import ctypes,os; os.sync(); ctypes.CDLL(None).syscall(88, 0xfee1dead, 672274793, 0xa1b2c3d4, b"normal")'
# If the test kernel has no SSH: Download mode (Vol-Down+Home+Power) and
#   heimdall flash --RECOVERY firmware/extracted/recovery.img   (stock recovery is harmless to us)
#   tools/kernel/test-in-recovery.sh [image]   (default firmware/extracted/boot-kernel-test.img)
set -e
cd "$(dirname "$0")/../.."
IMG=${1:-firmware/extracted/boot-kernel-test.img}
H=root@192.168.42.129
SZ=$(stat -c %s "$IMG")
scp -q "$IMG" $H:/tmp/test.img
ssh $H "set -e
dd if=/tmp/test.img of=/dev/mmcblk0p21 bs=1M conv=fsync 2>/dev/null
[ \"\$(head -c $SZ /dev/mmcblk0p21 | sha256sum)\" = \"\$(sha256sum < /tmp/test.img)\" ] || { echo 'verify FAILED'; exit 1; }
rm /tmp/test.img; sync
echo 'written + verified; rebooting into it'
python3 -c 'import ctypes; ctypes.CDLL(None).syscall(88, 0xfee1dead, 672274793, 0xa1b2c3d4, b\"recovery\")'"

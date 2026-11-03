#!/bin/sh
# READ-ONLY test of the BootROM route to the bootloader (SBOOT). Nothing is written to the phone.
# Loads SC8830 FDL1 (iRAM 0x50000000) + FDL2 (DRAM 0x80000000) via the chip's BootROM, then reads
# SBOOT / SBOOT2 back and compares them with our backups. A match = working path in AND out.
#
#   sudo tools/bootloader/bootrom-read.sh
# Then: unplug USB, battery out + back in, HOLD VOLUME UP, plug USB in (keep holding ~3 s).
# Afterwards: unplug, battery out/in, power on normally.
set -e
# spd_dump needs tools/bootloader/spd_dump-sc8830-64byte.patch (SPD_CHUNK=64: the BootROM takes 64-byte USB packets only)
cd "$(dirname "$0")/../.."
SPD=tools/ext/spreadtrum_flash/spd_dump
F=tools/ext/fdl-sc8830
OUT=backup/bootrom-read-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
echo "== waiting for the phone in BootROM mode (Vol-Up + plug USB)..."
SPD_CHUNK=64 $SPD --verbose 1 --wait 300 \
	timeout 15000 \
	keep_charge 1 \
	fdl $F/fdl1-sign.bin 0x50000000 \
	fdl $F/fdl2-sign.bin 0x80000000 \
	partition_list "$OUT/partitions.xml" \
	read_part SBOOT 0 2M "$OUT/SBOOT.bin" \
	read_part SBOOT2 0 2M "$OUT/SBOOT2.bin" \
	power_off 2>&1 | tee "$OUT/spd_dump.log"
chown -R --reference=. "$OUT"
echo "== compare with backups"
for p in SBOOT SBOOT2; do
	n=$([ $p = SBOOT ] && echo mmcblk0p1-SBOOT || echo mmcblk0p2-SBOOT2)
	want=$(gunzip -c backup/phone-image-2026-11-03/$n.img.gz | sha256sum | cut -d' ' -f1)
	got=$(sha256sum < "$OUT/$p.bin" | cut -d' ' -f1)
	[ "$want" = "$got" ] && echo "MATCH   $p" || echo "DIFFERS $p  (got $got)"
done

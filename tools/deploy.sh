#!/bin/sh
# Deploy the TREND OS userland (shell, helpers, services) to the phone, rebuild the C renderer
# and restart the shell. Boot-image parts (ramdisk init, bootanim, charger) are NOT touched:
# rebuild those with tools/native/mkramdisk.py + tools/repack_keep_dt.py (see PLAN.md).
#   [SPOTIFY=1] tools/deploy.sh [user@host]   (default root@192.168.42.129, the USB link; SPOTIFY=1 re-enables the shelved Spotify service)
set -e
HOST=${1:-root@192.168.42.129}
cd "$(dirname "$0")/.."
O=tools/native/alpine-overlay
FILES="usr/local/bin/trendos.py usr/local/bin/mksound.py usr/local/bin/mkcharger.py
       usr/local/lib/trendos/tos usr/local/sbin etc/init.d/bootscreen etc/init.d/usbnet etc/local.d
       etc/init.d/spotify etc/init.d/wifi etc/init.d/timesync etc/init.d/btuart etc/init.d/btaudio etc/conf.d/hwclock etc/timezone
       var/lib/go-librespot/config.yml usr/local/share/trendos/fonts"
echo "== copying files to $HOST"
tar -C "$O" --owner=0 --group=0 --exclude=__pycache__ -cf - $FILES | ssh "$HOST" 'tar -C / -xf -'
ssh "$HOST" 'rm -rf /tmp/libtrend-src && mkdir /tmp/libtrend-src'
tar -C native/libtrend --exclude=libtrend.so --exclude=test_libtrend -cf - include src | ssh "$HOST" 'tar -C /tmp/libtrend-src -xf -'
# Spotify player engine (built by tools/spotify/build-go-librespot.sh, not in git): with SPOTIFY=1, copy if changed
GLR=tools/spotify/go-librespot
if [ "${SPOTIFY:-0}" = 1 ] && [ -f "$GLR" ] && [ "$(ssh "$HOST" 'md5sum < /usr/local/bin/go-librespot 2>/dev/null')" != "$(md5sum < "$GLR")" ]; then
	echo "== copying go-librespot"
	ssh "$HOST" 'rc-service spotify stop >/dev/null 2>&1; true'
	scp -q "$GLR" "$HOST:/usr/local/bin/go-librespot"
fi
echo "== building libtrend.so, restarting the shell"
ssh "$HOST" "SPOTIFY=${SPOTIFY:-0}; "'set -e
cd /tmp/libtrend-src
gcc -std=gnu11 -O3 -mcpu=cortex-a7 -mfpu=neon-vfpv4 -ftree-vectorize -Iinclude -Wall -Wextra -shared -fPIC -o /usr/local/lib/trendos/libtrend.so src/*.c src/apps/*.c -lm
cd /
rm -rf /tmp/libtrend-src /usr/local/lib/trendos/librender.so
find /usr/local/lib/trendos -name __pycache__ -type d -exec rm -rf {} +
rm -f /usr/local/bin/cube.py
rc-service bootscreen restart >/dev/null
if [ "$SPOTIFY" = 1 ] && [ -x /usr/local/bin/go-librespot ]; then
	apk info -e alsa-lib flac-libs mpg123-libs libvorbis libogg >/dev/null || apk add -q alsa-lib flac-libs mpg123-libs libvorbis libogg
	rc-update add spotify default >/dev/null 2>&1
	rc-service spotify restart >/dev/null
else
	rc-service spotify stop >/dev/null 2>&1 || true
	rc-update del spotify default >/dev/null 2>&1 || true
fi
sleep 2; rc-service bootscreen status'

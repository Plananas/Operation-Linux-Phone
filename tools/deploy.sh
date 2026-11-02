#!/bin/sh
# Deploy the TREND OS userland (shell, helpers, services) to the phone, rebuild the C renderer
# and restart the shell. Boot-image parts (ramdisk init, bootanim, charger) are NOT touched:
# rebuild those with tools/native/mkramdisk.py + tools/repack_keep_dt.py (see PLAN.md).
#   tools/deploy.sh [user@host]      (default root@192.168.42.129, the USB link)
set -e
HOST=${1:-root@192.168.42.129}
cd "$(dirname "$0")/.."
O=tools/native/alpine-overlay
FILES="usr/local/bin/trendos.py usr/local/bin/mksound.py usr/local/bin/mkcharger.py
       usr/local/lib/trendos/tos usr/local/sbin etc/init.d/bootscreen etc/init.d/usbnet etc/local.d
       etc/init.d/spotify var/lib/go-librespot/config.yml"
echo "== copying files to $HOST"
tar -C "$O" --owner=0 --group=0 --exclude=__pycache__ -cf - $FILES | ssh "$HOST" 'tar -C / -xf -'
scp -q tools/native/render.c "$HOST:/tmp/render.c"
# Spotify player engine (built by tools/spotify/build-go-librespot.sh, not in git): copy if changed
GLR=tools/spotify/go-librespot
if [ -f "$GLR" ] && [ "$(ssh "$HOST" 'md5sum < /usr/local/bin/go-librespot 2>/dev/null')" != "$(md5sum < "$GLR")" ]; then
	echo "== copying go-librespot"
	ssh "$HOST" 'rc-service spotify stop >/dev/null 2>&1; true'
	scp -q "$GLR" "$HOST:/usr/local/bin/go-librespot"
fi
echo "== building librender.so, restarting the shell"
ssh "$HOST" 'set -e
gcc -O3 -mcpu=cortex-a7 -mfpu=neon-vfpv4 -ftree-vectorize -Wall -Wextra -shared -fPIC -o /usr/local/lib/trendos/librender.so /tmp/render.c -lm
rm -f /tmp/render.c
find /usr/local/lib/trendos -name __pycache__ -type d -exec rm -rf {} +
rm -f /usr/local/bin/cube.py
rc-service bootscreen restart >/dev/null
if [ -x /usr/local/bin/go-librespot ]; then
	apk info -e alsa-lib flac-libs mpg123-libs libvorbis libogg >/dev/null || apk add -q alsa-lib flac-libs mpg123-libs libvorbis libogg
	rc-update add spotify default >/dev/null 2>&1
	rc-service spotify restart >/dev/null
fi
sleep 2; rc-service bootscreen status'

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
       usr/local/lib/trendos/tos usr/local/sbin etc/init.d/bootscreen etc/init.d/usbnet etc/local.d"
echo "== copying files to $HOST"
tar -C "$O" --owner=0 --group=0 --exclude=__pycache__ -cf - $FILES | ssh "$HOST" 'tar -C / -xf -'
scp -q tools/native/render.c "$HOST:/tmp/render.c"
echo "== building librender.so, restarting the shell"
ssh "$HOST" 'set -e
gcc -O2 -Wall -Wextra -shared -fPIC -o /usr/local/lib/trendos/librender.so /tmp/render.c -lm
rm -f /tmp/render.c
find /usr/local/lib/trendos -name __pycache__ -type d -exec rm -rf {} +
rm -f /usr/local/bin/cube.py
rc-service bootscreen restart >/dev/null
sleep 2; rc-service bootscreen status'

#!/system/bin/sh
# Start the Alpine chroot at /data/alpine. Installed on phone as /data/alpine-boot.sh.
#   alpine-boot.sh          -> mount + DNS, then exec sshd in foreground (used by init service)
#   alpine-boot.sh mount    -> mount + DNS only
#   alpine-boot.sh shell    -> mount + DNS, then root shell inside Alpine
B=/system/xbin/busybox
R=/data/alpine

mp() { $B mountpoint -q "$R/$1"; }
$B mkdir -p $R/proc $R/sys $R/dev $R/tmp
mp proc    || $B mount -t proc proc $R/proc
mp sys     || $B mount -t sysfs sysfs $R/sys
mp dev     || $B mount -o bind /dev $R/dev
mp dev/pts || $B mount -o bind /dev/pts $R/dev/pts
$B mkdir -p $R/dev/shm; mp dev/shm || $B mount -t tmpfs -o mode=1777 shm $R/dev/shm
$B chmod 1777 $R/tmp

# DNS: Android 4.4 keeps it in properties, not resolv.conf. Fallback to public resolvers.
{
  for p in net.dns1 net.dns2 dhcp.wlan0.dns1 dhcp.wlan0.dns2; do
    v=$(getprop $p); [ -n "$v" ] && echo "nameserver $v"
  done
  echo "nameserver 1.1.1.1"
  echo "nameserver 9.9.9.9"
} > $R/etc/resolv.conf

CH="$B chroot $R /usr/bin/env -i HOME=/root TERM=${TERM:-linux} PATH=/usr/sbin:/usr/bin:/sbin:/bin"
case "$1" in
  mount) exit 0 ;;
  shell) exec $CH /bin/sh -l ;;
  *)
    [ -x $R/usr/sbin/sshd ] || { echo "sshd not installed in $R"; exit 1; }
    $CH /usr/bin/ssh-keygen -A >/dev/null
    exec $CH /usr/sbin/sshd -D -e
    ;;
esac

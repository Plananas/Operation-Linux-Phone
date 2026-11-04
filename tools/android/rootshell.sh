#!/bin/sh
# Root shell on the phone via the roottelnet service in boot-root4.img (127.0.0.1:2323 on the phone).
#   tools/android/rootshell.sh              -> interactive root shell
#   tools/android/rootshell.sh 'cmd; cmd'   -> run commands as root, print only their output
if [ $# -eq 0 ]; then
  exec adb shell /system/xbin/busybox telnet 127.0.0.1 2323
fi
adb forward tcp:2323 tcp:2323 >/dev/null
S=__BEGIN_$$__; E=__END_$$__
printf 'echo %s; %s; echo %s\nexit\n' "$S" "$*" "$E" | nc 127.0.0.1 2323 2>/dev/null | tr -d '\r' |
  awk -v s="$S" -v e="$E" '$0==e {exit} f {print} $0==s {f=1}'

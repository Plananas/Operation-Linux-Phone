#!/bin/sh
# Let the phone (192.168.42.129 on the USB link) reach the internet through this laptop,
# but NOT other devices on the home LAN. NAT itself is done by the NetworkManager
# connection "phone-usb" (ipv4.method shared). Needed because Docker sets FORWARD policy DROP.
# Rules are not persistent: re-run after a laptop reboot / Docker restart.
#   sudo tools/pc-share-internet.sh        -> add rules
#   sudo tools/pc-share-internet.sh off    -> remove rules
set -e
NET=192.168.42.0/24
PRIV="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10"

CHAIN=DOCKER-USER
iptables -nL $CHAIN >/dev/null 2>&1 || CHAIN=FORWARD   # no Docker -> plain FORWARD

del() { while iptables -C $CHAIN "$@" 2>/dev/null; do iptables -D $CHAIN "$@"; done; }
rules() {  # $1 = add|del ; listed in final order (top first)
  for p in $PRIV; do
    [ "$1" = add ] && iptables -I $CHAIN $((n=n+1)) -s $NET -d $p -j DROP || del -s $NET -d $p -j DROP
  done
  if [ "$1" = add ]; then
    iptables -I $CHAIN $((n=n+1)) -s $NET -j ACCEPT
    iptables -I $CHAIN $((n=n+1)) -d $NET -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  else
    del -s $NET -j ACCEPT
    del -d $NET -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  fi
}

rules del   # always start clean (idempotent)
if [ "$1" != off ]; then
  n=0; rules add
  echo "Phone internet sharing ON (chain $CHAIN, LAN blocked)"
else
  echo "Phone internet sharing OFF"
fi
iptables -nL $CHAIN --line-numbers | head -12

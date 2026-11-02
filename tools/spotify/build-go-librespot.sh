#!/bin/sh
# Cross-compile go-librespot (the Spotify player engine behind the TREND OS Spotify app) for the
# phone: Alpine / musl / ARMv7. Runs in an x86_64 Alpine container (no qemu needed): clang
# targets ARMv7 against a sysroot made of the phone's own Alpine armv7 packages, so the binary
# links against exactly the libraries the phone installs (alsa-lib, flac-libs, mpg123-libs, ...).
#   tools/spotify/build-go-librespot.sh [version]      -> tools/spotify/go-librespot (not in git)
set -e
VER=${1:-v0.10.5}
ALPINE=3.24
cd "$(dirname "$0")"
docker run --rm --platform linux/amd64 -v "$PWD:/out" -e VER="$VER" -e ALPINE="$ALPINE" alpine:$ALPINE sh -euc '
apk add -q go clang lld git pkgconf
R=https://dl-cdn.alpinelinux.org/alpine/v$ALPINE
apk add -q --root /sysroot --arch armv7 --initdb --allow-untrusted --no-scripts \
    -X $R/main -X $R/community musl-dev gcc alsa-lib-dev flac-dev mpg123-dev libogg-dev libvorbis-dev
git clone -q --depth 1 -b "$VER" https://github.com/devgianlu/go-librespot /src
cd /src
export CGO_ENABLED=1 GOOS=linux GOARCH=arm GOARM=7 GOTOOLCHAIN=local
export CC="clang --target=armv7-alpine-linux-musleabihf --sysroot=/sysroot" CGO_LDFLAGS="-fuse-ld=lld -no-pie"
export PKG_CONFIG_SYSROOT_DIR=/sysroot PKG_CONFIG_LIBDIR=/sysroot/usr/lib/pkgconfig
go build -trimpath -ldflags "-s -w -X github.com/devgianlu/go-librespot.version=${VER#v}" \
    -o /out/go-librespot ./cmd/daemon
chown "$(stat -c %u:%g /out)" /out/go-librespot
'
file go-librespot 2>/dev/null || ls -l go-librespot

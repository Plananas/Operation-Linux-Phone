#!/bin/sh
# Build the TREND OS kernel: Samsung's SM-G318H source (3.10.17) + our patches, GCC 4.7 in Docker.
#   tools/kernel/build.sh            -> firmware/extracted/boot-kernel-test.img
# Source: github.com/TechTex198/SM-G318H-Kernel-Source, cloned to tools/ext/kernel (gitignored).
# Config = Samsung's defconfig + tools/kernel/trendos.config (Broadcom chips, see there).
# Output image = our own zImage + boot-native6's ramdisk/cmdline + the stock Spreadtrum DT.
set -e
cd "$(dirname "$0")/../.."
K=tools/ext/kernel; O=tools/ext/kout
[ -d $K ] || git clone --depth 1 https://github.com/TechTex198/SM-G318H-Kernel-Source $K
docker image inspect trendos-kbuild >/dev/null 2>&1 || docker build -t trendos-kbuild tools/kernel
# our patches (idempotent): early TREND OS boot frame instead of the Samsung logo; always 3 fb pages
cp tools/kernel/trendos_logo.h $K/drivers/video/sprdfb/trendos_logo.h
git -C $K apply --check ../../kernel/trendos-logo.patch 2>/dev/null && git -C $K apply ../../kernel/trendos-logo.patch
mkdir -p $O
cp tools/kernel/trendos.config tools/ext/trendos.config
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/tools/ext:/w" -w /w/kernel trendos-kbuild sh -c '
  cat arch/arm/configs/vivalto3mveml3g_hw00_defconfig /w/trendos.config > /w/kout/.config.new
  cmp -s /w/kout/.config.new /w/kout/.config.src || { cp /w/kout/.config.new /w/kout/.config.src
    cp /w/kout/.config.new /w/kout/.config; make -s O=/w/kout ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig; }
  make -s O=/w/kout ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j"$(nproc)" zImage'
python3 tools/repack_keep_dt.py --kernel $O/arch/arm/boot/zImage \
	firmware/extracted/boot.img firmware/extracted/boot-native6.img firmware/extracted/boot-kernel-test.img

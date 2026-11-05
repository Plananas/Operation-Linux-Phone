#!/bin/sh
# Build the TREND OS kernel: Samsung's SM-G318H source (3.10.17) + our patches, GCC 4.7 in Docker.
#   kernel/build.sh            -> firmware/trendos/boot-kernel-test.img
# Source: github.com/TechTex198/SM-G318H-Kernel-Source, cloned to tools/ext/kernel (gitignored).
# Config = Samsung's defconfig + kernel/trendos.config (Broadcom chips, see there).
# Output image = our own zImage + boot-native6's ramdisk/cmdline + the stock Spreadtrum DT.
set -e
cd "$(dirname "$0")/.."
K=tools/ext/kernel; O=tools/ext/kout
[ -d $K ] || git clone --depth 1 https://github.com/TechTex198/SM-G318H-Kernel-Source $K
docker image inspect trendos-kbuild >/dev/null 2>&1 || docker build -t trendos-kbuild kernel
# our patches (idempotent): early TREND OS boot frame instead of the Samsung logo; always 3 fb pages
cp kernel/trendos_logo.h $K/drivers/video/sprdfb/trendos_logo.h
git -C $K apply --check ../../../kernel/trendos-logo.patch 2>/dev/null && git -C $K apply ../../../kernel/trendos-logo.patch
# a core that was hot-plugged off must not be trusted to still hold a thread's NEON registers
git -C $K apply --check ../../../kernel/vfp-hotplug.patch 2>/dev/null && git -C $K apply ../../../kernel/vfp-hotplug.patch
mkdir -p $O
cp kernel/trendos.config tools/ext/trendos.config
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/tools/ext:/w" -w /w/kernel trendos-kbuild sh -c '
  cat arch/arm/configs/vivalto3mveml3g_hw00_defconfig /w/trendos.config > /w/kout/.config.new
  cmp -s /w/kout/.config.new /w/kout/.config.src || { cp /w/kout/.config.new /w/kout/.config.src
    cp /w/kout/.config.new /w/kout/.config; make -s O=/w/kout ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig; }
  make -s O=/w/kout ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j"$(nproc)" zImage'
python3 bootimg/repack_keep_dt.py --kernel $O/arch/arm/boot/zImage \
	firmware/stock/boot.img firmware/trendos/boot-native6.img firmware/trendos/boot-kernel-test.img

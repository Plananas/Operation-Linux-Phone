# Galaxy Trend 2 Lite → Linux mini-server

## Device facts (read via adb, 2026-11-01)
| Item | Value |
|---|---|
| Model / codename | SM-G318H / `vivalto3mveml3g` |
| SoC | Spreadtrum SC8830, ARMv7 (32-bit) `armhf` |
| RAM | ~465 MB |
| Free storage | /data 1.2 GB (+ microSD slot) |
| Android / kernel | 4.4.4 / Linux 3.10.17 (2016) |
| Bootloader | G318HXCU0APF1 (Samsung, flash via Download mode) |

## Reality check
- **Spreadtrum chip = almost no mainline Linux support.** A "real" Linux (postmarketOS, Ubuntu Touch) is unlikely to exist for this phone. Check first (step 1) but don't count on it.
- **Realistic route:** keep Android's kernel, root it, run **Debian in a chroot** (Linux Deploy). You get a full Debian userland (apt, ssh, python, nginx) — good enough for a mini server.
- 465 MB RAM → headless only (no desktop). Light services: SSH, Pi-hole-ish DNS, small web server, scripts, MQTT.
- Old kernel 3.10 → no Docker. Plain services only.

## Plan
1. **Research** – search postmarketOS wiki / XDA for `vivalto3mve3g`, `SM-G318H`, `SC8830`: TWRP, root, any Linux port. Record findings below.
2. **Backup** – `adb pull /sdcard` for anything you want. Note firmware version (above) and download stock firmware (for unbricking).
3. **Tools on PC** – `sudo apt install heimdall-flash adb fastboot`. (Heimdall = Linux Odin.)
4. **Root** – flash TWRP via Heimdall (Download mode: Vol-Down+Home+Power), then flash Magisk/SuperSU zip. Alt: one-click root apps for 4.4 (riskier).
5. **Linux chroot** – *(changed 2026-11-02: using **Alpine Linux** in `/data/alpine`, see log; Debian notes kept for reference)* – install Linux Deploy (+ BusyBox). Debian `armhf`, image on microSD (≥4 GB), enable SSH. Start → `ssh user@<phone-ip>`.
6. **Optimise Android** – disable/uninstall Samsung bloat (`adb shell pm disable-user <pkg>`), keep Wi-Fi on while asleep, wakelock, stay plugged in.
7. **Server setup** – pick services; set static IP / DHCP reservation on router; autostart chroot on boot.
8. **Stretch** – if step 1 finds a pmOS/native port, try it later.

## Risks
- Wrong flash = brick → always have stock firmware + Heimdall ready.
- Battery swelling if always on charger → check monthly; remove battery if phone can run on charger without it.

## Findings / log
- 2026-11-01: phone detected over adb (USB debugging on). Quick web search found no postmarketOS port.
- 2026-11-01 Step 1 (research): No native Linux port found. Root/TWRP exists (all old, 2016–18):
  - TWRP for SM-G318 series (2.7.8 → 3.2.1 / 3.1.1 `vivalto3mveml3g`): xdaforums.com/t/3331182, forum.xda-developers.com/…t3855247
  - Root guide (Kingo temp root → TWRP → SuperSU): xdaforums.com/t/3281466
  - Mega thread (ROMs): xdaforums.com/t/3627637
  - Warning: newer stock with "ASKS security" may block root → may need to downgrade stock first. Ours = APF1 (2016-06 patch).
- 2026-11-01 Step 2 (backup): phone almost empty (~10 MB). Saved to `backup/` (sdcard, packages.txt = 155 apps, getprop.txt). Not rooted. No microSD inserted.
- 2026-11-01 Step 3: Heimdall v2.0.2 installed, detects phone in Download mode (`adb reboot download`). PIT saved `backup/pit.txt`. Key partitions: `RECOVERY` (recovery.img), `KERNEL` (boot.img), `system`, `userdata`.
- Step 4 root plan: `heimdall flash --RECOVERY twrp.img --no-reboot` → pull battery/force off → boot straight to recovery (Vol-Up+Home+Power) so stock doesn't overwrite TWRP → flash **SuperSU 2.82 zip** (modern Magisk needs Android 6+; old Magisk ≤v19 works on 4.4).
- 2026-11-01 Step 4 DIY root (chosen route — no untrusted apps, no TWRP needed):
  - Firmware downloaded: `firmware/SAMFW.COM_SM-G318H_BTU_G318HXCS0APF1.zip` (UK/BTU build, ~= our APF1). Extracted AP tar → `firmware/extracted/boot.img` (5.5M), `recovery.img` (6.8M). Keep originals = unbrick restore.
  - boot.img = **standard AOSP `ANDROID!` header**, page size 2048. So abootimg can unpack/repack (Spreadtrum non-standard-header risk did NOT materialise).
  - Method: unpack boot.img → edit ramdisk `default.prop` (`ro.secure=0`, `ro.debuggable=1`, `ro.adb.secure=0`) → repack `boot-rooted.img` → flash → `adb root` = root shell → remount /system, install su.
  - **Boot partition is named `KERNEL`** (not BOOT). Flash: `heimdall flash --KERNEL boot-rooted.img`.
  - Built OK: `firmware/extracted/boot-rooted.img` (default.prop secure=0/debuggable=1/adb.secure=0 + cmdline androidboot.selinux=permissive). Original `boot.img` kept.
  - Restore anytime: `heimdall flash --KERNEL boot.img` (original) or reflash full stock tar.
  - **Attempt 1 (FAILED → restored):** flashed boot-rooted.img, phone stuck on logo ~several min. Restored original boot.img via Heimdall → booted 4.4.4 fine. No damage. Cause: ramdisk repacked as user `robin` (uid≠0); Android init needs root-owned ramdisk (AOSP mkbootfs forces uid/gid 0). Fix: repack cpio with `--owner=0:0`.
- TODO: download stock firmware G318HXCU0APF1 (or nearest) from samfw.com / sammobile.com.
  - **Attempt 2 (boot-rooted2.img, ramdisk root-owned) also FAILED:** screen showed empty-battery + "!" icon. **Real cause of both failures:** stock boot.img carries a Spreadtrum device tree (`SPRD` DT table, 215040 bytes, header `dt_size` field) after the ramdisk. abootimg drops it → kernel has no DT → no boot. (The uid fix was harmless but not the cause.)
  - **Fix:** `boot-rooted3.img` = stock header/kernel/DT byte-identical + new ramdisk + cmdline; built with a small Python repacker (not abootimg). **Never repack this phone's boot/recovery with abootimg** — use a DT-aware tool (mkbootimg `--dt`, AIK, magiskboot) or the Python method.
  - **boot-rooted3.img BOOTS** (2026-11-02). `ro.secure=0`, `ro.debuggable=1` active, but `adb root` does nothing: Samsung `user` build adbd has root support compiled out → adbd stays uid 2000. SELinux still **Enforcing** (cmdline `androidboot.selinux=permissive` ignored). So default.prop tweak alone = no root. Need an su binary (SuperSU) via TWRP or ramdisk init service.
- 2026-11-02 **ROOT ACHIEVED** (no TWRP — none findable online):
  - Found leftovers of a 2018 **Kingo Root** install: `/system/xbin/daemonsu` (`-v` = "kingo 14"), `sugote`, `supolicy`, busybox 1.27.2, `/system/etc/install-recovery.sh` starts `daemonsu --auto-daemon` as root on every boot. No `su` / Kingo app → refuses requests. Closed-source root daemon → plan to remove.
  - `firmware/extracted/boot-root4.img` = stock kernel + DT + stock cmdline; ramdisk = stock + default.prop tweaks + init.rc service `roottelnet` (busybox telnetd, root, **bound to 127.0.0.1:2323 only**). Built with `tools/repack_keep_dt.py`.
  - Verified: `uid=0(root) context=u:r:init_shell:s0`, /system remount rw + write OK. SELinux still Enforcing but not blocking.
  - Use: `tools/rootshell.sh` (interactive) or `tools/rootshell.sh 'cmd'`.
  - Caveat: any app on the phone could connect to localhost:2323 → fine for a dedicated server phone; replace with chroot sshd later.
- 2026-11-02 **Kingo disabled (kept):** `daemonsu`, `sugote`, `sugote-mksh`, `supolicy` + original `install-recovery.sh` moved to `/system/kingo-disabled/` (mode 0644, not executable). `/system/etc/install-recovery.sh` replaced with a no-op comment. Verified after reboot: no daemonsu running, root shell OK. PC copy (non-exec): `backup/kingo/`. Analysis: rebranded SuperSU fork, no URLs/network sockets; grants root to whatever app is `com.kingouser.com` → risk if that package ever gets installed.
  - Undo: remount /system rw, move files back to /system/xbin (chmod 0755), restore install-recovery.sh.orig.
- 2026-11-02 **Alpine Linux chroot** (chosen over Debian: ~6 MB vs 1–2 GB, fits internal /data, less RAM):
  - `firmware/alpine/alpine-minirootfs-3.24.3-armv7.tar.gz` (sha256 `dc1ddfaf…f0c1`, verified against dl-cdn.alpinelinux.org). Extracted as root to **`/data/alpine`** (5.8 MB).
  - Start script `tools/alpine/alpine-boot.sh` → installed on phone as **`/data/alpine-boot.sh`** (root, 0700). Mounts proc/sys/dev/devpts/shm into the chroot, writes `/etc/resolv.conf` (Android 4.4 has none). Modes: `mount`, `shell` (root shell in Alpine), default = exec `sshd -D` (for an init service).
  - Verified: chroot runs, `armv7l`, Alpine 3.24.3.
- 2026-11-02 **USB-only networking (no Wi-Fi, by choice — keep phone local to laptop for now; Wi-Fi later)**:
  - Control: adb over USB. SSH will go over `adb forward tcp:2222 tcp:22` or the USB link IP.
  - **Reverse USB tethering** (laptop shares internet to phone):
    - Phone: as root `setprop sys.usb.config rndis,adb` (must run detached: `busybox setsid sh -c "sleep 2; setprop …" &`, else killed when shell exits) → phone `rndis0`, laptop gets `enx…` interface. Phone: `ifconfig rndis0 192.168.42.129 netmask 255.255.255.0 up; ip route add default via 192.168.42.1 dev rndis0`.
    - Laptop: NetworkManager connection **`phone-usb`** (`ipv4.method shared`, 192.168.42.1/24, IPv6 off) → NAT + dnsmasq DNS on 192.168.42.1. Created without sudo. Currently bound to `ifname enxbad7f9c2ff11` (may change → TODO check after replug/reboot).
    - Docker on laptop sets iptables FORWARD policy DROP → `sudo tools/pc-share-internet.sh` adds rules to `DOCKER-USER`: phone → internet allowed, **phone → private/LAN ranges blocked**. Not persistent: re-run after laptop reboot; `off` removes.
    - Phone↔laptop ping OK, DNS via 192.168.42.1 OK. Internet waiting on the firewall script.
  - **Not persistent yet:** phone USB mode + rndis0 IP/route reset on phone reboot → TODO add to boot (init service / alpine-boot.sh).
- 2026-11-02 Firewall script run → phone has internet via laptop; verified phone **cannot** reach home router 192.168.0.1 (LAN block works).
  - Alpine packages: `openrc busybox-openrc busybox-mdev-openrc openssh e2fsprogs busybox-static` (~16 MB total).
  - SSH: key-only (laptop `~/.ssh/id_ed25519.pub` → `/root/.ssh/authorized_keys`), `/etc/ssh/sshd_config.d/10-phone.conf`: ListenAddress 192.168.42.129 + 127.0.0.1, no passwords.
  - Laptop NM `phone-usb` changed to `match.driver rndis_host` (no ifname) — the USB host MAC/interface name is random every boot.

## 🎉 2026-11-02 NATIVE LINUX BOOT WORKS — Android no longer starts
- **`firmware/extracted/boot-native1.img`** = stock kernel + stock DT + our own ramdisk (built by `tools/native/mkramdisk.py`):
  - `tools/native/ramdisk/init` (busybox sh) + static busybox (from Alpine `busybox-static`). Mounts proc/sys/tmpfs-/dev, `mdev -s`, finds `PARTNAME=userdata` (mmcblk0p26), mounts it at /mnt/data, bind-mounts `/mnt/data/alpine` and `switch_root`s into Alpine's `/sbin/init` (busybox init + OpenRC). Log: `native-init.log` in root of userdata.
  - **Rescue mode** on any failure (or if `/data/alpine/.native-disable` exists): USB RNDIS up + `telnet 192.168.42.129` (port 23) root shell.
- Alpine side: `tools/native/alpine-overlay/etc/init.d/usbnet` (RNDIS gadget via `/sys/class/android_usb`, 192.168.42.129, gw/DNS 192.168.42.1). OpenRC: sysinit devfs mdev sysfs dmesg; boot hostname bootmisc syslog procfs; default usbnet sshd local; shutdown killprocs savecache. getty lines commented out of inittab (kernel has no VT). hostname `phone`. `/etc/local.d/dmesg.start` saves `/var/log/boot-dmesg.log`.
- Result: `ssh root@192.168.42.129` → PID 1 = Alpine init, **0 Android processes, 21 MB RAM used / 419 MB free**, internet via laptop OK, battery reads + charges (97%, kernel charger driver).
- **Back to Android:** power off (hold Power ~10 s or pull battery) → Download mode (Vol-Down+Home+Power) → `heimdall flash --KERNEL firmware/extracted/boot-root4.img` (rooted Android) or `boot.img` (stock). Android's /system and /data are untouched (Alpine lives in /data/alpine).
- Every boot with native image: laptop must have `phone-usb` up (automatic) + `sudo tools/pc-share-internet.sh` (after laptop reboot) for phone internet.
- Known limits: no `adb` in native mode (use SSH/rescue telnet); only root user has network (kernel `CONFIG_ANDROID_PARANOID_NETWORK`: non-root users need gid 3003 `inet`); screen just shows boot logo (no fb terminal yet); Wi-Fi not set up.
- NEXT: screen (framebuffer `/dev/graphics/fb0` 480x800x32 + touch `/dev/input/event1`) → test drawing → LVGL controller app; Wi-Fi later.

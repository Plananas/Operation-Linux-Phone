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
5. **Debian chroot** – install Linux Deploy (+ BusyBox). Debian `armhf`, image on microSD (≥4 GB), enable SSH. Start → `ssh user@<phone-ip>`.
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

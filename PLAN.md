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

## 🛟 Emergency recovery: Spreadtrum BootROM mode (confirmed 2026-11-02, twice)
- **Recipe:** phone fully off (pull battery, refit, don't press Power) → **hold Volume Up** → plug USB into laptop → keep holding ~5 s. Screen stays **black**; laptop shows USB `1782:4d00 Spreadtrum Communications Inc.`
- This is the chip's mask-ROM loader — works even if SPL/SBOOT/everything on eMMC is broken.
- Volume Down + plug = normal charge-mode boot (not BootROM).
- Talking to it needs `spd_dump` (github.com/ilyakurdyukov/spreadtrum_flash) + SC8830 FDL1/FDL2 loaders (from any SC8830 .pac; secure boot appears fused off, so unsigned FDLs should be accepted). Status: TODO — handshake / read-only test.
- Note: `poweroff` with USB connected does NOT stay off — bootloader enters charge mode (battery screen, no Samsung logo) and our init boots TREND OS. Pull battery to really power off.

## 2026-11-02 Screen: TREND OS startup screen
- Display from Linux: `/dev/fb0` sprdfb 480x800, 32bpp, **byte order R,G,B,X** (driver reports it wrong — use PIL raw mode `RGBX`), 3 pages (virtual 480x2400). Touch `/dev/input/event1` (ist30xx, 480x800), keys event0, accelerometer event3.
- **Waking the display without Android** (Samsung 3.10 earlysuspend kernel): take wake lock (`echo alpine-keepawake > /sys/power/wake_lock`, also stops real suspend) → `echo mem > /sys/power/state` → `echo on > /sys/power/state` (late resume re-inits panel+backlight) → wait (`/sys/power/wait_for_fb_wake`) → **FBIOPAN_DISPLAY** so the controller scans out fb0 instead of the bootloader's logo copy.
  - **Never write 0 to `/sys/class/backlight/panel/brightness`** — driver then disables backlight ("mode 0") until next late resume.
- `cube.py` (`/usr/local/bin`, OpenRC service `bootscreen`, supervise-daemon respawn): numpy ASCII cube (pre-rendered RGBX tiles per face colour x shade, gathered into mmap'd fb, page flip), 30 fps cap (~26% CPU), title + stats panel (CPU %/GHz/°C, RAM, battery %/V/°C, disk, USB net rates, uptime/load/fps), refreshed 1/s. Title "TREND OS" → typewriter transition: backspace, then "Welcome, Robin" typed so it ends centred, cursor disappears after typing.
- Early boot (all in boot image ramdisk, `boot-native3.img`): init draws `logo.rgbx` (= cube.py `--boot-frame`) into all fb pages, wakes display (above), `fbpan`, then starts `bootanim` (C, `tools/native/bootanim.c`, ~0% CPU): single-axis "loading" spin from pre-rendered frames (`cube.py --boot-anim`), frame = f(CLOCK_MONOTONIC). Survives switch_root. cube.py stops it via `/dev/.bootanim.pid` and continues from the exact same pose, blending into the full tumble over 2.5 s. `/dev/.trendos-screen-on` tells `screen-on` not to re-cycle the display.
  - Timeline: Samsung logo (bootloader + kernel) → TREND OS at ~5.9 s kernel time (was ~11 s) → cube.py handover ~10 s.
- `tools/native/fbpan.c` and `bootanim.c` compiled statically on the phone (`apk add gcc musl-dev linux-headers`); binaries kept as `*.armv7-static`.
- Rebuild boot image: `python3 tools/native/mkramdisk.py tools/native/ramdisk busybox.static out.cpio.gz logo.rgbx=... bin/fbpan=... bin/bootanim=... bootanim.bin=...` then `tools/repack_keep_dt.py boot.img out.cpio.gz boot-nativeN.img`. KERNEL partition (mmcblk0p20) is writable from Linux (dd) — Heimdall only needed if the image doesn't boot.

## 2026-11-02 Boot logo investigation (Samsung logo stays — cannot be changed safely)
- Power-on logo is **embedded in the bootloader `sboot`** (two copies at 0x76214/0x7beec, 23761 B each, size field follows each JPEG). PARAM partition (`mmcblk0p16`, GNU tar of JPEGs) also has logos but they are NOT used for the power-on screen. PARAM restored to stock (`backup/PARAM-original.bin`).
- sboot is signed (VLR block, RSA-1024 over 0x180000 bytes). SPL (in `mmcblk0boot0`) loads SBOOT, ROM-verifies it, **falls back to SBOOT2** on failure, hangs if both fail.
- BootROM handshake (`tools/bootrom_hello.py`) replies **`SPRD3` = secure boot fused OFF**. Our unsigned kernels confirm sboot doesn't enforce.
- But: eMMC **power-on write protection on group 0 (first 8 MB: SBOOT, SBOOT2, …)** → writes from Linux silently dropped (`mmc writeprotect user get /dev/mmcblk0`). And **Download mode accepts but refuses to write a modified SBOOT** (tried twice, verified by hash: SBOOT unchanged). Route closed; phone unharmed.
- Backups: `backup/SBOOT-original.bin`, `backup/mmcblk0boot0-SPL-original.bin`, `backup/PARAM-original.bin`. Patch tools kept in `tools/bootlogo/` for reference.

## 2026-11-02 Sound: startup sound from Linux (no Android)
- ALSA works natively: card 0 `sprdphone`, playback `hw:0,0` (HiFi). `apk add alsa-utils` (aplay/amixer).
- Routing from Android's `/system/etc/tiny_hw.xml` (mount `/dev/mmcblk0p24` ro to read it) → `/usr/local/sbin/audio-speaker [on|off]`:
  - **`VBC Switch` must be `ap`** (Android's "arm" value = item 2 'ap'). Default/wrong item 'cp0-dsp' sends audio to the modem DSP → aplay "I/O error".
  - DACL/R vol 5 (of 7), SPKL/R vol 10 (of 15, −9 dB), `Inter PA Config` 304, `Speaker Mute` 0, `SPKL Mixer DACL/DACRSPKL Switch` 1, `Speaker Function` 1.
- Sound: `/usr/local/bin/mksound.py` (numpy synth, ~1.5–2 min on the phone) → `/usr/local/share/trendos/startup.wav` (now v4: 6.0 s, cosine fade over the last 2 s, chord/reverb decay a bit faster; previously v2: dark swell + low rush → soft saturated impact + lush A-major pad chord, long dark reverb; HPF 150 Hz for the tiny speaker; chime/impact at 2.6 s). v1 (bell arpeggio, "too ringtone-like") kept as `startup-v1-bells.wav`.
- Played by cube.py at takeover (once per boot, marker `/run/trendos-sound-played`); swell matches the 2.5 s blend into the full tumble. `bootscreen` start_pre runs `audio-speaker`.

## 2026-11-02 TREND OS shell: launcher + apps + C renderer
- `cube.py` → **`/usr/local/bin/trendos.py`** (service `bootscreen`). Launcher: each app = spinning ASCII 3D object; swipe left/right (follows finger, snaps with ease-out; >25% width or >700 px/s flick), tap object to open, Back key / Home / tap title to return. Page dots + app label.
- Touch: `/dev/input/event1` ist30xx, MT protocol B (slots, tracking id), 0–479 × 0–799 = screen px; KEY_BACK on event1, KEY_HOME/POWER on event0. Parsed raw (`struct input_event` = `llHHi`, 16 B on armv7).
- Apps: **Cube** (empty placeholder), **Calculator** (spinning 3D plus sign; keypad + live preview; safe AST evaluator: numbers, + − × ÷, brackets only; keypad pre-rendered, per-press redraw ~23 ms).
- Shapes: generic `Shape` (sampled face points grouped by face, normals, centroids, palette per face). Cube (same sampling as boot anim), octahedron, union-of-boxes (plus sign). **Perspective-correct back-face culling** (dot(normal, centre − camera) < 0) + depth buffer — culling by normal.z alone showed back faces.
- **C renderer `tools/native/render.c` → `/usr/local/lib/trendos/librender.so`** (`gcc -O2 -shared -fPIC … -lm` on the phone), loaded via ctypes; numpy path kept as fallback. `render_draw` renders + blits straight into the framebuffer page; Python erases only last frame's dirty rects per page.
  - Verified: 0.001% cells differ from numpy (depth ties), blit pixel-identical. Shape maths 1.2–1.3 ms (numpy 7–9 ms), draw 0.6–0.9 ms.
  - Shell CPU at 30 fps: **~13% of one core** (was ~26% with numpy, ~50% before the earlier optimisations). Swipe frames well under the 33 ms budget.
- **Flicker/tearing fixes:** sprdfb `FBIOPAN_DISPLAY` returns immediately (switch happens at the next refresh) → after every pan wait with `FBIO_WAITFORVSYNC` (supported, ~62 Hz); **triple buffering** (3 pages, draw into the page shown 2 flips ago); never write to the visible page (stats rows rendered off-screen, copied per page when that page is drawn).
- **CPU meter fix:** kernel hot-plugs core 1 (sprd_hotplug, touch boost) → aggregate `cpu` line in /proc/stat jumps → nonsense %. Now computed per core over cores online in both samples; stats show `NN% Nc`.
- **Sleep:** short Power press (or 2 min idle) → `echo mem > /sys/power/state` (earlysuspend: panel/backlight/touch off; wake lock keeps the phone running, SSH stays up); shell stops drawing (select() on input, ~0% CPU). Power/Home → `echo on`, wait `wait_for_fb_wake` (retry once), pan, full redraw.
- **Power menu:** hold Power ≥0.9 s → Shut down / Restart / Cancel (OpenRC `poweroff` / `reboot`).
- Debug trick: inject key events by writing `struct input_event` to `/dev/input/event0` (Power/Home/Vol; Back is on event1). Capture the visible screen: read `/dev/fb0` at the `/sys/class/graphics/fb0/pan` y-offset.

## 2026-11-02 Charger mode (power-off while plugged in)
- Bootloader adds **`androidboot.mode=charger`** to the kernel cmdline when the phone is powered on by a charger (normal boots don't have it). `/etc/local.d/dmesg.start` saves each boot's cmdline to `/var/log/boot-cmdline.log`.
- Ramdisk init: in charger mode run `/bin/charger` (C, `tools/native/charger.c`, assets `charger.bin` from `mkcharger.py`): TREND OS title, ASCII-"liquid" battery (wave, depth shading, bubbles; green/yellow/red), big %, status line (state, V, °C), "hold power to start". Double-buffered + vsync, ~2% CPU. Screen off after 15 s, short Power = on; **hold Power 1.5 s → continue into normal boot**; **charger unplugged → `poweroff -f`**.
- Current boot image: **`firmware/extracted/boot-native5.img`** (logo, fbpan, bootanim + frames from trendos.py, charger + assets).

## 2026-11-02 Code layout (refactor) + workflow
**Phone userland** (`tools/native/alpine-overlay/` mirrors the phone's filesystem):
- `/usr/local/bin/trendos.py` — entry point (service `bootscreen`); `--boot-frame FILE` / `--boot-anim FILE` export the ramdisk logo + loading-spin frames.
- `/usr/local/lib/trendos/tos/` — the shell package:
  `config` (all constants) · `fb` (pages, flip+vsync, sleep/wake) · `gfx` (cached fonts, text, blit) · `render` (tiles, shapes, rotations, C renderer + numpy fallback) · `stats` (sampling + panel) · `title` (typewriter) · `inputdev` (touch/keys) · `launcher` (carousel; entry 0 = home cube, **no app**) · `power` (menu) · `boot` (handover, sound, exports) · `apps/` (`App` base, `calculator`) · `shell` (`Shell` main loop).
- To add an app: subclass `tos.apps.App` (name, touch, key, render), add an `Entry(shape, colour, app)` in `launcher.default_entries()`.
- `/usr/local/lib/trendos/librender.so` ← `tools/native/render.c`.
**Ramdisk / boot image** (`tools/native/`): `ramdisk/init`, `bootanim.c`, `fbpan.c`, `charger.c` (+ `mkcharger.py` assets), `mkramdisk.py`. Static binaries are compiled on the phone (`gcc -static`), kept as `*.armv7-static`.
**Workflow:**
- Userland change: `tools/deploy.sh` (copies overlay files, builds librender.so, restarts the shell).
- Boot image change: build assets on the phone (`trendos.py --boot-anim/--boot-frame`, `mkcharger.py`), `mkramdisk.py … name=path …`, `repack_keep_dt.py boot.img ramdisk.gz boot-nativeN.img`, then `dd` to `mmcblk0p20` (KERNEL) from the phone + verify sha256. Current: **`boot-native6.img`**.
- UI testing without touching the phone: inject evdev events (write `struct input_event` to `/dev/input/event1` for touch MT-B / Back, `event0` for Power/Home) and capture the visible page from `/dev/fb0` at the `/sys/class/graphics/fb0/pan` offset.
**Performance (after refactor):** launcher ~11% of one core at 30 fps (stats rows only re-rendered when their content changes; fonts cached; title anim stops scanning when done). Charger: 15 fps while animating, redraw only on change otherwise (~0.1% when full; was ~10%). Refactor verified byte-identical boot assets (logo, 120 spin frames, charger assets) vs the old code.

## 2026-11-02 Power menu + calculator redesign, transitions
- **Power menu** (`tos/power.py`, `PowerMenu`): screen behind is frozen + dims to 30%, card fades/slides up, options appear staggered, title types `> power` with cursor. Cancel/Back/Home reverses it (launcher resumes the frozen pose). Shut down/Restart type `> shutting down...`, fade the whole screen to black, then run the command.
- **Calculator** look: terminal display (history of last 2 sums, `> expression` prompt + blinking cursor, dim live preview → bright `= result`), colour-coded keys (dark digits with top highlight, amber operators, red C/DEL, solid green `=`), pressed keys light up; the typed sum stays visible after `=`.
- **App open/close transition** (`tos/transition.py`, `Slide`): launcher dims while the app slides up + fades in (0.32 s); closing reverses (0.24 s). Launcher animation is frozen while not visible (saves CPU, seamless return). Taps made while an app slides open are held and replayed to the app; apps are pre-rendered ~6 s after boot so the first open is instant (~364 ms tap→fully visible = the animation).
- **C helpers** in `render.c`: `scale_bytes` (dim a frame) and `blend_rect` (fade a rect in); librender now built with `-O3 -mcpu=cortex-a7 -mfpu=neon-vfpv4` (CPU has NEON): dimming 1.5 MB 11.8 → 3.3 ms; menu animation frame ~100 → 14 ms. 3D output unchanged (same 17 depth-tie cells of 1.58 M vs numpy).
- Fixes: screens clear each page once when switching (no remnants from transitions); the shell wakes the display at startup (a restart while the screen was asleep left it unresponsive to Home).
- Test note: reading `/dev/fb0` (and panning) returns EPERM while the display is asleep — wake it first (inject Home).

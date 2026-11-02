# TREND OS — technical reference

Current-state reference, organised by topic (not a diary; history is in git). Human guide: `README.md`.

## 1. Device
SM-G318H `vivalto3mveml3g` · Spreadtrum **SC8830** (Cortex-A7 ×2, ARMv7, NEON, core 1 hot-plugged) · 465 MB RAM · eMMC (`/data` 2.2 GB) · stock Android 4.4.4 · kernel **3.10.17 Samsung** (earlysuspend) · bootloader G318HXCU0APF1 · secure boot fused **off** (BootROM says `SPRD3`).
Partitions (by PARTNAME): SBOOT p1, SBOOT2 p2, PARAM p16, **KERNEL p20** (boot image), system p24, **userdata p26**. SPL in `mmcblk0boot0`. Full PIT: `backup/pit.txt`.

## 2. Current state
- Boot image on phone: **`firmware/extracted/boot-native6.img`** (stock kernel + stock DT + our ramdisk).
- Ramdisk `init` → (charger mode? `/bin/charger`) → early logo + `bootanim` → `switch_root` into **Alpine 3.24 in `/data/alpine`** (OpenRC). Android never starts; `/system` untouched.
- OpenRC: sysinit devfs mdev sysfs dmesg · boot hostname(`trend`) bootmisc syslog procfs · default **usbnet sshd bootscreen local** · shutdown killprocs savecache.
- Shell (`bootscreen` service, supervise-daemon) = `/usr/local/bin/trendos.py` → package `/usr/local/lib/trendos/tos` + `librender.so`. Launcher ~11 % of one core at 30 fps.
- Network: USB RNDIS only. Phone 192.168.42.129, laptop 192.168.42.1 (NM connection `phone-usb`, `ipv4.method shared`, `match.driver rndis_host`). SSH key-only (`/etc/ssh/sshd_config.d/10-phone.conf`, listens on .129 + 127.0.0.1). Laptop firewall: `sudo tools/pc-share-internet.sh` (Docker sets FORWARD DROP; script allows phone→internet, blocks phone→LAN; not persistent).
- Startup sound `/usr/local/share/trendos/startup.wav` = v4 (6 s). Backups `startup-v2.wav` (7 s), `startup-v1-bells.wav`.

## 3. Hardware quirks / gotchas (read before touching)
**Boot image**
- Stock boot.img has a Spreadtrum **device tree after the ramdisk** (`dt_size` header field). abootimg drops it → no boot. Always repack with `tools/repack_keep_dt.py` (keeps kernel + DT byte-identical).
- Ramdisk cpio must be root-owned → `tools/native/mkramdisk.py` writes newc with uid/gid 0 (no sudo).
- Bootloader passes **`androidboot.mode=charger`** when powered on by a charger. `poweroff` with USB plugged → charger boot.
- KERNEL (p20) is writable from Linux (`dd`). The first 8 MB (SBOOT/SBOOT2) are **eMMC power-on write-protected**; Download mode **refuses modified SBOOT**. Power-on Samsung logo lives in SBOOT → cannot be changed.

**Display (`/dev/fb0`, sprdfb, 480×800, 3 pages)**
- Byte order **R,G,B,X** (driver reports otherwise) → PIL raw mode `RGBX`.
- `FBIOPAN_DISPLAY` returns immediately; the flip happens at the next refresh → always `FBIO_WAITFORVSYNC` after panning, triple-buffer, never write the visible page.
- Wake without Android: wake lock → `echo mem` → `echo on` > `/sys/power/state` → wait `/sys/power/wait_for_fb_wake` → pan. Until panned, the controller shows the bootloader logo copy.
- **Never write 0 to `/sys/class/backlight/panel/brightness`** (backlight then stays off until the next late resume). Use 160.
- Pan and fb **read/write return EPERM while the display is asleep**.
- If the shell restarts while asleep, the display stays off → shell calls `screen_on` at startup.

**Input**: touch `/dev/input/event1` (ist30xx, MT protocol B, slot/tracking-id, coords = screen px; also KEY_BACK 158). Keys `/dev/input/event0` (HOME 102, POWER 116, VOL). `struct input_event` = `llHHi` (16 B).

**Audio**: card `sprdphone`, PCM 0. **Card numbers change between boots** (modem virtual cards `VIRTUAL AUDIO W`, `saudiovoip`, `alli2s` register in random order) → always address it by name: `amixer -c sprdphone`, `aplay -D hw:CARD=sprdphone,DEV=0` (using card 0 sent the sound to a modem card ~1 boot in 3 → silent startup). Route with `/usr/local/sbin/audio-speaker` (from Android `tiny_hw.xml`). **`VBC Switch` must be `ap`** (`cp0-dsp` → aplay I/O error). Startup sound: `/usr/local/sbin/play-startup-sound` (re-routes, retries, logs to `/var/log/trendos-sound.log`).

**CPU stats**: core 1 hot-plugs (touch boost) → aggregate `cpu` line of /proc/stat jumps; compute per core.

**Networking**: kernel `ANDROID_PARANOID_NETWORK` → only root (or gid 3003 `inet`) may open sockets. USB host MAC/interface name is random each boot.

## 4. Code map
`tools/native/alpine-overlay/` mirrors the phone filesystem.

| Phone path | Role |
|---|---|
| `/usr/local/bin/trendos.py` | entry; `--boot-frame F` / `--boot-anim F` export ramdisk assets |
| `tos/config.py` | every constant (layout, colours, timings, keys, paths) |
| `tos/fb.py` | `Framebuffer`: pages, `show()` (pan+vsync), `screen_on/off` |
| `tos/render.py` | tile atlas, `Shape` (cube, boxes/plus), `matrix()`, `Renderer` (C via ctypes, numpy fallback; `scale`/`blend` 2D helpers) |
| `tos/shell.py` | `Shell` main loop; modes launcher/app/transition/power/halt + asleep |
| `tos/launcher.py` | carousel (`Entry`: app **or** `opens=` sub-menu; `is_home`); home = [welcome cube, Calculator, Settings]; `render_band` for slide snapshots |
| `tos/transition.py` | `Slide` app open/close animation |
| `tos/power.py` | animated `PowerMenu` |
| `tos/stats.py`, `title.py`, `inputdev.py`, `gfx.py`, `boot.py` | stats panel · typewriter title · evdev · fonts/text/blit · handover/sound/exports |
| `tos/apps/` | `App` base (`touch`, `key`, `render`) · `calculator.py` · `wifi.py` (status + scan, background threads)
| `tos/transition.py` | `Slide` open/close animation (apps + sub-menus); `live_fn`/`live_side` re-render one side each frame so a carousel keeps spinning while it slides in/out | |
| `/usr/local/lib/trendos/librender.so` | ← `tools/native/render.c` (3D raster + blit, `scale_bytes`, `blend_rect`) |
| `/etc/init.d/{bootscreen,usbnet}`, `/usr/local/sbin/{screen-on,audio-speaker}` | services / helpers |
| `/usr/local/bin/mksound.py`, `mkcharger.py` | generate startup.wav / charger.bin |

Ramdisk (`tools/native/`): `ramdisk/init` · `bootanim.c` (loading spin, frame = f(CLOCK_MONOTONIC), stopped by shell via `/dev/.bootanim.pid`) · `fbpan.c` · `charger.c` · binaries `*.armv7-static`.
New app: subclass `App`, add `Entry(shape, colour, app)` in `launcher.default_entries()`.
Rendering rules: shell redraws a region per page only when its key changes, rendering once per key and copying to the other pages (`_region_cache`); per-page dirty rects; screens clear each page once on switch (`shown["base"]`).
Perf notes: full-frame ops are **memory-bound** (~13 ms per 480×800 frame that reads 2 frames + writes 1; explicit NEON was no faster) → transitions cost ~40–60 % CPU for their 0.3 s; idle app ≈ one render per cursor blink. Measure with 100 ms `/proc/PID/stat` sampling (`utime+stime`).

## 5. Procedures
- **Userland deploy:** `tools/deploy.sh` (tar overlay → phone, build librender `-O3 -mcpu=cortex-a7 -mfpu=neon-vfpv4`, restart shell).
- **Compile static C on phone:** `gcc -static -O2 -s -Wall -Wextra -o X X.c [-lm]` (Alpine has gcc musl-dev linux-headers).
- **Boot image:** on phone `trendos.py --boot-anim bootanim.bin`, `--boot-frame logo.rgbx`, `mkcharger.py charger.bin`; copy back with `charger/fbpan/bootanim` binaries; on laptop
  `python3 tools/native/mkramdisk.py tools/native/ramdisk busybox.static rd.gz logo.rgbx=… bin/fbpan=… bin/bootanim=… bootanim.bin=… bin/charger=… charger.bin=…`
  then `python3 tools/repack_keep_dt.py firmware/extracted/boot.img rd.gz firmware/extracted/boot-nativeN.img`.
  (`busybox.static` = Alpine `busybox-static` package `/bin/busybox.static`.)
- **Flash boot image from Linux:** copy to phone, `dd of=/dev/mmcblk0p20 conv=fsync`, compare sha256 of the first N bytes, reboot. Fallback: Heimdall in Download mode `heimdall flash --KERNEL img`.
- **Rescue:** init falls back to RNDIS + `telnet 192.168.42.129` if Alpine can't start, or if `/data/alpine/.native-disable` exists.
- **UI tests without hands:** write `input_event`s to event1 (touch: SLOT 0, TRACKING_ID n, X, Y, SYN … TRACKING_ID -1) / event0 (keys); screenshot = read `/dev/fb0` at offset `pan_y*480*4` (`/sys/class/graphics/fb0/pan`). Wake first (inject Home) — fb is EPERM while asleep.
- **CPU of the shell:** read utime+stime from `/proc/PID/stat` twice, ticks/second = %.
- **Emergency (BootROM):** battery out/in, hold Vol-Up, plug USB → `1782:4d00`. `tools/bootrom_hello.py` = read-only handshake. Flashing via BootROM needs SC8830 FDL1/FDL2 (not obtained) + spd_dump.

## 5a. Settings / nested carousels
- A sub-menu is just another `Launcher` (`is_home=False`). The shell keeps the home carousel plus the current one; opening a sub-menu or app uses the `Slide` transition (snapshot behind, destination in front). Nav: tap Settings icon → Settings carousel (Wi-Fi icon) → tap → Wi-Fi app. **Back** = up one level (title-tap too); **Home** = straight to the home carousel (`go_home`).
- New shapes `make_settings` (slider bars) / `make_signal` (Wi-Fi signal bars) via `make_boxes`.
- Add a setting: add an `Entry(shape, colour, app=…, name=…)` to `settings_entries()`.
- Wi-Fi app is read-only (status + nearby list; connect a new secured net over SSH — on-screen keyboard TODO).

## 6. Dead ends (don't retry)
- TWRP for this model: not findable. Root via TWRP/SuperSU unnecessary (we own the ramdisk).
- `adb root` on stock: Samsung user-build adbd ignores `ro.secure=0`. SELinux permissive via cmdline: ignored.
- Changing the power-on Samsung logo: in signed SBOOT, write-protected + Download mode rejects. PARAM logos are unused (PARAM restored to stock).
- Mainline Linux / postmarketOS port: none for SC8830.

## 7. Backups (never delete)
`backup/SBOOT-original.bin`, `mmcblk0boot0-SPL-original.bin`, `PARAM-original.bin`, `pit.txt`, `kingo/` (2018 Kingo Root leftovers, disabled on phone in `/system/kingo-disabled/`). Stock firmware zip: `firmware/` (gitignored, re-download from samfw.com).

## 8. Next ideas
Wi-Fi (bcmdhd, firmware in `/system/etc/wifi`, wpa_supplicant) · more apps · server services · notifications (ntfy/Telegram) · SMS/calls not possible (no SIM; modem would need vendor daemons).

## 9. History (one line per milestone)
`11aec19` root via ramdisk telnet service, DT-preserving repack · `7aae2ea` native Alpine boot, USB tethering, SSH · `dec2b87` startup screen, boot animation, boot-logo investigation · `ec20b35` startup sound · `9a4d218` launcher, calculator, C renderer, sleep, power menu, charger mode · `639f59a` refactor into `tos` package · `4cfe591` animated power menu, calculator redesign, transitions, sound v4.

## 2026-11-02 Wi-Fi (Broadcom bcmdhd, native)
- `wlan0` + driver are built into the kernel; firmware in Android's `/system/etc/wifi` (`bcmdhd_sta.bin`, `nvram_net.txt`). `cfg80211`/`phy0` present → **nl80211 only** (wext unsupported).
- Bring-up: copy firmware to `/data/wifi`, set `/sys/module/dhd/parameters/{firmware_path,nvram_path}`, `ip link set wlan0 up` → firmware loads (`/usr/local/sbin/wifi-up`). No stored MAC (`.mac.info` missing) → default Broadcom MAC `00:90:4c:…` (fine).
- Connect: `wpa_supplicant -D nl80211` + `udhcpc`. **Must `iw dev wlan0 set power_save off`** or bcmdhd drops the broadcast DHCP reply (lease never arrives). Scan with `iw dev wlan0 scan`.
- Tooling: `apk add wpa_supplicant iw`. Helpers: `wifi-up`, `wifi-connect` (prompts for SSID/password, hidden; wrong password → reason 15 `4WAY_HANDSHAKE_TIMEOUT` = WRONG_KEY, reported clearly), `wifi-autostart` + OpenRC **`wifi`** service (auto-connects saved net on boot, background so boot isn't delayed).
- Credentials: `/etc/wpa_supplicant/wpa_supplicant.conf` (0600, from `wpa_passphrase`). Set up over SSH so the password never goes through the chat.
- Routing: Wi-Fi default (udhcpc) is preferred; usbnet default is metric 100 (backup). SSH over USB still works (the 192.168.42.0/24 link route stays). Phone no longer needs the laptop for internet.
- Verified: reboot → auto-connects, internet OK.

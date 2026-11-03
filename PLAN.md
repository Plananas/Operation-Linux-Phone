# TREND OS — technical reference (for Claude)

Current state, by topic. History lives in git; user guide in `README.md`.

## 1. Device
SM-G318H `vivalto3mveml3g` · Spreadtrum **SC8830** (2× Cortex-A7 ARMv7+NEON, core 1 hot-plugs) · 465 MB RAM · `/data` 2.2 GB · stock Android 4.4.4 · kernel **3.10.17 Samsung** · secure boot **off**.
Partitions: SBOOT p1, SBOOT2 p2, PARAM p16, **KERNEL p20** (boot img), system p24, **userdata p26**; SPL in `mmcblk0boot0`. PIT: `backup/pit.txt`.

## 2. Current state
- Boot image: **`firmware/extracted/boot-native8.img`** = **our own kernel with Bluetooth** (§7 Kernel) + stock DT + our ramdisk. Previous: `boot-native7.img` (our kernel, no BT), `boot-native6.img` (stock Samsung kernel). RECOVERY (p21) also holds a TREND OS test kernel (stock recovery: `firmware/extracted/recovery.img`). Ramdisk `init` → charger mode? `/bin/charger` : logo + `bootanim` → `switch_root` to **Alpine 3.24 at `/data/alpine`** (OpenRC). Android never starts.
- OpenRC default runlevel: `usbnet sshd bootscreen wifi timesync dbus btuart bluetooth btaudio local`. Shell = `bootscreen` service (supervise-daemon) → `/usr/local/bin/trendos.py` → package `/usr/local/lib/trendos/tos` + `librender.so`.
- Storage: `userdata` (p26) holds only `alpine/` (TREND OS root) + `native-init.log` (Android's files deleted 2026-11-03, ~2 GB free). Android's `system` (p24) still intact but unused (Wi-Fi fw + FM patch already copied to `/data/wifi`, `/data/bt`).
- Network: **Wi-Fi** (default route, auto-connects) + **USB RNDIS** (phone 192.168.42.129, laptop .1, NM conn `phone-usb`, metric 100 backup). SSH key-only, root.
- Apps: home carousel = welcome cube, Calculator, Radio, Clock, Settings → [Wi-Fi, Bluetooth]. Spotify shelved (§7).
- Time: timezone Europe/London (`tzdata`, `/etc/localtime`). OpenRC **`timesync`** = busybox ntpd as root (Alpine's `ntpd` service can't work: it relies on ambient capabilities, not in 3.10); `-S ntp-synced` writes `/tmp/ntp-last-sync`; RTC saved at shutdown (`conf.d/hwclock` clock_systohc).

## 3. Gotchas (read before touching)
**Boot image**: `reboot recovery` boots RECOVERY (p21) and that flag is **sticky** across power-cycles until a normal reboot (`syscall(88,…,"normal")`, see `tools/kernel/test-in-recovery.sh`); `reboot download` = Download mode without buttons. Stock boot.img has a Spreadtrum DT *after* the ramdisk (`dt_size`); abootimg drops it → no boot. Always repack with `tools/repack_keep_dt.py`. Ramdisk cpio must be root-owned → `tools/native/mkramdisk.py`. Bootloader passes `androidboot.mode=charger` when powered on by a charger (`poweroff` with USB in → charger boot). First 8 MB (SBOOT/SBOOT2) write-protected; Samsung power-on logo can't change.
**Display** `/dev/fb0` 480×800, 3 pages, byte order **RGBX**. Pan returns immediately → always `FBIO_WAITFORVSYNC`, triple-buffer, never write the visible page. **Never write 0 to backlight** (use 160). Pan/read/write = EPERM while asleep. Wake: wake lock → `mem` → `on` > `/sys/power/state` → wait `/sys/power/wait_for_fb_wake` → pan.
**Input**: touch `/dev/input/event1` (MT protocol B, screen px; KEY_BACK 158). Keys `event0` (HOME 102, POWER 116, VOL). `input_event` = `llHHi`.
**Audio**: card numbers change per boot → always by name: `amixer -c sprdphone`, `aplay -D hw:CARD=sprdphone,DEV=0`. Route with `/usr/local/sbin/audio-speaker`; `VBC Switch` must be `ap`.
**CPU**: compute /proc/stat per core (core 1 hot-plugs). **Sockets**: `ANDROID_PARANOID_NETWORK` → only root/gid 3003 may open sockets.
**Wi-Fi** (bcmdhd built in, nl80211 only): `/usr/local/sbin/wifi-up` loads fw from `/data/wifi`; **must `iw dev wlan0 set power_save off`** or DHCP never completes. `wifi-connect` (SSH, prompts), OpenRC `wifi` service autoconnects; creds `/etc/wpa_supplicant/wpa_supplicant.conf`.
**Font**: VT323 has **no arrows/geometric glyphs (↓↑○●▶✓)** — use ASCII or draw shapes. `gfx.font(size)` takes DejaVu-equivalent px. 3D ASCII atlas uses DejaVu (`gfx.art_font`).
**Perf**: idle shell ~11 % of one core. The A7 is in-order and its prefetcher is weak: hot full-frame loops need NEON *unrolled ×4* + `__builtin_prefetch` (transition `slide_frame`: plain C 10.5 ms → 4.5 ms/frame; NEON without unrolling barely helps, and a benchmark with constant args inlined lies). Plain copy of a frame ≈ 2.7–5 ms. Avoid per-frame full-frame copies in Python. Measure via `utime+stime` from `/proc/PID/stat`.

## 4. Code map
`tools/native/alpine-overlay/` mirrors the phone filesystem. Package root `usr/local/lib/trendos/tos/`:

| File | Role |
|---|---|
| `config.py` | all constants: `W=480 H=800 TOP=66 APP_H`, `PALETTE` + colour indices (`RED GREEN … CYAN ORANGE WHITE`), `ACCENT`, `SHADES`, timings |
| `shell.py` | main loop; modes launcher/app/transition/power/halt/asleep; region cache per page keyed by `app.key()` |
| `launcher.py` | `Entry(model, app=None, opens=None, name=None, phase=…)`; `default_entries()`, `settings_entries()` |
| `apps/` | `base.App`, `calculator.py`, `wifi.py` (threads + keyboard example), `radio.py` (hardware worker thread, live 30 fps numpy drawing), `clock.py` (7-segment glow digits, alarms via `background()`), `spotify.py` (shelved) |
| `render.py` 3D for apps | `self.renderer.view(buf, shape, m9, K, cols, rows, x, y, tiles)` draws a Shape into any cell viewport (K ≈ cols×1.5 fills it); `card_tiles(y, PANEL, SCAN, card_y0)` = ASCII tiles on a card's background; `MINI` 5×7 tiles; `matrix(tilt, a, b, c)` pose. Shapes: `Shape.combine`, `.transformed(R, t)`; for moving parts update `shape.pts/fnrm/fcen` in place (see `Clock3D`). Palette adds `DIMGREEN`. Shell draws each app's launcher icon as a spinning badge in its title bar (`App.icon_shape`, set by `Entry`); `tos/flight.py` flies it between the carousel and the badge on every app open/close (cell-size ladder 8×12→5×7, object cut out of the launcher snapshot, badge left out of the sliding app frame) — automatic for any app opened from a carousel. |
| `ui.py` | shared look: palette (`PANEL MID DIM GHOST FLARE ERR…`), `card()`, `key_image()`, `Keys` (key rows + hit test) — use it for new apps |
| `fm.py` | FM radio driver (`FM().on/tune/rssi/off`, `set_volume`); CLI `/usr/local/sbin/fmctl` |
| `btchip.py` | the BCM43430A1 BT/FM chip: rfkill power, patch, 3 Mbaud, BD address; `RawUart` (no BlueZ) or `HciSocket` (via hci0) — FM uses whichever applies |
| `bluetooth.py` / `audio.py` | `BtCtl`: long-lived `bluetoothctl` as pairing agent + parsed device list; `audio.bt_sink()` = connected A2DP device, `bt_device(mac)` = ALSA name |
| `models/` | 3D icons: `shape.py` (`Shape`, `boxes`, `extrude`, `arc`, `relief`), `icons.py` (`@model(name, colour)`), `registry.py` |
| `keyboard.py` | on-screen keyboard (`Keyboard(on_done, on_cancel, text)`, `.touch/.key/.render`, `KB_Y`) |
| `gfx.py` | `font`, `text_strip`, `canvas`, `to_rgbx`, `blit`; glyph cache `draw_text(im,x,y,s,size,col)` / `text_len` (use for big or often-redrawn text) |
| `fb.py` `render.py` `transition.py` `power.py` `stats.py` `title.py` `inputdev.py` `boot.py` | framebuffer · C renderer wrapper · Slide anim · power menu · stats panel · typewriter title · evdev · boot handover/sound |

Other: `tools/native/render.c` → `librender.so` (built on phone by deploy) · `/etc/init.d/{bootscreen,usbnet,wifi}` · `/usr/local/sbin/*` helpers · ramdisk sources in `tools/native/` (`ramdisk/init`, `bootanim.c`, `fbpan.c`, `charger.c`, `*.armv7-static`).

## 5. Adding an app (recipe)
1. **App** — `tos/apps/myapp.py`:
   ```python
   from PIL import Image, ImageDraw
   from ..config import W, APP_H, ACCENT
   from ..gfx import font, to_rgbx
   from .base import App
   class MyApp(App):
       name = "My App"                       # title bar + launcher label
       def on_open(self): ...                # optional: start hardware/threads (on_close stops them)
       def on_key(self, code, pressed): ...  # optional: volume keys 114/115; return True if used
       def background(self, now): ...        # optional: ~1/s even when closed/asleep; True = shell wakes the screen + brings app to front
       keep_awake = False                    # optional: True = no auto screen-off while open
       def touch(self, ev, x, y): ...        # ev "down"/"move"/"up", screen coords (y >= TOP)
       def key(self, now): return self.state # hashable; render() only runs when it changes
       def render(self, now):                # -> numpy RGBX array (APP_H, W, 4)
           im = Image.new("RGB", (W, APP_H)); d = ImageDraw.Draw(im)
           d.text((20, 20), "hello", font=font(28), fill=ACCENT); return to_rgbx(im)
   ```
   Rules: keep `key()` cheap and stable when idle (that's what keeps CPU low); include time buckets (`int(now*30)`) only when animating. `render()` may run before `on_open` (launcher pre-renders apps). For animation: keep one persistent buffer, redraw only changed regions, and use whole-array numpy (uint32 views + lookup tables); per-pixel Python/PIL per frame is far too slow (each full app-area copy alone is ~5 ms). Measure on the phone before deploying. Slow work (subprocess, network) → daemon thread that updates state and bumps a version in `key()` (see `wifi.py`). Text input → `Keyboard` (see `wifi.py` connect mode). Back/Home/title-tap close the app automatically. Style: black bg, green-phosphor `ACCENT`, VT323, ASCII only — build screens from `tos/ui.py` (`card`, `Keys`). Add a 3D touch where it fits (house style: ASCII-shaded 3D): draw the 2D layer only when it changes, keep a copy, and each frame restore the 3D viewport from it and `self.renderer.view(...)` into it (wifi.py `_draw_bars`, clock.py `_draw_3d`); include `int(now*15)` in `key()`. A once-a-second full PIL redraw (~45 ms) is fine; for 20–30 fps follow radio.py.
2. **Export** in `tos/apps/__init__.py`.
3. **Icon** — in `tos/models/icons.py` add `@model("myicon", COLOUR)` returning a Shape from `boxes([...], colour_by_axis=(…))` (blocky), `extrude(inside_fn, outlines, depth, colour)` (2D silhouette) or `relief(colour_at, depth)`. Fit within ~[-1.3, 1.3] x/y, flat front. Preview: `ssh phone 'cd /usr/local/lib/trendos && python3 -m tos.models myicon'`.
4. **Launcher** — `Entry("myicon", MyApp(), phase=(a, b, c))` in `default_entries()` (or `settings_entries()` for a setting; a sub-menu is `Entry(..., opens="name")`).
5. **Deploy** `tools/deploy.sh`, then check: `ssh root@192.168.42.129 rc-service bootscreen status`; logs via `logread`/supervise output. Screenshot + tap without hands: §6.
New OpenRC service: add `etc/init.d/X` to the overlay **and** to `FILES` in `tools/deploy.sh` (note: `etc/init.d/wifi` is currently *not* in `FILES` — it was installed by hand), then `rc-update add X default` on the phone.

## 6. Procedures
- **Deploy userland**: `tools/deploy.sh [user@host]` (tar overlay → phone, build librender, restart shell). `SPOTIFY=1` re-enables Spotify.
- **Static C on phone**: `gcc -static -O2 -s -o X X.c [-lm]`.
- **Boot image**: on phone `trendos.py --boot-anim bootanim.bin`, `--boot-frame logo.rgbx`, `mkcharger.py charger.bin`; copy back; then on laptop
  `python3 tools/native/mkramdisk.py tools/native/ramdisk busybox.static rd.gz logo.rgbx=… bin/fbpan=… bin/bootanim=… bootanim.bin=… bin/charger=… charger.bin=…` →
  `python3 tools/repack_keep_dt.py firmware/extracted/boot.img rd.gz firmware/extracted/boot-nativeN.img`. Flash: `dd of=/dev/mmcblk0p20 conv=fsync` on phone, verify sha256, reboot (fallback `heimdall flash --KERNEL img` in Download mode).
- **Rescue**: init falls back to RNDIS + `telnet 192.168.42.129` if Alpine fails or `/data/alpine/.native-disable` exists. BootROM: battery out, hold Vol-Up, plug USB → `1782:4d00` (`tools/bootrom_hello.py`; flashing needs FDL1/FDL2, not obtained).
- **UI tests**: inject `input_event`s into event1 (SLOT 0, TRACKING_ID n, X, Y, SYN … TRACKING_ID -1) / event0 (keys). Screenshot = read `/dev/fb0` at `pan_y*480*4` (`/sys/class/graphics/fb0/pan`), as RGBX. Wake first (inject Home).

## 7. Subsystems
**FM radio** (works, analog): FM core inside BCM43430A1 BT combo, driven by vendor HCI `0xFC15 [reg, 0=w|1=r, data…]` over `/dev/ttyS0` 115200 RTS/CTS. Driver `tos/fm.py`, CLI `fmctl on [MHz] | tune MHz | off`; patch `/data/bt/BCM43430A1.hcd` (auto-copied from /system). Headphones = antenna. Radio app: opening powers on (~4 s), closing powers off; dial/keys tune; vol keys = codec HP volume 0–15; visualiser = `arecord` of the codec line-in (`hw:CARD=sprdphone,DEV=0`, 16 kHz mono works while the analog path plays); state in `/var/lib/trendos/radio.json`. CPU ~35 % of a core live (20 fps), ~60 % while dragging.
- UART EIO until `rfkill0` toggled 0→1. Bring-up: reset → `0xFC2E` → send .hcd → reset → **`0xFC27` (12 zeros) sleep off** (else `close()` hangs, port wedged till reboot). Always `tcflush` before close.
- Regs: 0x00 power (1 FM, 3 +RDS) · 0x01 ctrl (0x04 stereo) · 0x05 audio (0x1c = DAC L+R; 0x02 mute) · 0x09 tune mode (1 preset, 2 seek) · 0x0a/0b freq = kHz−64000 LE · 0x0f RSSI · 0x12 flags · 0xf8 volume. Codec line-in path in `codec_on()`.
- **DON'T use digital FM** (`hw:sprdphone,4` / EXTDIGFM) — reboots the phone. Open: RSSI reads a flat ~170–185 across the whole band (no station found yet; antenna/headphones or RSSI meaning unverified) → no auto-seek yet; RDS (0x80); chip volume 0xf8.

**Kernel** (ours since 2026-11-03): Samsung source github.com/TechTex198/SM-G318H-Kernel-Source (3.10.17) in `tools/ext/kernel`, `tools/kernel/build.sh` (GCC 4.7.3, Docker) → `firmware/extracted/boot-kernel-test.img`. Config = `vivalto3mveml3g_hw00_defconfig` + `tools/kernel/trendos.config` (public defconfig is the Spreadtrum-Marlin board variant; ours has Broadcom: BCM4343 dhd, BCM BT rfkill/LPM, GPS BCM47520, zswap/vnswap; matched to stock `/proc/kallsyms`, remaining diffs = Samsung security hooks, MUIC debug UART, MAC-from-file). Patch `tools/kernel/trendos-logo.patch`: sprdfb paints the boot frame (`tools/kernel/bootframe.rgbx` ← `tools/bootlogo/sboot_logo.jpg`, via `mklogo_h.py`) into the bootloader's buffer at ~0.44 s → Samsung logo only ~1 s; always 3 fb pages (stock uses 2 in recovery mode). Test new builds with `tools/kernel/test-in-recovery.sh`, install by `dd` to p20 + normal reboot.

**Bootloader (SBOOT logo) via BootROM** — paused, plan: own FDL1. BootROM (Vol-Up + USB) = `SPRD3`, runs any FDL1 at 0x50000000; spd_dump needs `tools/bootloader/spd_dump-sc8830-64byte.patch` (`SPD_CHUNK=64`: high-speed device, 64-byte bulk maxpacket). Public SC8830 FDL1 (zeallar/w_sprd_fdls, TD860 phone) hangs after exec (DDR init). Own SPL has the right DDR init but no USB. Read-only test: `tools/bootloader/bootrom-read.sh`.

**Bluetooth** (needs our kernel with BT, `trendos.config`): OpenRC `btuart` (`bt-up`: `btchip.boot_raw(3000000, efs address)` then `btattach -B /dev/ttyS0 -P h4 -S 3000000` → hci0), `bluetooth` (BlueZ 5.86 bluetoothd), `btaudio` (bluealsa, A2DP source+sink), `dbus`. Address `D0:87:E2:DB:B7:94` from efs `bluetooth/bt_addr` (copied to `/data/bt/bt_addr`; chip default is 43:43:A1:…). UART at 3 Mbaud works (needed for A2DP). Quirks: Alpine's `bluealsa` service segfaults — bluealsa reads past the stack top where env strings live, so OpenRC's tiny environment crashes it; `btaudio` passes an 8 KB `STACK_PAD` env var. bluealsa's storage dir is `/usr/var/lib/bluealsa`. Bluetooth app: Settings → Bluetooth (on/off, scan 20 s, pair = pair+trust+connect, connect/disconnect, forget). Radio streams to a connected A2DP device (line-in 44.1 kHz stereo → `aplay -D bluealsa:…`), wired headphones muted (still the antenna).

**Spotify** (shelved): go-librespot works for browsing/login, but every track fails `aes key code 1` (Spotify refuses librespot clients; workaround = DRM circumvention, not doing it). Code kept (`apps/spotify.py`, `etc/init.d/spotify`, `tools/spotify/`). Revive: import in `apps/__init__.py`, re-add Entry, `SPOTIFY=1 tools/deploy.sh`.

## 8. Dead ends (don't retry)
TWRP for this model · `adb root` on stock · SELinux permissive via cmdline · changing Samsung power-on logo from Linux/Download mode (WP + signed SBOOT; BootROM route paused, §7) · mainline/postmarketOS (no SC8830 port) · digital FM path · spotifyd/librespot playback.

## 9. Backups (never delete)
`backup/` (SBOOT, SPL, PARAM originals, `pit.txt`, `kingo/`). **Full phone image** `backup/phone-image-2026-11-03/` (gitignored: all partitions except userdata + Android's userdata files; restore steps in its README). Never wipe efs/prodnv/*nv/PARAM/MODEM/bootloaders on the phone. Stock firmware in `firmware/` (gitignored; samfw.com).

## 10. Next ideas
Radio: seek + RDS once a real station is confirmed · Clock: timer/stopwatch · Settings: Display/Sound/About · music player · file transfer page · Bluetooth · more apps (system monitor, notes, smart-home controller) · server services (web, DNS ad-block, MQTT) · notifications (ntfy). No SMS/calls (no SIM).

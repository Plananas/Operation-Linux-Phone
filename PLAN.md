# TREND OS — technical reference (for Claude)

Current state, by topic. History lives in git; user guide in `README.md`.

## 1. Device
SM-G318H `vivalto3mveml3g` · Spreadtrum **SC8830** (2× Cortex-A7 ARMv7+NEON, core 1 hot-plugs) · 465 MB RAM · `/data` 2.2 GB · stock Android 4.4.4 · kernel **3.10.17 Samsung** · secure boot **off**.
Partitions: SBOOT p1, SBOOT2 p2, PARAM p16, **KERNEL p20** (boot img), system p24, **userdata p26**; SPL in `mmcblk0boot0`. PIT: `backup/pit.txt`.

## 2. Current state
- Boot image: **`firmware/extracted/boot-native6.img`** (stock kernel + DT, our ramdisk). Ramdisk `init` → charger mode? `/bin/charger` : logo + `bootanim` → `switch_root` to **Alpine 3.24 at `/data/alpine`** (OpenRC). Android never starts.
- OpenRC default runlevel: `usbnet sshd bootscreen wifi local`. Shell = `bootscreen` service (supervise-daemon) → `/usr/local/bin/trendos.py` → package `/usr/local/lib/trendos/tos` + `librender.so`.
- Network: **Wi-Fi** (default route, auto-connects) + **USB RNDIS** (phone 192.168.42.129, laptop .1, NM conn `phone-usb`, metric 100 backup). SSH key-only, root.
- Apps: home carousel = welcome cube, Calculator, Radio (icon only, app not written yet), Settings → [Wi-Fi]. Spotify shelved (§7).

## 3. Gotchas (read before touching)
**Boot image**: stock boot.img has a Spreadtrum DT *after* the ramdisk (`dt_size`); abootimg drops it → no boot. Always repack with `tools/repack_keep_dt.py`. Ramdisk cpio must be root-owned → `tools/native/mkramdisk.py`. Bootloader passes `androidboot.mode=charger` when powered on by a charger (`poweroff` with USB in → charger boot). First 8 MB (SBOOT/SBOOT2) write-protected; Samsung power-on logo can't change.
**Display** `/dev/fb0` 480×800, 3 pages, byte order **RGBX**. Pan returns immediately → always `FBIO_WAITFORVSYNC`, triple-buffer, never write the visible page. **Never write 0 to backlight** (use 160). Pan/read/write = EPERM while asleep. Wake: wake lock → `mem` → `on` > `/sys/power/state` → wait `/sys/power/wait_for_fb_wake` → pan.
**Input**: touch `/dev/input/event1` (MT protocol B, screen px; KEY_BACK 158). Keys `event0` (HOME 102, POWER 116, VOL). `input_event` = `llHHi`.
**Audio**: card numbers change per boot → always by name: `amixer -c sprdphone`, `aplay -D hw:CARD=sprdphone,DEV=0`. Route with `/usr/local/sbin/audio-speaker`; `VBC Switch` must be `ap`.
**CPU**: compute /proc/stat per core (core 1 hot-plugs). **Sockets**: `ANDROID_PARANOID_NETWORK` → only root/gid 3003 may open sockets.
**Wi-Fi** (bcmdhd built in, nl80211 only): `/usr/local/sbin/wifi-up` loads fw from `/data/wifi`; **must `iw dev wlan0 set power_save off`** or DHCP never completes. `wifi-connect` (SSH, prompts), OpenRC `wifi` service autoconnects; creds `/etc/wpa_supplicant/wpa_supplicant.conf`.
**Font**: VT323 has **no arrows/geometric glyphs (↓↑○●▶✓)** — use ASCII or draw shapes. `gfx.font(size)` takes DejaVu-equivalent px. 3D ASCII atlas uses DejaVu (`gfx.art_font`).
**Perf**: full-frame ops memory-bound (~13 ms/frame); idle shell ~11 % of one core. Measure via `utime+stime` from `/proc/PID/stat`.

## 4. Code map
`tools/native/alpine-overlay/` mirrors the phone filesystem. Package root `usr/local/lib/trendos/tos/`:

| File | Role |
|---|---|
| `config.py` | all constants: `W=480 H=800 TOP=66 APP_H`, `PALETTE` + colour indices (`RED GREEN … CYAN ORANGE WHITE`), `ACCENT`, `SHADES`, timings |
| `shell.py` | main loop; modes launcher/app/transition/power/halt/asleep; region cache per page keyed by `app.key()` |
| `launcher.py` | `Entry(model, app=None, opens=None, name=None, phase=…)`; `default_entries()`, `settings_entries()` |
| `apps/` | `base.App`, `calculator.py`, `wifi.py` (threads + keyboard example), `spotify.py` (shelved) |
| `models/` | 3D icons: `shape.py` (`Shape`, `boxes`, `extrude`, `arc`, `relief`), `icons.py` (`@model(name, colour)`), `registry.py` |
| `keyboard.py` | on-screen keyboard (`Keyboard(on_done, on_cancel, text)`, `.touch/.key/.render`, `KB_Y`) |
| `gfx.py` | `font`, `text_strip`, `canvas`, `to_rgbx`, `blit` |
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
       def touch(self, ev, x, y): ...        # ev "down"/"move"/"up", screen coords (y >= TOP)
       def key(self, now): return self.state # hashable; render() only runs when it changes
       def render(self, now):                # -> numpy RGBX array (APP_H, W, 4)
           im = Image.new("RGB", (W, APP_H)); d = ImageDraw.Draw(im)
           d.text((20, 20), "hello", font=font(28), fill=ACCENT); return to_rgbx(im)
   ```
   Rules: keep `key()` cheap and stable when idle (that's what keeps CPU low); include time buckets in it only when animating. Slow work (subprocess, network) → daemon thread that updates state and bumps a version in `key()` (see `wifi.py`). Text input → `Keyboard` (see `wifi.py` connect mode). Back/Home/title-tap close the app automatically. Style: black bg, green-phosphor `ACCENT`, VT323, ASCII only.
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
**FM radio** (works, analog; app not written): FM core inside BCM43430A1 BT combo, driven by vendor HCI `0xFC15 [reg, 0=w|1=r, data…]` over `/dev/ttyS0` 115200 RTS/CTS. Script `tools/fm/fmctl.py on [MHz] | tune MHz | off` (phone: `/root/bt/fmctl.py` + `BCM43430A1.hcd`). Headphones = antenna.
- UART EIO until `rfkill0` toggled 0→1. Bring-up: reset → `0xFC2E` → send .hcd → reset → **`0xFC27` (12 zeros) sleep off** (else `close()` hangs, port wedged till reboot). Always `tcflush` before close.
- Regs: 0x00 power (1 FM, 3 +RDS) · 0x01 ctrl (0x04 stereo) · 0x05 audio (0x1c = DAC L+R; 0x02 mute) · 0x09 tune mode (1 preset, 2 seek) · 0x0a/0b freq = kHz−64000 LE · 0x0f RSSI · 0x12 flags · 0xf8 volume. Codec line-in path in `codec_on()`.
- **DON'T use digital FM** (`hw:sprdphone,4` / EXTDIGFM) — reboots the phone. Open: station check, RDS (0x80), seek, volume semantics.

**Spotify** (shelved): go-librespot works for browsing/login, but every track fails `aes key code 1` (Spotify refuses librespot clients; workaround = DRM circumvention, not doing it). Code kept (`apps/spotify.py`, `etc/init.d/spotify`, `tools/spotify/`). Revive: import in `apps/__init__.py`, re-add Entry, `SPOTIFY=1 tools/deploy.sh`.

## 8. Dead ends (don't retry)
TWRP for this model · `adb root` on stock · SELinux permissive via cmdline · changing Samsung power-on logo (signed SBOOT) · mainline/postmarketOS (no SC8830 port) · digital FM path · spotifyd/librespot playback.

## 9. Backups (never delete)
`backup/` (SBOOT, SPL, PARAM originals, `pit.txt`, `kingo/`). Stock firmware in `firmware/` (gitignored; samfw.com).

## 10. Next ideas
Radio app (via `fmctl.py`) · more apps (system monitor, notes, smart-home controller) · server services (web, DNS ad-block, MQTT) · notifications (ntfy). No SMS/calls (no SIM).

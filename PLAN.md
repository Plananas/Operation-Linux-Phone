# TREND OS: technical reference (for Claude)

Current state only. History is in git; user guide in `README.md`.

## 1. Device and state
SM-G318H `vivalto3mveml3g` · Spreadtrum SC8830 (2x Cortex-A7, NEON, core 1 hot-plugs) · 454 MB RAM · `/data` 2.2 GB · kernel 3.10.17 · secure boot off.
Partitions: SBOOT p1, SBOOT2 p2, PARAM p16, KERNEL p20, RECOVERY p21, system p24, userdata p26; SPL in `mmcblk0boot0`. PIT: `backup/pit.txt`.

- Boot image: `firmware/trendos/boot-native9.img` = our kernel with BT and the NEON fix + stock DT + our ramdisk (`native8`: without the fix; `native7`: no BT; `native6`: Samsung kernel). RECOVERY holds a test kernel (stock: `firmware/stock/recovery.img`). Ramdisk `init`: charger mode → `/bin/charger`; else logo + `bootanim` → `switch_root` to Alpine 3.24 at `/data/alpine`.
- OpenRC default: `usbnet sshd bootscreen wifi timesync dbus btuart bluetooth btaudio local`. Shell = `bootscreen` (supervise-daemon) → `/usr/local/bin/trendos.py` → `tos` package + `libtrend.so`.
- Storage: userdata holds `alpine/` + `native-init.log`. Android's `system` is intact but unused (Wi-Fi firmware and FM patch copied to `/data/wifi`, `/data/bt`).
- Network: Wi-Fi (default route) + USB RNDIS (phone 192.168.42.129, laptop .1, NM conn `phone-usb`). SSH key-only, root.
- Carousel: cube, Web, Calculator, Radio, Music, Clock, Files, Utilities → [Wi-Fi, Bluetooth, SSH].
- Time: Europe/London. `timesync` = busybox ntpd as root (Alpine's `ntpd` needs ambient capabilities, not in 3.10); `-S ntp-synced` writes `/tmp/ntp-last-sync`; RTC saved at shutdown.

## 2. Gotchas
- **Charger-mode boot**: on the one logged boot with `androidboot.mode=charger`, Wi-Fi (`wl_android_wifi_on failed (-35)`), BT and FM stayed down; a normal `reboot` fixed them. Cause unknown.
- **Boot image**: `reboot recovery` is sticky across power-cycles until a normal reboot (`syscall(88,…,"normal")`, see `kernel/test-in-recovery.sh`). `reboot download` = Download mode. Stock boot.img has a Spreadtrum DT after the ramdisk (`dt_size`) and abootimg drops it → no boot: always use `bootimg/repack_keep_dt.py`. Ramdisk cpio must be root-owned: `bootimg/mkramdisk.py`. `poweroff` with USB in → charger boot. First 8 MB write-protected.
- **Display**: `/dev/fb0` 480x800, 3 pages, RGBX. Pan returns immediately: always `FBIO_WAITFORVSYNC`, triple-buffer, never write the visible page. **Never write 0 to backlight** (use 160). Pan/read/write = EPERM asleep. Wake: wake lock → `mem` → `on` > `/sys/power/state` → wait `/sys/power/wait_for_fb_wake` → pan.
- **Input**: touch `event1` (MT protocol B, screen px; KEY_BACK 158). Kernel drops repeated values per slot, so injected gestures must vary X and Y (`drive.py` does). Keys `event0` (HOME 102, POWER 116, VOL 114/115). `input_event` = `llHHi`.
- **Audio**: card numbers change per boot, so use names: `amixer -c sprdphone`, `aplay -D hw:CARD=sprdphone,DEV=0`. Route with `audio-speaker`; `VBC Switch` must be `ap`. Device is exclusive: anything that plays must call `audio.take_output()` first.
- **CPU**: compute /proc/stat per core. **Sockets**: `ANDROID_PARANOID_NETWORK`: only root/gid 3003 may open them.
- **SSH**: `sshd_config.d/10-phone.conf` listens on USB and 127.0.0.1 only. No `/proc/PID/io` or `ss`, so the SSH app uses sshd CPU time + pts timestamps.
- **Wi-Fi**: `wifi-up` loads firmware from `/data/wifi`; **must `iw dev wlan0 set power_save off`** or DHCP never completes. Creds in `/etc/wpa_supplicant/wpa_supplicant.conf`.
- **Font**: VT323 has no arrows or geometric glyphs: use ASCII or draw shapes. 3D atlas uses DejaVu (`gfx.art_font`).
- **Perf**: home ~10 % of a core. `to_rgbx` ~14 ms per frame, mostly PIL: use `canvas`. Not yet moved to canvas: Clock, Wi-Fi, Bluetooth, SSH, power menu. Open: a shell that had been through several apps used 24.9 % with Calculator idle vs 8.1 % fresh (not traced; Radio alone isn't it). A7 is in-order with a weak prefetcher: hot full-frame loops need NEON unrolled x4 + `__builtin_prefetch`; benchmarks with constant args inline and lie. Frame copy 2.7-5 ms. Measure with `utime+stime` from `/proc/PID/stat`.
- **Stale NEON registers after hot-plug (the ~50 % CPU bug, found 2026-11-05)**: 3.10.17's `vfp_hotplug` clears `vfp_current_hw_state[cpu]` only if the dying core's current thread owns it, and that's the stopper thread, so it never does. A thread that last used NEON on CPU1, sleeps through CPU1 going off and on, and wakes there isn't given its registers back and gets the core's power-on noise. Seen as: Music paused, ~60 new processes/s from the audio routing. GCC keeps `take_requests`' reset constants in d9-d11 for the whole of `player_thread`, so it wrote noise into `want_*` on every pass and rescanned, toggled and seeked forever. Any thread using NEON can be hit, and most would just get a wrong number. `tools/phone/vfpcheck.c` lost registers in 37 of 40 tries; CPU0 alone with its deepest idle lost none. Fix: `kernel/vfp-hotplug.patch`. On the fixed kernel `vfpcheck` lost none in 148 tries and the repro that used to trigger it (Music, play, pause, Web, message Blip, leave) stayed clean, though the hot-plug behind it was never caught happening in normal use. Installed to KERNEL as `boot-native9.img` on 2026-11-05.
- **UI font**: FreeType costs ~2.5 ms a glyph, seconds across the apps' tables, so `tools/deploy.sh` runs `trendos.py --bake-glyphs` to write `/usr/local/share/trendos/glyphs.bin` (~430 KB, read in ~60 ms; not in git). New app text sizes are picked up on the next deploy. No usable file = drawn as needed, so a slow start but nothing breaks. Changing the font or `FONT_UI_SCALE` takes a deploy to show. Screens still on PIL (`gfx.glyph`, Clock, Wi-Fi, Bluetooth, SSH, power menu) don't use it.
- **Icon shading**: shared light is to one side, so flat-fronted icons (Files, SSH) go nearly dark at one end of the sway. Not fixed: affects every icon.

## 3. Code map
`overlay/` mirrors the phone. New service: add to `FILES` in `tools/deploy.sh`, then `rc-update add X default`. Package `usr/local/lib/trendos/tos/`; each layer uses only those above it:

| Module | Role |
|---|---|
| `config` | all constants, `PALETTE`, colour indices |
| `native` | only door into C: numpy in, no pointers out |
| `hw/` | `fb`, `inputdev`, `fm` (CLI `fmctl`), `btchip` (BCM43430A1: `RawUart` or `HciSocket`), `bluetooth` (`BtCtl`), `audio`, `volume` (system level, kept in `VOLUME_FILE`; `on_change`, `gain`), `voice` (Blip), `sshmon` |
| `canvas` | fast 2D into RGBX: use for anything redrawn often. Rectangles half-open (PIL's inclusive) |
| `gfx`, `ui` | fonts, `to_rgbx`; shared look (`native_card` fast, `card`, `Keys`) |
| `render` | `draw_view(buf, shape, m9, K, cols, rows, x, y, tiles)`, K ≈ cols*1.5 fills; `card_tiles`, `MINI`, `matrix(tilt,a,b,c)`. Moving parts: update `shape.pts/fnrm/fcen` (see `Clock3D`) |
| `models/` | `shape.py` (`Shape`, `boxes`, `extrude`, `arc`, `relief`), `icons.py` (`@model(name, colour)`), `registry.py` |
| `keyboard` | `Keyboard(on_done, on_cancel, text, on_change, prose)`, `KB_Y`. A second finger reaches it through `App.second_finger`, and its landing types the first finger's key. `prose=True` adds sentence capitals, `. ` for a double space and going back to letters after a symbol: keep it off for passwords |
| `apps/` | `base.App`, one folder each. C in `native/libtrend/src/apps/`: calculator, music, files, web. Python: wifi (threads + keyboard example), radio (worker thread, 30 fps numpy), clock (alarms via `background()`), ssh, bluetooth, spotify (shelved) |
| `shell`, `launcher`, `flight`, `transition`, `power`, `stats`, `title`, `volumebar`, `boot` | main loop and region cache by `app.key()`; `Entry(model, app, opens, name, phase)`; icon flight to title badge (automatic); slide; power menu; stats; title; boot handover |

C rules: `native/README.md`. Other: `/usr/local/sbin/*` helpers, `bootimg/ramdisk/init`.

## 4. Adding an app
1. `tos/apps/myapp/app.py` + `__init__.py` (`from .app import MyApp`), export in `tos/apps/__init__.py`. Subclass `App`: `name`, `touch(ev, x, y)` (screen coords), `key(now)` (hashable; render only runs when it changes), `render(now)` → RGBX array `(APP_H, W, 4)`. Optional: `on_open/on_close`, `on_key(code, pressed)` (True if used; the shell keeps the volume keys unless `wants_volume_keys()`, and anything that plays follows `hw.volume`), `background(now)` (~1/s even closed; True wakes and fronts it), `keep_awake`.
2. Icon: `@model("myicon", COLOUR)` returning `boxes`, `extrude` or `relief`, within ~±1.3 x/y, flat front. Preview: `cd /usr/local/lib/trendos && python3 -m tos.models myicon`.
3. `Entry("myicon", MyApp(), phase=(a, b, c))` in `default_entries()` or `utilities_entries()`; submenu `opens="name"`.
4. `tools/deploy.sh`, then `rc-service bootscreen status`. Log: `/var/log/bootscreen.log`.

Rules:
- Use `canvas` + `ui.native_card` (~10 ms vs PIL ~50 ms); PIL for one-off images or a once-a-second redraw (~45 ms).
- Keep `key()` cheap and stable when idle; add time buckets (`int(now*30)`) only when animating.
- `render()` runs before `on_open`: the shell pre-renders every app before its first frame, behind the ramdisk's loading spin, so one-off setup belongs in the first `render()` and costs no stall. Anything slow after that goes on a thread.
- Animation: one persistent buffer, whole-array numpy, redraw changed regions. Slow work: daemon thread + version in `key()`.
- Style: black, `ACCENT`, VT323, ASCII. Add 3D where it fits: keep a copy of the 2D layer, restore the viewport each frame, `draw_view` into it (wifi `_draw_bars`, clock `_draw_3d`).

## 5. Procedures
- **Deploy**: `tools/deploy.sh [user@host]`. `SPOTIFY=1` re-enables Spotify.
- **Static C on phone**: `gcc -static -O2 -s -o X X.c [-lm]`.
- **Boot image**: on phone `trendos.py --boot-anim bootanim.bin`, `--boot-frame logo.rgbx`, `mkcharger.py charger.bin`; copy back; on laptop
  `python3 bootimg/mkramdisk.py bootimg/ramdisk busybox.static rd.gz logo.rgbx=… bin/fbpan=… bin/bootanim=… bootanim.bin=… bin/charger=… charger.bin=…` then
  `python3 bootimg/repack_keep_dt.py firmware/stock/boot.img rd.gz firmware/trendos/boot-nativeN.img`. Flash: `dd of=/dev/mmcblk0p20 conv=fsync` on phone, verify sha256, reboot (fallback `heimdall flash --KERNEL img`).
- **Rescue**: init falls back to RNDIS + `telnet 192.168.42.129` if Alpine fails or `/data/alpine/.native-disable` exists. BootROM: battery out, hold Vol-Up, plug USB → `1782:4d00` (`tools/bootloader/bootrom_hello.py`; flashing needs FDL1/FDL2, not obtained).
- **Phone tools** (`tools/phone/`, copy to `/tmp`, run with `python3 -I`): `bench.py` (frame costs, shell CPU: run before and after), `vfpcheck.c` (do NEON registers survive hot-plug; compile on the phone), `test_keyboard.py` (keyboard and two-finger input; how to run it is at its top), `cpuwho.py` (what's using the CPU right now, by thread, and what's being spawned; no copying needed: `ssh root@192.168.42.129 python3 -I - < tools/phone/cpuwho.py`), `drive.py` (injected input), `shot.py` (screenshot), `mkchime.py`, `mkjungle.py` (32-bit ints and memory limit it: watch numpy overflow).
- **UI tests**: inject into event1 (SLOT 0, TRACKING_ID n, X, Y, SYN … TRACKING_ID -1) / event0. Screenshot = `/dev/fb0` at `pan_y*480*4` (`/sys/class/graphics/fb0/pan`), RGBX. Wake first with Home.

## 6. Subsystems
**FM radio** (analog): FM core in the BCM43430A1, vendor HCI `0xFC15 [reg, 0=w|1=r, data…]` over `/dev/ttyS0` 115200 RTS/CTS. CLI `fmctl on [MHz] | tune MHz | off`; patch `/data/bt/BCM43430A1.hcd`. Visualiser = `arecord` of codec line-in (`hw:CARD=sprdphone,DEV=0`, 16 kHz mono). State `/var/lib/trendos/radio.json`. ~35 % of a core live.
- UART EIO until `rfkill0` toggled 0→1. Bring-up: reset → `0xFC2E` → .hcd → reset → **`0xFC27` (12 zeros) sleep off**, else `close()` hangs till reboot. Always `tcflush` before close.
- Regs: 0x00 power (1 FM, 3 +RDS) · 0x01 ctrl (0x04 stereo) · 0x05 audio (0x1c DAC L+R; 0x02 mute) · 0x09 tune mode (1 preset, 2 seek) · 0x0a/0b freq = kHz−64000 LE · 0x0f RSSI · 0x12 flags · 0xf8 volume. Codec path in `codec_on()`.
- **Don't use digital FM** (`hw:sprdphone,4`): reboots the phone. Open: RSSI flat ~170-185 across the band, no station confirmed, so no seek or RDS yet.

**Kernel**: Samsung source github.com/TechTex198/SM-G318H-Kernel-Source in `tools/ext/kernel`, `kernel/build.sh` (GCC 4.7.3, Docker) → `firmware/trendos/boot-kernel-test.img`. Config = `vivalto3mveml3g_hw00_defconfig` + `kernel/trendos.config` (public defconfig is the Marlin board; ours is Broadcom, matched to stock `/proc/kallsyms`). `trendos-logo.patch`: sprdfb paints the boot frame at ~0.44 s (`bootframe.rgbx` via `mklogo_h.py`), so the Samsung logo shows ~1 s; always 3 fb pages. Test with `kernel/test-in-recovery.sh`; install by `dd` to p20 + normal reboot.

**SBOOT logo via BootROM** (paused, plan: own FDL1): BootROM runs any FDL1 at 0x50000000; spd_dump needs `tools/bootloader/spd_dump-sc8830-64byte.patch` (`SPD_CHUNK=64`). Public SC8830 FDL1 (zeallar/w_sprd_fdls) hangs in DDR init. Own SPL has the right DDR init but no USB. Read test: `tools/bootloader/bootrom-read.sh`.

**Bluetooth**: `btuart` (`bt-up`: `btchip.boot_raw(3000000, efs address)`, `btattach -B /dev/ttyS0 -P h4 -S 3000000`), `bluetooth` (BlueZ), `btaudio` (bluealsa, A2DP), `dbus`. Address from `/data/bt/bt_addr`. Alpine's `bluealsa` service segfaults: it reads past the stack top into env strings, so `btaudio` passes an 8 KB `STACK_PAD` env var. Storage `/usr/var/lib/bluealsa`. Radio streams to A2DP via `aplay -D trendbt:DEV=…`, wired headphones muted but still the antenna. **Play to Bluetooth only through `trendbt`** (`etc/alsa/conf.d/30-trendos-bt.conf`): it's pinned to 44.1 kHz stereo, matching `--a2dp-force-audio-cd`, and converts anything else. Asking BlueALSA 4.3.1 for a rate or channel count other than the stream's (mono counts) makes it renegotiate the codec, which fails with BlueZ 5.86 ("Transport already configured") and destroys the stream until the device reconnects, while BlueZ still shows it connected.

**Music**: `src/apps/music/` = touches → `tr_music_cmd`, pure render (`music_viz.c`: visualiser). `native/player/` = thread scanning `/data/music`, libsndfile decode, ALSA output. Folders are playlists: tracks sort by folder, so a `tr_music_folder` is a run of the library, and next/previous/end of track stay inside it. The list is one level: nested folders appear at the top as `Band/Album`. The app rescans when opened, so it sees uploads then. Custom playlists (tags or symlinks) are still to do; the scan already follows symlinks, but `filesd` hides them. Output: Bluetooth > headphones (`/sys/class/switch/h2w/state`) > speaker, routed on every open. Software volume 0-15, set by the system volume. Viz uses 12 Goertzel bands from `status.scope`, before volume, so it works at volume 0 for silent tests. **Don't encode MP3 with libsndfile on the phone**: noise bursts, cause not traced; use FLAC. Player reads float and clips itself: 16-bit reads make loud MP3s wrap and float WAVs near-silent. Limits: 1024 tracks and 256 folders (extra ones aren't listed, with no warning), scan depth 6, Latin-1 titles, nothing remembered across restart. Test: `player/tests/test_player.c` on ALSA `null`. ~24 % of a core playing with the app open, ~11 % closed.

**Files**: `native/filesd/`, started by `apps/files/app.py` (`Popen`, off at boot), status lines read non-blocking. Root to bind :80, chowns shared folders to `trendfiles`, then setuid, no groups, NO_NEW_PRIVS: can accept but not open sockets. Ends with parent, on SIGTERM, after 30 idle min or 10 wrong PINs. One thread + one request per connection, max 16. Uploads: `/data/.filesd-tmp`, fsync, rename. Paths walked by component with O_NOFOLLOW. **Open each shared folder with `openat(root, ".")`, never dup: a dup shares its read position, so listings came back empty.** ~3-5 MB/s. Page: `usr/local/share/trendos/files/index.html`.

**Web**: `native/webd/`, started twice by `apps/web/app.py` (`webd agent`, `webd web`). User `trendweb`, group 3003, NO_NEW_PRIVS, non-dumpable, `nice 5`, 256 MB RLIMIT_AS, ends with parent. Pure and tested: `doc.c`, `url.c`, `html.c` (tag walk, no JS/CSS; skips nav/aside unless under 6 rows remain), `json.c`, `ascii.c`, `gemini.c`. Phone-only: `net.c` (OpenSSL, certs always checked; waits poll stdin to interrupt, except getaddrinfo), `fetch.c`, `agent.c`, `webd.c`. Frames in `trend/apps/web_wire.h`: both tabs are rows on a 46-column grid, drawn by `src/apps/web/`. `tr_web_status` ~2 MB of `mmap`ed rows; `tr_web_feed` input is hostile. No cookies, disk writes or downloads. `webd` ~4 MB after pages.
- **Agent**: Gemini `streamGenerateContent?alt=sse`, `x-goog-api-key`, `WEB_MODEL` = `gemini-3.1-flash-lite`: the free tier runs out on requests per day per model (20 on `gemini-3.6-flash`, from its 429), not tokens, and every tool round is a request. On 2026-11-05 `gemini-3.5-flash-lite` gave 503, `gemma-4-31b-it` 500, `gemini-2.5-flash-lite` 404. A request is 454 tokens before the conversation (system ~226, tools ~226), so what matters is page text and history: `TOOL_TEXT_MAX` 8000 chars, `HISTORY_MAX` 24000 bytes (oldest whole turns forgotten, still on screen), `MAX_ROUNDS` 5. Key `/etc/trendos/gemini-key`, read before dropping root. `generateContent` is "legacy" but has no shutdown date; the Interactions API's docs don't show streamed function arguments: move if that changes or a shutdown is announced. History = JSON text of `contents`; failed, refused or stopped turns are cut whole. Parts are echoed as received so thought signatures survive; only empty text with no signature is dropped. Tools run on the phone: `search_web` (DuckDuckGo HTML; Google Search isn't free on this model), `read_page`, `show_page`. Tools can't reach private addresses (checked on resolved IP).
- **Blip's voice**: `hw/voice.py`, fed by `tr_web_take_said`, so it follows the writing. One chip note per letter, the same each time; ~14 a second, newest letter wins. Silent at volume 0 or while music plays (device is exclusive; no mixing). `audio.take_output` stops it for an alarm.
- **Blip**: spheres from `_ball` in `models/icons.py`; dark eyes and mouth are cut into the surface (bulging eyeballs became noise); red tongue when wide; own `BLIP_LIGHT` so the mouth isn't in shadow. One mesh per pose, order must match `TR_WEB_MASCOT_*`, built on a thread (~3 s). Pose from mood and clock in `web_view.c`: hello on empty chat, look around while busy, talks while `WEB_REPLYING` or while there's text left to write. The chat writes itself out in `web.c` (`reveal_advance`), by time and independent of the network: ~45 characters/s, faster on long answers, pausing at punctuation; a tap shows it all; the user's words, errors and dim rows (notes, code blocks) appear at once. Shell ~12 % of a core idle on the chat, ~22 % writing; 5 fps idle, 15 fps busy, 24 fps writing.

**Spotify** (shelved): every track fails `aes key code 1`; the workaround is DRM circumvention, so not doing it. Revive: import in `apps/__init__.py`, re-add Entry, `SPOTIFY=1 tools/deploy.sh`.

## 7. Dead ends
TWRP for this model · `adb root` on stock · SELinux permissive via cmdline · changing the Samsung logo from Linux or Download mode (WP + signed SBOOT) · mainline/postmarketOS (no SC8830 port) · digital FM · spotifyd/librespot playback.

## 8. Backups (never delete)
`backup/` (SBOOT, SPL, PARAM originals, `pit.txt`, `kingo/`). Full image `backup/phone-image-2026-11-03/` (gitignored, restore steps in its README). Never wipe efs/prodnv/*nv/PARAM/MODEM/bootloaders on the phone. Stock zip in `firmware/stock/` (gitignored; samfw.com).

## 9. Next ideas
Radio seek + RDS · Clock timer/stopwatch · Utilities: Display/Sound/About · Music: shuffle, custom playlists, remember place · system monitor, notes, smart-home controller · web, DNS ad-block, MQTT services · ntfy notifications.

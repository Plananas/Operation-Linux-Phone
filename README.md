# TREND OS — a Samsung Galaxy Trend 2 Lite running Linux

This old phone (SM-G318H, 2015) no longer runs Android. It boots straight into **TREND OS**:
a small Linux system (Alpine Linux) with its own animated home screen, apps and a
retro terminal look. It's meant to become a tiny always-on server and controller.

Android is still on the phone, untouched — it just doesn't start. You can switch back at any
time (see *Getting out of trouble*).

---

## Using the phone

| What you do | What happens |
|---|---|
| **Power on** | Samsung logo (~1 s) → TREND OS logo → spinning cube → startup sound → "Welcome, Robin" |
| **Swipe left / right** | Move between apps (each app is a spinning 3D object) |
| **Tap an object** | Open that app (the home cube is just a welcome — it doesn't open anything) |
| **Back key, Home button, or tap the title** | Close the app |
| **Short press Power** | Screen off (the phone keeps running). Press Power or Home to wake |
| **Hold Power (~1 s)** | Power menu: Shut down / Restart / Cancel |
| **Leave it alone 2 minutes** | Screen turns off by itself |
| **Plug in while switched off** | Charging screen. Hold Power 1.5 s to start TREND OS. Unplug = it switches off |

The look: a retro CRT terminal (green phosphor, VT323 font, scanlines) with 3D objects drawn in
shaded ASCII characters, demoscene style. Each app shows its home-screen object spinning in its
title bar.

**Apps so far:**
- **Calculator** (the spinning plus sign) — green-phosphor terminal style, with history.
- **Settings** (the sliders icon) — opens a second carousel. Inside it, **Wi-Fi** shows your
  connection (with 3D signal bars that follow the real signal) and nearby networks; tap a network and type the password on the on-screen keyboard.
  **Bluetooth** is next to it: switch it on/off, tap **scan**, then tap your headphones or speaker
  under *nearby* to pair and connect (put them in pairing mode first). Others see the phone as
  "TREND OS".
- **Music** (the two notes) — plays MP3, FLAC, Ogg, Opus and WAV files from `/data/music` on the phone
  (subfolders are fine). Copy them over USB: `scp song.mp3 root@192.168.42.129:/data/music/`, then
  reopen the app. Tap a track to play it; drag the bar to seek; the **volume keys** set the volume
  while the app is open. Music keeps playing when you close the app or the screen turns off, and
  moves on through the list until it runs out. The **song / visualiser** tabs at the top switch
  between the track list and an abstract 3D visualiser in the same ASCII style as the icons, moving
  with the music, with the title and controls still underneath it. It plays through Bluetooth if connected, otherwise
  wired headphones, otherwise the speaker. Losing headphones or Bluetooth pauses it, and an alarm or
  the Radio pauses it too.
- **Clock** (the clock face) — big glowing time, date, and up to 4 alarms. Tap **+ new alarm**
  or an alarm to set the time and the days it repeats (no days = rings once). Alarms ring
  through the speaker even with the screen off or another app open; volume key = snooze 5 min.
  A 3D clock with real moving hands sits next to the next alarm (it shakes when ringing).
  The phone sets its own time from the internet over Wi-Fi (UK time, summer time included).
- **SSH** (the terminal screen) — who is connected over SSH right now: address, USB or Wi-Fi,
  how long, which key, what they are running, plus a log of logins and rejected attempts. View only.
- **Radio** (the mast icon) — FM radio. **Plug in wired headphones first: they're the antenna.**
  Opening it switches the radio on (takes ~4 s), closing it switches it off. Drag or flick the
  tuning drum (or tap a number on it); `<` `>` step 0.1 MHz (hold to repeat), `<<` `>>` jump
  1 MHz, the middle key switches on/off, the **volume keys** set the volume. The scope and the
  3D waterfall landscape show the actual audio. It remembers your last station. With Bluetooth
  headphones or a speaker connected, the radio plays there (keep the wired headphones plugged in:
  they're still the antenna).
The bottom of the home screen shows live stats: CPU, memory, battery, storage, network, uptime.

## Connecting from the laptop

The phone is on your **Wi-Fi** now, and also reachable over the **USB cable**.

- **Log in over USB:** `ssh root@192.168.42.129` (key-based, no password). SSH only listens on the
  USB link, so it can't be reached over Wi-Fi.
- **Internet:** the phone gets its own internet from Wi-Fi — the laptop isn't needed. If you ever
  turn Wi-Fi off and want internet over the cable instead, run `sudo tools/pc-share-internet.sh`
  on the laptop once (shares internet but blocks the phone from the rest of your home network).
- **Add/Change the Wi-Fi network:** easiest on the phone — Settings → Wi-Fi → tap a network → type
  the password. (Or over SSH: `ssh -t root@192.168.42.129 /usr/local/sbin/wifi-connect`.)

## Updating TREND OS

- **Apps / home screen / anything in `overlay/`:** run `tools/deploy.sh`.
  It copies the files, rebuilds the graphics engine and restarts the screen — about 10 seconds.
- **Boot logo, boot animation, charging screen:** these live in the *boot image* and need a
  rebuild + flash (`bootimg/`). Ask Claude, or see "Procedures" in `PLAN.md`.

## Getting out of trouble

| Problem | Fix |
|---|---|
| Screen frozen / weird | `ssh root@192.168.42.129 rc-service bootscreen restart` |
| Phone won't boot TREND OS | Pull battery, hold **Vol-Down + Home + Power** (Download mode), then on the laptop: `heimdall flash --KERNEL firmware/trendos/boot-native8.img` (our kernel) or `firmware/trendos/boot-native6.img` (Samsung's kernel) |
| Want Android back | Same Download mode, then `heimdall flash --KERNEL firmware/stock/boot.img` (stock) or `firmware/android-rooted/boot-root4.img` (rooted Android) |
| Phone totally dead (no logo, no Download mode) | Emergency chip mode: battery out and back in, **hold Volume Up** while plugging in USB → screen stays black, laptop sees a "Spreadtrum" device. Recovering from there needs extra tools (not set up yet). |

**Really switching off:** with the cable plugged in, "Shut down" lands on the charging screen
(that's normal). To be fully off, unplug — or pull the battery.

**Battery:** it's always on the charger. Check it every month or so for swelling.

## What's in this folder

```
README.md                  this guide
PLAN.md                    technical notes for Claude: how it all works, quirks, procedures, adding an app

overlay/                   everything installed on the phone; mirrors the phone's filesystem
  etc/init.d/              services: bootscreen (the shell), usbnet, wifi, timesync, btuart, btaudio, spotify (shelved)
  etc/conf.d/, etc/local.d/, etc/timezone    hardware clock, boot log, UK time
  usr/local/bin/           trendos.py (shell entry point), mksound.py, mkcharger.py (startup sound, charger assets)
  usr/local/sbin/          helpers: wifi-up, wifi-connect, wifi-autostart, bt-up, fmctl, audio-speaker,
                           audio-headphones, play-startup-sound, screen-on, ntp-synced
  usr/local/share/trendos/fonts/    VT323
  var/lib/go-librespot/    Spotify engine config (shelved)
  usr/local/lib/trendos/tos/    the home screen and apps, in Python (map below)

native/                    all our C; rules and style in native/README.md
  libtrend/                the C core, built into libtrend.so on the phone by deploy.sh
    include/trend/, src/   pixels, draw, mesh, viz, expr
    src/apps/<app>/        the apps written in C, one folder each: calculator/, music/
    tests/                 unit tests: make test
  player/                  Music's playback: libtrendplay.so, built on the phone by deploy.sh
  boot/                    bootanim, charger, fbpan: source + prebuilt static binaries for the ramdisk

bootimg/                   putting a boot image together
  ramdisk/init             the first thing that runs: charging screen, or logo and animation, then Alpine
  mkramdisk.py             packs the ramdisk
  repack_keep_dt.py        builds the boot image, keeping Spreadtrum's device tree (needed to boot)

kernel/                    our Linux kernel: Samsung's source plus these
  build.sh, Dockerfile     build it (GCC 4.7 in Docker), output firmware/trendos/boot-kernel-test.img
  test-in-recovery.sh      try a new kernel from the recovery partition
  trendos.config           our kernel options
  trendos-logo.patch       the early TREND OS logo
  mklogo_h.py, trendos_logo.h, bootframe.rgbx    the logo image and the header made from it

tools/                     things you run on the laptop
  deploy.sh                push updates to the phone
  pc-share-internet.sh     share the laptop's internet with the phone
  phone/                   copied to the phone to test it: bench.py (speed), drive.py (walks the UI), shot.py (screenshot),
                           mkjungle.py, mkchime.py (make test sounds for Music)
  bootloader/              emergency-mode (BootROM) tools, paused: bootrom_hello.py, bootrom-read.sh, spd_dump patch
    logo/                  attempts at replacing the Samsung logo. mklogo.py needs cube.py, which no longer exists
  android/                 for rooted Android and the old chroot setup: rootshell.sh, alpine-boot.sh
  spotify/                 shelved Spotify engine build (Spotify blocks playback for this kind of client)
  ext/ *                   third-party clones: kernel, kout (kernel build output), chipram, spreadtrum_flash, fdl-sc8830

assets/music/              our own sounds for the Music app: Polygon Jungle.flac, Chime.wav
                           (made by tools/phone/mkjungle.py, mkchime.py); copy to /data/music to play

firmware/
  stock/                   Samsung's boot.img and recovery.img, plus the full firmware zip *
  android-rooted/          rooted Android boot images: boot-root4.img is the one to use
  trendos/                 TREND OS boot images, boot-native1 to 8 (8 is current), boot-kernel-test.img *,
                           and the patched SBOOT/PARAM from the logo attempts
  alpine/                  the Alpine Linux base system

backup/                    the phone's original bootloader and settings. NEVER DELETE
  SBOOT, SPL, PARAM originals, pit.txt, getprop.txt, packages.txt, kingo/
  phone-image-2026-11-03/ *    full phone image, with its own restore README (private: holds the IMEI)
  bootrom-read-*/ *        output from BootROM read tests
```

`*` means not in git: too big, private or re-downloadable.

**The rule for `overlay/`:** a file at `overlay/etc/init.d/wifi` lands at `/etc/init.d/wifi` on the
phone. A new service also has to be added to `FILES` in `tools/deploy.sh`.

### The Python package: `overlay/usr/local/lib/trendos/tos/`

Each layer only uses the ones above it.

| Layer | Modules |
|---|---|
| **Foundations** | `config` (every constant), `native` (the only door into the C library) |
| **`hw/`: the devices** | `fb` (screen), `inputdev` (touch and keys), `btchip` (Bluetooth/FM chip), `fm`, `bluetooth`, `audio`, `sshmon` |
| **Drawing** | `gfx`, `canvas`, `render` (3D), `ui` (the shared look), `keyboard`, `models/` (the 3D icons) |
| **`apps/`** | `base`, then one folder per app, with its class in `app.py`: `calculator/`, `radio/`, `music/`, `clock/`, `ssh/`, `wifi/`, `bluetooth/`, `spotify/` (shelved) |
| **The shell** | `shell` (main loop), `launcher`, `transition`, `flight`, `stats`, `title`, `power`, `boot` |

### Where to go for...

| To change... | Look in |
|---|---|
| An app | `overlay/usr/local/lib/trendos/tos/apps/<app>/` (Calculator and Music are really in `native/libtrend/src/apps/<app>/`) |
| Music playback | `native/player/` |
| Anything that draws too slowly | `native/libtrend/` |
| How the phone starts | `bootimg/ramdisk/init`, then `overlay/etc/init.d/` |
| Boot animation or charging screen | `native/boot/`, then rebuild the boot image |
| The kernel | `kernel/` |

## Ideas for later

Radio station search + station names (RDS) · more apps (system monitor, notes, a controller for smart-home things) · server
services (website, DNS ad-blocker, MQTT) · notifications to your phone.
Calls/SMS aren't possible (no SIM, and the modem needs Android's vendor software).

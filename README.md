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

**Apps so far:**
- **Calculator** (the spinning plus sign) — green-phosphor terminal style, with history.
- **Settings** (the sliders icon) — opens a second carousel. Inside it, **Wi-Fi** shows your
  connection and nearby networks; tap a network and type the password on the on-screen keyboard.
- **Clock** (the clock face) — big glowing time, date, and up to 4 alarms. Tap **+ new alarm**
  or an alarm to set the time and the days it repeats (no days = rings once). Alarms ring
  through the speaker even with the screen off or another app open; volume key = snooze 5 min.
  The phone sets its own time from the internet over Wi-Fi (UK time, summer time included).
- **Radio** (the mast icon) — FM radio. **Plug in wired headphones first: they're the antenna.**
  Opening it switches the radio on (takes ~4 s), closing it switches it off. Drag or flick the
  tuning drum (or tap a number on it); `<` `>` step 0.1 MHz (hold to repeat), `<<` `>>` jump
  1 MHz, the middle key switches on/off, the **volume keys** set the volume. The scope and the
  ASCII bars show the actual audio. It remembers your last station.
The bottom of the home screen shows live stats: CPU, memory, battery, storage, network, uptime.

## Connecting from the laptop

The phone is on your **Wi-Fi** now, and also reachable over the **USB cable**.

- **Log in over USB** (always works): `ssh root@192.168.42.129` (key-based, no password).
- **Log in over Wi-Fi:** `ssh root@<phone-wifi-ip>` (the phone shows its Wi-Fi IP in Settings → Wi-Fi).
- **Internet:** the phone gets its own internet from Wi-Fi — the laptop isn't needed. If you ever
  turn Wi-Fi off and want internet over the cable instead, run `sudo tools/pc-share-internet.sh`
  on the laptop once (shares internet but blocks the phone from the rest of your home network).
- **Add/Change the Wi-Fi network:** easiest on the phone — Settings → Wi-Fi → tap a network → type
  the password. (Or over SSH: `ssh -t root@192.168.42.129 /usr/local/sbin/wifi-connect`.)

## Updating TREND OS

- **Apps / home screen / anything in `tools/native/alpine-overlay/`:** run `tools/deploy.sh`.
  It copies the files, rebuilds the graphics engine and restarts the screen — about 10 seconds.
- **Boot logo, boot animation, charging screen:** these live in the *boot image* and need a
  rebuild + flash. Ask Claude, or see "Procedures" in `PLAN.md`.

## Getting out of trouble

| Problem | Fix |
|---|---|
| Screen frozen / weird | `ssh root@192.168.42.129 rc-service bootscreen restart` |
| Phone won't boot TREND OS | Pull battery, hold **Vol-Down + Home + Power** (Download mode), then on the laptop: `heimdall flash --KERNEL firmware/extracted/boot-native7.img` (our kernel) or `boot-native6.img` (Samsung's kernel) |
| Want Android back | Same Download mode, then `heimdall flash --KERNEL firmware/extracted/boot.img` (stock) or `boot-root4.img` (rooted Android) |
| Phone totally dead (no logo, no Download mode) | Emergency chip mode: battery out and back in, **hold Volume Up** while plugging in USB → screen stays black, laptop sees a "Spreadtrum" device. Recovering from there needs extra tools (not set up yet). |

**Really switching off:** with the cable plugged in, "Shut down" lands on the charging screen
(that's normal). To be fully off, unplug — or pull the battery.

**Battery:** it's always on the charger. Check it every month or so for swelling.

## What's in this folder

| Path | What it is |
|---|---|
| `README.md` | This guide |
| `PLAN.md` | Technical notes for Claude: how everything works, quirks, procedures, how to add an app |
| `tools/native/alpine-overlay/` | Everything installed on the phone (home screen, apps, services) |
| `tools/native/` | Boot-image parts: startup script, boot animation, charging screen, graphics engine |
| `tools/kernel/` | Our own Linux kernel build (Samsung's source + the early TREND OS logo) |
| `tools/bootloader/` | Emergency-mode (BootROM) tools for a future bootloader logo swap |
| `tools/deploy.sh` | Push updates to the phone |
| `tools/pc-share-internet.sh` | Share the laptop's internet with the phone |
| `tools/spotify/` | Shelved Spotify player build (Spotify blocks playback for this kind of client) |
| `tools/bootlogo/`, `tools/ext/`, `bootrom_hello.py` | Old experiments: boot-logo attempts, emergency-flash tools |
| `firmware/extracted/` | Boot images (stock Android and all TREND OS versions) |
| `backup/` | Copies of the phone's original bootloader and settings — **never delete** |

## Ideas for later

Radio station search + station names (RDS) · more apps (system monitor, notes, a controller for smart-home things) · server
services (website, DNS ad-blocker, MQTT) · notifications to your phone.
Calls/SMS aren't possible (no SIM, and the modem needs Android's vendor software).

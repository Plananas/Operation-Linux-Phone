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
| **Power on** | Samsung logo → TREND OS logo with a spinning cube → startup sound → "Welcome, Robin" |
| **Swipe left / right** | Move between apps (each app is a spinning 3D object) |
| **Tap an object** | Open that app (the home cube is just a welcome — it doesn't open anything) |
| **Back key, Home button, or tap the title** | Close the app |
| **Short press Power** | Screen off (the phone keeps running). Press Power or Home to wake |
| **Hold Power (~1 s)** | Power menu: Shut down / Restart / Cancel |
| **Leave it alone 2 minutes** | Screen turns off by itself |
| **Plug in while switched off** | Charging screen. Hold Power 1.5 s to start TREND OS. Unplug = it switches off |

**Apps so far:** Calculator (the spinning plus sign) and **Settings** (the sliders icon) — swipe to it and tap to open a second carousel of setting icons; **Wi-Fi** is in there, showing your connection, signal and nearby networks.
The bottom of the home screen shows live stats: CPU, memory, battery, storage, network, uptime.

## Connecting from the laptop

The phone talks to the laptop over the **USB cable only** (no Wi-Fi yet, on purpose).

- **Log in:** `ssh root@192.168.42.129` (key-based, no password).
- **Internet for the phone** goes through the laptop. After every laptop reboot run once:
  `sudo tools/pc-share-internet.sh` — the phone can then reach the internet but **not** other
  devices on your home network.

## Updating TREND OS

- **Apps / home screen / anything in `tools/native/alpine-overlay/`:** run `tools/deploy.sh`.
  It copies the files, rebuilds the graphics engine and restarts the screen — about 10 seconds.
- **Boot logo, boot animation, charging screen:** these live in the *boot image* and need a
  rebuild + flash. Ask Claude, or see "Procedures" in `PLAN.md`.

## Getting out of trouble

| Problem | Fix |
|---|---|
| Screen frozen / weird | `ssh root@192.168.42.129 rc-service bootscreen restart` |
| Phone won't boot TREND OS | Pull battery, hold **Vol-Down + Home + Power** (Download mode), then on the laptop: `heimdall flash --KERNEL firmware/extracted/boot-native6.img` |
| Want Android back | Same Download mode, then `heimdall flash --KERNEL firmware/extracted/boot.img` (stock) or `boot-root4.img` (rooted Android) |
| Phone totally dead (no logo, no Download mode) | Emergency chip mode: battery out and back in, **hold Volume Up** while plugging in USB → screen stays black, laptop sees a "Spreadtrum" device. Recovering from there needs extra tools (not set up yet). |

**Really switching off:** with the cable plugged in, "Shut down" lands on the charging screen
(that's normal). To be fully off, unplug — or pull the battery.

**Battery:** it's always on the charger. Check it every month or so for swelling.

## What's in this folder

| Path | What it is |
|---|---|
| `README.md` | This guide |
| `PLAN.md` | Technical notes: how everything works, quirks, procedures (written for Claude, readable for you) |
| `tools/native/alpine-overlay/` | Everything installed on the phone (home screen, apps, services) |
| `tools/native/` | Boot-image parts: startup script, boot animation, charging screen, graphics engine |
| `tools/deploy.sh` | Push updates to the phone |
| `tools/pc-share-internet.sh` | Share the laptop's internet with the phone |
| `firmware/extracted/` | Boot images (stock Android and all TREND OS versions) |
| `backup/` | Copies of the phone's original bootloader and settings — **never delete** |

## Ideas for later

Wi-Fi · more apps (system monitor, notes, a controller for smart-home things) · server
services (website, DNS ad-blocker, MQTT) · notifications to your phone.

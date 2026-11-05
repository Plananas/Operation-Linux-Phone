# TREND OS

A Samsung Galaxy Trend 2 Lite (SM-G318H, 2015) running its own small Linux system, built on Alpine, with a retro terminal look and 3D objects drawn in shaded ASCII. Android is still on the phone but doesn't start, and you can switch back at any time.

## Using the phone

| Action | Result |
|---|---|
| Swipe left or right | Move between apps |
| Tap an object | Open that app |
| Back, Home or tap the title | Close the app |
| Short press Power | Screen off, still running. Power or Home wakes it |
| Hold Power (~1 s) | Shut down / Restart / Cancel |
| Leave for 2 minutes | Screen turns off |
| Plug in while off | Charging screen. Hold Power 1.5 s to start |

## Apps

- **Web:** chat with Blip, an AI mascot that can search and read the web and babbles in chip sounds as it writes (quiet while music plays), with a small browser in the next tab. No JavaScript or cookies, so simple sites work best. The chat needs a key (below) and lasts until a restart.
- **Calculator:** with history.
- **Volume:** the volume keys set one volume for everything, from any screen, even with the screen off. Hold a key to keep going, or drag the bar that appears at the top. Alarms always ring at full volume.
- **Radio:** FM. Plug in wired headphones first, because they're the antenna, even if you listen over Bluetooth.
- **Music:** plays MP3, FLAC, Ogg, Opus and WAV from `/data/music`, with a 3D visualiser tab. Keeps playing when closed. Uses Bluetooth, then wired headphones, then the speaker.
- **Clock:** up to 4 alarms, which ring even with the screen off. A volume key snoozes for 5 minutes. Sets its own time over Wi-Fi.
- **Files:** manage `/data/music` and `/data/files` from a browser. Tap **start sharing**, open the address shown and type the PIN. It's plain HTTP, so only use it on a Wi-Fi network you trust.
- **Utilities:** Wi-Fi, Bluetooth and SSH. For Bluetooth, put headphones or speakers in pairing mode, tap **scan**, then tap the device. SSH shows who's connected and a log of logins, and is view only.

## From the laptop

```sh
ssh root@192.168.42.129                                  # log in: USB only, key-based
scp song.mp3 root@192.168.42.129:/data/music/            # add music, then reopen the app
tools/deploy.sh                                          # install changes from overlay/ and native/
```

The phone gets internet from Wi-Fi. For internet over the cable instead, run `sudo tools/pc-share-internet.sh`.

Boot logo, boot animation and charging screen changes need a new boot image: see Procedures in `PLAN.md`.

## The chat's key

The chat uses Gemini's free tier, which has per-minute and daily limits. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then run this, paste the key, press Enter, then Ctrl-D:

```sh
ssh root@192.168.42.129 'mkdir -p /etc/trendos && umask 077 && cat > /etc/trendos/gemini-key && rc-service bootscreen restart'
```

To change model, set `WEB_MODEL` in `overlay/usr/local/lib/trendos/tos/config.py`.

## If something goes wrong

| Problem | Fix |
|---|---|
| Screen frozen | `ssh root@192.168.42.129 rc-service bootscreen restart` |
| Won't boot TREND OS | Pull the battery, hold **Vol-Down + Home + Power** for Download mode, then `heimdall flash --KERNEL firmware/trendos/boot-native9.img` (or `boot-native6.img` for Samsung's kernel) |
| Want Android back | Same Download mode, then `heimdall flash --KERNEL firmware/stock/boot.img` (or `firmware/android-rooted/boot-root4.img` for rooted) |
| No logo and no Download mode | Battery out and back in, then hold **Vol-Up** while plugging in USB. The laptop sees a Spreadtrum device, but recovery from there isn't set up yet |

- **Fully off:** "Shut down" with the cable in lands on the charging screen, so unplug it or pull the battery.
- **Battery:** it's always on the charger, so check it for swelling every month or so.

## The repo

| Path | Contents |
|---|---|
| `overlay/` | Everything installed on the phone, mirroring its filesystem. The home screen and apps are in `usr/local/lib/trendos/tos/` |
| `native/` | All our C: the core library, music player, Files server, Web engine and boot programs |
| `bootimg/`, `kernel/` | Building the boot image and our kernel |
| `tools/` | Laptop and test scripts. `tools/ext/` is third-party clones |
| `firmware/` | Boot images and the Alpine base |
| `backup/` | The phone's original bootloader and settings. **Never delete** |
| `assets/music/` | Our own test sounds |

Technical notes are in `PLAN.md`, and the C rules are in `native/README.md`.

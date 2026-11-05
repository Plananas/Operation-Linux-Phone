"""Where TREND OS sound goes: the phone's own outputs, or a connected Bluetooth speaker /
headphones (BlueALSA, service btaudio).

    bt_sink()          address of a connected Bluetooth audio device (A2DP), or None
    bt_device(mac)     ALSA device name to play to it (aplay -D ...)
    route_output()     send the phone's sound to the best output; returns the ALSA device for it
    take_output()      call before playing anything: pauses the music and frees the audio device
    on_take_output(f)  whatever holds the device registers how to let go of it
    music_playing()    whether the music is holding the device, so something less important can wait
    on_music_playing(f) the Music app registers how to tell
"""
import subprocess

PHONE_DEVICE = "plughw:CARD=sprdphone,DEV=0"
HEADPHONES_STATE = "/sys/class/switch/h2w/state"
SPEAKER, HEADPHONES = "/usr/local/sbin/audio-speaker", "/usr/local/sbin/audio-headphones"

_releases = []
_music_playing = None


def on_take_output(release):
    _releases.append(release)


def take_output():
    for release in _releases:
        release()


def on_music_playing(playing):
    global _music_playing
    _music_playing = playing


def music_playing():
    return _music_playing is not None and _music_playing()


def _headphones_in():
    try:
        with open(HEADPHONES_STATE) as f:
            return int(f.read()) != 0
    except (OSError, ValueError):
        return False


def route_output():
    """Bluetooth, then wired headphones, then the speaker: the same order as native/player/player.c."""
    mac = bt_sink()
    if mac:
        return bt_device(mac)
    off, on = (SPEAKER, HEADPHONES) if _headphones_in() else (HEADPHONES, SPEAKER)
    subprocess.run([off, "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([on, "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return PHONE_DEVICE


def bt_sink():
    try:
        out = subprocess.run(["bluealsa-cli", "-q", "list-pcms"], capture_output=True, text=True,
                             timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for path in out.split():                   # /org/bluealsa/hci0/dev_XX_XX_.../a2dpsrc/sink
        if "/a2dpsrc/sink" in path and "/dev_" in path:
            return path.split("/dev_")[1].split("/")[0].replace("_", ":")
    return None


def bt_device(mac):
    return f"trendbt:DEV={mac}"

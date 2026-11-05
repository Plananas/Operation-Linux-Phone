"""Where TREND OS sound goes: the phone's own outputs, or a connected Bluetooth speaker /
headphones (BlueALSA, service btaudio).

    bt_sink()          address of a connected Bluetooth audio device (A2DP), or None
    bt_device(mac)     ALSA device name to play to it (aplay -D ...)
    take_output()      call before playing anything: pauses the music and frees the audio device
    on_take_output(f)  the Music app registers how to do that
"""
import subprocess

_release_music = None


def on_take_output(release):
    global _release_music
    _release_music = release


def take_output():
    if _release_music is not None:
        _release_music()


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

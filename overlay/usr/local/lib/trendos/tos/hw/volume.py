"""The system volume: one level for everything that plays, kept across restarts. The shell changes
it (volume keys, the bar on screen); the apps that make sound follow it. Alarms don't, so that a
phone left turned down still wakes you.

    level()          0 .. MAX
    change(steps)    up or down from here
    set_level(n)     to this level
    gain()           what to multiply samples by, for sound that isn't played by the music player
    on_change(f)     f(level) is called after each change, on the caller's thread
"""
import os

from ..config import VOLUME_FILE

MAX = 15                # native/libtrend/include/trend/apps/music.h: TR_MUSIC_VOLUME_MAX
DEFAULT = 10


def _load():
    try:
        with open(VOLUME_FILE) as f:
            return max(0, min(MAX, int(f.read())))
    except (OSError, ValueError):
        return DEFAULT


_level = _load()
_listeners = []


def _save():
    try:
        os.makedirs(os.path.dirname(VOLUME_FILE), exist_ok=True)
        with open(VOLUME_FILE + ".new", "w") as f:
            f.write(str(_level))
        os.replace(VOLUME_FILE + ".new", VOLUME_FILE)
    except OSError:
        pass


def level():
    return _level


def set_level(n):
    global _level
    n = max(0, min(MAX, n))
    if n == _level:
        return
    _level = n
    _save()
    for f in _listeners:
        f(n)


def change(steps):
    set_level(_level + steps)


def gain():
    """The same curve as the music player's gain_of() (native/player/player.c)."""
    return _level * _level / (MAX * MAX)


def on_change(f):
    _listeners.append(f)

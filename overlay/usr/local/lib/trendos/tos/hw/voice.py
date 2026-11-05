"""Blip's voice: a chip-sound babble, where each letter is always the same short note, the way Animal
Crossing's characters talk. say() is given the letters as they appear on screen, so it pauses where the writing
does and stops when the writing is skipped.

The audio device takes one player at a time, so the voice only speaks when it's free: music carries on and Blip is
silent, and an alarm takes the device straight back (audio.take_output).

    voice = Voice(); voice.say(b"hello"); voice.stop()
"""
import collections, subprocess, threading, time

import numpy as np

from . import audio, volume

RATE = 11025                   # low on purpose: the crunch of an old sound chip
CHUNK = 256                    # samples written at a time: 23 ms
LEAD_S = 0.05                  # how far ahead of the clock to write, which is how late the sound is
IDLE_S = 1.0                   # let go of the device after this long with nothing to say
BLIP_S, GAP_S = 0.055, 0.015   # each note, and the silence after it: about 14 a second, whatever the writing speed
LOUDNESS = 0.4
STEPS = 8                      # volume steps in a note's fade
BASE_HZ = 520.0
SCALE = (0, 2, 4, 7, 9, 12, 14, 16)                    # pentatonic semitones, so that any babble sounds tuneful
VOWELS, HISSES = "aeiouy", "bcdfgjkpqstvxz"


def _note(ch):
    """The samples for one letter. The same letter always sounds the same."""
    n = int(BLIP_S * RATE)
    t = np.arange(n) / n
    vowel = ch in VOWELS
    hz = BASE_HZ * 2.0 ** (SCALE[ord(ch) * 7 % len(SCALE)] / 12.0)
    phase = np.cumsum(hz * (1.0 + 0.12 * (1.0 - t))) / RATE       # starts a little sharp and falls
    wave = np.where(phase % 1.0 < (0.5 if vowel else 0.25), 1.0, -1.0)
    if ch in HISSES:                                              # a consonant starts with a burst of noise
        burst = int(0.008 * RATE)
        noise = np.random.default_rng(ord(ch)).choice((-1.0, 1.0), burst // 3 + 1)
        wave[:burst] = np.repeat(noise, 3)[:burst]
    fade = np.ceil(np.minimum(t * 12.0, 1.0) * (1.0 - t * 0.7) * STEPS) / STEPS
    return np.concatenate((wave * fade * LOUDNESS * 32767.0, np.zeros(int(GAP_S * RATE)))).astype(np.float32)


class Voice:
    def __init__(self):
        self._pending = collections.deque(maxlen=16)
        self._notes = {}
        self._left = np.zeros(0, np.float32)     # the rest of the note being played
        self._stop = threading.Event()
        self._thread = self._proc = None
        self._spoke_at = 0.0
        audio.on_take_output(self.stop)

    def say(self, letters):
        """Latin-1 bytes that have just appeared. Doesn't wait."""
        if volume.level() == 0 or audio.music_playing():
            return
        self._pending.extend(letters)
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._spoke_at = time.monotonic()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop now and let go of the device. Returns once it has."""
        thread = self._thread
        self._stop.set()
        proc = self._proc
        if proc is not None:
            proc.kill()                          # in case it's stuck: a write to it can't then block
        if thread is not None and thread is not threading.current_thread():
            thread.join(1.0)
        self._pending.clear()

    def _next_note(self):
        """The newest letter waiting: the writing can be much faster than notes can follow. None if there isn't one."""
        letters = [chr(c).lower() for c in self._pending if chr(c).isalnum()]
        self._pending.clear()
        if not letters:
            return None
        self._spoke_at = time.monotonic()
        ch = letters[-1]
        if ch not in self._notes:
            self._notes[ch] = _note(ch)
        return self._notes[ch]

    def _chunk(self):
        out, at = np.zeros(CHUNK, np.float32), 0
        while at < CHUNK:
            if not len(self._left):
                note = self._next_note()
                if note is None:
                    break
                self._left = note
            n = min(CHUNK - at, len(self._left))
            out[at:at + n] = self._left[:n]
            self._left = self._left[n:]
            at += n
        return (out * volume.gain()).astype(np.int16).tobytes()

    def _run(self):
        try:
            self._proc = subprocess.Popen(["aplay", "-q", "-D", audio.route_output(), "-f", "S16_LE", "-c", "1",
                                           "-r", str(RATE), "-t", "raw", "-B", "100000"],
                                          stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        except OSError:
            return
        proc = self._proc
        chunk_s, wrote_to = CHUNK / RATE, time.monotonic()
        try:
            while not self._stop.is_set() and time.monotonic() - self._spoke_at < IDLE_S:
                proc.stdin.write(self._chunk())  # paced by the clock, so the pipe can't fill up and add a delay
                wrote_to = max(wrote_to, time.monotonic()) + chunk_s
                self._stop.wait(max(0.0, wrote_to - time.monotonic() - LEAD_S))
        except OSError:
            pass                                 # it went away: an output disconnected, or stop()
        finally:
            self._proc = None
            self._left = np.zeros(0, np.float32)
            proc.kill()
            proc.wait()
            proc.stdin.close()

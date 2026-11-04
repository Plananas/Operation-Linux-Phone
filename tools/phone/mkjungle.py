#!/usr/bin/env python3
"""Synthesise a test track for the Music app: "Polygon Jungle", original jungle / drum and bass in
the style of late-90s console audio. Nothing is sampled; every sound is made here.

The console sound comes from how it's built: voices run at 22 kHz, drums and stabs go through
4-bit ADPCM like the PS1's sound chip, and the mix sits in a long, dark reverb.

Needs numpy, so run it on the phone: python3 -I mkjungle.py out.wav   (about two minutes; same result
every time). Convert it to FLAC, not MP3: libsndfile's MP3 encoder on the phone writes bursts of noise.
"""
import sys
import wave

import numpy as np

SR = 22050                     # the voices' rate; the file is 44.1 kHz
OUT_SR = 44100
BPM = 165
STEP = 60 / BPM / 4            # a 16th note
BAR = STEP * 16
SWING = 0.10                   # off-beat 16ths land this fraction of a step late
SECTIONS = {"intro": (0, 8), "main": (8, 24), "breakdown": (24, 32), "peak": (32, 48), "outro": (48, 52)}
BARS = 52
TAIL = 4.0                     # seconds of reverb after the last bar
N = int((BARS * BAR + TAIL) * SR)
rng = np.random.default_rng(1998)


def note(n):
    """Frequency of MIDI note n."""
    return 440.0 * 2 ** ((n - 69) / 12)


# Fm9 | Dbmaj7 | Bbm9 | C7sus, two bars each
CHORDS = [(53, 60, 63, 67, 72), (49, 56, 60, 65, 68), (46, 53, 60, 61, 65), (48, 55, 58, 60, 65)]
ROOTS = [29, 25, 22, 24]


def chord_at(bar):
    return bar // 2 % 4


# ---- signal tools ------------------------------------------------------------------------------
def times(seconds):
    return np.arange(int(seconds * SR)) / SR


def spectral(x, gain_of):
    """Filter x by a gain curve over frequency."""
    size = 1 << int(np.ceil(np.log2(len(x) * 1.05 + 64)))     # padded: nothing wraps round the ends
    f = np.fft.rfftfreq(size, 1 / SR)
    return np.fft.irfft(np.fft.rfft(x, size) * gain_of(f), size)[:len(x)]


def lowpass(x, cutoff, order=2):
    return spectral(x, lambda f: 1 / (1 + (f / cutoff) ** (2 * order)))


def highpass(x, cutoff, order=2):
    return spectral(x, lambda f: 1 - 1 / (1 + (f / cutoff) ** (2 * order)))


def bandpass(x, lo, hi):
    return highpass(lowpass(x, hi), lo)


def saw(freq, t, phase=0.0):
    return 2 * ((freq * t + phase) % 1.0) - 1


def adpcm(x):
    """Crunch a sound through PS1-style ADPCM: 28-sample blocks of 4-bit deltas, each block with the
    best shift for its loudest moment. It's what gives the drums their grit."""
    x = np.clip(x, -1, 1) * 32767
    out = np.zeros(len(x))
    s1, s2 = 0.0, 0.0
    for start in range(0, len(x), 28):
        block = x[start:start + 28]
        # the second-order predictor the chip uses most, estimated from this block
        pred = 2 * s1 - s2 if start else 0.0
        peak = max(np.abs(block - pred).max(), 1.0)
        shift = max(0, int(np.ceil(np.log2(peak / 7))))
        for i, v in enumerate(block):
            p = 1.8 * s1 - 0.81 * s2
            d = max(-8, min(7, round((v - p) / 2 ** shift)))
            s2, s1 = s1, max(-32768.0, min(32767.0, p + d * 2 ** shift))
            out[start + i] = s1
    return out / 32767


def normalised(x, peak=1.0):
    return x * peak / max(np.abs(x).max(), 1e-9)


# ---- instruments -------------------------------------------------------------------------------
def make_kick():
    t = times(0.26)
    pitch = 48 + 150 * np.exp(-t * 38)
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-t * 11)
    click = lowpass(rng.standard_normal(len(t)), 3500) * np.exp(-t * 260) * 0.8
    return adpcm(normalised(np.tanh(2.2 * body + click)))


def make_snare():
    t = times(0.2)
    tone = (np.sin(2 * np.pi * 196 * t) + 0.6 * np.sin(2 * np.pi * 332 * t)) * np.exp(-t * 26)
    noise = bandpass(rng.standard_normal(len(t)), 900, 7500) * np.exp(-t * 17)
    return adpcm(normalised(np.tanh(1.8 * (0.8 * tone + normalised(noise)))))


def make_ghost():
    t = times(0.09)
    noise = bandpass(rng.standard_normal(len(t)), 1200, 8000) * np.exp(-t * 42)
    tone = np.sin(2 * np.pi * 240 * t) * np.exp(-t * 55)
    return adpcm(normalised(noise + 0.5 * tone))


def make_hat(length, decay):
    t = times(length)
    return adpcm(normalised(highpass(rng.standard_normal(len(t)), 6000) * np.exp(-t * decay)))


def make_ride():
    t = times(0.55)
    ratios = (1.0, 1.48, 1.83, 2.41, 2.97, 3.56)
    metal = sum(np.sign(np.sin(2 * np.pi * 1180 * r * t)) for r in ratios)
    return adpcm(normalised(highpass(metal, 3000) * np.exp(-t * 7.5)))


def make_stab(notes):
    t = times(0.42)
    tone = sum(saw(note(n + 12) * d, t) for n in notes for d in (0.997, 1.003))
    return adpcm(normalised(lowpass(tone, 2600) * np.minimum(t * 300, 1) * np.exp(-t * 9)))


def make_bell(n):
    """Two-operator FM: the glassy lead."""
    t = times(0.9)
    f = note(n)
    mod = np.sin(2 * np.pi * f * 3.5 * t) * 2.6 * np.exp(-t * 7)
    return normalised(np.sin(2 * np.pi * f * t + mod) * np.exp(-t * 4.2))


def make_pluck(n):
    t = times(0.2)
    square = np.sign(np.sin(2 * np.pi * note(n) * t))
    return normalised(lowpass(square, 3000) * np.exp(-t * 18))


def make_reverse_snare():
    t = times(STEP * 4)
    noise = bandpass(rng.standard_normal(len(t)), 900, 6000) * np.exp((t - t[-1]) * 7)
    return adpcm(normalised(noise))


# ---- the mix -----------------------------------------------------------------------------------
class Bus:
    def __init__(self):
        self.l, self.r = np.zeros(N), np.zeros(N)

    def add(self, sound, at, gain=1.0, pan=0.5):
        start = int(at * SR)
        if start < 0 or start >= N:
            return
        s = sound[:N - start] * gain
        self.l[start:start + len(s)] += s * np.cos(pan * np.pi / 2)
        self.r[start:start + len(s)] += s * np.sin(pan * np.pi / 2)

    def add_stereo(self, left, right, gain=1.0):
        self.l += left * gain
        self.r += right * gain


def step_time(bar, step):
    return (bar + step / 16) * BAR + (SWING * STEP if step % 2 else 0.0)


def resampled(sound, ratio):
    """Play a sample faster or slower, as a sampler would: pitch and length change together."""
    return np.interp(np.arange(0, len(sound), ratio), np.arange(len(sound)), sound)


# Two bars of chopped break, a step per character: k kick, s snare, g ghost snare, - nothing.
BREAKS = [
    "k-g-s--gk-k-s-g-" "k-g-s-g--kg-s-gs",
    "k---s-g-k-g-s--g" "--k-s-gkg-k-s-g-",
    "k-g-s--g-gk-s-g-" "k-gks-g--k-gs-ss",
]
FILLS = ["s-gss-gsg-ss-gsg", "kgs-gsk-sgssgsss"]


def drums(bus, room):
    kick, snare, ghost = make_kick(), make_snare(), make_ghost()
    closed, opened, ride = make_hat(0.05, 90), make_hat(0.2, 20), make_ride()
    reverse = make_reverse_snare()
    voices = {"k": (kick, 0.95), "s": (snare, 0.85), "g": (ghost, 0.42)}

    def in_section(bar, name):
        lo, hi = SECTIONS[name]
        return lo <= bar < hi

    for bar in range(BARS):
        playing_break = in_section(bar, "main") or in_section(bar, "peak")
        last_of_phrase = bar % 8 == 7
        pattern = BREAKS[(bar // 2) % len(BREAKS)][(bar % 2) * 16:(bar % 2) * 16 + 16]
        if last_of_phrase:
            pattern = pattern[:8] + FILLS[bar // 8 % 2][8:]
        if playing_break:
            for step, hit in enumerate(pattern):
                if hit in voices:
                    sound, gain = voices[hit]
                    # the small pitch moves of a chopped-up break
                    ratio = 1.0 + 0.04 * rng.choice((-1, 0, 0, 1)) if hit != "k" else 1.0
                    bus.add(resampled(sound, ratio), step_time(bar, step), gain * rng.uniform(0.9, 1.0), 0.5)
                    room.add(sound, step_time(bar, step), gain * (0.5 if hit == "s" else 0.12))
            for step in range(0, 16, 2):
                bus.add(closed, step_time(bar, step + 1), 0.24 + 0.08 * (step % 4 == 2), 0.62)
            if bar % 2 == 0:
                bus.add(opened, step_time(bar, 14), 0.22, 0.62)
            if in_section(bar, "peak"):
                for step in range(0, 16, 4):
                    bus.add(ride, step_time(bar, step), 0.14, 0.34)
            if (bar + 1) % 16 == 0 and bar + 1 < BARS:
                room.add(reverse, step_time(bar, 12), 0.5)
                bus.add(reverse, step_time(bar, 12), 0.35)
        elif in_section(bar, "intro") and bar >= 4:
            for step in range(0, 16, 4):             # a filtered ride hints at what's coming
                bus.add(ride, step_time(bar, step), 0.05 + 0.012 * (bar - 4), 0.4)
            if bar == 7:
                room.add(reverse, step_time(bar, 12), 0.6)
                bus.add(reverse, step_time(bar, 12), 0.5)
                for step in (8, 10, 11, 13, 14, 15):
                    bus.add(snare, step_time(bar, step), 0.3 + 0.03 * step)
        elif in_section(bar, "breakdown") and bar >= 28:
            for step in range(0, 16, 2 if bar < 31 else 1):  # the roll back in
                bus.add(ghost, step_time(bar, step), 0.2 + 0.03 * (bar - 28) + 0.012 * step, 0.5)


def bass():
    """Reese: detuned saws with a slow filter sweep, saturated so it still speaks on a tiny speaker,
    over a clean sub. Rendered as one long take so the phasing keeps moving."""
    # bars to a note, on the 16ths where it moves: the bassline's two-bar shape
    freq = np.zeros(N)
    gate = np.zeros(N)
    shape = ((0, 0, 5), (5, 0, 3), (8, 12, 2), (10, 0, 4), (16, 0, 6), (22, 7, 2), (24, 0, 4), (28, 3, 4))
    for bar in range(0, BARS, 2):
        section_on = SECTIONS["main"][0] <= bar < SECTIONS["breakdown"][0] or \
            SECTIONS["peak"][0] <= bar < SECTIONS["outro"][0]
        root = ROOTS[chord_at(bar)]
        for step, interval, length in shape:
            a = int((bar + step / 16) * BAR * SR)
            b = min(N, a + int(length * STEP * SR))
            freq[a:b] = note(root + interval)
            if section_on:
                gate[a:b] = 1.0
    # breakdown: long held roots only
    for bar in range(*SECTIONS["breakdown"]):
        a, b = int(bar * BAR * SR), int((bar + 1) * BAR * SR)
        freq[a:b] = note(ROOTS[chord_at(bar)])
        gate[a:b] = 0.55 if bar % 2 == 0 else 0.0
    # a rest holds the last pitch, so the filter and phase carry on through it
    freq = freq[np.maximum.accumulate(np.where(freq > 0, np.arange(N), 0))]
    # glide between notes and soften the gate, so it's a voice rather than clicks
    freq = np.convolve(freq, np.ones(220) / 220, "same")
    gate = np.convolve(gate, np.ones(90) / 90, "same")

    phase = np.cumsum(freq) / SR
    reese = (2 * (phase * 2 * 0.993 % 1) - 1) + (2 * (phase * 2 * 1.007 % 1) - 1) + 0.6 * (2 * (phase * 1.0 % 1) - 1)
    dark, bright = lowpass(reese, 260), lowpass(reese, 1100)
    t = np.arange(N) / SR
    sweep = 0.5 + 0.5 * np.sin(2 * np.pi * t / (BAR * 2))
    voiced = np.tanh(2.4 * (dark * (1 - sweep) + bright * sweep)) * gate
    sub = np.sin(2 * np.pi * phase) * gate
    return 0.55 * voiced + 0.45 * sub


def pads():
    """Slow detuned chords in stereo. Rendered per two bars, then crossfaded."""
    left, right = np.zeros(N), np.zeros(N)
    length = BAR * 2 + 1.0
    t = times(length)
    env = np.minimum(t / 0.35, 1) * np.minimum((length - t) / 0.9, 1)
    for bar in range(0, BARS, 2):
        for side, out in ((0.0, left), (0.37, right)):
            tone = sum(saw(note(n) * d, t, side + i * 0.13)
                       for i, n in enumerate(CHORDS[chord_at(bar)]) for d in (0.996, 1.004))
            tone = lowpass(tone, 1500) * env
            a = int(bar * BAR * SR)
            part = tone[:N - a]
            out[a:a + len(part)] += part
    peak = max(np.abs(left).max(), np.abs(right).max())
    return left / peak, right / peak


# Peak-section melody: (bar in a 4-bar loop, 16th, MIDI note).
MELODY = [(0, 0, 77), (0, 6, 80), (0, 10, 82), (1, 0, 84), (1, 8, 80), (2, 0, 77), (2, 6, 75), (2, 12, 73),
          (3, 0, 72), (3, 4, 75), (3, 10, 77)]
ARP = (0, 3, 2, 4, 1, 3, 2, 4)


def melodic(bus, wet):
    bells, plucks, stabs = {}, {}, [make_stab(c[:4]) for c in CHORDS]
    for bar in range(BARS):
        chord = CHORDS[chord_at(bar)]
        if 2 <= bar < 8 or 24 <= bar < 32 or 40 <= bar < 48:     # the arpeggio
            for step in range(0, 16, 2):
                n = chord[ARP[(step // 2) % 8]] + 12
                sound = plucks.setdefault(n, make_pluck(n))
                level = 0.13 if bar >= 24 else 0.03 + 0.016 * bar
                pan = 0.25 + 0.5 * ((step // 2) % 2)
                bus.add(sound, step_time(bar, step), level, pan)
                wet.add(sound, step_time(bar, step), level * 0.8)
        if 8 <= bar < 24 or 32 <= bar < 48:                      # the off-beat stab
            if bar % 2 == 0:
                for step in (3, 11):
                    stab = stabs[chord_at(bar)]
                    bus.add(stab, step_time(bar, step), 0.2, 0.42)
                    wet.add(stab, step_time(bar, step), 0.35)
                    wet.add(stab, step_time(bar, step + 3), 0.16)   # a dotted echo
        if 32 <= bar < 48:                                       # the lead
            for loop_bar, step, n in MELODY:
                if bar % 4 == loop_bar:
                    sound = bells.setdefault(n, make_bell(n))
                    bus.add(sound, step_time(bar, step), 0.2, 0.55)
                    wet.add(sound, step_time(bar, step), 0.3)
                    wet.add(sound, step_time(bar, step + 3), 0.14, 0.2)
                    wet.add(sound, step_time(bar, step + 6), 0.07, 0.8)


def convolve(signal, ir):
    """Block by block, because one transform of the whole song doesn't fit in the phone's memory."""
    block = 1 << 16
    size = block * 2
    while size < block + len(ir):
        size *= 2
    spectrum = np.fft.rfft(ir, size)
    out = np.zeros(len(signal) + size)
    for start in range(0, len(signal), block):
        part = np.fft.irfft(np.fft.rfft(signal[start:start + block], size) * spectrum, size)
        out[start:start + size] += part
    return out[:len(signal)]


def reverb(wet):
    """A long dark room: two decorrelated noise tails, convolved. Dark and a touch metallic, like the
    console's hall presets."""
    n_ir = int(3.2 * SR)
    t = np.arange(n_ir) / SR
    out = []
    for signal in (wet.l, wet.r):
        ir = lowpass(rng.standard_normal(n_ir), 3200) * np.exp(-t * 2.3)
        ir[:int(0.022 * SR)] = 0.0                       # predelay
        ir /= np.sqrt(np.sum(ir ** 2))
        out.append(convolve(signal, ir))
    return out


def main(path):
    drum_bus, room, wet, music = Bus(), Bus(), Bus(), Bus()
    print("drums", flush=True)
    drums(drum_bus, room)
    print("melody", flush=True)
    melodic(music, wet)
    print("bass and pads", flush=True)
    low = bass()
    pad_l, pad_r = pads()

    # The pad swells in, ducks under the break, and gets the final word.
    t = np.arange(N) / SR
    pad_level = np.interp(t, np.array([0, 4, 8, 24, 26, 32, 48, 50, 52, 54]) * BAR,
                          [0.0, 0.32, 0.26, 0.18, 0.34, 0.3, 0.18, 0.32, 0.3, 0.0])
    print("reverb", flush=True)
    room_l, room_r = reverb(room)
    wet_l, wet_r = reverb(wet)
    del room, wet

    # Sidechain: the music breathes around the kick and snare, which is most of what makes it pump.
    env = np.convolve(np.abs(drum_bus.l + drum_bus.r), np.ones(600) / 600, "same")
    duck = 1 - 0.5 * np.clip(env / max(env.max(), 1e-9) * 1.8, 0, 1)

    drums_l, drums_r = np.tanh(1.25 * (drum_bus.l + 0.3 * room_l)), np.tanh(1.25 * (drum_bus.r + 0.3 * room_r))
    left = drums_l * 0.85 + duck * (low * 0.42 + pad_l * pad_level + music.l + wet_l * 0.5)
    right = drums_r * 0.85 + duck * (low * 0.42 + pad_r * pad_level + music.r + wet_r * 0.5)
    del drum_bus, music, low, pad_l, pad_r, room_l, room_r, wet_l, wet_r, drums_l, drums_r, env, duck, pad_level, t

    # The chip's output: 22 kHz voices, slightly dull, upsampled.
    left, right = lowpass(left, 9500), lowpass(right, 9500)
    peak = max(np.abs(left).max(), np.abs(right).max())
    left, right = np.tanh(left / peak * 1.3) * 0.89 / np.tanh(1.3), np.tanh(right / peak * 1.3) * 0.89 / np.tanh(1.3)

    n_out = N * OUT_SR // SR
    x = np.arange(n_out, dtype=np.float64) * SR / OUT_SR    # float: this overflows the phone's 32-bit ints
    fade = np.minimum((n_out - np.arange(n_out)) / (OUT_SR * 1.5), 1.0)
    left, right = np.interp(x, np.arange(N), left) * fade, np.interp(x, np.arange(N), right) * fade

    stereo = np.empty(n_out * 2, np.int16)
    stereo[0::2], stereo[1::2] = (np.clip(left, -1, 1) * 32767).astype(np.int16), (np.clip(right, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(OUT_SR)
        w.writeframes(stereo.tobytes())

    print(f"{path}: {n_out / OUT_SR:.1f} s")
    for name, (a, b) in SECTIONS.items():
        part = left[int(a * BAR * OUT_SR):int(b * BAR * OUT_SR)]
        print(f"  {name:10s} bars {a:2d}-{b:2d}  rms {np.sqrt(np.mean(part ** 2)):.3f}  peak {np.abs(part).max():.3f}")
    clipped = int(np.sum(np.abs(left) > 0.999) + np.sum(np.abs(right) > 0.999))
    print(f"  clipped samples: {clipped}")


if __name__ == "__main__":
    main(sys.argv[1])

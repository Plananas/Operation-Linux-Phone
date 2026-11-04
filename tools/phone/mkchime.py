#!/usr/bin/env python3
"""Synthesise "Chime": a soft, pleasant sound in the family of the startup sound (mksound.py), and a
clean thing to test the Music app with. Warm A-major pad, five slow bell notes rising over it, a long
dark reverb. Energy is kept above about 180 Hz, because the phone's speaker can't move anything lower.
Needs numpy, so run it on the phone: python3 -I mkchime.py out.wav
"""
import sys
import wave

import numpy as np

SR = 44100
DUR = 8.0
N = int(SR * DUR)
PEAK = 0.6                     # gentle on purpose
t = np.arange(N) / SR
rng = np.random.default_rng(7)


def note(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def highpass(x, cutoff):
    size = 1 << int(np.ceil(np.log2(len(x) * 2)))
    f = np.fft.rfftfreq(size, 1 / SR)
    return np.fft.irfft(np.fft.rfft(x, size) * (1 - 1 / (1 + (f / cutoff) ** 4)), size)[:len(x)]


def pad(pan):
    """Sine stacks with a little detune: it moves slowly, and has no edges to it."""
    level = smooth(t / 1.8) * smooth((DUR - 0.5 - t) / 4.5)
    out = np.zeros(N)
    for n, gain in ((57, 0.8), (64, 0.7), (69, 0.6), (73, 0.42), (76, 0.28), (83, 0.12)):
        for detune, phase in ((0.9985, pan), (1.0015, pan + 0.9)):
            f = note(n) * detune
            out += gain * (np.sin(2 * np.pi * f * t + phase) + 0.18 * np.sin(4 * np.pi * f * t + phase))
    return out * level


def bell(n, at, gain):
    """A soft mallet: mostly the fundamental, with upper partials that fade first."""
    u = np.maximum(t - at, 0.0)
    attack = smooth(u / 0.012)
    f = note(n)
    tone = np.sin(2 * np.pi * f * u) * np.exp(-u * 1.1)
    tone += 0.22 * np.sin(2 * np.pi * f * 2.0 * u) * np.exp(-u * 2.4)
    tone += 0.05 * np.sin(2 * np.pi * f * 3.01 * u) * np.exp(-u * 5.0)
    return gain * attack * tone * smooth((DUR - t) / 1.0)


def reverb(x):
    """A long, dark hall: a noise tail convolved with the dry sound."""
    n_ir = int(3.6 * SR)
    u = np.arange(n_ir) / SR
    size = 1 << int(np.ceil(np.log2(N + n_ir)))
    f = np.fft.rfftfreq(size, 1 / SR)
    ir = np.fft.irfft(np.fft.rfft(rng.standard_normal(n_ir), size) / (1 + (f / 2400) ** 4), size)[:n_ir]
    ir *= np.exp(-u * 1.7)
    ir[:int(0.03 * SR)] = 0.0
    ir /= np.sqrt(np.sum(ir ** 2))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:N]


# The bells rise through the chord, then one settles back: (note, time, gain, pan).
BELLS = ((69, 0.55, 0.60, 0.45), (73, 1.00, 0.52, 0.60), (76, 1.45, 0.50, 0.38),
         (81, 1.95, 0.46, 0.62), (83, 2.55, 0.26, 0.50), (76, 3.15, 0.30, 0.42))

dry_l, dry_r = pad(0.0) * 0.10, pad(1.3) * 0.10
for n, at, gain, pan in BELLS:
    b = bell(n, at, gain)
    dry_l += b * np.cos(pan * np.pi / 2)
    dry_r += b * np.sin(pan * np.pi / 2)

left = highpass(dry_l + 0.55 * reverb(dry_l), 180)
right = highpass(dry_r + 0.55 * reverb(dry_r), 180)
fade = smooth((DUR - t) / 1.2)
scale = PEAK / max(np.abs(left).max(), np.abs(right).max())
left, right = left * scale * fade, right * scale * fade

stereo = np.empty(N * 2, np.int16)
stereo[0::2], stereo[1::2] = (left * 32767).astype(np.int16), (right * 32767).astype(np.int16)
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(stereo.tobytes())

F = np.abs(np.fft.rfft(left)) ** 2
f = np.fft.rfftfreq(N, 1 / SR)
print(f"{sys.argv[1]}: {DUR} s, peak {np.abs(left).max():.2f}, rms {np.sqrt(np.mean(left ** 2)):.3f}, "
      f"below 150 Hz {100 * F[f < 150].sum() / F.sum():.1f}%, above 4 kHz {100 * F[f > 4000].sum() / F.sum():.2f}%, "
      f"biggest step {np.abs(np.diff(left)).max():.3f}")

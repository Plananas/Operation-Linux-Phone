#!/usr/bin/env python3
"""Synthesise the TREND OS startup sound, v2 (original; dark, cinematic late-90s console feel).
No melody: dark swell + low rush -> soft heavy impact + one lush sustained A-major pad chord
that blooms, slowly darkens and hangs in a long dark reverb. Tuned for a tiny phone speaker
(energy kept above ~150 Hz). Usage: mksound.py out.wav"""
import sys, wave
import numpy as np

SR = 44100
DUR = 6.0                          # 1 s shorter than v2; swell/impact timing unchanged
T_HIT = 2.6
rng = np.random.default_rng(11)
t = np.arange(int(SR * DUR)) / SR
L = np.zeros_like(t); R = np.zeros_like(t)

def smooth(x):
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

def saw_bank(freqs_gains_pans, env, cutoff, top=4500):
    """Detuned band-limited saws through a time-varying 4-pole-ish low-pass."""
    global L, R
    for f0, gain, pan in freqs_gains_pans:
        for det, dp in ((-0.0045, -0.2), (0.0, 0.0), (0.0045, 0.2)):
            f = f0 * (1 + det); ph = rng.uniform(0, 2 * np.pi)
            sig = np.zeros_like(t)
            for k in range(1, int(top / f) + 1):
                sig += np.sin(2 * np.pi * k * f * t + ph * k) / (k * (1.0 + (k * f / cutoff) ** 4))
            sig *= gain * env
            p = np.clip(pan + dp, 0, 1)
            L += sig * (1 - p); R += sig * p

# ---- 1. dark swell before the hit (A2, E3, A3), filter opens only partly ----
pre = smooth(t / T_HIT) ** 1.8 * np.where(t < T_HIT, 1.0, np.exp(-(t - T_HIT) / 0.35))
saw_bank([(110.0, 0.7, 0.4), (164.81, 0.6, 0.6), (220.0, 0.45, 0.5)], pre,
         cutoff=200 + 1300 * smooth(t / T_HIT), top=3000)

# ---- 2. low rush building into the hit (dark band-passed noise) ----
noise = rng.standard_normal((2, len(t)))
spec = np.fft.rfft(noise, axis=1); fr = np.fft.rfftfreq(len(t), 1 / SR)
spec *= np.exp(-((np.log(fr + 1) - np.log(900)) ** 2) / 0.6)
noise = np.fft.irfft(spec, n=len(t), axis=1); noise /= np.abs(noise).max()
renv = smooth(t / T_HIT) ** 4 * np.where(t < T_HIT, 1.0, np.exp(-(t - T_HIT) / 0.12))
L += 0.5 * noise[0] * renv; R += 0.5 * noise[1] * renv

# ---- 3. impact: pitch-dropping boom, saturated so harmonics reach a small speaker ----
tt = np.clip(t - T_HIT, 0, None); on = (t >= T_HIT).astype(float)
fboom = 90 + 130 * np.exp(-tt / 0.08)                       # 220 Hz -> 90 Hz glide
boom = np.sin(2 * np.pi * np.cumsum(fboom) / SR) * on * np.exp(-tt / 0.45)
boom = np.tanh(2.5 * boom) * 0.8
thud = noise[0] * on * np.exp(-tt / 0.06) * 0.5              # soft transient
L += boom + thud; R += boom + thud

# ---- 4. lush sustained chord: A3 E4 A4 C#5 E5, blooms in, slowly darkens ----
bloom = on * smooth(tt / 0.35) * np.exp(-tt / 1.7)
darken = 900 + 2200 * np.exp(-tt / 1.8)                      # filter slowly closes
saw_bank([(220.0, 0.55, 0.35), (329.63, 0.5, 0.65), (440.0, 0.45, 0.4),
          (554.37, 0.35, 0.6), (659.26, 0.3, 0.5)], bloom, cutoff=darken, top=4500)
# airy "choir" layer: soft sines an octave up with slow vibrato
vib = 1 + 0.003 * np.sin(2 * np.pi * 5.0 * t)
for f0, pan in ((880.0, 0.3), (1108.73, 0.7), (1318.51, 0.5)):
    s = 0.12 * np.sin(2 * np.pi * f0 * np.cumsum(vib) / SR) * on * smooth(tt / 0.6) * np.exp(-tt / 1.6)
    L += s * (1 - pan); R += s * pan

# ---- 5. long dark reverb ----
irn = int(SR * 3.6); ti = np.arange(irn) / SR
def ir():
    x = rng.standard_normal(irn) * np.exp(-ti / 0.9); x[:int(0.02 * SR)] = 0
    X = np.fft.rfft(x); f = np.fft.rfftfreq(irn, 1 / SR); X *= 1 / (1 + (f / 3000) ** 2)   # dark
    x = np.fft.irfft(X, n=irn); return x / np.sqrt((x ** 2).sum())
n = len(t) + irn
wetL = np.fft.irfft(np.fft.rfft(L, n) * np.fft.rfft(ir(), n), n)[:len(t)]
wetR = np.fft.irfft(np.fft.rfft(R, n) * np.fft.rfft(ir(), n), n)[:len(t)]
L = 0.7 * L + 0.7 * wetL; R = 0.7 * R + 0.7 * wetR

# ---- 6. tiny-speaker EQ (cut < 150 Hz), fade out, normalise ----
out = np.stack([L, R])
spec = np.fft.rfft(out, axis=1); fr = np.fft.rfftfreq(out.shape[1], 1 / SR)
spec *= 1 / (1 + (150 / np.maximum(fr, 1)) ** 4)
out = np.fft.irfft(spec, n=out.shape[1], axis=1)
fade = np.clip((DUR - t) / 2.0, 0, 1)               # last 2 s: cosine ease into silence
out *= 0.5 - 0.5 * np.cos(np.pi * fade)
out = out / np.abs(out).max() * 0.85
pcm = (out.T * 32767).astype("<i2")
w = wave.open(sys.argv[1], "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
w.writeframes(pcm.tobytes()); w.close()
print("wrote", sys.argv[1], f"{DUR}s")

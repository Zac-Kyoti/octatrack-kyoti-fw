#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
A synthetic boom-bap drum loop for listening tests (tools/repitch_ab_pack.py): two bars,
swung 16ths, kick / snare (with a ghost) / closed and open hats, a short stereo room.
Every sound is synthesised here (numpy only), so the clip carries no third-party audio.

    python3 tools/repitch_test_beat.py out/ab_pack2/beat.wav --bpm 104
"""
import argparse
import math
import pathlib
import wave

import numpy as np

SR = 44100
rng = np.random.default_rng(1200)


def band(x, lo=None, hi=None, n=2):
    """Zero-phase band-limit in the frequency domain (Butterworth-shaped magnitude)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    f[0] = 1e-3
    H = np.ones_like(f)
    if lo:
        H /= np.sqrt(1 + (lo / f) ** (2 * n))
    if hi:
        H /= np.sqrt(1 + (f / hi) ** (2 * n))
    return np.fft.irfft(X * H, len(x))


def env(n, tau, attack=0.0008):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / attack) * np.exp(-t / tau)


def kick(vel=1.0):
    n = int(0.55 * SR)
    t = np.arange(n) / SR
    f = 48 + 120 * np.exp(-t / 0.032)
    body = np.sin(2 * math.pi * np.cumsum(f) / SR) * env(n, 0.26)
    click = band(rng.standard_normal(n), 1500, 7000) * env(n, 0.004) * 0.35
    return np.tanh(2.2 * vel * (body + click)) / np.tanh(2.2)


def snare(vel=1.0):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    body = (np.sin(2 * math.pi * 186 * t) + 0.6 * np.sin(2 * math.pi * 331 * t)) * env(n, 0.07)
    wires = band(rng.standard_normal(n), 1800, 9500) * env(n, 0.16)
    crack = band(rng.standard_normal(n), 3000, 14000) * env(n, 0.012)
    return np.tanh(1.6 * vel * (0.55 * body + 0.7 * wires + 0.5 * crack))


def hat(vel=1.0, open_=False):
    n = int((0.5 if open_ else 0.09) * SR)
    t = np.arange(n) / SR
    metal = sum(np.sign(np.sin(2 * math.pi * f * t)) for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
    x = band(0.6 * metal / 6 + 0.8 * rng.standard_normal(n), 6500, 16000, n=3)
    return vel * x * env(n, 0.22 if open_ else 0.022)


def room(x, seconds=0.35, wet=0.2):
    n = int(seconds * SR)
    out = np.zeros((len(x) + n, 2))
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.08 * SR))
        ir = band(ir, 300, 9000)
        ir /= np.sqrt(np.sum(ir ** 2))
        L = len(x) + n
        out[:, c] = np.fft.irfft(np.fft.rfft(x.mean(1), 2 * L) * np.fft.rfft(ir, 2 * L), 2 * L)[:L]
    return np.vstack([x, np.zeros((n, 2))]) * (1 - wet) + out * wet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--bpm", type=float, default=104.0)
    ap.add_argument("--swing", type=float, default=0.58, help="where the off 16th falls, 0.5 = straight")
    a = ap.parse_args()
    s16 = 60.0 / a.bpm / 4
    bars = 2
    n = int(bars * 16 * s16 * SR)
    mix = np.zeros((n + SR, 2))

    def at(step):
        pair, off = divmod(step, 2)
        return int(round((pair * 2 + (2 * a.swing if off else 0)) * s16 * SR))

    def put(sig, step, pan=0.0):
        i = at(step)
        g = np.array([math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)]) * math.sqrt(2)
        mix[i:i + len(sig)] += sig[:, None] * g[None, :]

    # one bar = 16 steps; bar 2 varies the kick and adds a ghost snare and an open hat
    for b in range(bars):
        o = 16 * b
        for st, v in ((0, 1.0), (10, 0.9)) + (((3, 0.55), (11, 0.7)) if b else ()):
            put(kick(v), o + st)
        for st in (4, 12):
            put(snare(1.0), o + st)
        if b:
            put(snare(0.32), o + 15, -0.15)
            put(snare(0.25), o + 7, -0.15)
        for st in range(0, 16, 2):
            if b and st == 14:
                put(hat(0.75, open_=True), o + st, 0.45)
            else:
                put(hat(0.9 if st % 4 == 0 else 0.55), o + st, 0.45)
        for st in (3, 9, 13):
            put(hat(0.28), o + st, -0.5)
    mix = room(mix[:n + SR // 2])
    mix = mix[:n]                                      # exactly two bars: it loops
    mix *= 0.89 / np.abs(mix).max()
    y = np.clip(np.round(mix * 32767), -32768, 32767).astype("<i2")
    p = pathlib.Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(y.tobytes())
    print(f"wrote {p}: {n / SR:.3f} s, {a.bpm} BPM, two bars")


if __name__ == "__main__":
    main()

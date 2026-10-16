#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
S950 recording-rate listening pack (scope: reference/handoffs/VARISPEED_EMUS_S950_RATE_SCOPE.md).

Per source and project tempo (the loop is 104 BPM; one trig at the start, levels as on the unit):
  ot        the OT's own 2-tap read (the reference)
  s40       S950 as shipped: the DSP-exact twin (varispeed_emus_listen.render), 40 kHz
  s32, s22  a FULL low-rate S950 (float): the record filter (6th-order Butterworth at
            0.4 x rate) applied, then the signal SAMPLED at the virtual rate -- whatever the
            filter lets through above half the rate folds back, as on the real machine --
            stored at 12 bits (truncated, as the kernel's mask), then played back cleanly:
            band-limited reconstruction at (rate x speed), the tracking output filter at
            the stored Nyquist (images only), and the OT's own 22.05 kHz ceiling
  s22f      the CHEAP 22 kHz variant: today's DSP structure with a 22.05 kHz table (24 taps)
            -- the cutoff moves, no record aliasing (the float design model)
Also checks the full model at 40 kHz against the shipped twin (band levels), so the full
model is known to agree with what ships where the two should agree.

    python3 tools/varispeed_emus_s950_rates.py OUTDIR beat=beat.wav wide=wide.wav --bpm 104
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import varispeed_emus_ab_pack as p              # noqa: E402
import varispeed_emus_model as m         # noqa: E402
import varispeed_emus_listen as vl       # noqa: E402

SR = 44100
TEMPOS = (78, 104, 130, 156)


def butter_mag(f, fc, order=6):
    return 1 / np.sqrt(1 + (np.asarray(f, float) / fc) ** (2 * order))


def fft_filter(x, H_of_f, rate):
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), 1 / rate)
    return np.fft.irfft(X * H_of_f(f)[:, None], len(x), axis=0)


def upsample(x, k):
    """Band-limited k x upsampling (FFT zero-padding)."""
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    Y = np.zeros((n * k // 2 + 1, x.shape[1]), dtype=complex)
    Y[:len(X)] = X
    return np.fft.irfft(Y, n * k, axis=0) * k


def lin_read(x, pos):
    i = np.floor(pos).astype(int)
    f = (pos - i)[:, None]
    i = np.clip(i, 0, len(x) - 2)
    return x[i] * (1 - f) + x[i + 1] * f


def s950_full(src, fs_v, speed):
    # record: the MF6 filter, then point-sample at fs_v (aliasing included), 12-bit truncation
    rec = fft_filter(src, lambda f: butter_mag(f, 0.4 * fs_v), SR)
    up = upsample(rec, 8)
    nk = int((len(src) - 2) * fs_v / SR)
    stored = lin_read(up, np.arange(nk) * (SR / fs_v) * 8)
    stored = np.floor(stored * 2048) / 2048
    # play: the DAC clock is fs_v x speed; the tracking output filter removes the images
    # (steep, at the stored Nyquist), and nothing passes above the OT's own Nyquist (in
    # stored-sample frequency: / speed). The shipped design treats playback the same way:
    # clean apart from the images, so only the RECORD filter shapes the band.
    fc = min(0.49 * fs_v, 0.49 * SR / speed)
    clean = fft_filter(stored, lambda f: butter_mag(f, fc, order=24), fs_v)
    up2 = upsample(clean, 8)
    n_out = int((nk - 2) * SR / (fs_v * speed))
    return lin_read(up2, np.arange(n_out) * (speed * fs_v / SR) * 8)


def s950_cheap(src, fs_v, speed):
    m.FS_AKAI = fs_v
    m.FIR[m.MODE_S950]["taps"] = 24
    for n in ("fir_table", "fir_q23"):
        f = getattr(m, n, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    try:
        return p.run(m.MODE_S950, src, speed, [0])
    finally:
        m.FS_AKAI = 40000.0
        m.FIR[m.MODE_S950]["taps"] = 16
        for n in ("fir_table", "fir_q23"):
            f = getattr(m, n, None)
            if hasattr(f, "cache_clear"):
                f.cache_clear()


def bands(y):
    F = np.abs(np.fft.rfft(y.mean(axis=1) * np.hanning(len(y)))) ** 2
    f = np.fft.rfftfreq(len(y), 1 / SR)
    edges = (0, 2000, 5000, 8000, 12000, 16000, 22050)
    return [10 * np.log10(F[(f >= a) & (f < b)].sum() + 1e-20) for a, b in zip(edges, edges[1:])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--bpm", type=float, required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, checks = [], []
    for spec in a.sources:
        name, path = spec.split("=", 1)
        src = p.read_wav(path)
        clips = {}
        for bpm in TEMPOS:
            speed = bpm / a.bpm
            inc0 = vl.increment(bpm, a.bpm, 0)
            clips[(bpm, "ot")] = vl.render(src, inc0, 0)
            clips[(bpm, "s40")] = vl.render(src, vl.increment(bpm, a.bpm, m.MODE_S950), m.MODE_S950)
            full40 = s950_full(src, 40000.0, speed)
            n = min(len(full40), len(clips[(bpm, "s40")]))
            d = np.max(np.abs(np.array(bands(full40[:n])) - np.array(bands(clips[(bpm, "s40")][:n]))))
            checks.append(dict(source=name, bpm=bpm, full40_vs_shipped_max_band_db=round(float(d), 2)))
            clips[(bpm, "s32")] = s950_full(src, 32000.0, speed)
            clips[(bpm, "s22")] = s950_full(src, 22050.0, speed)
            clips[(bpm, "s22f")] = s950_cheap(src, 22050.0, speed)
            print(f"{name} {bpm}: done (full 40 kHz vs shipped: {d:.2f} dB max band)", flush=True)
        peak = max(np.abs(y).max() for y in clips.values())
        g = min(1.0, 0.89 / peak)
        for (bpm, key), y in clips.items():
            f = f"{name}_{bpm}_{key}.wav"
            p.write_wav(out / f, y * g)
            manifest.append(dict(source=name, bpm=bpm, key=key, file=f, bands_db=[round(v, 1) for v in bands(y)]))
    (out / "manifest.json").write_text(json.dumps(dict(clips=manifest, checks=checks), indent=1))


if __name__ == "__main__":
    main()

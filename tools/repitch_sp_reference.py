#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti: an INDEPENDENT reference SP-1200 and a "junk" measurement, for
checking RPSP against the machine rather than against its own model
(Session 111: RPSP vs this reference on the user's isaak.wav, NOTES).

The reference shares no engine code. Only the record-filter TARGET magnitude
(the spec) is taken from tools/repitch_engine_model.py:
  record filter (zero-phase, FFT) -> sampled on a true 26.04 kHz grid (windowed
  sinc) -> 12-bit floor -> drop-sample playback (stored index = floor(k * r))
  -> staircase at 26.04 kHz -> an ideal converter (brick wall at 20 kHz, 44.1 kHz).
  (E-mu SP-1200 Service Manual; Rossum: "Transpose a sound away from its recorded
  pitch and you get the aliasing and grit that define the instrument.")

junk(y, clean): y minus the best 96-tap linear filter of a clean pitch-down --
what no filter can explain (drop-sample, 12-bit, staircase images, folds).

    python3 tools/repitch_sp_reference.py SOURCE.wav RATIO [OUT_DIR]
        prints junk-to-music per band for the reference SP and RPSP's float model,
        and writes WAVs (clean, RPSP, reference, and each one's junk) to OUT_DIR.
"""
import math
import pathlib
import sys
import wave

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repitch_engine_model as m   # noqa: E402  (record-filter target + RPSP's float model)

SR = 44100.0
FSP = 20e6 / 768
BANDS = [(20, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 6000), (6000, 8000),
         (8000, 11000), (11000, 14000), (14000, 18000), (18000, 22050)]


def load(path):
    w = wave.open(str(path))
    assert w.getsampwidth() == 2 and w.getnchannels() == 2 and w.getframerate() == 44100, "16-bit stereo 44.1 kHz"
    return np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').reshape(-1, 2) / 32768.


def save(path, y):
    y = np.clip(np.round(np.asarray(y) * 32767), -32768, 32767).astype('<i2')
    w = wave.open(str(path), 'wb')
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(int(SR)); w.writeframes(y.tobytes()); w.close()


def record_filter(x):
    n = len(x); f = np.fft.rfftfreq(n, 1 / SR); d = m.FIR[m.MODE_RPSP]
    shape = 1 / np.sqrt(1 + (f / d["corner"]) ** (2 * d["poles"]))
    H = np.where(f <= d["flat"], 1.0, np.where(f >= d["stop"], 0.0, shape))
    return np.fft.irfft(np.fft.rfft(x, axis=0) * H[:, None], n, axis=0)


def bl_interp(x, t, half=48):
    """x at fractional sample positions t (Kaiser-windowed sinc)."""
    k0 = np.floor(t).astype(int); out = np.zeros((len(t), x.shape[1]))
    win = np.kaiser(2 * half, 9)
    for j in range(-half + 1, half + 1):
        idx = k0 + j; ok = (idx >= 0) & (idx < len(x))
        wgt = np.sinc(idx - t) * win[j + half - 1]
        out[ok] += wgt[ok, None] * x[idx[ok]]
    return out


def sp_render(x, r, n_out, os=64, fc=20000.0, interpolate=False):
    """The reference SP-1200 (raw outputs 7/8). interpolate=True replaces
    drop-sample with linear interpolation on the 26 kHz grid (for comparison)."""
    xf = record_filter(x)
    nstore = int(len(x) / SR * FSP) - 2
    st = bl_interp(xf, np.arange(nstore) * SR / FSP)
    st = np.floor(np.clip(st, -1, 1 - 2 ** -23) * 2048) / 2048
    nt = int(n_out / SR * FSP) + 4
    a = np.arange(nt) * r
    i0 = np.clip(np.floor(a + 1e-12).astype(int), 0, nstore - 2)
    if interpolate:
        fr = (a - np.floor(a))[:, None]
        held = np.floor((st[i0] * (1 - fr) + st[i0 + 1] * fr) * 2048) / 2048
    else:
        held = st[i0]
    tt = np.arange(nt) / FSP * SR
    k = np.clip(np.searchsorted(tt, np.arange(n_out * os) / os, side='right') - 1, 0, nt - 1)
    F = np.fft.rfft(held[k], axis=0); ff = np.fft.rfftfreq(n_out * os, 1 / (SR * os)); F[ff > fc] = 0
    return np.fft.irfft(F, n_out * os, axis=0)[::os]


def clean_pitch(x, r, n_out):
    return bl_interp(x, np.arange(n_out) * r)


def junk(y, u, K=96):
    out = np.zeros_like(y)
    for ch in range(y.shape[1]):
        a, b = y[:, ch], u[:, ch]; n = len(a)
        c = np.fft.irfft(np.fft.rfft(a, 2 * n) * np.conj(np.fft.rfft(b, 2 * n)))
        lag = int(np.argmax(np.abs(c[:4000]))) - K // 2
        rows = np.arange(2 * K, n - 2 * K)
        A = np.stack([b[rows - lag - j] for j in range(-K // 2, K // 2)], 1)
        h, *_ = np.linalg.lstsq(A, a[rows], rcond=None)
        out[rows, ch] = a[rows] - A @ h
    return out


def band_power(v):
    N = 4096; w = np.hanning(N); P = 0
    for i in range(0, len(v) - N, N // 2):
        P = P + np.abs(np.fft.rfft(v[i:i + N] * w)) ** 2
    f = np.fft.rfftfreq(N, 1 / SR)
    return np.array([P[(f >= a) & (f < b)].sum() for a, b in BANDS])


def junk_to_music(y, u):
    j = junk(y, u)[:, 0]
    return 10 * np.log10(band_power(j) / band_power(y[:, 0]))


if __name__ == "__main__":
    src, r = load(sys.argv[1]), float(sys.argv[2])
    out = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
    n = int(min(5.0, (len(src) - 200) / r / SR) * SR)
    clean = clean_pitch(src, r, n)
    ref = sp_render(src, r, n)
    rpsp = m.run(m.MODE_RPSP, src, r)[:n]
    n = min(len(clean), len(ref), len(rpsp)); clean, ref, rpsp = clean[:n], ref[:n], rpsp[:n]
    print("junk-to-music (dB):", " ".join(f"{a/1e3:g}-{b/1e3:g}k".rjust(9) for a, b in BANDS))
    for name, y in (("reference SP-1200", ref), ("RPSP float model", rpsp)):
        print(f"{name:20}" + " ".join(f"{v:9.1f}" for v in junk_to_music(y, clean)))
    if out:
        out.mkdir(parents=True, exist_ok=True)
        for name, y in (("clean", clean), ("rpsp", rpsp), ("reference_sp", ref)):
            save(out / f"{name}_{r:g}.wav", y)
        save(out / f"rpsp_junk_{r:g}.wav", junk(rpsp, clean))
        save(out / f"reference_sp_junk_{r:g}.wav", junk(ref, clean))
        print(f"WAVs in {out}")

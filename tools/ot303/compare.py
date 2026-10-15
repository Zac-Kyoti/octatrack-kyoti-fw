#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 1: compare the voice renders (tools/ot303/run_study.sh) against their
# references. Metrics, all delay-insensitive or delay-compensated:
#   null   residual after sub-sample alignment, dB relative to the reference (lower = closer;
#          -40 dB ~ "hard to tell apart", -60 dB ~ "inaudible difference" as a rule of thumb)
#   spec   STFT log-magnitude difference, mean |dB| over the bins within 60 dB of the take's
#          loudest bin (2048 Hann, hop 512)
#   hi     the same, 5-20 kHz only (where oversampling differences live)
#   p95    95th percentile of the spec difference
import argparse, glob, os, sys
import numpy as np

FS = 44100


def load(p):
    return np.fromfile(p, dtype=np.float32).astype(np.float64)


def align(x, ref):
    """shift x by the (fractional) delay that best matches ref; returns shifted x"""
    n = 1 << int(np.ceil(np.log2(len(x) + len(ref))))
    X = np.fft.rfft(x, n); R = np.fft.rfft(ref, n)
    xc = np.fft.irfft(R * np.conj(X), n)
    lag = int(np.argmax(np.concatenate([xc[-200:], xc[:200]]))) - 200
    i = lag % n
    y0, y1, y2 = xc[(i - 1) % n], xc[i], xc[(i + 1) % n]
    frac = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) != 0 else 0.0
    d = lag + frac
    f = np.fft.rfftfreq(n)
    Xs = np.fft.rfft(x, n) * np.exp(-2j * np.pi * f * d)      # delay x by d (was +: wrong way)
    return np.fft.irfft(Xs, n)[:len(ref)], d


def stft_db(x):
    w = np.hanning(2048)
    frames = np.lib.stride_tricks.sliding_window_view(x, 2048)[::512] * w
    S = np.abs(np.fft.rfft(frames, axis=1))
    return 20 * np.log10(S + 1e-12)


def metrics(x, ref):
    xa, d = align(x, ref)
    trim = slice(4096, len(ref) - 4096)
    resid = xa[trim] - ref[trim]
    null = 20 * np.log10(np.sqrt(np.mean(resid ** 2)) / np.sqrt(np.mean(ref[trim] ** 2)))
    A = stft_db(xa[trim]); B = stft_db(ref[trim])
    m = B >= B.max() - 60
    diff = np.abs(A - B)
    freqs = np.fft.rfftfreq(2048, 1 / FS)
    hi = m & ((freqs >= 5000) & (freqs <= 20000))[None, :]
    return dict(null=null, spec=float(diff[m].mean()), hi=float(diff[hi].mean()) if hi.any() else 0.0,
                p95=float(np.percentile(diff[m], 95)), delay=d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='out/ot303/renders')
    ap.add_argument('--wav', action='store_true', help='also write 24-bit WAVs for listening')
    a = ap.parse_args()
    R = lambda s, n: os.path.join(a.dir, f'{s}.{n}.f32')
    scenes = ['sweep', 'hot', 'squelch', 'square']

    def table(title, pairs):
        print(f'\n{title}')
        print(f"{'scene':8} {'variant':22} {'vs':14} {'null dB':>8} {'spec':>6} {'hi':>6} {'p95':>6}")
        for sc in scenes:
            for var, ref in pairs:
                if not (os.path.exists(R(sc, var)) and os.path.exists(R(sc, ref))):
                    continue
                m = metrics(load(R(sc, var)), load(R(sc, ref)))
                print(f"{sc:8} {var:22} {ref:14} {m['null']:8.1f} {m['spec']:6.2f} {m['hi']:6.2f} {m['p95']:6.2f}")

    table('LINEAR vs Open303 as shipped (o303-4-ell)',
          [('o303-4-fir', 'o303-4-ell'), ('ref-8', 'o303-4-ell'),
           ('zdf-4', 'o303-4-ell'), ('zdf-3', 'o303-4-ell'), ('zdf-2', 'o303-4-ell')])
    table('LINEAR vs the analog model (ref-8, RK4)',
          [('o303-4-fir', 'ref-8'), ('zdf-4', 'ref-8'), ('zdf-3', 'ref-8'), ('zdf-2', 'ref-8')])
    for d in ['0.5', '1', '2']:
        table(f'NONLINEAR D={d}: how far saturation moves the sound (refnl vs ref), and the '
              f'candidates vs the nonlinear model (refnl-8)',
              [(f'refnl-8-d{d}', 'ref-8')] +
              [(f'zdfnl-{n}-d{d}-h{h}', f'refnl-8-d{d}') for n in (4, 3, 2) for h in (0, 1)])

    if a.wav:
        import wave
        wd = os.path.join(os.path.dirname(a.dir), 'wav'); os.makedirs(wd, exist_ok=True)
        for p in sorted(glob.glob(os.path.join(a.dir, '*.f32'))):
            x = load(p); x = x / max(1e-9, np.max(np.abs(x))) * 0.89
            pcm = np.clip(np.round(x * 8388607), -8388608, 8388607).astype(np.int32)
            b = bytearray()
            for v in pcm:
                b += int(v).to_bytes(4, 'little', signed=True)[:3]
            with wave.open(os.path.join(wd, os.path.basename(p)[:-4] + '.wav'), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(3); w.setframerate(FS); w.writeframes(bytes(b))


if __name__ == '__main__':
    main()

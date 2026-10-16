#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# BLACKPYRAMIDS_303: how loud each WAVE value is against the saw (WAVE 0), at every WAVE value and a grid of
# CUT / RES / VOL settings. Renders tools/ot303/wave_loudness.cpp (the integer twin with params.c's words), then
# measures each WAVE block three ways:
#   ISO 532-1 time-varying loudness (Zwicker, MoSQITo's loudness_zwtv; free field), as N5 (the loudness reached
#     5 % of the time, ISO 532-1's figure for time-varying sounds) and the mean; each setting is calibrated so
#     its WAVE 0 plays at 75 dB SPL, and a loudness ratio is given as phon (10 log2 N / N0 above 1 sone)
#   ITU-R BS.1770 integrated loudness (K-weighting, gated), LU
#   plain RMS, dB
# Writes out/ot303/wave/RUN.json (per setting, per WAVE: the three against WAVE 0) and prints a summary.
#   python3 tools/ot303/wave_loudness.py [--gains FILE] [--run NAME] [--quick]
# --gains FILE  128 dB values applied to the oscillator words by the renderer (a candidate compensation)
# --quick       every 8th WAVE value only (the renders still cover all 128)
# Needs numpy, scipy and mosqito (pip install mosqito scipy matplotlib).
import json, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'wave')
FS = 44100; STEP = 5088; LEAD = 22050; BLOCK = LEAD + 2 * 16 * STEP
SPL = 75.0
# (scene, CUT, RES, VOL, PTCH): VOL 64 clean, 99 driven (+2.5 dB into the drive)
GRID = [('acid', c, r, v, 36) for c in (20, 45, 80) for r in (0, 64, 110) for v in (64, 99)] + \
       [('held', 45, r, 64, 36) for r in (0, 100)] + [('acid', 45, 64, 64, 24)]


def key(s):
    return '%s c%d r%d v%d p%d' % s


def build():
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    exe = os.path.join(OUT, 'wave_loudness')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(OUT, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/wave_loudness.cpp'),
                    os.path.join(OUT, 'params.o'), '-o', exe], check=True)
    return exe


def render(args):
    exe, s, gains, path = args
    cmd = [exe, path, s[0]] + [str(v) for v in s[1:]] + ([gains] if gains else [])
    subprocess.run(cmd, check=True)
    return path


def kfilter(x, fs):
    """BS.1770-4 K-weighting (the standard's two biquads, designed for fs)"""
    from scipy.signal import lfilter
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = np.tan(np.pi * f0 / fs); Vh = 10 ** (G / 20); Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    y = lfilter(b, a, x)
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / fs); a0 = 1 + K / Q + K * K
    return lfilter([1, -2, 1], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0], y)


def lufs(x, fs):
    y = kfilter(x, fs)
    n, hop = int(0.4 * fs), int(0.1 * fs)
    z = np.array([np.mean(y[i:i + n] ** 2) for i in range(0, len(y) - n + 1, hop)])
    l = -0.691 + 10 * np.log10(z + 1e-30)
    z = z[l > -70]
    rel = -0.691 + 10 * np.log10(np.mean(z)) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return -0.691 + 10 * np.log10(np.mean(z))


def measure(args):
    """one WAVE block -> (N5 sone, Nmean sone, LUFS, RMS dB); cal: the setting's Pa per unit"""
    path, w, cal = args
    from scipy.signal import resample_poly
    from mosqito.sq_metrics import loudness_zwtv
    x = np.fromfile(path, dtype=np.float32, count=BLOCK, offset=4 * w * BLOCK).astype(np.float64)
    meas = x[LEAD:]
    rms = 20 * np.log10(np.sqrt(np.mean(meas ** 2)))
    x48 = resample_poly(x, 160, 147)
    lu = lufs(resample_poly(meas, 160, 147), 48000)
    N, _, _, t = loudness_zwtv(x48 * cal, 48000, field_type='free')
    N = np.asarray(N)[np.asarray(t) >= LEAD / FS]
    return float(np.percentile(N, 95)), float(np.mean(N)), float(lu), float(rms)


def phon(n):
    return 40 + 10 * np.log2(n) if n >= 1 else 40 * (n + 0.0005) ** 0.35


def main():
    a = sys.argv[1:]
    gains = os.path.abspath(a[a.index('--gains') + 1]) if '--gains' in a else None
    run = a[a.index('--run') + 1] if '--run' in a else ('gains' if gains else 'base')
    waves = list(range(0, 128, 8)) + [127] if '--quick' in a else list(range(128))
    os.makedirs(OUT, exist_ok=True)
    exe = build()
    paths = {key(s): os.path.join(OUT, '%s.%s.f32' % (run, key(s).replace(' ', '_'))) for s in GRID}
    with ProcessPoolExecutor(12) as ex:
        list(ex.map(render, [(exe, s, gains, paths[key(s)]) for s in GRID]))
    jobs = []
    for s in GRID:
        p = paths[key(s)]
        x0 = np.fromfile(p, dtype=np.float32, count=BLOCK).astype(np.float64)[LEAD:]
        cal = 20e-6 * 10 ** (SPL / 20) / np.sqrt(np.mean(x0 ** 2))   # (a gains run: WAVE 0 at 0 dB, the same cal)
        jobs += [(p, w, cal) for w in waves]
    with ProcessPoolExecutor(12) as ex:
        res = list(ex.map(measure, jobs, chunksize=4))
    out, i = {}, 0
    for s in GRID:
        rows = res[i:i + len(waves)]; i += len(waves)
        n50, nm0, lu0, r0 = rows[0]
        out[key(s)] = {str(w): {'n5': n5, 'nmean': nm, 'd_phon_n5': phon(n5) - phon(n50), 'd_phon_mean': phon(nm) - phon(nm0),
                                'd_lufs': lu - lu0, 'd_rms': r - r0} for w, (n5, nm, lu, r) in zip(waves, rows)}
    with open(os.path.join(OUT, run + '.json'), 'w') as f:
        json.dump({'spl': SPL, 'waves': waves, 'settings': out}, f, indent=1)
    for p in paths.values():
        os.remove(p)
    # summary: per WAVE, the mean and the range over the settings (phon from N5)
    print(f'{run}: WAVE against WAVE 0, ISO 532-1 N5 (phon) | BS.1770 (LU) | RMS (dB): mean over {len(GRID)} settings [min, max]')
    for w in waves:
        d = np.array([out[key(s)][str(w)]['d_phon_n5'] for s in GRID])
        l = np.array([out[key(s)][str(w)]['d_lufs'] for s in GRID])
        r = np.array([out[key(s)][str(w)]['d_rms'] for s in GRID])
        print(f'  WAVE {w:3d}  {d.mean():+5.2f} [{d.min():+5.2f},{d.max():+5.2f}]  |  {l.mean():+5.2f} [{l.min():+5.2f},{l.max():+5.2f}]'
              f'  |  {r.mean():+5.2f} [{r.min():+5.2f},{r.max():+5.2f}]')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# (1) The real 303 against itself on realref2's yardstick: Din Sync recorded the all-25/50/75/100 % settings in five
#     sets each (B pos 1, C pos 2, D pos 3, E pos 4): the same notes, recorded at different times.
# (2) The real 303's fundamental against an ideal saw: CUTOFF 100 %, RESONANCE / ENV MOD 0 (A1 position 4, plain saw):
#     harmonics 1..8 with the saw's 1/k removed, relative to harmonics 4..6; an equivalent first-order high-pass corner.
import itertools, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, realref2 as R2
if __name__ == '__main__':
    R = R2.ref_features(); diffs = []
    for g, pos in (('B', 0), ('C', 1), ('D', 2), ('E', 3)):
        sets = ['%s%d' % (g, i) for i in range(1, 6)]
        for a, b in itertools.combinations(sets, 2):
            ra = R[a][4 * pos:4 * pos + 4]; rb = R[b][4 * pos:4 * pos + 4]
            rms, gain, d = R2.compare({'x': ra}, {'x': rb}, sets=['x'])
            diffs.append(rms)
    print('real 303 vs itself (same settings, different sets): RMS %.2f dB (median %.2f, range %.2f-%.2f over %d pairs)' %
          (np.mean(diffs), np.median(diffs), min(diffs), max(diffs), len(diffs)))
    x = RR.rd(os.path.join(RR.RAW, 'SET-A1.wav')); on = RR.ref_onsets(x)
    for n in (12, 8):                                   # position 4 (CUT 100 %) and 3 (75 %), plain saw
        seg = x[on[n] + int(0.1 * 44100): on[n] + int(0.6 * 44100)]
        N = 1 << 17; X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), N)); df = 44100 / N
        f0 = 65.41; ks = np.arange(1, 9)
        a = np.array([X[int(k * f0 / df) - 20:int(k * f0 / df) + 21].max() for k in ks]) * ks
        r = 20 * np.log10(a / a[3:6].mean())
        # a first-order high-pass with corner fc: |H(f)| = f / sqrt(f^2 + fc^2); fit fc to harmonics 1-3
        best = min(((sum((r[k - 1] - 20 * math.log10((k * f0) / math.hypot(k * f0, fc)) + 20 * math.log10((5 * f0) / math.hypot(5 * f0, fc))) ** 2
                         for k in (1, 2, 3)), fc) for fc in np.arange(5, 400, 1.0)))
        print('A1 note %d (CUT %d %%, RES 0, plain saw): harmonics 1..8 re an ideal saw, dB: %s -> as a 1st-order high-pass: %.0f Hz' %
              (n + 1, 25 * (n // 4 + 1), ' '.join('%+.1f' % v for v in r), best[1]))

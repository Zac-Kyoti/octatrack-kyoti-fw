#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# Overall level over time, real 303 vs a fitted model: is the "falling away" the filter or the VCA?
#   levels.py FIT.json
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S
if __name__ == '__main__':
    R = RR.ref_features(); fit = json.load(open(sys.argv[1]))
    nc = RR.NoteCache(S.params_file('lv', fit['params']) if fit['params'] else None, tag='lv')
    M, pk = nc.model(RR.law_table(fit['law'])); rms, gain, d = RR.compare(R, M)
    r = np.stack([R[s] for s in RR.SETS]); m = np.stack([M[s] for s in RR.SETS]) + gain
    tot = lambda a: 10 * np.log10((10 ** (a / 10)).sum(axis=2))
    dt = tot(r) - tot(m)
    print('windows ms:', ' '.join('%d-%d' % w for w in RR.WINS_MS))
    print('total level, real - model (dB):', ' '.join('%+.1f' % v for v in dt.mean(axis=(0, 1))))
    for name, sel in (('saw plain', [0]), ('saw accent', [1]), ('square plain', [2]), ('square accent', [3])):
        idx = [n for n in range(16) if n % 4 in sel]
        print('  %-14s' % name, ' '.join('%+.1f' % v for v in dt[:, idx].mean(axis=(0, 1))))
    for s in ('A2', 'C2', 'E2', 'A4', 'C4'):
        i = RR.SETS.index(s)
        print('  set %s plain saw, positions 25/50/75/100 %%, level 100-1300 ms real-model:' % s,
              ' '.join('%+.1f' % dt[i, n, 4:].mean() for n in (0, 4, 8, 12)))
    nc.pool.shutdown()

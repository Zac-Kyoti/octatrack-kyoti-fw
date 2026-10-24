#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# Where a joint fit still misses the real 303 (realref2 cells): mean (real - model) dB by third-octave band group and
# window, over all notes and over the high-RES notes only (RESONANCE >= 75 %).   residual.py JOINT.json
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, realref2 as R2, fit_joint as FJ, study as S
G = [('50-125', 0, 4), ('125-315', 4, 8), ('315-800', 8, 12), ('800-2000', 12, 16), ('2000-5000', 16, 20), ('5000-10k', 20, 23)]
if __name__ == '__main__':
    J = json.load(open(sys.argv[1]))
    nc = R2.NoteCache(S.params_file('rs', J['params']), tag='rs')
    M, pk = nc.model(RR.law_table(J['law'])); rms, gain, d = R2.compare(R2.ref_features(), M)
    hi = np.array([[n['res'] >= 75 for n, _, _ in RR.notes_of(s)] for s in RR.SETS])
    for name, sel in (('all notes', np.ones_like(hi)), ('RES >= 75 %', hi)):
        print('%s (RMS %.2f): mean real - model, dB' % (name, rms))
        print('   %-10s' % '' + ''.join('%10s' % ('%d-%d' % w) for w in R2.WINS_MS))
        for nm, a, b in G:
            print('   %-10s' % nm + ''.join('%10.1f' % np.nanmean(d[sel][:, a:b, w]) for w in range(len(R2.WINS_MS))))
    nc.pool.shutdown()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# What an accent does, real vs model: (accented - plain) per band group and window, saw notes, by ACCENT %.
#   accent.py FIT.json
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S
G = [('sub', 0, 3), ('lowmid', 3, 7), ('mid', 7, 10), ('pres', 10, 14), ('air', 14, 16)]
def lin(a): return 10 ** (a / 10)
def grp(f, a, b): return 10 * np.log10(lin(f[a:b]).sum(axis=0))
if __name__ == '__main__':
    R = RR.ref_features(); fit = json.load(open(sys.argv[1]))
    nc = RR.NoteCache(S.params_file('ac', fit['params']) if fit['params'] else None, tag='ac')
    M, pk = nc.model(RR.law_table(fit['law']))
    for s in ('A5', 'C5', 'E5', 'C2', 'E2'):
        print('set %s (ACCENT 25/50/75/100 %% by position), accented - plain saw, dB; windows %s' % (s, ' '.join('%d-%d' % w for w in RR.WINS_MS[1:])))
        for pos in range(4):
            line = []
            for nm, a, b in G:
                dr = grp(R[s][4 * pos + 1], a, b) - grp(R[s][4 * pos], a, b)
                dm = grp(M[s][4 * pos + 1], a, b) - grp(M[s][4 * pos], a, b)
                line.append('%s real %s | ours %s' % (nm, ' '.join('%+5.1f' % v for v in dr[1:]), ' '.join('%+5.1f' % v for v in dm[1:])))
            print('  pos %d:' % (pos + 1)); [print('    ' + l) for l in line]
    nc.pool.shutdown()

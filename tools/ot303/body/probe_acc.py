#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# Quick probe: accent decay / attack variants on the accent sets (A5 C5 E5) and all sets, laws held fixed.
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S
if __name__ == '__main__':
    R = RR.ref_features(); base = json.load(open(sys.argv[1])); law = RR.law_table(base['law'])
    acc_sets = ['A5', 'B5', 'C5', 'D5', 'E5']
    for name, extra in [('base', {}), ('acc_t20 0.25', {'acc_t20': 0.25}), ('acc_t20 0.15', {'acc_t20': 0.15}),
                        ('acc_t20 0.10', {'acc_t20': 0.10}), ('c2 5ms', {'c2_ms': 5}), ('c2 8ms', {'c2_ms': 8}),
                        ('acc_t20 0.15 c2 5', {'acc_t20': 0.15, 'c2_ms': 5}), ('acc_t20 0.15 c2 8 ag 1.4', {'acc_t20': 0.15, 'c2_ms': 8, 'ag_mult': 1.4})]:
        p = dict(base['params']); p.update(extra)
        nc = RR.NoteCache(S.params_file('pa', p), tag='pa'); M, pk = nc.model(law)
        a, g, _ = RR.compare(R, M, sets=acc_sets); b, _, _ = RR.compare(R, M)
        # accented notes only
        r = np.stack([R[s] for s in RR.SETS]); _, g2, d = RR.compare(R, M)
        accd = float(np.sqrt(np.nanmean(d[:, 1::2] ** 2)))
        print('%-26s accent sets %.2f  all %.2f  accented notes %.2f  peak %.1f dBFS' % (name, a, b, accd, 20 * np.log10(pk)), flush=True)
        nc.pool.shutdown()

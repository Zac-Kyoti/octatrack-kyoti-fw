#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# A joint result with some settings changed: re-adapt the CUT law only (realref2), write a new joint json.
#   adapt_cut.py IN.json OUT.json KEY=VALUE ...
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fit_joint as FJ, fit as FIT
if __name__ == '__main__':
    J = json.load(open(sys.argv[1])); v = dict(J['values'])
    for kv in sys.argv[3:]:
        k, x = kv.split('='); v[k] = float(x)
    f = FJ.Fitter('ad', J['law']); law, sc = f.law_pass(v, J['law'], knobs=('cut',), steps=FIT.STEPS['cut'][1:])
    json.dump({'values': v, 'params': FJ.to_params(v), 'law': law, 'rms': sc}, open(sys.argv[2], 'w'), indent=1)
    print('%s: %.3f dB  cut law %s' % (sys.argv[2], sc, [round(c / 256, 1) for c in law['cut']]))

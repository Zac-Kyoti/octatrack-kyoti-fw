#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# Fit the knob laws (each knob's value at the chart's 0/25/50/75/100 %) that bring a model closest to the
# real TB-303 (realref.py), by coordinate descent; what error is left is the engine's character.
#   fit.py NAME [PARAMS-JSON]     -> out/body/fit_NAME.json
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S

START = {'cut': [8 * 256, 12 * 256, 25 * 256, 45 * 256, 60 * 256], 'res': [0, 32, 64, 95, 127],
         'env': [0, 32 * 256, 64 * 256, 95 * 256, 127 * 256], 'dec': [0, 20, 50, 85, 105], 'acc': [1, 32, 64, 95, 127]}
LIM = {'cut': (0, 127 * 256), 'res': (0, 127), 'env': (0, 127 * 256), 'dec': (0, 127), 'acc': (1, 127)}
STEPS = {'cut': [8 * 256, 3 * 256, 256], 'res': [12, 4, 1], 'env': [12 * 256, 4 * 256, 256], 'dec': [12, 4, 1], 'acc': [12, 4, 1]}

def fit(name, params=None, start=None, passes=3, log=print):
    R = RR.ref_features()
    nc = RR.NoteCache(S.params_file(name, params) if params else None, tag=name)
    tab = json.loads(json.dumps(start or START))
    def score(t):
        M, pk = nc.model(RR.law_table(t)); rms, gain, _ = RR.compare(R, M); return rms
    best = score(tab); log('%s start %.3f dB' % (name, best))
    for p in range(passes):
        for k in RR.KNOBS:
            for i in range(5):
                for st in STEPS[k][min(p, 2):min(p, 2) + 2] if p < 2 else STEPS[k][2:]:
                    improved = True
                    while improved:
                        improved = False
                        for sgn in (+1, -1):
                            t = json.loads(json.dumps(tab)); v = t[k][i] + sgn * st
                            v = min(max(v, LIM[k][0]), LIM[k][1])
                            if v == tab[k][i]: continue
                            t[k][i] = v
                            sc = score(t)
                            if sc < best - 1e-4: best, tab, improved = sc, t, True; break
        log('%s pass %d: %.3f dB  %s' % (name, p + 1, best, json.dumps({k: [round(v / (256 if k in ('cut', 'env') else 1), 1) for v in tab[k]] for k in tab})))
    M, pk = nc.model(RR.law_table(tab)); rms, gain, d = RR.compare(R, M)
    json.dump({'law': tab, 'rms': rms, 'gain': gain, 'params': params or {}, 'peak': pk}, open(os.path.join(RR.WORK, 'fit_%s.json' % name), 'w'))
    nc.pool.shutdown()
    return tab, rms, gain, d

if __name__ == '__main__':
    name = sys.argv[1]; params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    t0 = time.time(); tab, rms, gain, d = fit(name, params)
    RR.report('%s fitted (gain %+.1f dB)' % (name, gain), d, rms); print('%.0f s' % (time.time() - t0))

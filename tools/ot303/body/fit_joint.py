#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# Joint calibration of BLACKPYRAMIDS_303 against Din Sync's real TB-303 (realref2.py's yardstick): every data-only
# part of the voice free at once, with the knob laws. Coordinate descent,
# alternating a settings pass (each setting up / down; the two high-passes judged after the CUT law has
# re-adapted, since a high-pass moves the brightness) and a law pass (all 25 law points). The onset (declicker,
# soft attack) is not free. Log: out/body/joint_NAME.log; result: out/body/joint_NAME.json.
#   fit_joint.py NAME START_LAW.json [PASSES]
import json, math, os, sys, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, realref2 as R2, study as S, fit as FIT

# name: (start, lo, hi, steps, multiplicative)
SPACE = {
    'hp1_hz':  (44.486, float(os.environ.get('HP1_MIN', 30)), float(os.environ.get('HP1_MAX', 170)), (1.25, 1.08), True),
    'fb_hz':   (150.0, float(os.environ.get('FB_MIN', 35)), float(os.environ.get('FB_MAX', 350)), (1.25, 1.08), True),
    'hp2_hz':  (24.167, float(os.environ.get('HP2_MIN', 10)), float(os.environ.get('HP2_MAX', 120)), (1.25, 1.08), True),     # the post high-pass (Open303 24 Hz; the 303: ~92 Hz after the ladder)
    'ag_mult': (1.0, 0.0, 1.0, (0.25, 0.1), False),       # Open303's fast accent share (the 303's circuit: none)
    'kp200':   (1.0, 0.7, float(os.environ.get('KP_MAX', 1.12)), (0.08, 0.03), False),
    'kp500':   (1.0, 0.7, float(os.environ.get('KP_MAX', 1.12)), (0.08, 0.03), False),
    'kp1200':  (1.0, 0.7, float(os.environ.get('KP_MAX', 1.12)), (0.08, 0.03), False),
    'kp3000':  (1.0, 0.7, float(os.environ.get('KP_MAX', 1.12)), (0.08, 0.03), False),
    'g_mult':  (1.0, 0.6, 1.6, (0.15, 0.05), False),
    'envoff':  (0.0, -0.4, 0.4, (0.1, 0.04), False),
    'es_mult': (1.0, 0.6, 1.5, (0.1, 0.04), False),
    'acc_t20': (0.46, 0.08, 0.7, (1.25, 1.08), True),
    'k8_mult': (1.0, 0.5, 2.0, (1.2, 1.07), True),
    'c2_ms':   (15.0, 3.0, 30.0, (1.3, 1.1), True),
    'amp_tau': (1.23, 0.6, 3.0, (1.2, 1.07), True),
    'ring_d':  (0.0, -0.4, 0.6, (0.1, 0.04), False),      # the ring-out law (bp_render.cpp)
    'ring_q':  (0.0, -1.0, 1.5, (0.25, 0.1), False),
    'env_r':   (0.0, -0.5, 1.0, (0.1, 0.04), False),      # envelope depth by RES
    'lg_p':    (0.0, -0.4, 0.6, (0.1, 0.04), False),      # level by cutoff
    'wow_d':   (0.0, 0.0, float(os.environ.get('WOWD_MAX', 5.0)), (0.5, 0.2), False),        # the accent sweep capacitor (Whittle's circuit): direct path
    'wow_thr': (0.4, 0.0, 0.9, (0.1, 0.04), False),       # the sweep's threshold on the ACCENT pot (circuit reading: ~0.4)
    'wow_c':   (0.0, 0.0, 8.0, (0.5, 0.2), False),        # and capacitor path, octaves; its time constants stay at the
}                                                         # circuit's 60 / 126 ms (Din Sync's isolated notes cannot see them)
HP = ('hp1_hz', 'fb_hz', 'hp2_hz')
FIX = json.loads(os.environ.get('FIX', '{}'))             # settings held fixed (and written to the params) for a run
for _k in FIX:
    SPACE.pop(_k, None)

def to_params(v):
    p = {k: v[k] for k in ('hp1_hz', 'fb_hz', 'hp2_hz', 'g_mult', 'envoff', 'es_mult', 'acc_t20', 'ag_mult', 'k8_mult', 'c2_ms', 'amp_tau') if k in v}
    for k in ('wow_d', 'wow_c'):
        if v.get(k, 0) > 0: p[k] = v[k]
    if 'wow_thr' in v: p['wow_thr'] = v['wow_thr']
    for k in ('ring_d', 'ring_q', 'env_r', 'lg_p', 'sat_d'):
        if k in v and v[k] != 0: p[k] = v[k]
    p.update({k: x for k, x in FIX.items() if not k.startswith('kp')})   # (fixed kp points go in kp_pts below)
    p['kp_pts'] = [[200, v['kp200']], [500, v['kp500']], [1200, v['kp1200']], [3000, v['kp3000']]]
    return p

class Fitter:
    def __init__(self, name, law):
        self.name, self.law, self.pool = name, json.loads(json.dumps(law)), ProcessPoolExecutor(8)
        self.R = R2.ref_features(); self.caches = {}; self.n = 0
        self.log = open(os.path.join(RR.WORK, 'joint_%s.log' % name), 'a')
    def say(self, s):
        print(s, flush=True); self.log.write(s + '\n'); self.log.flush()
    def cache(self, v):
        key = json.dumps(v, sort_keys=True)
        if key not in self.caches:
            if len(self.caches) > 6: self.caches.pop(next(iter(self.caches)))
            self.n += 1
            self.caches[key] = R2.NoteCache(S.params_file('jt_%s_%d' % (self.name, self.n), to_params(v)), tag='%s%d' % (self.name, self.n), pool=self.pool)
        return self.caches[key]
    def score(self, v, law):
        M, pk = self.cache(v).model(RR.law_table(law)); return R2.compare(self.R, M)[0]
    # LAW_KNOBS (env, comma list): the knob laws the fit may move (default all; the RES taper is a product decision)
    LAWK = tuple(os.environ['LAW_KNOBS'].split(',')) if os.environ.get('LAW_KNOBS') else RR.KNOBS
    def law_pass(self, v, law, knobs=None, steps=None):
        knobs = knobs or self.LAWK
        best = self.score(v, law)
        for k in knobs:
            for i in range(5):
                for st in (steps or FIT.STEPS[k][1:]):
                    improved = True
                    while improved:
                        improved = False
                        for sg in (1, -1):
                            t = json.loads(json.dumps(law)); nv = min(max(t[k][i] + sg * st, FIT.LIM[k][0]), FIT.LIM[k][1])
                            if nv == law[k][i]: continue
                            t[k][i] = nv; sc = self.score(v, t)
                            if sc < best - 1e-4: best, law, improved = sc, t, True; break
        return law, best
    def run(self, v, passes):
        law = self.law; best = self.score(v, law)
        self.say('%s start %.3f' % (self.name, best))
        for p in range(passes):
            for k, (_, lo, hi, steps, mul) in SPACE.items():
                st = steps[0] if p == 0 else steps[1]
                for sg in (1, -1):
                    nv = v[k] * st ** sg if mul else v[k] + sg * st
                    nv = min(max(nv, lo), hi)
                    if abs(nv - v[k]) < 1e-9: continue
                    t = dict(v, **{k: nv})
                    if k in HP:                                   # let the CUT law follow the brightness first
                        tl, sc = self.law_pass(t, law, knobs=('cut',), steps=[FIT.STEPS['cut'][1]])
                    else:
                        tl, sc = law, self.score(t, law)
                    if sc < best - 1e-3:
                        self.say('  pass %d %-8s %8.3f -> %8.3f   %.3f' % (p + 1, k, v[k], nv, sc))
                        v, law, best = t, tl, sc
                        while True:                               # line search: keep going while it helps
                            nv = v[k] * st ** sg if mul else v[k] + sg * st
                            nv = min(max(nv, lo), hi)
                            if abs(nv - v[k]) < 1e-9: break
                            t = dict(v, **{k: nv})
                            if k in HP:
                                tl, sc = self.law_pass(t, law, knobs=('cut',), steps=[FIT.STEPS['cut'][1]])
                            else:
                                tl, sc = law, self.score(t, law)
                            if sc >= best - 1e-3: break
                            self.say('  pass %d %-8s %8.3f -> %8.3f   %.3f' % (p + 1, k, v[k], nv, sc))
                            v, law, best = t, tl, sc
                        break
            law, best = self.law_pass(v, law)
            self.say('%s pass %d: %.3f  %s' % (self.name, p + 1, best, json.dumps({k: round(x, 3) for k, x in v.items()})))
            json.dump({'values': v, 'params': to_params(v), 'law': law, 'rms': best},
                      open(os.path.join(RR.WORK, 'joint_%s.json' % self.name), 'w'), indent=1)
        return v, law, best

if __name__ == '__main__':
    name, start = sys.argv[1], json.load(open(sys.argv[2]))
    passes = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    v = {k: s[0] for k, s in SPACE.items()}
    for k, x in start.get('params', {}).items():
        if k in v: v[k] = x
    v.update(start.get('values', {}))
    t0 = time.time(); Fitter(name, start['law']).run(v, passes)
    print('%.0f s' % (time.time() - t0))

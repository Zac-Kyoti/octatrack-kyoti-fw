#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# BLACKPYRAMIDS_303 body study: score the machine (and candidates) against Din Sync's real TB-303 (realref.py).
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR

def params_file(name, d):
    p = os.path.join(RR.WORK, 'params_%s.txt' % name)
    with open(p, 'w') as f:
        for k, v in d.items():
            if k == 'kp_pts': f.write('kp_pts %d %s\n' % (len(v), ' '.join('%g %g' % tuple(fm) for fm in v)))
            elif isinstance(v, (list, tuple)): f.write('%s %s\n' % (k, ' '.join('%g' % x for x in v)))   # res_law
            else: f.write('%s %g\n' % (k, v))
    return p

def run(name, law, params=None, show=True, vol=64):
    R = RR.ref_features()
    M, pk = RR.model_features(law, params_file(name, params) if params else None, tag=name, vol=vol)
    rms, gain, d = RR.compare(R, M)
    if show: RR.report('%s (gain %+.1f dB, worst peak %.1f dBFS)' % (name, gain, 20 * np.log10(max(pk.values()))), d, rms)
    return rms, gain, d, M

if __name__ == '__main__':
    run('as-built', RR.law_identity())
    run('fb150', RR.law_identity(), {'fb_hz': 150})

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# Does more level into the VOL drive bring the voice closer to the real 303 when pushed? Din Sync's 400 notes rendered at
# VOL 99 (the default, through the soft drive) with each version, against the real TB-303:
#   * realref2's score (spectrum by band and time, one global gain) and its tone-only form;
#   * the accent peaks: each accented note's peak over the median plain note's peak in its set (dB), real vs model --
#     does the voice hold its loudest moments down as the recordings do.
#   drivecheck.py VERSION.json ...
import json, math, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, realref2 as R2, cfcheck as CC
EXE = os.path.join(RR.WORK, 'bp_render.k'); VOL = 99

def render(args):
    s, tab, pf = args; law = RR.law_table(tab)
    txt = RR.score_text(s, law, VOL)
    sc = os.path.join(RR.WORK, 'dc_%s_%s.txt' % (os.path.basename(pf)[:-4], s)); out = sc[:-4] + '.f32'
    open(sc, 'w').write(txt); subprocess.run([EXE, sc, out, pf], check=True, stderr=subprocess.DEVNULL)
    return s, np.fromfile(out, dtype=np.float32).astype(np.float64)

def peaks(x, onsets):
    return [float(np.abs(x[o:o + int(0.3 * 44100)]).max()) for o in onsets]

if __name__ == '__main__':
    R = R2.ref_features(); real = {}
    for s in RR.SETS:
        xr = RR.rd(os.path.join(RR.RAW, 'SET-%s.wav' % s)); real[s] = peaks(xr, [o - int(round(RR.detect_bias())) for o in RR.ref_onsets(xr)])
    def lift(P):
        d = []
        for s in RR.SETS:
            nts = RR.notes_of(s); plain = [P[s][n] for n, (kn, sq, a) in enumerate(nts) if not a]
            if not plain: continue
            ref = np.median(plain)
            d += [20 * math.log10(P[s][n] / ref) for n, (kn, sq, a) in enumerate(nts) if a]
        return np.array(d)
    lr = lift(real)
    print('real 303: accented peaks over the plain notes\' median %+.1f dB (median), %+.1f dB (90th percentile)' % (np.median(lr), np.percentile(lr, 90)))
    for vf in sys.argv[1:]:
        J = json.load(open(vf)); pf = CC.params_file(os.path.join(RR.WORK, 'dc_%s.txt' % os.path.basename(vf)[:-5]), J['params'])
        with ProcessPoolExecutor(8) as ex:
            X = dict(ex.map(render, [(s, J['law'], pf) for s in RR.SETS]))
        M = {s: R2.feats(X[s], [n * RR.NSTEP for n in range(16)]) for s in RR.SETS}
        P = {s: peaks(X[s], [n * RR.NSTEP for n in range(16)]) for s in RR.SETS}
        lm = lift(P)
        print('%-12s VOL %d: real-303 match %.3f dB, tone only %.3f dB; accent peaks %+.1f dB (median), %+.1f dB (90th), error vs real %+.1f dB'
              % (os.path.basename(vf)[:-5], VOL, R2.compare(R, M)[0], CC.tone_only(R, M), np.median(lm), np.percentile(lm, 90), np.median(lm - lr)))

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# The new voice as the ColdFire makes it (bp_cf: record.c + params.c -DOT_BODY) against its prototype (bp_render with
# the chosen version's parameters), both scored on realref2's yardstick against Din Sync's real TB-303 (400 notes).
# The prototype takes the fitted RES law as engine RES; the ColdFire build takes the RES knob (real % x 127 / 100)
# and tapers it itself.
#   cfcheck.py [VERSION.json]
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR
import realref2 as R2

ROOT = RR.ROOT
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'tools', 'ot303', 'body', 'data', 'voice.json')

def params_file(path, d):
    L = []
    for k, v in d.items():
        if isinstance(v, (list, tuple)) and k != 'kp_pts':
            L.append('%s %s' % (k, ' '.join('%r' % x for x in v)))
        elif k == 'kp_pts':
            L.append('kp_pts %d %s' % (len(v), ' '.join('%r %r' % (f, m) for f, m in v)))
        else:
            L.append('%s %r' % (k, v))
    open(path, 'w').write('\n'.join(L) + '\n')
    return path

def tone_only(R, M):
    """the score with every note at its own best gain: the tone and its shape in time, not the level between notes"""
    Mt = {}
    for s in RR.SETS:
        m = M[s].copy()
        for n in range(m.shape[0]):
            fl = R[s][n].max() - R2.FLOOR; k = (R[s][n] > fl) & R2.VALID
            m[n] += np.median((R[s][n] - m[n])[k])
        Mt[s] = m
    return R2.compare(R, Mt)[0]

def score(exe, params, law, tag, tone=False):
    RR.EXE = os.environ['BP_RENDER'] = exe     # the pool's workers import realref afresh
    C = R2.NoteCache(params, tag)
    M, pk = C.model(law)
    R = R2.ref_features()
    e, g, _ = R2.compare(R, M)
    C.pool.shutdown()
    return (e, g, pk, tone_only(R, M)) if tone else (e, g, pk)

def main():
    J = json.load(open(SRC))
    law = RR.law_table(J['law'])
    proto = params_file(os.path.join(RR.WORK, 'cfcheck_proto.txt'), J['params'])
    D = json.load(open(os.path.join(ROOT, 'tools', 'ot303', 'cf', 'body_dsp.json')))
    cf = params_file(os.path.join(RR.WORK, 'cfcheck_cf.txt'), {k: D[k] for k in ('fb_hz', 'hp1_hz', 'hp2_hz', 'c2_ms', 'kp_pts', 'lt_base', 'lt_spo') if k in D})
    # the knobs: the ColdFire tapers both; the knob that plays the law's engine value (out/body/body_knobs.json)
    KB = json.load(open(os.environ.get('BODY_KNOBS', os.path.join(RR.WORK, 'body_knobs.json'))))
    inv = lambda q8, e: float(np.interp(e * 256, q8, np.arange(128)))
    lawk = dict(law); lawk['res'] = lambda p: inv(KB['res_q8'], law['res'](p)); lawk['acc'] = lambda p: inv(KB['acc_q8'], law['acc'](p))
    lawk['cut'] = lambda p: (law['cut'](p) - KB['cut_lo_q8']) * KB.get('cut_knee', 127) * 256 / (KB['cut_hi_q8'] - KB['cut_lo_q8'])   # CUT 8.8 on the knob
    ep, gp, pp, tp = score(os.environ.get('BP_PROTO', os.path.join(RR.WORK, 'bp_render.k')), proto, law, 'cfp', True)
    ec, gc, pc, tc = score(os.path.join(RR.WORK, 'bp_cf'), cf, lawk, 'cfc', True)
    print('prototype  %.3f dB, tone only %.3f dB (gain %+.2f dB, worst note peak %.3f)' % (ep, tp, gp, pp))
    print('ColdFire   %.3f dB, tone only %.3f dB (gain %+.2f dB, worst note peak %.3f)' % (ec, tc, gc, pc))

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# The RES and ACCENT knobs' effect, measured on the voice itself (bp_render, the chosen version's parameters: the
# accent sweep reads the pots from the fitted laws), so the knobs can be spaced evenly without changing any sound:
#   * ACCENT: the accented note's level over the plain note's (dB, the first 100 ms), by the engine's ACCENT value,
#     averaged over RES 25 / 50 / 75 % and CUT 25 / 50 % (ENV, DECAY 50 %);
#   * RES: the boost the resonance adds (a held C2, 200-450 ms, ENV 0: its harmonics against RES 0's, the ratio's
#     peak over its median, dB), by the engine's RES, averaged over CUT 25 / 50 / 75 %.
# Writes out/body/knob_curves.json.
#   evenknob.py [VERSION.json]
import json, math, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, cfcheck as CC
EXE = os.path.join(RR.WORK, 'bp_render.k')
FS = 44100; F0 = 65.406; STEP = 22050

def render(tag, notes, frames, params):
    sc = os.path.join(RR.WORK, 'ek_%s.txt' % tag); out = sc[:-4] + '.f32'
    open(sc, 'w').write('\n'.join(['%d %d %d %d %d %d' % (STEP, len(notes), 100, 38, 64, 64)] + notes + frames) + '\n')
    subprocess.run([EXE, sc, out, params], check=True, stderr=subprocess.DEVNULL)
    return np.fromfile(out, dtype=np.float32).astype(np.float64)

def acc_point(args):
    a, tab, params = args; law = RR.law_table(tab)
    lifts = []
    for rp in (25, 50, 75):
        for cp in (25, 50):
            row = '%d %d %d %d 0' % (round(law['cut'](cp)), round(law['env'](50)), round(law['res'](rp)), round(law['dec'](50)))
            # a plain note, a rest, the accented note, a rest: each a step (0.5 s)
            x = render('a%d_%d_%d' % (a, rp, cp), ['N 24 0 0', 'R 0 0 0', 'N 24 %d 0' % a, 'R 0 0 0'], [row] * (4 * STEP // 16), params)
            lv = lambda o: 10 * math.log10(np.mean(x[o:o + int(0.1 * FS)] ** 2) + 1e-20)
            lifts.append(lv(2 * STEP) - lv(0))
    return a, float(np.mean(lifts))

def harm_db(x):
    seg = x[int(0.2 * FS):int(0.45 * FS)]
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 4 * len(seg))); f1 = FS / (4 * len(seg))
    return np.array([20 * math.log10(X[int(round(h * F0 / f1))] + 1e-12) for h in range(1, 60)])

def res_point(args):
    """the resonance as the boost it adds: the held note's harmonics against the same note at RES 0, the ratio's
    peak over its median (the make-up gain moves the whole note, not the peak)"""
    r, tab, params = args; law = RR.law_table(tab)
    boosts = []
    for cp in (25, 50, 75):
        hd = []
        for rr in (0, r):
            row = '%d 0 %d 127 0' % (round(law['cut'](cp)), rr)
            hd.append(harm_db(render('r%d_%d_%d' % (r, rr, cp), ['N 24 0 0'], [row] * (STEP // 16), params)))
        d = hd[1] - hd[0]
        boosts.append(float(d.max() - np.median(d)))
    return r, float(np.mean(boosts))

if __name__ == '__main__':
    J = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RR.WORK, 'joint_K5.json')))
    law = RR.law_table(J['law'])
    params = CC.params_file(os.path.join(RR.WORK, 'ek_params.txt'), J['params'])
    amax, rmax = J['law']['acc'][-1], J['law']['res'][-1]
    with ProcessPoolExecutor(8) as ex:
        A = list(ex.map(acc_point, [(a, J['law'], params) for a in range(1, int(amax) + 1)]))
        R = list(ex.map(res_point, [(r, J['law'], params) for r in range(0, int(rmax) + 1)]))
    json.dump({'acc': A, 'res': R, 'acc_max': amax, 'res_max': rmax, 'source': os.path.basename(sys.argv[1] if len(sys.argv) > 1 else 'joint_K5.json')},
              open(os.path.join(RR.WORK, 'knob_curves.json'), 'w'), indent=1)
    for a, v in A[::8]: print('ACC engine %3d: accent lift %+5.1f dB' % (a, v))
    for r, v in R[::6]: print('RES engine %3d: resonant peak %+5.1f dB' % (r, v))

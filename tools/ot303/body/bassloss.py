#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# The 303's bass loss as RES rises: Din Sync C2 set (RESONANCE 25/50/75/100 %, the rest 50 %), plain saw notes, 400-900 ms
# (the envelope settled): the fundamental (H1) and the 2nd-3rd harmonics against harmonics 4-6, real vs models (each at
# the same real-303 setting through its fitted law).
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S
def prof(seg):
    N = 1 << 17; X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), N)); df = 44100 / N; f0 = 65.41
    a = np.array([X[int(k * f0 / df) - 20:int(k * f0 / df) + 21].max() for k in range(1, 7)]) * np.arange(1, 7)
    r = 20 * np.log10(a / a[3:6].mean()); return r[0], r[1:3].mean()
def model(fitfile, extra=None):
    J = json.load(open(fitfile)); p = dict(J['params'], **(extra or {}))
    x = RR.render_set('C2', RR.law_table(J['law']), S.params_file('bl', p), tag='bl')
    return [prof(x[(2 * n * RR.STEP) + int(0.4 * 44100):(2 * n * RR.STEP) + int(0.9 * 44100)]) for n in (0, 4, 8, 12)]
if __name__ == '__main__':
    x = RR.rd(os.path.join(RR.RAW, 'SET-C2.wav')); on = RR.ref_onsets(x)
    real = [prof(x[on[n] + int(0.4 * 44100):on[n] + int(0.9 * 44100)]) for n in (0, 4, 8, 12)]
    rows = [('real 303', real), ('joint fit (in 136, loop 120)', model('out/body/joint_J2_pass1.json')),
            ('same, in 44.5 / loop 45', model('out/body/joint_J2_pass1.json', {'hp1_hz': 44.486, 'fb_hz': 45})),
            ('same, in 44.5 / loop 75', model('out/body/joint_J2_pass1.json', {'hp1_hz': 44.486, 'fb_hz': 75}))]
    print('RES 25/50/75/100 %%: H1 (fundamental) | H2-3, dB against H4-6')
    for name, r in rows:
        print('  %-30s' % name + '   '.join('%+5.1f | %+5.1f' % v for v in r))

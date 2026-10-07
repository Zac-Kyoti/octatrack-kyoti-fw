#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 Phase 2b: the integer twin (tools/ot303/twin.h) against the approved voice
# (voice_study render SCENE o303q 4 hb2 blep:1,tab:1,q:1,stbits:24,top:16000).
#   python3 tools/ot303/twin_check.py TAG OPTS     renders out/ot303/twin/SCENE.TAG.f32 and reports
# per scene: the spectral metrics (compare.py), the null per second, and the error per band.
import os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare as c

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V = os.path.join(ROOT, 'out', 'ot303', 'voice_study')
D = os.path.join(ROOT, 'out', 'ot303', 'twin')
SCENES = ['sweep', 'hot', 'squelch', 'accents', 'square']
BANDS = [(0, 50), (50, 200), (200, 1000), (1000, 4000), (4000, 10000), (10000, 22050)]
REF_OPTS = 'blep:1,tab:1,q:1,stbits:24,top:16000'


def main():
    tag, opts = sys.argv[1], sys.argv[2]
    os.makedirs(D, exist_ok=True)
    for s in SCENES:
        ref = os.path.join(D, f'{s}.ref.f32')
        if not os.path.exists(ref):
            subprocess.run([V, 'render', s, 'o303q', '4', 'hb2', REF_OPTS, '0', ref], check=True, capture_output=True)
        out = os.path.join(D, f'{s}.{tag}.f32')
        p = subprocess.run([V, 'twin', s, opts, out], check=True, capture_output=True, text=True)
        head = p.stdout.splitlines()[0]
        r, t = c.load(ref), c.load(out)
        m = c.metrics(t, r)
        nulls = []
        for k in range(len(r) // 44100):
            a = slice(k * 44100, (k + 1) * 44100)
            nulls.append(20 * np.log10(np.sqrt(np.mean((t[a] - r[a]) ** 2)) / np.sqrt(np.mean(r[a] ** 2)) + 1e-12))
        a = slice(44100, 5 * 44100)
        E = np.abs(np.fft.rfft(r[a] - t[a])) ** 2; R = np.abs(np.fft.rfft(r[a])) ** 2
        f = np.fft.rfftfreq(a.stop - a.start, 1 / 44100)
        bands = ' '.join(f'{10*np.log10(E[(f>=lo)&(f<hi)].sum()/R[(f>=lo)&(f<hi)].sum()):6.1f}' for lo, hi in BANDS)
        print(f"{s:8} spec {m['spec']:.3f} hi {m['hi']:.3f} p95 {m['p95']:.3f} | null/s min {min(nulls):6.1f} "
              f"max {max(nulls):6.1f} | bands {bands} | {head.split('(')[-1].rstrip(')')}")


if __name__ == '__main__':
    main()

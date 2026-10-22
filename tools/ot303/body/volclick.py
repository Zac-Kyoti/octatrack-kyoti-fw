#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# Clicks as VOL crosses 64 / 65 (the clean path to the soft drive and back): a held note, VOL stepping a value every
# 40 ms across the crossing and back, through the ColdFire voice (bp_cf, BP_VOL_FRAMES). A click shows as a burst of
# energy above 6 kHz at a VOL change, over that band's level elsewhere in the note (dB): the crossing against the
# neighbouring steps that stay on one path.
#   volclick.py [EXE]
import math, os, subprocess, sys
import numpy as np
from scipy.signal import butter, sosfilt
FS = 44100
EXE = sys.argv[1] if len(sys.argv) > 1 else 'out/body/bp_cf'
VOLS = [60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 68, 67, 66, 65, 64, 63, 62, 61, 60]
HOLD = int(0.04 * FS) // 16                         # frames a VOL value is held
def run(cut, res, wave, ptch):
    NF = HOLD * (len(VOLS) + 4); STEP = NF * 16
    L = ['%d 1 127 73 64 64' % STEP, 'N %d 0 0' % ptch] + ['%d 0 %d 127 %d' % (cut * 256, res, wave)] * NF
    open('out/body/vc.txt', 'w').write('\n'.join(L) + '\n')
    vf = [VOLS[0]] * (2 * HOLD) + [v for v in VOLS for _ in range(HOLD)] + [VOLS[-1]] * (2 * HOLD)
    open('out/body/vc_vol.txt', 'w').write('\n'.join(map(str, vf)) + '\n')
    subprocess.run([EXE, 'out/body/vc.txt', 'out/body/vc.f32', 'out/body/cfcheck_cf.txt'], check=True, stderr=subprocess.DEVNULL,
                   env=dict(os.environ, BP_VOL_FRAMES='out/body/vc_vol.txt'))
    x = np.fromfile('out/body/vc.f32', dtype=np.float32).astype(float)
    hp = sosfilt(butter(4, 6000, 'highpass', fs=FS, output='sos'), x)
    def burst(i):                                    # the 3 ms after the i-th VOL change, against the 30 ms before it
        t = (2 * HOLD + i * HOLD) * 16
        a = 10 * math.log10(np.mean(hp[t:t + int(0.003 * FS)] ** 2) + 1e-20); b = 10 * math.log10(np.mean(hp[t - int(0.033 * FS):t - int(0.003 * FS)] ** 2) + 1e-20)
        return a - b
    up, down = burst(5), burst(14)                   # 64 -> 65 and 65 -> 64
    others = [burst(i) for i in range(1, len(VOLS)) if i not in (5, 14)]
    return up, down, max(others)
print('burst above 6 kHz at the VOL change (dB over the note there): 64->65 | 65->64 | worst other step')
for cut, res, wave, ptch, nm in ((64, 0, 0, 24, 'saw C2, CUT 64 RES 0'), (100, 64, 0, 24, 'saw C2, CUT 100 RES 64'), (40, 100, 0, 36, 'saw C3, CUT 40 RES 100'), (64, 64, 127, 24, 'square C2, CUT 64 RES 64')):
    u, d, o = run(cut, res, wave, ptch)
    print('  %-28s %+6.1f | %+6.1f | %+6.1f' % (nm, u, d, o))

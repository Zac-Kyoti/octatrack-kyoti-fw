#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# The MT33-style ceiling sweep, in the machine's own knob space: 4,320 single notes
# (CUT 8 x RES 5 x ENV 3 x ACC 3 x WAVE 2 x VOL 2 x PTCH 3), DEC 72, GATE 74, SLID 38.
# Reports the share of samples at the ceiling (|y| >= 0.999 FS) and the worst peak, per VOL half and accent.
#   headroom.py NAME [PARAMS-JSON]
import itertools, json, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR, study as S
STEP = 17648                                   # ~0.4 s steps: a note + a rest
GRID = list(itertools.product(range(0, 128, 18), (0, 32, 64, 100, 127), (0, 64, 127), (0, 64, 127), (0, 127), (64, 99), (24, 36, 48)))

def batch(args):
    items, params, tag, i = args
    out = []
    for vol in (64, 99):
        sel = [g for g in items if g[5] == vol]
        if not sel: continue
        lines = ['%d %d %d %d %d %d' % (STEP, 2 * len(sel), 74, 38, vol, 64)]; frames = []
        for (c, r, e, a, w, v, p) in sel:
            lines.append('N %d %d 0' % (p, a)); lines.append('R 0 0 0')
            frames += ['%d %d %d %d %d' % (c * 256, e * 256, r, 72, w)] * (2 * STEP // 16)
        sc = os.path.join(RR.WORK, 'hr_%s_%d_%d.txt' % (tag, i, vol)); f32 = sc[:-4] + '.f32'
        open(sc, 'w').write('\n'.join(lines + frames) + '\n')
        r = subprocess.run([RR.EXE, sc, f32] + ([params] if params else []), check=True, capture_output=True, text=True)
        sat = int(r.stderr.strip().split()[-1]) if 'saturations' in r.stderr else -1
        x = np.fromfile(f32, dtype=np.float32)
        for n, g in enumerate(sel):
            y = np.abs(x[2 * n * STEP:(2 * n + 2) * STEP])
            out.append((g, float(y.max()), int((y >= 0.999).sum()), len(y), sat if n == 0 else 0))
    return out

if __name__ == '__main__':
    name = sys.argv[1]; params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    pf = S.params_file('hr_' + name, params) if params else None
    chunks = [GRID[i::8] for i in range(8)]
    with ProcessPoolExecutor(8) as ex:
        res = [r for part in ex.map(batch, [(c, pf, name, i) for i, c in enumerate(chunks)]) for r in part]
    print('%s %s: %d notes' % (name, json.dumps(params or {}), len(res)))
    for vol in (64, 99):
        for acc in ('plain', 'accented'):
            sel = [r for r in res if r[0][5] == vol and ((r[0][3] > 0) == (acc == 'accented'))]
            clip = sum(r[2] for r in sel) / sum(r[3] for r in sel) * 100
            notes = sum(1 for r in sel if r[2] > 0)
            print('  VOL %d %-9s: worst peak %6.2f dBFS, notes that clip %4d / %d, samples at the ceiling %.3f %%' % (
                vol, acc, 20 * np.log10(max(r[1] for r in sel)), notes, len(sel), clip))
        print('  VOL %d: saturating stores anywhere in the engine (twin g_sat): %d' % (vol, sum(r[4] for r in res if r[0][5] == vol)))
    json.dump([[list(r[0]), r[1], r[2]] for r in res], open(os.path.join(RR.WORK, 'headroom_%s.json' % name), 'w'))

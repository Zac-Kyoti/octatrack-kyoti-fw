#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""Ties across a cued pattern change (the author on OCTABAM41, 2026-11-19; control.c tie_xfer). ot_emu, BOTLI, the
runtime's own counters and event log (ot_evlog: track << 28 | ev << 24 | gate samples; ot_evptch the pitch sent).
Pattern 0 and pattern 1 share Part 1; T2 a BLKPYRAMD; in pattern 0 a note on step 13 tied (trigless locks) to step 16,
and a note on step 1 (so the note's own gate, wrapped into pattern 0, ends in step 16). Pattern 1 is cued at frame
9000:
  ties   pattern 1 starts with trigless locks on steps 1-4: one tie event (NOTE | SLIDE, the same pitch) is sent once
         pattern 1 is scheduled, its gate ~3 steps + GATE's share past the boundary (more than the note's own gate)
  note   pattern 1 starts with a note: no tie event (the gate already ends in the last step)
    python3 tools/ot303/verify_tie_xfer.py [image] [elf]   (default: the standalone unit)"""
import os, sys, tempfile, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import verify_ot303 as V
import verify_one_per_core as O
IMAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'out/BLACKPYRAMIDS_303/mainos_blackpyramids_303.bin')
if len(sys.argv) > 2:
    V.ELF = sys.argv[2]
S = V.syms()
PART, STRIDE, B0 = O.PART, O.STRIDE, V.BANK0
FRAMES, CUE_AT = 16000, 9000


def line(t, pat, notes, ties):
    out = []
    for off, val in ((0x04, sum(1 << x for x in notes)), (0x0c, 0), (0x14, sum(1 << x for x in ties)), (0x4c, 0)):
        out += [f'{B0 + pat * 0x8ed8 + t * 0x91a + off + i:#x}={b:#x}' for i, b in enumerate(val.to_bytes(4, 'big'))]
    return out


def bp(t):
    out = [f'{PART + 0x22 + t:#x}=1'] + [f'{PART + 60 + 30 * t + i:#x}={c:#x}' for i, c in enumerate(b'OT\x01')]
    out += [f'{PART + (0x2a if k < 6 else 0x1da) + 30 * t + 6 + k % 6:#x}={v:#x}' for k, v in enumerate(V.DEFAULTS)]
    out += [f'{0x80000810 + 72 * t + 0x20 + k - 6:#x}={v:#x}' for k, v in enumerate(V.DEFAULTS) if k >= 6]
    return out


BASE = bp(1) + line(1, 0, [0, 12], [13, 14, 15]) + [f'{B0 + 0x8ed8 + 0x8e57:#x}=0']   # pattern 1 -> Part 1
SC = {'ties': BASE + line(1, 1, [], [0, 1, 2, 3]), 'note': BASE + line(1, 1, [0], [])}


def run(pokes):
    with tempfile.TemporaryDirectory() as td:
        args = ['--sequencer', '--internal-clock', '--frames', str(FRAMES), '--step', '-:poke:' + ';'.join(pokes),
                '--step', f'{CUE_AT}:call:{O.CUE:#x},0,1',
                '--mem-dump', f'{S["ot_evlog"]:#x},128={td}/log.bin;{S["ot_evptch"]:#x},32={td}/pt.bin;{S["ot_evn"]:#x},4={td}/n.bin;'
                f'{S["ot_tie_xfers"]:#x},4={td}/x.bin;{S["ot_tie_sent"]:#x},4={td}/s.bin;0x80000003,1={td}/part.bin;'
                f'{B0 + 0x8ed8 * 0 + 0x8e57:#x},1={td}/p0.bin']
        p = V.emu(IMAGE, args, td)
        return p, {f[:-4]: open(os.path.join(td, f), 'rb').read() for f in os.listdir(td) if f.endswith('.bin')}


with cf.ThreadPoolExecutor(2) as ex:
    res = {k: f.result() for k, f in {k: ex.submit(run, v) for k, v in SC.items()}.items()}
ok = True
w = lambda b, i: int.from_bytes(b[4 * i:4 * i + 4], 'big')
for k, (p, g) in res.items():
    n = w(g['n'], 0)
    evs = [(w(g['log'], i & 31), g['pt'][i & 31]) for i in range(max(0, n - 32), n)]
    evs = [(x >> 28, x >> 24 & 15, x & 0xffffff, pt) for x, pt in evs]
    x, s = w(g['x'], 0), w(g['s'], 0)
    print(f'{k}: rc {p.returncode}; tie recomputes {x}, tie events sent {s}; the last events (track, ev, gate, PTCH):')
    for e in evs[-6:]:
        print(f'      T{e[0] + 1} ev {e[1]} gate {e[2]} PTCH {e[3]}')
    notes = [e for e in evs if e[1] == 1]
    ties = [e for e in evs if e[1] == 3]
    if k == 'ties':
        c = p.returncode == 0 and x >= 1 and s >= 1 and ties and notes and ties[-1][3] == notes[-1][3] and ties[-1][2] > notes[-1][2]
        print(f'   {"ok  " if c else "FAIL"} a tie event: the sounding note\'s pitch, a gate longer than its own')
    else:
        c = p.returncode == 0 and x == 0 and s == 0 and not ties
        print(f'   {"ok  " if c else "FAIL"} no tie event')
    ok &= bool(c)
print('ALL GOOD' if ok else 'FAILED')
sys.exit(0 if ok else 1)

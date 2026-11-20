#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""OCTABAM42 (2026-11-19): (1) the first note of a pattern's first play (after the load, or into another Part for the
first time) is a short blip; (2) the first note after a switch into another Part (the OT-303 on the same track) is
shorter. ot_emu, BOTLI: T2 an OT-303 in Part 1 (pattern 0) and Part 2 (pattern 1), a note every step; Part 2's T2
GATE 120 / DEC 110 (Part 1: the defaults). Pattern 1 cued at frame 9000. The event log (gate samples) and the
SETUP live bytes (0x80000810 + 72 t + 0x20..: WAVE TUNE SLID GATE VOL) and the page-1 lane (PTCH CUT RES ENV DEC ACC,
the record's fp at 0x800062a8 -> 6 halfwords) are dumped along the way.
    STALE=1 python3 tools/ot303/verify_first_gate.py [image] [elf]   (STALE=1: the live GATE byte left at 0, as a load leaves it)
  Pass: every note in Part 1 gets 4136 samples (GATE 74), every note in Part 2 6672 (GATE 120), the first ones included."""
import os, sys, tempfile
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
FRAMES, CUE_AT = 16500, 9000


def line(t, pat, notes):
    out = []
    for off, val in ((0x04, sum(1 << x for x in notes)), (0x0c, 0), (0x14, 0), (0x4c, 0)):
        out += [f'{B0 + pat * 0x8ed8 + t * 0x91a + off + i:#x}={b:#x}' for i, b in enumerate(val.to_bytes(4, 'big'))]
    return out


def bp(t, p, knobs):
    o = p * STRIDE
    out = [f'{PART + o + 0x22 + t:#x}=1'] + [f'{PART + o + 60 + 30 * t + i:#x}={c:#x}' for i, c in enumerate(b'OT\x01')]
    out += [f'{PART + o + (0x2a if k < 6 else 0x1da) + 30 * t + 6 + k % 6:#x}={v:#x}' for k, v in enumerate(knobs)]
    if p == 0:
        out += [f'{0x80000810 + 72 * t + 0x20 + k - 6:#x}={(0 if (k == 9 and os.environ.get("STALE")) else v):#x}'
                for k, v in enumerate(knobs) if k >= 6]
    return out


K1 = list(V.DEFAULTS)
K2 = list(V.DEFAULTS); K2[9] = 120; K2[4] = 110          # GATE (SETUP 9), DEC (page 1, 4)
pokes = bp(1, 0, K1) + line(1, 0, range(16)) + bp(1, 1, K2) + line(1, 1, range(16))
AT = list(range(500, FRAMES, 250))
with tempfile.TemporaryDirectory() as td:
    args = ['--sequencer', '--internal-clock', '--frames', str(FRAMES), '--step', '-:poke:' + ';'.join(pokes),
            '--step', f'{CUE_AT}:call:{O.CUE:#x},0,1']
    for fr in AT:
        args += ['--step', f'{fr}:dump:{S["ot_evlog"]:#x},128={td}/l{fr}.bin;{S["ot_evn"]:#x},4={td}/n{fr}.bin;'
                 f'{0x80000810 + 72 * 1 + 0x20:#x},5={td}/s{fr}.bin;0x80000003,1={td}/p{fr}.bin;{S["ot_frames"]:#x},4={td}/f{fr}.bin']
    p = V.emu(IMAGE, args, td)
    g = {f[:-4]: open(os.path.join(td, f), 'rb').read() for f in os.listdir(td) if f.endswith('.bin')}
w = lambda b, i: int.from_bytes(b[4 * i:4 * i + 4], 'big')
seen = 0
print(f'rc {p.returncode}  image {os.path.basename(IMAGE)}')
for fr in AT:
    if f'n{fr}' not in g:
        continue
    n = w(g[f'n{fr}'], 0)
    new = [(w(g[f'l{fr}'], i & 31)) for i in range(max(seen, n - 32), n)]
    seen = n
    gates = [x & 0xffffff for x in new if (x >> 28) == 1 and (x >> 24 & 15) & 1]
    if gates:
        print(f'  frame {fr:5} (ot_frames {w(g[f"f{fr}"], 0):5}) engine Part {g[f"p{fr}"][0]} T2 SETUP live (WAVE TUNE SLID GATE VOL) '
              f'{list(g[f"s{fr}"])}: notes, gate samples {gates}')
ok = p.returncode == 0
allg = []
for fr in AT:
    if f'n{fr}' in g:
        allg.append((g[f'p{fr}'][0], fr))
bad = []
seen = 0
for fr in AT:
    if f'n{fr}' not in g:
        continue
    n = w(g[f'n{fr}'], 0)
    new = [w(g[f'l{fr}'], i & 31) for i in range(max(seen, n - 32), n)]
    seen = n
    for x in new:
        if (x >> 28) == 1 and (x >> 24 & 15) & 1:
            gl = x & 0xffffff
            if gl not in (4136, 6672):
                bad.append((fr, gl))
sw = next((fr for part, fr in allg if part == 1), None)
post = []
seen = 0
for fr in AT:
    if f'n{fr}' not in g:
        continue
    n = w(g[f'n{fr}'], 0)
    new = [w(g[f'l{fr}'], i & 31) for i in range(max(seen, n - 32), n)]
    seen = n
    if sw and fr > sw:
        post += [x & 0xffffff for x in new if (x >> 28) == 1 and (x >> 24 & 15) & 1]
c1 = not bad
c2 = bool(post) and post[0] == 6672
print(f'   {"ok  " if c1 else "FAIL"} every note gate is its Part GATE (off: {bad[:4]})')
print(f'   {"ok  " if c2 else "FAIL"} the first note into Part 2 has the GATE of Part 2 ({post[:2]})')
ok &= c1 and c2
print('ALL GOOD' if ok else 'FAILED')
sys.exit(0 if ok else 1)

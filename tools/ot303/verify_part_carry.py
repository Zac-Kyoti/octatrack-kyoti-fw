#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""OCTABAM40 item 7 (2026-11-19): a cued Part switch from a Part with an OT-303 on one track to a Part with an OT-303
on another track of the same core. ot_emu (no audio: the voice is not in this emulator's mix), BOTLI, the runtime's
own trace (ot_trace / ot_tracet: kind 2 = a trig flag the renderer took as an OT-303, a = the step).
  fwd  Part 1 T2 a note every step; Part 2 (pattern 1) T3 one trig, step 5: T2's step-16 note is taken (it was lost:
       the renderer asked the UI Part, which moves ~7 ticks early), T2 keeps rendering until T3's trig, T3's note
       is taken; ot_yields > 0
  rev  Part 1 T4 a note every step; Part 2 T2 one trig, step 5: the same, and T2's first note held one frame
       (ot_handovers > 0) while T4 still holds the voice
    python3 tools/ot303/verify_part_carry.py [image] [elf]   (default: the standalone unit)"""
import os, sys, re, tempfile, concurrent.futures as cf
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


def line(t, pat, steps):
    out = []
    v = sum(1 << x for x in steps)
    for off, val in ((0x04, v), (0x0c, 0), (0x14, 0), (0x4c, 0)):
        out += [f'{B0 + pat * 0x8ed8 + t * 0x91a + off + i:#x}={b:#x}' for i, b in enumerate(val.to_bytes(4, 'big'))]
    return out


def bp(t, p):
    o = p * STRIDE
    out = [f'{PART + o + 0x22 + t:#x}=1'] + [f'{PART + o + 60 + 30 * t + i:#x}={c:#x}' for i, c in enumerate(b'OT\x01')]
    out += [f'{PART + o + (0x2a if k < 6 else 0x1da) + 30 * t + 6 + k % 6:#x}={v:#x}' for k, v in enumerate(V.DEFAULTS)]
    if p == 0:
        out += [f'{0x80000810 + 72 * t + 0x20 + k - 6:#x}={v:#x}' for k, v in enumerate(V.DEFAULTS) if k >= 6]
    return out


def lens(t, pat, n=16):
    return [f'{B0 + pat * 0x8ed8 + t * 0x91a + 0x50:#x}={n:#x}']


SC = {
    'fwd': (1, 2, bp(1, 0) + line(1, 0, range(16)) + bp(2, 1) + line(2, 1, [4]) + line(2, 0, [])),
    'rev': (3, 1, bp(3, 0) + line(3, 0, range(16)) + lens(3, 0) + bp(1, 1) + line(1, 1, [4]) + line(1, 0, [])),
}
DUMPS = list(range(CUE_AT + 3000, FRAMES, 100))


def run(k, pokes):
    with tempfile.TemporaryDirectory() as td:
        args = ['--sequencer', '--internal-clock', '--frames', str(FRAMES), '--step', '-:poke:' + ';'.join(pokes),
                '--step', f'{CUE_AT}:call:{O.CUE:#x},0,1']
        for fr in DUMPS:
            args += ['--step', f'{fr}:dump:0x80000002,2={td}/e{fr}.bin;0x8000182a,16={td}/pp{fr}.bin']
        args += ['--mem-dump', f'{S["ot_trace"]:#x},512={td}/tr.bin;{S["ot_tracet"]:#x},512={td}/tt.bin;'
                 f'{S["ot_tracen"]:#x},4={td}/tn.bin;{S["ot_yields"]:#x},4={td}/y.bin;{S["ot_handovers"]:#x},4={td}/h.bin']
        p = V.emu(IMAGE, args, td)
        g = {f[:-4]: open(os.path.join(td, f), 'rb').read() for f in os.listdir(td) if f.endswith('.bin')}
    return p, g


with cf.ThreadPoolExecutor(2) as ex:
    res = {k: f.result() for k, f in {k: ex.submit(run, k, v[2]) for k, v in SC.items()}.items()}
ok = True
for k, (p, g) in res.items():
    old, new = SC[k][0], SC[k][1]
    sw = next((fr for fr in DUMPS if g.get(f'e{fr}', b'\0\0')[1] == 1), None)
    w = lambda b, i: int.from_bytes(b[4 * i:4 * i + 4], 'big')
    n = w(g['tn'], 0)
    ev = sorted((w(g['tt'], i & 127), w(g['tr'], i & 127)) for i in range(max(0, n - 128), n))
    flags = [(f, x >> 24 & 15, x >> 16 & 255) for f, x in ev if x >> 28 == 2]
    print(f'{k}: rc {p.returncode}; the engine Part is 2 by frame {sw}; yields {w(g["y"], 0)}, handovers {w(g["h"], 0)}')
    for fr in DUMPS:
        pp = g.get(f'pp{fr}')
        if pp and fr % 500 == 0:
            print(f'    frame {fr}: engine bank/Part {tuple(g[f"e{fr}"])}; T{old + 1} plays (bank, Part) ({pp[old]}, {pp[8 + old]}), '
                  f'T{new + 1} ({pp[new]}, {pp[8 + new]})')
    print('    renderer trig flags taken (ot_frames, track, step):', [(f, t + 1, s) for f, t, s in flags][-14:])
    f_new = next((f for f, t, s in flags if t == new and s == 4), None)
    last_old = [s for f, t, s in flags if t == old and (f_new is None or f < f_new)]
    got_new = [s for f, t, s in flags if t == new]
    c1 = bool(last_old) and last_old[-1] == 15
    c2 = f_new is not None and f_new > (sw or 0) and got_new == [4]
    print(f'    {"ok  " if c1 else "FAIL"} T{old + 1}: its last note before the handover is step 16 (last steps taken {last_old[-4:]})')
    print(f'    {"ok  " if c2 else "FAIL"} T{new + 1}: only its step-5 note taken, after the switch (frame {f_new})')
    ok &= c1 and c2 and p.returncode == 0
    if k == 'fwd':
        ok &= w(g['y'], 0) > 0
    else:
        c3 = w(g['h'], 0) > 0
        print(f'    {"ok  " if c3 else "FAIL"} the incoming note held one frame (handovers {w(g["h"], 0)})')
        ok &= c3
print('ALL GOOD' if ok else 'FAILED')
sys.exit(0 if ok else 1)

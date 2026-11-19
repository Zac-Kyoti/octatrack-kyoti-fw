#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""SRC page copy / paste keeps the machine (B3, 2026-11-18). ot_emu, BOTLI, stock routines through call steps:
page copy 0x40027d38(part, track, page, midi), the undo save 0x40027d64(0x2d, ...), the page paste 0x40028fc4(part,
track, page, midi), the page UNDO 0x40028f40(0x2d, ...) -- the [FUNC]+[COPY]/[PASTE] handler's own calls (0x4005df40..).
  flex_on_bp    T2 BLKPYRAMD, T4 FLEX: copy T4's SRC, paste onto T2 -> T2 a plain FLEX with T4's twelve values;
                then UNDO -> T2 a BLKPYRAMD again with its own knobs
  bp_on_flex    T1 BLKPYRAMD, T3 / T5 FLEX: copy T1's SRC, paste onto T5 (core 0) -> a BLKPYRAMD with T1's knobs;
                paste onto T3 (core 1) -> refused (0), T3 unchanged, one toast
  static_on_bp  T2 BLKPYRAMD, T4 STATIC: copy T4's SRC, paste onto T2 -> T2 STATIC with T4's static values, no
                signature, its FLEX values the pre-303 ones
    python3 tools/ot303/verify_page_paste.py [image elf]   (default: the standalone unit; V1.8BC: its mainos + bp_runtime/ot303_runtime.elf)"""
import os, re, sys, tempfile, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import verify_ot303 as V
import verify_one_per_core as O

IMAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'out/BLACKPYRAMIDS_303/mainos_blackpyramids_303.bin')
if len(sys.argv) > 2:
    V.ELF = sys.argv[2]
S = V.syms()
PART, SHADOW, STRIDE = O.PART, O.SHADOW, O.STRIDE
PCOPY, PSAVE, PPASTE, PUNDO = 0x40027d38, 0x40027d64, 0x40028fc4, 0x40028f40
mk, machine = O.mk, O.machine


def c(a, *args):
    return f'call:{a:#x},' + ','.join(str(x) for x in args)


def dump(name):
    return f'dump:{PART:#x},{STRIDE}=@/{name}.bin;{SHADOW:#x},{STRIDE}=@/{name}_sh.bin'


SC = {
    'flex_on_bp': [('-', [dump('pre0')] + mk(S, 1) + machine(3, 1)), (40, [dump('pre')]),
                   (50, [c(PCOPY, 0, 3, 0, 0)]), (60, [c(PSAVE, 0x2d, 0, 1, 0, 0)]), (70, [c(PPASTE, 0, 1, 0, 0)]),
                   (200, [dump('mid')]), (300, [c(PUNDO, 0x2d, 0, 1, 0, 0)])],
    'bp_on_flex': [('-', mk(S, 0) + machine(2, 1) + machine(4, 1)), (40, [dump('pre')]),
                   (50, [c(PCOPY, 0, 0, 0, 0)]), (60, [c(PSAVE, 0x2d, 0, 4, 0, 0)]), (70, [c(PPASTE, 0, 4, 0, 0)]),
                   (200, [dump('mid')]), (250, [c(PSAVE, 0x2d, 0, 2, 0, 0)]), (260, [c(PPASTE, 0, 2, 0, 0)])],
    'static_on_bp': [('-', [dump('pre0')] + mk(S, 1) + machine(3, 0)), (40, [dump('pre')]),
                     (50, [c(PCOPY, 0, 3, 0, 0)]), (60, [c(PSAVE, 0x2d, 0, 1, 0, 0)]), (70, [c(PPASTE, 0, 1, 0, 0)])],
}


def run(steps, frames=700):
    with tempfile.TemporaryDirectory() as td:
        args = ['--sequencer', '--internal-clock', '--frames', str(frames), '--main-level', '64']
        for fr, acts in steps:
            pk = []
            for a in acts:
                if a.startswith('poke:'):
                    pk.append(a[5:]); continue
                if pk:
                    args += ['--step', f'{fr}:poke:' + ';'.join(pk)]; pk = []
                args += ['--step', f'{fr}:' + a.replace('@', td)]
            if pk:
                args += ['--step', f'{fr}:poke:' + ';'.join(pk)]
        args += ['--watch-pc', f'{O.NOTIFY:#x}']
        args += ['--mem-dump', f'{PART:#x},{STRIDE}={td}/post.bin;{SHADOW:#x},{STRIDE}={td}/post_sh.bin;'
                 f'{S["bp_toasts"]:#x},4={td}/toasts.bin;{S["bp_net_demoted"]:#x},4={td}/demoted.bin']
        p = V.emu(IMAGE, args, td)
        got = {f[:-4]: open(os.path.join(td, f), 'rb').read() for f in os.listdir(td) if f.endswith('.bin')}
    calls = re.findall(r'call\s+: (0x[0-9a-f]+)\(\d+ args\) returned, d0 = (0x[0-9a-f]+|\d+)', p.stdout)
    return p, got, calls


def sig(b, t):
    return b[0x22 + t] == 1 and b[60 + 30 * t:63 + 30 * t] == b'OT\x01'


def slot(b, t, m):                                   # machine m's twelve bytes (page 1 then SETUP)
    return bytes(b[0x2a + 30 * t + 6 * m:0x2a + 30 * t + 6 * m + 6]) + bytes(b[0x1da + 30 * t + 6 * m:0x1da + 30 * t + 6 * m + 6])


with cf.ThreadPoolExecutor(len(SC)) as ex:
    res = {k: f.result() for k, f in {k: ex.submit(run, v) for k, v in SC.items()}.items()}
ok = True


def check(cond, what):
    global ok
    print(f'   {"ok  " if cond else "FAIL"} {what}')
    ok &= bool(cond)


print(f'image {IMAGE}\nruntime {V.ELF}')
for k, (p, g, calls) in res.items():
    toasts = int.from_bytes(g.get('toasts', bytes(4)), 'big')
    print(f'{k}: rc {p.returncode}; calls {calls}; toasts {toasts}')
    check(p.returncode == 0 and 'ILLEGAL' not in p.stdout, 'the run ends cleanly')
    pre, post = g.get('pre', b''), g.get('post', b'')
    pastes = [int(r, 0) for a, r in calls if a == f'{PPASTE:#x}']
    if k == 'flex_on_bp':
        mid, pre0 = g.get('mid', b''), g.get('pre0', b'')
        check(sig(pre, 1) and not sig(pre, 3), 'set up: T2 a BLKPYRAMD, T4 not')
        check(pastes == [1], 'the paste went through (1)')
        check(not sig(mid, 1) and mid[0x22 + 1] == 1, 'after the paste T2 is a plain FLEX')
        check(slot(mid, 1, 1) == slot(pre, 3, 1), f'... with T4\'s FLEX values {list(slot(pre, 3, 1))} (got {list(slot(mid, 1, 1))})')
        check(not sig(g.get('mid_sh', b''), 1), '... in the SRAM copy too')
        check(calls[-1][0] == f'{PUNDO:#x}' and int(calls[-1][1], 0) != 0, 'UNDO went through')
        check(sig(post, 1) and slot(post, 1, 1) == slot(pre, 1, 1), f'after UNDO T2 is a BLKPYRAMD with its own knobs {list(slot(pre, 1, 1))}')
        check(toasts == 0, 'no toast')
    elif k == 'bp_on_flex':
        mid = g.get('mid', b'')
        check(pastes[:1] == [1] and sig(mid, 4) and slot(mid, 4, 1) == slot(pre, 0, 1),
              f'T5 (core 0) a BLKPYRAMD with T1\'s knobs {list(slot(pre, 0, 1))}')
        check(sig(g.get('mid_sh', b''), 4), '... in the SRAM copy too')
        check(pastes == [1, 0], 'the paste onto T3 (core 1) refused (0)')
        check(not sig(post, 2) and slot(post, 2, 1) == slot(pre, 2, 1) and post[0x22 + 2] == pre[0x22 + 2], 'T3 unchanged')
        check(sig(post, 0) and sig(post, 4), 'T1 and T5 still BLKPYRAMD')
        check(toasts == 1, 'one toast')
    elif k == 'static_on_bp':
        pre0 = g.get('pre0', b'')
        check(pastes == [1], 'the paste went through')
        check(post[0x22 + 1] == 0 and not (post[60 + 30] == ord('O') and post[61 + 30] == ord('T')), 'T2 STATIC, no signature')
        check(slot(post, 1, 0) == slot(pre, 3, 0), 'T2 has T4\'s STATIC values')
        check(slot(post, 1, 1) == slot(pre0, 1, 1), f'T2\'s FLEX values are its pre-303 ones {list(slot(pre0, 1, 1))}')
        check(toasts == 0, 'no toast')
print('ALL GOOD' if ok else 'FAILED')
sys.exit(0 if ok else 1)

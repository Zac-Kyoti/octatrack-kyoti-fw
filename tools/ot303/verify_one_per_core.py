#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
One BLKPYRAMD per DSP core, on every path (the author, 2026-11-17): the emulator gate for the paths the chooser's
refusal does not see (control.c "One BLKPYRAMD per DSP core, on every path"). ot_emu, the BOTLI project (verify_ot303's
setup: out/ot303/ot_emu_8d0ad6f4, its card), transport running. Every change is made the stock way in RAM: stock's
own routines through the emulator's call steps (TRACK COPY 0x4002993c, the undo copy 0x400298d0, the paste wrapper
0x4002b988, the Part validator 0x40002318, the pattern cue 0x400a1030), a BLKPYRAMD track made by the runtime's own
ot_assign (what the chooser's commit calls) plus its machine byte, a stock machine-byte writer as a poke of both
copies (SRC page paste 0x40027e4c and the file browser's 0x40093e9c write only that byte). No file is edited.

  paste_t3   T1 BLKPYRAMD; TRACK COPY T1, the undo copy, TRACK PASTE onto T3 (same core): refused -- T3 and the whole
             Part unchanged, the wrapper returns 0, the undo state cleared, ONE toast (NOTIFY with our text, once)
  paste_t5   the same onto T5 (the other core): pasted -- T5 is a BLKPYRAMD, no toast
  stale      T2 BLKPYRAMD; T2 -> STATIC by a machine-byte write (SRC page paste): its signature is stale; T1 ->
             BLKPYRAMD; T2 -> FLEX by a machine-byte write: T2 must NOT come back as a BLKPYRAMD (the net cleared the
             stale signature at its first pass) -- with the FLEX values it had before it was one; no toast
  load_two   T2 and T3 BLKPYRAMD (two on core 1) and the Part validator run (as every bank / project load runs it):
             the net keeps T2 (the lowest-numbered, a load), T3 goes back to FLEX with its pre-303 values, the Part is
             marked edited, ONE toast
  held       T2 BLKPYRAMD for a while, then T1 becomes one too (no load: an undo, a stock writer): the net keeps T2
             (it held the core at the previous pass), T1 goes back to FLEX, ONE toast
  partswitch Part 1's T2 and Part 2's T3 BLKPYRAMD (the same core, different Parts); pattern 1 linked to Part 2 and
             cued, then pattern 0 again: two Part switches -- nothing refused, nothing demoted, no toast
  inactive_cue  T2 and T3 BLKPYRAMD written into Part 2 (NOT the active Part: the fast path's fingerprint does not see
             it), pattern 1 linked to Part 2 and cued at once: the net repairs Part 2 when the cue is made (the pending
             pattern woke it: bp_net_why bit 8), while Part 1 still plays -- before Part 2 sounds (the switch lands
             ~7,000 frames later); T2 kept, one toast. (Both made at frame 50, transport running: a cue while stopped
             switches at once, and the Part-change wake (bit 4) catches it then, before the transport starts.)
  inactive_periodic  the same with no cue: the periodic full pass repairs it (why bit 16), Part 1 playing throughout
  cost       watch-pc on bp_uitail's entry, its fast exit (bp_ut_idle) and its full pass (bp_ut_full and after the
             call): instructions per idle pass and per full pass, from the instruction-count timestamps; the amortised
             cost a second at the UI's 60 Hz tick with a full pass every NET_EVERY = 60

    python3 tools/ot303/verify_one_per_core.py [--image out/BLACKPYRAMIDS_303/mainos_blackpyramids_303.bin]
        [--elf out/ot303/cf/ot303_runtime.elf] [--only a,b] [--control]   (--control: the scenarios that need no new
        symbol on an image without the net -- the evidence of the bug)
"""
import argparse, concurrent.futures as cf, os, re, struct, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import verify_ot303 as V  # noqa: E402

PART, SHADOW, STRIDE = V.PART, V.SHADOW, 0x18b2
BANK0 = V.BANK0
COPY, UNDO_SAVE, PASTE, VALIDATE, CUE, NOTIFY = 0x4002993c, 0x400298d0, 0x4002b988, 0x40002318, 0x400a1030, 0x4005a2b8
CTRS = {"bp_pend": "bp_pend", "stale": "bp_net_stale", "demoted": "bp_net_demoted", "passes": "bp_net_passes",
        "refusals": "bp_refusals", "toasts": "bp_toasts", "full": "bp_net_full", "why": "bp_net_why", "fixpart": "bp_net_fixpart"}


def mk(S, t, p=0):
    """track t of Part p a BLKPYRAMD, as the chooser's commit makes it: ot_assign(part, t, 1), then FLEX"""
    return [f'call:{S["ot_assign"]:#x},{PART + p * STRIDE:#x},{t},1',
            f'poke:{PART + p * STRIDE + 0x22 + t:#x}=1;{SHADOW + p * STRIDE + 0x22 + t:#x}=1']


def machine(t, v, p=0):
    return [f'poke:{PART + p * STRIDE + 0x22 + t:#x}={v};{SHADOW + p * STRIDE + 0x22 + t:#x}={v}']


def scenarios(S):
    return {
        'paste_t3': (600, [('-', mk(S, 0)), (40, ['dump:pre']), (50, [f'call:{COPY:#x},0,0']),
                           (70, [f'call:{UNDO_SAVE:#x},7,0,2']), (80, [f'call:{PASTE:#x},0,2'])]),
        'paste_t5': (600, [('-', mk(S, 0)), (40, ['dump:pre']), (50, [f'call:{COPY:#x},0,0']),
                           (70, [f'call:{UNDO_SAVE:#x},7,0,4']), (80, [f'call:{PASTE:#x},0,4'])]),
        'stale': (900, [('-', ['dump:pre'] + mk(S, 1)), (100, machine(1, 0)), (300, mk(S, 0)), (500, machine(1, 1))]),
        'load_two': (900, [('-', ['dump:pre'] + mk(S, 1) + mk(S, 2) + [f'call:{VALIDATE:#x},{PART:#x}'])]),
        'held': (900, [('-', ['dump:pre'] + mk(S, 1)), (300, mk(S, 0))]),
        'inactive_cue': (2000, [('-', [f'poke:{BANK0 + 0x8ed8 + 0x8e57:#x}=1']),
                                (50, ['dump:pre'] + mk(S, 1, 1) + mk(S, 2, 1) + [f'call:{CUE:#x},0,1'])]),
        'inactive_periodic': (2000, [('-', ['dump:pre'] + mk(S, 1, 1) + mk(S, 2, 1))]),
        'partswitch': (24000, [('-', mk(S, 1, 0) + mk(S, 2, 1) + [f'poke:{BANK0 + 0x8ed8 + 0x8e57:#x}=1']),
                               (50, [f'call:{CUE:#x},0,1']), (9000, [f'call:{CUE:#x},0,0'])]),
    }


def run(image, S, name, frames, steps, watch=None, dumps_at=()):
    with tempfile.TemporaryDirectory() as td:
        args = ['--sequencer', '--internal-clock', '--frames', str(frames), '--main-level', '64']
        for fr, acts in steps:
            pk = []
            for a in acts:
                if a.startswith('poke:'):
                    pk.append(a[5:])
                    continue
                if pk:
                    args += ['--step', f'{fr}:poke:' + ';'.join(pk)]; pk = []
                if a == 'dump:pre':
                    args += ['--step', f'{fr}:dump:{PART:#x},{2 * STRIDE}={td}/pre.bin;{SHADOW:#x},{STRIDE}={td}/preshadow.bin']
                else:
                    args += ['--step', f'{fr}:{a}']
            if pk:
                args += ['--step', f'{fr}:poke:' + ';'.join(pk)]
        for fr in dumps_at:
            args += ['--step', f'{fr}:dump:0x80000003,1={td}/part_{fr}.bin']
        args += ['--watch-pc', watch or f'{NOTIFY:#x}']
        args += ['--mem-dump', f'{PART:#x},{2 * STRIDE}={td}/post.bin;{SHADOW:#x},{2 * STRIDE}={td}/shadow.bin;'
                 + ''.join(f'{S[sym]:#x},4={td}/ctr_{k}.bin;' for k, sym in CTRS.items()) +
                 f'0x460c80f0,8={td}/undo.bin;{BANK0 + 0x95048:#x},1={td}/edited.bin;'
                 f'0x80000003,1={td}/part.bin']
        p = V.emu(image, args, td)
        got = {f[:-4]: open(os.path.join(td, f), 'rb').read() for f in os.listdir(td) if f.endswith('.bin')}
    calls = re.findall(r'call\s+: (0x[0-9a-f]+)\(\d+ args\) returned, d0 = (0x[0-9a-f]+|\d+)', p.stdout)
    hits = re.findall(r'\[\s*(\d+)\] at (0x[0-9a-f]+) .*?\[sp 0x[0-9a-f]+: (\S+) (\S+)', p.stdout)
    return p, got, calls, hits


def sig(b, t, p=0):
    o = p * STRIDE
    return b[o + 0x22 + t] == 1 and b[o + 60 + 30 * t:o + 63 + 30 * t] == b'OT\x01'


def flexrow(b, t, p=0):
    o = p * STRIDE
    return bytes(b[o + 0x2a + 30 * t + 6:o + 0x2a + 30 * t + 12]) + bytes(b[o + 0x1da + 30 * t + 6:o + 0x1da + 30 * t + 12])


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', default=os.path.join(ROOT, 'out/BLACKPYRAMIDS_303/mainos_blackpyramids_303.bin'))
    ap.add_argument('--elf', default=None)
    ap.add_argument('--only', default='')
    a = ap.parse_args(argv)
    if a.elf:
        V.ELF = a.elf
    S = V.syms()
    reject = S['ot_reject_name']
    sc = scenarios(S)
    only = [x for x in a.only.split(',') if x] or list(sc) + ['cost']
    jobs = {k: (k, *sc[k]) for k in sc if k in only}
    if 'cost' in only:
        jobs['cost'] = ('cost', 900, [('-', mk(S, 1) + mk(S, 2) + [f'call:{VALIDATE:#x},{PART:#x}'])])
    print(f'image {a.image}\nruntime {V.ELF}')
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        fut = {}
        for k, (name, fr, st) in jobs.items():
            w = f'{S["bp_uitail"]:#x},{S["bp_ut_idle"]:#x},{S["bp_ut_full"]:#x},{S["bp_ut_full"] + 6:#x}' if k == 'cost' else None
            fut[k] = ex.submit(run, a.image, S, name, fr, st, w, (8500, 23500) if k == 'partswitch' else ())
        res = {k: f.result() for k, f in fut.items()}
    ok = True

    def check(cond, what):
        nonlocal ok
        print(f'   {"ok  " if cond else "FAIL"} {what}')
        ok &= bool(cond)
    for k, (p, got, calls, hits) in res.items():
        print(f'{k}: rc {p.returncode}')
        check(p.returncode == 0 and 'ILLEGAL' not in p.stdout, 'the run ends cleanly')
        c = {k: int.from_bytes(got.get(f'ctr_{k}', bytes(4)), 'big') for k in CTRS}
        post, pre = got.get('post', b''), got.get('pre', b'')
        ours = [h for h in hits if int(h[3], 0) == reject]
        if k != 'cost':
            print(f'      counters {{full passes {c["full"]}, refusals {c["refusals"]}, toasts {c["toasts"]}, demoted {c["demoted"]}, '
                  f'stale {c["stale"]}, pend {c["bp_pend"]}, why 0x{c["why"]:x}, fixpart {c["fixpart"]}}}; NOTIFY calls {len(hits)} '
                  f'(with our text {len(ours)}); calls {calls}')
            check(c['full'] >= 3, f'the net ran on the UI task ({c["full"]} full passes)')
        if k == 'paste_t3':
            check(calls and calls[-1][0] == f'{PASTE:#x}' and int(calls[-1][1], 0) == 0, 'the paste wrapper returned 0 (no PASTE TRACK toast)')
            check(pre[:STRIDE] == post[:STRIDE], 'the whole Part is as before the paste (T3 kept what it had)')
            check(not sig(post, 2) and sig(post, 0), 'T1 is the only BLKPYRAMD on core 1')
            check(got.get('undo') == bytes(8), 'the undo state cleared (stock\'s after an undo)')
            check(c['refusals'] == 1 and c['toasts'] == 1 and len(ours) == 1 and len(hits) == 1, 'exactly one toast, ours')
        elif k == 'paste_t5':
            check(calls and int(calls[-1][1], 0) == 1, 'the paste wrapper returned 1 (stock\'s PASTE TRACK)')
            check(sig(post, 4) and sig(post, 0), 'T5 is a BLKPYRAMD (core 0), T1 still one (core 1)')
            check(flexrow(post, 4) == flexrow(post, 0), 'T5 carries T1\'s knobs')
            check(c['refusals'] == 0 and c['toasts'] == 0 and c['demoted'] == 0 and not ours, 'no refusal, no toast, nothing demoted')
        elif k == 'stale':
            check(sig(post, 0) and not sig(post, 1), 'T1 a BLKPYRAMD; T2 FLEX, not one (no revival on core 1)')
            check(post[60 + 30 * 1] == 0x50, 'T2\'s signature replaced by the park mark (the stale one cleared)')
            check(flexrow(post, 1) == flexrow(pre, 1), f'T2\'s FLEX values are its pre-303 ones {list(flexrow(pre, 1))}')
            check(c['stale'] == 1 and c['demoted'] == 0 and c['toasts'] == 0 and not ours, 'one stale signature cleared, nothing demoted, no toast')
        elif k in ('load_two', 'held'):
            keep, gone = (1, 2) if k == 'load_two' else (1, 0)
            check(sig(post, keep) and not sig(post, gone), f'T{keep + 1} kept, T{gone + 1} no longer a BLKPYRAMD')
            check(post[0x22 + gone] == 1 and flexrow(post, gone) == flexrow(pre, gone),
                  f'T{gone + 1} is FLEX with its pre-303 values {list(flexrow(pre, gone))} (got {list(flexrow(post, gone))})')
            sh = got.get('shadow', b'')
            check(not sig(sh, gone) and sig(sh, keep), 'the same in the SRAM copy')
            check(got.get('edited', b'\0')[0] & 1, f'Part 1 marked edited (0x{got.get("edited", b"")[:1].hex()})')
            check(c['demoted'] == 1 and c['toasts'] == 1 and len(ours) == 1 and c['bp_pend'] == 0,
                  'one track demoted, exactly one toast, nothing left pending')
        elif k in ('inactive_cue', 'inactive_periodic'):
            pre1, post1 = pre[STRIDE:], post[STRIDE:]
            check(sig(post, 1, 1) and not sig(post, 2, 1), 'Part 2: T2 kept, T3 no longer a BLKPYRAMD')
            check(post1[0x22 + 2] == 1 and flexrow(post, 2, 1) == flexrow(pre, 2, 1), 'Part 2 T3: FLEX with its pre-303 values')
            check(c['demoted'] == 1 and c['toasts'] == 1 and len(ours) == 1, 'one track demoted, one toast')
            bit = 8 if k == 'inactive_cue' else 16
            check(c['why'] == bit, f'repaired by the {"pending pattern" if bit == 8 else "periodic full pass"} (why 0x{c["why"]:x})')
            check(c['fixpart'] == 0, f'... while Part 1 still played (the engine Part at the repair: {c["fixpart"]})')
        elif k == 'partswitch':
            seen = {fr: got.get(f'part_{fr}', b'?')[0] for fr in (8500, 23500)}
            print(f'      the playing Part (0x80000003) at frame 8500 / 23500: {seen} (0 = Part 1, 1 = Part 2)')
            check(seen.get(8500) == 1 and seen.get(23500) == 0, 'both Part switches happened (Part 2, then Part 1)')
            check(sig(post, 1, 0) and sig(post, 2, 1), 'Part 1 T2 and Part 2 T3 still BLKPYRAMD')
            check(c['refusals'] == 0 and c['toasts'] == 0 and c['demoted'] == 0 and not ours, 'nothing refused, nothing demoted, no toast')
        elif k == 'cost':
            ev = sorted((int(h[0]), int(h[1], 16)) for h in hits)
            idle, full = [], []
            for (t0, a0), (t1, a1) in zip(ev, ev[1:]):
                if a0 == S['bp_uitail'] and a1 == S['bp_ut_idle']:
                    idle.append(t1 - t0 + 2)                     # + the exit's tst.l and rts
                if a0 == S['bp_uitail'] and a1 == S['bp_ut_full']:
                    full.append(t1 - t0)
            fulls = [t1 - t0 + 2 for (t0, a0), (t1, a1) in zip(ev, ev[1:]) if a0 == S['bp_ut_full'] and a1 == S['bp_ut_full'] + 6]
            st = lambda v: (min(v), sorted(v)[len(v) // 2], max(v)) if v else (None, None, None)
            ia = st(idle)
            print(f'      idle passes timed {len(idle)}: instructions min / median / max {st(idle)}')
            print(f'      full passes timed {len(fulls)}: bp_net alone min / median / max {st(fulls)}; the fast checks before it '
                  f'{st(full)}  (a max: an interrupt inside, or the repair pass)')
            if idle and fulls and full:
                per_s = 59 * ia[1] + min(full) + min(fulls)
                print(f'      amortised at 60 passes a second, one full every 60: {per_s} instructions a second '
                      f'(was 60 x 525 = 31,500)')
            check(idle and ia[1] < 100, 'an idle pass under 100 instructions (median)')
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

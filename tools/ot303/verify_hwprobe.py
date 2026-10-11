#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 hardware probe (DIAG14) under the firmware (ot_emu, the BOTLI project playing): DJ EQ on all
# four FX1 slots of a core, page 2 poked per run; the voice at the per-track source seam.
#   src-*    the stopwatch over each track's source (seam PC -> the stock code after it):
#            inert (303 = 0 everywhere) = stock + the glue's guard on every track; voice (303 = 40 on the
#            core's 2nd track) = the engine on that track only, the other three as inert; tone (303 = 8)
#   dj-*     the stopwatch over FX1's second call: inert = stock DJ EQ + the remote's guard; voice = + the
#            claim on the 2nd track only
#   in       DJ EQ's input on the voice run (a pcwatch just after DJ EQ's stock proc reads its first
#            sample): the voice after stock AMP, per track
#   SPRING (id 0x15) -> the passthrough stub; DARK REV (0x16) and PLATE REV (0x14), whose shared helper
#   moved, against stock
# Instruction counts are the stopwatch's unit; the bench (hwprobe_check.py) prices cycles and checks
# the samples. ot_emu 8d0ad6f4's --audio-out capture is all zeros here, stock included: no audio check.
import concurrent.futures as cf, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(os.path.realpath(os.path.join(ROOT, 'refs', 'octabam')), 'out', 'botli_card2.img')
PROBE = os.path.join(ROOT, 'out', os.environ.get('HWP_IMAGE', 'mainos_ot303_hwprobe_diag14.bin'))
STOCK = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
SW = {(1, 1): '1:2cc:2cd', (0, 1): '0:4d7:4d8', (0, 2): '0:50d:50e', (1, 2): '1:302:303'}
SRC = {1: '1:1a2:221', 0: '0:39c:426'}           # payload B (core 1) / A (core 0): seam -> continuation
DJIN = {1: '1:1b43', 0: '0:1d83'}                 # DJ EQ's stock proc, after `move x:(r0)+,a`
IDS = {1: 0x80000ec4, 2: 0x80000ecc}
LANE = lambda t, slot: 0x80000810 + 72 * t + (0x32 if slot == 1 else 0x38)    # slot 6's byte; slot 7 = +1
FRAMES = int(os.environ.get('HWP_FRAMES', '3000'))


def run(image, core, slot, fxid, sw, t303=None, val=0, pcw=None):
    first = 0 if core == 1 else 4
    pokes = [f'{IDS[slot] + first + i:#x}={fxid:#x}' for i in range(4)]
    if image == PROBE:
        pokes += [f'{LANE(first + i, slot):#x}=0' for i in range(4)] + [f'{LANE(first + i, slot) + 1:#x}=0' for i in range(4)]
    if t303 is not None:
        pokes.append(f'{LANE(t303, slot) + 1:#x}={val:#x}')
    with tempfile.TemporaryDirectory() as td:
        card = os.path.join(td, 'card.img'); shutil.copyfile(CARD, card)
        args = [EMU, '--image', image, '--card', card, '--set', 'OCTABAM', '--project', 'BOTLI', '--mount',
                '--sequencer', '--internal-clock', '--frames', str(FRAMES), '--dsp', '--main-level', '64',
                '--dsp-stopwatch', sw, '--step', '5:poke:' + ';'.join(pokes)]
        if pcw:
            args += ['--dsp-pcwatch', pcw]
        p = subprocess.run(args, capture_output=True, text=True, timeout=7200)
        m = re.search(r'last 24:([\d ]+)', p.stdout)
        hits = []
        if pcw:
            sec = p.stdout.split('dsp pcwatch:', 1)
            if len(sec) == 2:
                for line in sec[1].splitlines()[1:]:
                    f = line.split()
                    if len(f) != 20 or ':' not in f[1]:
                        break
                    hits.append((f[1].split(':')[0], f[16]))      # a1, r7 (the instance block)
        return ([int(x) for x in m.group(1).split()] if m else None), p.returncode, hits


def main():
    os.makedirs(os.path.join(ROOT, 'out', 'ot303', 'hwprobe'), exist_ok=True)
    jobs = {}
    for core in (1, 0):
        t = 1 if core == 1 else 5
        first = 0 if core == 1 else 4
        jobs[('src-stock', core)] = (STOCK, core, 1, 0x0d, SRC[core])
        jobs[('src-inert', core)] = (PROBE, core, 1, 0x0d, SRC[core])
        jobs[('src-voice', core)] = (PROBE, core, 1, 0x0d, SRC[core], t, 40, DJIN[core])
        jobs[('src-tone', core)] = (PROBE, core, 1, 0x0d, SRC[core], t, 8)
        # the voice on the core's 4th track (BOTLI's T8 plays no sample): does stock AMP pass it?
        jobs[('src-idle', core)] = (PROBE, core, 1, 0x0d, SRC[core], first + 3, 40, DJIN[core])
        jobs[('dj-stock', core)] = (STOCK, core, 1, 0x0d, SW[(core, 1)])
        jobs[('dj-inert', core)] = (PROBE, core, 1, 0x0d, SW[(core, 1)])
        jobs[('dj-voice', core)] = (PROBE, core, 1, 0x0d, SW[(core, 1)], t, 40)
        jobs[('spring', core)] = (PROBE, core, 2, 0x15, SW[(core, 2)])
        for name, fx in (('dark', 0x16), ('plate', 0x14)):
            jobs[(name, core)] = (PROBE, core, 2, fx, SW[(core, 2)])
            jobs[(name + '-stock', core)] = (STOCK, core, 2, fx, SW[(core, 2)])
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        res = dict(zip(jobs, ex.map(lambda a: run(*a), jobs.values())))
    ok = True
    for k, (last, rc, _) in sorted(res.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f'{k[0]:12} core {k[1]}: rc {rc}  last 8 {last[-8:] if last else None}')
        ok &= rc == 0 and bool(last)
    if not ok:
        print('FAILED (a run did not finish)')
        return 1

    def by_track(v):
        return [v[-24:][i::4] for i in range(4)]        # the last 24 pairs: 6 frames x the core's 4 tracks
    for core in (1, 0):
        print(f'core {core}:')
        s, i = by_track(res[('src-stock', core)][0]), by_track(res[('src-inert', core)][0])
        d = [[b - a for a, b in zip(x, y)] for x, y in zip(s, i)]
        print(f'   source, inert - stock per track: {d}')
        ok &= all(0 <= v <= 16 for row in d for v in row)
        for v in ('src-voice', 'src-tone'):
            e = by_track(res[(v, core)][0])
            print(f'   {v}: track 2 {e[1]} (inert {i[1]}); tracks 1/3/4 as inert: {[e[k] == i[k] for k in (0, 2, 3)]}')
            ok &= all(e[k] == i[k] for k in (0, 2, 3))
            ok &= min(e[1]) > max(i[1]) + 3000 if v == 'src-voice' else all(150 < x < 400 for x in e[1])   # the tone: ~230
        s, i = by_track(res[('dj-stock', core)][0]), by_track(res[('dj-inert', core)][0])
        d = [[b - a for a, b in zip(x, y)] for x, y in zip(s, i)]
        e = by_track(res[('dj-voice', core)][0])
        dv = [[b - a for a, b in zip(x, y)] for x, y in zip(i, e)]
        print(f'   DJ EQ, inert - stock: {d}; voice - inert: {dv}')
        ok &= all(0 <= v <= 16 for row in d for v in row) and all(v == 0 for k in (0, 2, 3) for v in dv[k]) \
            and all(0 < v <= 60 for v in dv[1])
        sp = res[('spring', core)][0][-4:]
        print(f'   SPRING id -> {sp} (stub ~69)')
        ok &= all(x < 200 for x in sp)
        for name in ('dark', 'plate'):
            dk, dks = res[(name, core)][0], res[(name + '-stock', core)][0]
            # a reverb's work on a track with signal varies call to call (stock alike: 3207..3277 seen);
            # a track whose 6 stock calls are all equal must match exactly, the others stay in range
            same = True
            for t in range(4):
                a, b = dks[t::4], dk[t::4]
                same &= (b == a) if len(set(a)) == 1 else (min(a) <= min(b) and max(b) <= max(a) + 100)
            print(f'   {name.upper()} REV {dk[-4:]} vs stock {dks[-4:]}: {"same" if same else "DIFFERS"}')
            ok &= same
        for v in ('src-voice', 'src-idle'):
            hits = res[(v, core)][2]
            r7s = sorted({h[1] for h in hits})
            rows = {r: [h[0] for h in hits if h[1] == r] for r in r7s}
            print(f'   {v}: DJ EQ input (a1 after its first read; the last 24 samples) by instance (r7): ' +
                  '; '.join(f'{r}: {" ".join(x[-6:])}' for r, x in rows.items()))
        e = by_track(res[('src-idle', core)][0])
        print(f'   src-idle: track 4 {e[3]} (the voice there)')
        ok &= min(e[3]) > 3000
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

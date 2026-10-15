#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 0b: verify the burn-probe image under the firmware (ot_emu, BOTLI playing).
#   inert      BURN 0 on every DJ EQ: per call = stock DJ EQ + the 8-instruction guard
#   step       BURN n on ONE track: that track's call grows by 3 * 8 * n * 16 (+ the DO), others not
#   both cores, both slots; SPRING (id 0x15) -> the passthrough stub; DARK REV still runs
# Instruction counts (the stopwatch's unit). The 24-cycles-per-step scale is the body's
# cycle count (3 single-cycle nops per iteration, 8 iterations per step per sample).
import concurrent.futures as cf, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(os.path.realpath(os.path.join(ROOT, 'refs', 'octabam')), 'out', 'botli_card2.img')
PROBE = os.path.join(ROOT, 'out', 'mainos_ot303_burnprobe.bin')
STOCK = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
SW = {(1, 1): '1:2cc:2cd', (1, 2): '1:302:303', (0, 1): '0:4d7:4d8', (0, 2): '0:50d:50e'}
IDS = {1: 0x80000ec4, 2: 0x80000ecc}           # + track
LANE = lambda t, slot: 0x80000810 + 72 * t + (0x32 if slot == 1 else 0x38)


def run(image, core, slot, fxid, burn_track=None, burn=0, frames=120):
    first = 0 if core == 1 else 4
    pokes = [f'{IDS[slot] + first + i:#x}={fxid:#x}' for i in range(4)]
    # a poked id keeps the previous effect's page-2 bytes; choosing DJ EQ on the unit loads the
    # descriptor defaults (BURN 0) -- zero every BURN lane of this core and slot first
    if image == PROBE:
        pokes += [f'{LANE(first + i, slot):#x}=0' for i in range(4)]
    if burn_track is not None:
        pokes.append(f'{LANE(burn_track, slot):#x}={burn:#x}')
    with tempfile.TemporaryDirectory() as td:
        card = os.path.join(td, 'card.img'); shutil.copyfile(CARD, card)
        p = subprocess.run([EMU, '--image', image, '--card', card, '--set', 'OCTABAM', '--project',
                            'BOTLI', '--mount', '--sequencer', '--internal-clock', '--frames',
                            str(frames), '--dsp', '--main-level', '64', '--dsp-stopwatch',
                            SW[(core, slot)], '--step', '5:poke:' + ';'.join(pokes)],
                           capture_output=True, text=True, timeout=3600)
    m = re.search(r'last 24:([\d ]+)', p.stdout)
    return [int(x) for x in m.group(1).split()] if m else None, p.returncode


def main():
    jobs = {}
    for core in (1, 0):
        for slot in (1, 2):
            t = 1 if core == 1 else 5                     # second track of the core
            jobs[('stock', core, slot)] = (STOCK, core, slot, 0x0d)
            jobs[('inert', core, slot)] = (PROBE, core, slot, 0x0d)
            jobs[('burn10', core, slot)] = (PROBE, core, slot, 0x0d, t, 10)
            jobs[('burn30', core, slot)] = (PROBE, core, slot, 0x0d, t, 30)
        jobs[('spring', core, 2)] = (PROBE, core, 2, 0x15)
        jobs[('dark', core, 2)] = (PROBE, core, 2, 0x16)
        jobs[('dark-stock', core, 2)] = (STOCK, core, 2, 0x16)
    with cf.ThreadPoolExecutor(8) as ex:
        res = dict(zip(jobs, ex.map(lambda a: run(*a), jobs.values())))
    ok = True
    for k, (last, rc) in sorted(res.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
        print(f'{k[0]:10} core {k[1]} FX{k[2]}: rc {rc}  last 4 calls {last[-4:] if last else None}')
        ok &= rc == 0 and bool(last)
    for core in (1, 0):
        for slot in (1, 2):
            s = res[('stock', core, slot)][0][-4:]
            i = res[('inert', core, slot)][0][-4:]
            d = [b - a for a, b in zip(s, i)]
            print(f'core {core} FX{slot}: inert overhead per call {d}')
            ok &= all(x == 8 for x in d)
            # stock's own page-2 bytes are not reset by an id poke: compare like with like
            if any(x != 8 for x in d):
                print('   (non-8 = that track carried old page-2 bytes in the STOCK run too)')
            for n in (10, 30):
                b = res[(f'burn{n}', core, slot)][0][-4:]
                extra = [x - y for x, y in zip(b, i)]
                want = 3 * 8 * n * 16 + 1
                print(f'   BURN {n:3d}: extra per call {extra}  (expected {want} on the 2nd track only)')
                ok &= abs(extra[1] - want) <= 1 and extra[0] == extra[2] == extra[3] == 0
    for core in (1, 0):
        sp = res[('spring', core, 2)][0][-4:]
        dk, dks = res[('dark', core, 2)][0][-4:], res[('dark-stock', core, 2)][0][-4:]
        print(f'core {core}: SPRING id -> {sp} (stub ~69)   DARK REV {dk} vs stock {dks}')
        ok &= all(x < 200 for x in sp) and dk == dks
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

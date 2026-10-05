#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 Phase 0a: the DSP cost of every stock effect, per track instance, measured under the
# firmware in octabam's ColdFire+DSP port (ot_emu --dsp-stopwatch at the dispatcher's call
# sites). reference/handoffs/OT303_SCOPE.md §8 Phase 0.
#
# Method: the user's BOTLI project plays (stock 1.40C image); at frame 5 all four tracks of one
# core get effect E in one slot by poking the live id arrays (0x80000ec4[t] FX1 / 0x80000ecc[t]
# FX2 -- the Part's bytes alone do nothing on the DSP, NOTES S112 gate 0a); the stopwatch
# counts instructions per effect call (one call = one track, one 16-sample frame).
# Units: INSTRUCTIONS, not cycles (octabam CHIP.md: ~2 cycles per simple instruction, more
# for displaced addressing; only a hardware burn sweep measures cycles).
#
# usage: phase0_fxcost.py [--jobs 8] [--frames 120]
import argparse, concurrent.futures as cf, json, os, re, shutil, statistics, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRIMARY = os.path.realpath(os.path.join(ROOT, 'refs', 'octabam'))
# a private copy of the octabam remixer clone's port (8d0ad6f4, has --step FRAME:poke); copied so a
# rebuild of the shared clone cannot SIGKILL a run (memory: shared-octabam-clone-hazard)
EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(PRIMARY, 'out', 'botli_card2.img')
IMAGE = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
OUT = os.path.join(ROOT, 'out', 'ot303', 'phase0')

FX = {  # id: (name, fx1_allowed)
    0x00: ('NONE', True), 0x04: ('FILTER', True), 0x05: ('SPATIALIZER', True),
    0x0c: ('EQ', True), 0x0d: ('DJ EQ', True), 0x10: ('PHASER', True), 0x11: ('FLANGER', True),
    0x12: ('CHORUS', True), 0x13: ('COMB', True), 0x18: ('COMPRESSOR', True),
    0x1c: ('LO-FI', True), 0x14: ('PLATE REV', False), 0x15: ('SPRING REV', False),
    0x16: ('DARK REV', False), 0x08: ('DELAY', False)}
# (core, slot): (stopwatch spec, first track index of the live id arrays)
SITES = {(1, 1): ('1:2cc:2cd', 0x80000ec4), (1, 2): ('1:302:303', 0x80000ecc),
         (0, 1): ('0:4d7:4d8', 0x80000ec8), (0, 2): ('0:50d:50e', 0x80000ed0)}


def run(fxid, core, slot, frames):
    sw, base = SITES[(core, slot)]
    poke = ';'.join(f'{base + t:#x}={fxid:#x}' for t in range(4))
    with tempfile.TemporaryDirectory() as td:
        card = os.path.join(td, 'card.img')
        shutil.copyfile(CARD, card)
        cmd = [EMU, '--image', IMAGE, '--card', card, '--set', 'OCTABAM', '--project', 'BOTLI',
               '--mount', '--sequencer', '--internal-clock', '--frames', str(frames), '--dsp',
               '--main-level', '64', '--dsp-stopwatch', sw, '--step', f'5:poke:{poke}']
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    log = p.stdout + p.stderr
    m = re.search(r'last 24:([\d ]+)', log)
    last = [int(x) for x in m.group(1).split()] if m else []
    pokes = log.count('poke       :')
    return dict(id=fxid, name=FX[fxid][0], core=core, slot=slot, last24=last,
                per_call=statistics.median(last) if last else None, pokes=pokes, rc=p.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--frames', type=int, default=120)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    for fxid, (name, fx1ok) in FX.items():
        for core in (1, 0):
            for slot in (1, 2):
                if slot == 1 and not fx1ok:
                    continue
                jobs.append((fxid, core, slot))
    res = []
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(lambda j: run(*j, a.frames), jobs):
            res.append(r)
            print(f"{r['name']:12} core {r['core']} FX{r['slot']}: per call {r['per_call']}  "
                  f"(per sample {r['per_call'] / 16 if r['per_call'] else float('nan'):.1f})  "
                  f"pokes {r['pokes']} rc {r['rc']}", flush=True)
    with open(os.path.join(OUT, 'fxcost.json'), 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()

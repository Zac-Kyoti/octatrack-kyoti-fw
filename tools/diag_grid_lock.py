#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Does an armed DIRECT JUMP commit move the step grid?  (Session 82)

Every DIRECT JUMP test up to Session 79 cont.39 measured WHERE each track landed and none
measured WHEN.  The user's hardware report is entirely about WHEN: after a pattern change
the sequencer runs off the master clock by a FRACTION of a step, the fraction depending on
the instant the change was requested.

The grid is observable directly.  The sequencer body runs once per CLOCK TICK (measured:
tools/diag_tick_domain.py), and a master step boundary is exactly a tick on which
0x800065b6 == 0, which is the gate for the step body at 0x400a4220.  So: count clock ticks
from transport start, record the absolute tick index of every step boundary, and look at
the gaps.  A locked grid gives a constant gap of LEN_TBL[SCALE_IX] ticks, forever, across
the commit.  A moved grid gives one short (or long) gap at the commit and a permanently
shifted phase after it.

To make the fraction visible, the pattern change is cued at a CHOSEN sub-step phase --
`--phase 3` cues it 3 ticks into a 6-tick step.  Sweeping the phase is the test: if the
grid is locked, every phase produces the identical gap sequence.

Usage:
  python3 tools/diag_grid_lock.py [--image F] [--phase N | --sweep] [--dj 0|1]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

DJ_MODE = 0x800000D8
TICK_CTR = 0x800065B6          # master ticks-within-step
SCALE_IX = 0x8000663D
BAR_CTR = 0x800065B2           # master STEP counter (word, ++ at 0x400a423a)
ACT_PAT, ACT_BANK = 0x800065BE, 0x800065BD
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
LEN_TBL = 0x400ABA50
TICK_PC = 0x400A3FDC           # the 0x800065b6 increment -- once per clock tick
STEP_PC = 0x400A4220           # first instruction of the step body -- once per master step


def run_one(er, a, phase, quiet=False):
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.from_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))

    st = dict(tick=0, bounds=[], commit=None, cued=None, acts=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        # Cue the change at the requested sub-step phase, once, after `pre` ticks.
        if st["cued"] is None and st["tick"] >= a.pre:
            if bytes(u.mem_read(TICK_CTR, 1))[0] == phase:
                u.mem_write(PEND_BANK, bytes([bank]))
                u.mem_write(PEND_PAT, bytes([a.to_pattern]))
                st["cued"] = st["tick"]
        ap = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap:
            st["acts"].append((st["tick"], ap))
            if st["cued"] is not None and st["commit"] is None and len(st["acts"]) > 1:
                st["commit"] = st["tick"]

    def on_step(u, addr, size, user):
        st["bounds"].append(st["tick"])

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_step, begin=STEP_PC, end=STEP_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    tps = tbl[rd(SCALE_IX, 1)[0]] if rd(SCALE_IX, 1)[0] < 12 else None
    gaps = [b - aa for aa, b in zip(st["bounds"], st["bounds"][1:])]
    return dict(tps=tps, bounds=st["bounds"], gaps=gaps, commit=st["commit"],
                cued=st["cued"], acts=st["acts"], ticks=st["tick"])


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--from-pattern", type=int, default=6)
    ap.add_argument("--to-pattern", type=int, default=7)
    ap.add_argument("--dj", type=int, default=1)
    ap.add_argument("--phase", type=int, default=3)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--pre", type=int, default=40, help="ticks to run before cueing")
    ap.add_argument("--frames", type=int, default=4000)
    ap.add_argument("--tree", default="out/_emu_gridlock")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    print(f"image   {a.image}")
    print(f"project {a.project}  pattern {a.from_pattern} -> {a.to_pattern}  DJ_MODE={a.dj}")
    phases = range(6) if a.sweep else [a.phase]
    verdicts = []
    for ph in phases:
        res = run_one(er, a, ph)
        tps_in = res["tps"]                      # the INCOMING pattern's ticks-per-step
        gaps, bounds = res["gaps"], res["bounds"]
        # Session 82: the first version of this check compared EVERY gap against the
        # end-of-run tps and so flagged the outgoing pattern's own (perfectly legitimate)
        # step length as "moved". When the two patterns differ in MASTER SCALE the gap
        # sequence is SUPPOSED to change -- A07 runs 6-tick steps, A08 runs 3-tick steps.
        # What must never appear is a gap that is neither rate: that is a fractional step,
        # i.e. the grid re-phased mid-step. Judge on that instead.
        tps_out = gaps[0] if gaps else None
        legit = {tps_out, tps_in} - {None}
        bad = [(i, g) for i, g in enumerate(gaps) if g not in legit]
        print(f"\n--- cue at sub-step phase {ph} ---")
        print(f"  outgoing tps={tps_out}  incoming tps={tps_in}  "
              f"(a gap of either is a whole step; anything else is a fraction)")
        print(f"  clock ticks run={res['ticks']}  cued at tick {res['cued']}  "
              f"ACT_PAT changes at {res['acts']}")
        print(f"  step boundaries (absolute tick): {bounds[:26]}")
        print(f"  gaps between boundaries:         {gaps[:26]}")
        if bad:
            print(f"  ** GRID MOVED: {len(bad)} fractional gap(s) (not in {sorted(legit)}): "
                  f"{[(bounds[i], g) for i, g in bad][:8]}")
        else:
            print(f"  GRID LOCKED: every gap is a whole step ({sorted(legit)})")
        # A clean jump also switches rate exactly once, at the commit.
        changes = [(bounds[i], gaps[i - 1], g)
                   for i, g in enumerate(gaps) if i and g != gaps[i - 1]]
        print(f"  rate changes: {changes}  (expect exactly one, at the commit boundary)")
        verdicts.append((ph, not bad, res["commit"]))

    print("\n=== verdict ===")
    for ph, okk, commit in verdicts:
        print(f"  phase {ph}: {'LOCKED' if okk else 'MOVED '}  (commit at tick {commit})")
    return 0 if all(v[1] for v in verdicts) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

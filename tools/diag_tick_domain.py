#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
What domain does the sequencer body at 0x400a3fdc actually run in? (Session 82)

Every DIRECT JUMP hook rests on the claim -- written into patch_directjump.s as
"Runs every step tick" -- that the block

    0x400a3fdc  moveb 0x800065b6,d0 ; addq #1,d0 ; moveb d0,0x800065b6
    0x400a3fec  mvsb 0x8000663d,d1                       ; SCALE_IX
    0x400a3ff8  cmp.l LEN_TBL[d1],d0  ; blt -> keep      ; else 0x800065b6 = 0

executes once per MASTER STEP, and that 0x800065b6 is the master STEP counter.

But cont.20 measured LEN_TBL as a TICKS-PER-STEP table (3,4,6,8,12,24,48,96,...), and this
block wraps 0x800065b6 against LEN_TBL[SCALE_IX].  A step counter cannot wrap at 6.  If the
block really runs per CLOCK TICK and 0x800065b6 is ticks-within-step, then:

  * Hook A (0x400a4006) runs every clock tick, and its `clr.b STEP` forces the step-0 body
    at an arbitrary sub-step instant -- re-phasing the whole grid to the moment of the
    pattern change.  (= the user's hardware report.)
  * dj_c writing a STEP INDEX into 0x800065b6 jitters the grid a second time.
  * dj_abstick's cont.38 `+= LEN_TBL[SCALE_IX]` over-counts by exactly tps.

Measured here on STOCK, no patch involved:
  A. executions of 0x400a3fdc per execution of the per-track step advance 0x400a3d78
  B. the value range 0x800065b6 actually takes
  C. executions of 0x400a3fdc per entry into the step-0 body (0x400a401a)

Usage:
  python3 tools/diag_tick_domain.py [--project DIR] [--pattern N] [--frames N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

MASTER_CTR   = 0x800065B6
SCALE_IX     = 0x8000663D
LEN_TBL      = 0x400ABA50
TICK_PC      = 0x400A3FDC   # the 0x800065b6 increment
STEP0_PC     = 0x400A401A   # first instruction of the step-0 body (past tstb/bne)
TRK_ADV_PC   = 0x400A3D78   # per-track step-within-pattern store
BLOB, BANK_STRIDE, PAT_STRIDE, TRK_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(STOCK))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--pattern", type=int, default=6)
    ap.add_argument("--frames", type=int, default=3000)
    ap.add_argument("--tree", default="out/_emu_tickdomain")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = a.bank if a.bank is not None else loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    base = BLOB + bank * BANK_STRIDE + a.pattern * PAT_STRIDE
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    print(f"project {a.project}  bank {bank} pattern {a.pattern}")
    print(f"SCALE_MODE(+0x8e55)={rd(base+0x8E55,1)[0]}  MASTER LEN(+0x8e51)={rd(base+0x8E51,1)[0]}"
          f"  PAT LEN(+0x8e53)={rd(base+0x8E53,1)[0]}")

    counts = {TICK_PC: 0, STEP0_PC: 0, TRK_ADV_PC: 0}
    seen = set()
    order = []          # (pc_label, counter_value_after) trace, first 80 events

    def mk(pc, label):
        def h(u, addr, size, user):
            counts[pc] += 1
            if pc == TICK_PC:
                v = bytes(u.mem_read(MASTER_CTR, 1))[0]
                seen.add(v)
            if len(order) < 80:
                order.append((label, counts[TICK_PC]))
        return h

    for pc, label in ((TICK_PC, "tick"), (STEP0_PC, "STEP0"), (TRK_ADV_PC, "trkadv")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(pc, label), begin=pc, end=pc)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    six = rd(SCALE_IX, 1)[0]
    tps = tbl[six] if six < 12 else None
    print(f"\nSCALE_IX={six}  LEN_TBL[SCALE_IX]={tps}   (LEN_TBL={tbl})")
    print(f"\nexecutions:  0x400a3fdc (0x800065b6++) = {counts[TICK_PC]}")
    print(f"             0x400a401a (step-0 body)   = {counts[STEP0_PC]}")
    print(f"             0x400a3d78 (per-track step)= {counts[TRK_ADV_PC]}")
    if counts[STEP0_PC]:
        print(f"\n  0x400a3fdc per step-0 body = {counts[TICK_PC] / counts[STEP0_PC]:.3f}"
              f"   (== LEN_TBL[SCALE_IX] = {tps}?)")
    print(f"\n  values 0x800065b6 takes: {sorted(seen)}")
    print(f"  -> max {max(seen) if seen else '-'}; a STEP counter would reach "
          f"patternLen-1, a TICK counter reaches tps-1 = {tps - 1 if tps else '?'}")

    print("\n  first events (label, tick# at that moment):")
    print("   ", order[:40])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

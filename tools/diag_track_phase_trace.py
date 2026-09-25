#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: WHO sets track 0's tick counter across an armed DIRECT JUMP commit?

Measured on V5.3 (tools/diag_step_align.py): the track's advance ticks, taken modulo its
own ticks-per-step, flip between congruence classes [5] and [2] at armed commits -- a
3-tick shift, in BOTH directions. That is the "fractional relative to the metronome"
report.

The arithmetic that names the culprit: track 0 last advanced at tick 41 and next advanced
at tick 44, three ticks EARLY (its period is 6). For TICKS_IN_STEP[0] to reach 6 at tick
44 it must have held 4 at the commit. Stock's tail writes 0 there (0x400a4bf0) and PAIR[t]
can only be 0 or 3 in this configuration, so neither stock's zero nor Hook R's PAIR write
produced that 4. Something else sets it.

This logs EVERY write to TICKS_IN_STEP[0] with its PC and value, plus a per-tick snapshot,
through the window around the commit -- so the writer is named rather than inferred.

Usage: python3 tools/diag_track_phase_trace.py --project DIR --pattern N --to-pattern M
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
TAIL_PC = 0x400A4BE6
STEP_ARR, TICKS_ARR = 0x800064D0, 0x800064F0
PAIR_ARR, HOLD_MASK = 0x80006604, 0x80006626
TICK_CTR, MASTER_STEP, SCALE_IX = 0x800065B6, 0x800065B2, 0x8000663D
TRK_SCALE_IX, LEN_TBL = 0x8000663E, 0x400ABA50
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
CAVE_LO, CAVE_HI = 0x400D7400, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=70)
    ap.add_argument("--window", type=int, default=12)
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--image", default=str(V5))
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_tp_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1).to_bytes(4, "big"))
    rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    T = a.track
    st = dict(tick=0, cued=None, commit=None, ev=[], snap=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["cued"] is None and st["tick"] >= a.cue_at:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
        rd = lambda ad, n: bytes(u.mem_read(ad, n))
        st["snap"].append((st["tick"], rd(TICKS_ARR + T, 1)[0], rd(STEP_ARR + T, 1)[0],
                           rd(TICK_CTR, 1)[0],
                           int.from_bytes(rd(MASTER_STEP, 2), "big"),
                           int.from_bytes(rd(PAIR_ARR + 2 * T, 2), "big"),
                           int.from_bytes(rd(HOLD_MASK, 2), "big")))

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if addr == TAIL_PC - TAIL_PC + STEP_ARR + T and pc == TAIL_PC and st["commit"] is None:
            st["commit"] = st["tick"]
        st["ev"].append((st["tick"], addr, pc, value & 0xFF))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=TICKS_ARR + T, end=TICKS_ARR + T)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP_ARR + T, end=STEP_ARR + T)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    ct = st["commit"]
    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(8)]
    tsc = rd(TRK_SCALE_IX + T, 1)[0]
    print(f"track {T}: scale idx {tsc} -> tps {tbl[tsc] if tsc < 8 else '?'}; "
          f"commit at t{ct}; cued t{st['cued']}")
    lo = (ct - a.window) if ct else 1
    hi = (ct + a.window) if ct else a.ticks
    print(f"\nper-tick snapshot (start of tick), ticks {lo}..{hi}:")
    print(f"{'tick':>5} {'TICKS[0]':>8} {'STEP[0]':>7} {'TICK_CTR':>8} {'MSTEP':>5} "
          f"{'PAIR[0]':>7} {'HOLD':>6}")
    for tk, ti, s0, tc, ms, pr, hm in st["snap"]:
        if lo <= tk <= hi:
            mark = "  <== COMMIT" if tk == ct else ""
            print(f"{tk:5d} {ti:8d} {s0:7d} {tc:8d} {ms:5d} {pr:7d} 0x{hm:04x}{mark}")
    print(f"\nevery write to TICKS_IN_STEP[{T}] and STEP_ARR[{T}] in that window:")
    for tk, addr, pc, v in st["ev"]:
        if lo <= tk <= hi:
            nm = "TICKS" if addr == TICKS_ARR + T else "STEP "
            who = " <-- OUR CAVE" if CAVE_LO <= pc < CAVE_HI else ""
            print(f"   t{tk:4d} {nm}[{T}] pc=0x{pc:08x} = {v}{who}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

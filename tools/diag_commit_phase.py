#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: at an armed DIRECT JUMP commit, WHICH tracks get re-phased and which are left
mid-step?

Hypothesis under test. Stock's commit tail guards its whole body on CNTDN_TBL[t] == 0
(`bne 0x400a4c52` at 0x400a4bce), and that body contains BOTH the reposition
(STEP_ARR[t], 0x400a4be6) and the tick-phase reset (TICKS_IN_STEP[t] = 0, 0x400a4bf0).
Since CNTDN_TBL[t] = max(1, tps_master + 1 - tps_t), every track has CNTDN == 1 at 1x and
the body runs for all 16 -- which is why Session 87 called Hook P's own TICKS_IN_STEP write
"redundant" and removed it. For a track FASTER than the master (tps_t < tps_master, e.g. a
2x track under a 1x master: max(1, 6+1-3) = 4) the body is SKIPPED, so that track is neither
repositioned by stock nor tick-phase reset by anyone.

AR re-phases every track at its commit (loop 2's `clr.b (A4)+` on 0x4056672d[t], plus loop
1's per-track countdown reload 0x405667c7[t] = ticksPerStep-1).

Prediction if the hypothesis holds: on a non-1x fixture, tracks with CNTDN_TBL > 1 receive
NO write to STEP_ARR or TICKS_IN_STEP from stock's tail at the commit tick, and their
TICKS_IN_STEP is non-zero across it. On the 1x control, all 16 get both.

Uses MEM_WRITE hooks over the whole arrays, so NOTES.md S87 rule 1 (a code hook fires
BEFORE its instruction) cannot apply -- a write hook reports the value actually stored and
the track it was stored for.

Usage:
  python3 tools/diag_commit_phase.py --project DIR --pattern N --to-pattern M [--image IMG]
"""
import argparse
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
GOLD = ROOT / "out" / "GOLD_S87_mainos_directjump.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
STEP_ARR, TICKS_ARR = 0x800064D0, 0x800064F0
CNTDN_TBL, TRK_SCALE_IX = 0x800065C3, 0x8000663E
SCALE_IX = 0x8000663D
LEN_TBL = 0x400ABA50
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK, ACT_PAT = 0x800065C0, 0x800065BF, 0x800065BE

ARRAYS = [(STEP_ARR, 16, 1, "STEP"), (TICKS_ARR, 16, 1, "TICKS"),
          (CNTDN_TBL, 16, 1, "CNTDN")]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--cue-at", type=int, default=30)
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--image", default=str(GOLD))
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_cp_{tag}")
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

    st = dict(tick=0, cued=None, commit=None, w=collections.defaultdict(list), snaps={})

    def snap(u, label):
        rd = lambda ad, n: bytes(u.mem_read(ad, n))
        st["snaps"][label] = dict(
            step=list(rd(STEP_ARR, 16)), ticks=list(rd(TICKS_ARR, 16)),
            cntdn=list(rd(CNTDN_TBL, 16)), tsc=list(rd(TRK_SCALE_IX, 8)),
            six=rd(SCALE_IX, 1)[0])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["cued"] is None and st["tick"] >= a.cue_at:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
            snap(u, "pre-cue")
        if st["commit"] is not None and st["tick"] == st["commit"] + 1:
            snap(u, "commit+1")
        if st["commit"] is not None and st["tick"] == st["commit"] + 8:
            snap(u, "commit+8")

    def on_write(u, access, addr, size, value, user):
        for base, n, w, nm in ARRAYS:
            if base <= addr < base + n * w:
                t = (addr - base) // w
                pc = u.reg_read(er.eb.UC_M68K_REG_PC)
                st["w"][(nm, t)].append((st["tick"], pc, value & 0xFF))
                if nm == "STEP" and pc == 0x400A4BE6 and st["commit"] is None:
                    st["commit"] = st["tick"]

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP_ARR, end=CNTDN_TBL + 16)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(8)]
    pre = st["snaps"].get("pre-cue", {})
    print(f"image={pathlib.Path(a.image).name}  {a.pattern} -> {a.to_pattern}  "
          f"cued=t{st['cued']}  commit=t{st['commit']}  ticks={st['tick']}")
    if st["commit"] is None:
        print("FAILED: stock's tail never wrote STEP_ARR -- no commit observed, run proves nothing")
        return 2
    six = pre.get("six")
    print(f"master SCALE_IX={six} (tps {tbl[six] if six is not None and six < 8 else '?'})")
    ct = st["commit"]
    print(f"\nper-track at the commit tick t{ct}:")
    print(f"{'trk':>3} {'tps':>4} {'CNTDN@cue':>9} {'tail STEP':>9} {'tail TICKS0':>11} "
          f"{'HookP STEP':>10} {'TICKS@c+1':>9}")
    for t in range(16):
        tps = tbl[pre["tsc"][t]] if t < 8 and pre.get("tsc") and pre["tsc"][t] < 8 else None
        tail_step = [v for (tk, pc, v) in st["w"][("STEP", t)] if tk == ct and pc == 0x400A4BE6]
        tail_tick = [v for (tk, pc, v) in st["w"][("TICKS", t)] if tk == ct and pc == 0x400A4BF0]
        hookp = [v for (tk, pc, v) in st["w"][("STEP", t)]
                 if tk == ct and 0x400D7400 <= pc < 0x400D7C3C]
        c1 = st["snaps"].get("commit+1", {}).get("ticks", [None] * 16)[t]
        print(f"{t:3d} {str(tps):>4} {pre['cntdn'][t]:9d} "
              f"{(tail_step[0] if tail_step else '--'):>9} "
              f"{('0' if tail_tick else '--'):>11} "
              f"{(hookp[0] if hookp else '--'):>10} {str(c1):>9}")
    print(f"\nALL writes to STEP_ARR at the commit tick t{ct}, by PC "
          f"(is any non-cave PC covering tracks 8-15?):")
    bypc = {}
    for t in range(16):
        for (tk, pc, v) in st["w"][("STEP", t)]:
            if tk == ct:
                bypc.setdefault(pc, []).append((t, v))
    for pc in sorted(bypc):
        where = "CAVE (Hook P)" if 0x400D7400 <= pc < 0x400D7C3C else "stock"
        print(f"   pc=0x{pc:08x} [{where}] tracks/values: {bypc[pc]}")

    miss = [t for t in range(16)
            if not [1 for (tk, pc, v) in st["w"][("TICKS", t)]
                    if tk == ct and pc == 0x400A4BF0]]
    print(f"\ntracks whose TICKS_IN_STEP was NOT zeroed by stock's tail at the commit: "
          f"{miss if miss else 'none (all 16 re-phased)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 88: WHO writes track 0's step position, and does it change when trigs exist?

Hardware report (MKI, DJ ON, MASTER SCALE 2x, per-track mode, one 16-step track at 1x):
the steps the playhead visits depend on WHAT TRIGS ARE ON THE GRID.

    no trigs        -> 1..8            (nominal)
    trig on 1       -> 1,3,4,7,9,10,11,12
    trig on 2       -> 1,2,5,6,9,11,12,13
    trigs on 2,3    -> 1,2,5,7,8,11,13,14

Position depending on content means something on the TRIG-FIRE path is writing the
per-track position/tick state. This logs every write to track 0's STEP (0x800064d0),
ticks-within-step (0x800064f0) and countdown (0x800065c3) with the PC that did it, so the
writer is identified rather than inferred.

Uses a MEM_WRITE hook, not a code hook, so NOTES.md S87 rule 1 (a code hook fires before
its instruction) does not apply -- a write hook reports the value actually stored.

Usage:
  python3 tools/diag_step_writers.py --project DIR --pattern IDX [--dj] [--ticks N]
"""
import argparse
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
MASTER_STEP = 0x800065B2
STEP0 = 0x800064D0
TICKS0 = 0x800064F0
CNTDN0 = 0x800065C3
WATCH = {STEP0: "STEP[0]", TICKS0: "TICKS[0]", CNTDN0: "CNTDN[0]"}
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
CAVE_LO, CAVE_HI = 0x400D7400, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, default=1)
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=140)
    ap.add_argument("--dj", action="store_true")
    ap.add_argument("--to-pattern", type=int, default=None,
                    help="cue a REAL direct jump (PEND_PAT/PEND_BANK) so Hook A can arm; "
                         "seq_select_live alone never cues and the run would be void")
    ap.add_argument("--cue-at", type=int, default=30)
    ap.add_argument("--image", default=None, help="override the patched image under test")
    ap.add_argument("--stock", action="store_true")
    ap.add_argument("--no-poison", action="store_true",
                    help="do NOT pre-fill our scratch block with 0xAA (Unicorn zero-fills; "
                         "hardware does not -- NOTES.md S86 / handoff rule 8.2)")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    image = pathlib.Path(a.image) if a.image else (STOCK if a.stock else PATCHED)
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    # Session 88: the tree name MUST be unique per (image, project, pattern) or two runs
    # launched in parallel stage into the same directory and race. That produced three
    # crashed runs whose empty output compared "IDENTICAL" to each other -- the vacuous
    # green this file's own docstring warns about.
    tag = f"{pathlib.Path(image).stem}_{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_sw_{tag}")
    r, rt = er.attach(str(image), card, ips=3990.0, pit_clock_hz=264e6,
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
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))
    # Session 86 / handoff rule 8.2: 0x80006a40.. is outside stock's boot re-image
    # (0x3e88 bytes from 0x401086f4) AND outside its zero-fill (to 0x80004000), so it is
    # GARBAGE at power-on on real hardware. Unicorn zero-fills it, which silently disarms
    # G_JUST_COMMITTED and makes Hook P look inert when on hardware it is not.
    if not a.no_poison:
        rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, ev=[], pcs=collections.Counter(), cued=None)

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if a.to_pattern is not None and st.get("cued") is None and st["tick"] >= a.cue_at:
            u.mem_write(0x800065BF, bytes([bank]))
            u.mem_write(0x800065C0, bytes([a.to_pattern]))
            st["cued"] = st["tick"]

    def on_write(u, access, addr, size, value, user):
        if st["tick"] > a.ticks:
            return
        for base, name in WATCH.items():
            if addr <= base < addr + size:
                pc = u.reg_read(er.eb.UC_M68K_REG_PC)
                st["pcs"][(name, pc)] += 1
                st["ev"].append((st["tick"], name, pc, value & 0xFF))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP0, end=CNTDN0 + 1)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 80:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"cued at t{st['cued']} -> pattern {a.to_pattern}")
    print(f"project={a.project} pattern={a.pattern} DJ={'ON' if a.dj else 'OFF'} "
          f"image={'stock' if a.stock else 'patched'} ticks={st['tick']}")
    print("\nwriters (array, PC) -> count:")
    for (name, pc), n in sorted(st["pcs"].items(), key=lambda kv: -kv[1]):
        tag = "  <-- OUR CAVE" if CAVE_LO <= pc < CAVE_HI else ""
        print(f"   {name:9s} pc=0x{pc:08x}  x{n}{tag}")
    nstep = sum(1 for _, nm, _, _ in st["ev"] if nm == "STEP[0]")
    if nstep == 0:
        print("\nFAILED: no STEP[0] writes observed -- this run proves NOTHING")
        return 2
    print("\nSTEP[0] write timeline (tick, pc, newvalue-1based):")
    for t, name, pc, v in st["ev"]:
        if name == "STEP[0]":
            tag = "  <-- OUR CAVE" if CAVE_LO <= pc < CAVE_HI else ""
            print(f"   t{t:4d}  pc=0x{pc:08x}  -> {v + 1}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 88: which DIRECT JUMP hooks actually EXECUTE, and what do they write?

Two traps this thread has already paid for, both avoided here:
  * NOTES.md S79 cont.: seq_select_live() never cues, so a "DJ_MODE=1" run that does not
    poke PEND_PAT/PEND_BANK measures stock behaviour with the feature merely enabled.
    G_ARMED must be OBSERVED, not assumed.
  * Sampling G_ARMED once per tick is a false negative: dj_a arms at 0x400a4006 and dj_c
    clears it at 0x400a4840, both INSIDE one tick, so a probe at the tick top never sees it.
    This counts HOOK ENTRIES from the cave instead, which cannot be missed.

Cave symbols are read from out/patch_directjump_v4.elf so they can never drift from the
built image.

Usage:
  python3 tools/diag_dj_hooks.py --project DIR --pattern N [--to-pattern M] [--ticks N]
"""
import argparse
import collections
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
ELF = ROOT / "out" / "patch_directjump_v4.elf"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
MASTER_STEP = 0x800065B2
STEP0, TICKS0, CNTDN0 = 0x800064D0, 0x800064F0, 0x800065C3
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK, ACT_PAT = 0x800065C0, 0x800065BF, 0x800065BE
WATCH = {STEP0: "STEP[0]", TICKS0: "TICKS[0]", CNTDN0: "CNTDN[0]"}


def cave_symbols():
    out = subprocess.run(["m68k-elf-nm", "-n", str(ELF)], capture_output=True, text=True).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ("T", "t"):
            addr = int(parts[0], 16)
            if 0x400D7400 <= addr < 0x400D7C3C:
                syms[addr] = parts[2]
    return syms


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, default=0)
    ap.add_argument("--to-pattern", type=int, default=None)
    ap.add_argument("--cue-at", type=int, default=30)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--no-poison", action="store_true")
    a = ap.parse_args(argv)

    syms = cave_symbols()
    if not syms:
        sys.exit("no cave symbols found in " + str(ELF))

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree="out/_emu_djhooks")
    r, rt = er.attach(str(PATCHED), card, ips=3990.0, pit_clock_hz=264e6,
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
    if not a.no_poison:
        rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, hooks=collections.Counter(), first={}, ev=[], cued=None,
              acts=[], steps=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if a.to_pattern is not None and st["cued"] is None and st["tick"] >= a.cue_at:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
        ap_ = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap_:
            st["acts"].append((st["tick"], ap_))
        s0 = bytes(u.mem_read(STEP0, 1))[0]
        if not st["steps"] or st["steps"][-1] != s0:
            st["steps"].append(s0)

    def on_cave(u, addr, size, user):
        name = syms.get(addr)
        if name:
            st["hooks"][name] += 1
            st["first"].setdefault(name, st["tick"])

    def on_write(u, access, addr, size, value, user):
        for base, nm in WATCH.items():
            if addr <= base < addr + size:
                pc = u.reg_read(er.eb.UC_M68K_REG_PC)
                st["ev"].append((st["tick"], nm, pc, value & 0xFF))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_cave, begin=0x400D7400, end=0x400D7C3C)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP0, end=CNTDN0 + 1)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"project={a.project} pattern={a.pattern} -> {a.to_pattern} "
          f"cued=t{st['cued']} ticks={st['tick']}")
    print(f"ACT_PAT timeline: {st['acts']}")
    print("\nHOOK ENTRIES (from the cave, counted -- not inferred):")
    for name, n in sorted(st["hooks"].items(), key=lambda kv: -kv[1]):
        print(f"   {name:18s} x{n:<6d} first at t{st['first'][name]}")
    armed = st["hooks"].get("dja_real", 0)
    print(f"\n   dja_real (the ARM path) ran {armed} times -> "
          f"{'DIRECT JUMP REALLY ARMED' if armed else 'NEVER ARMED - RUN IS VOID'}")
    print(f"   djp_store (Hook P per-track STEP writes) = "
          f"{st['hooks'].get('djp_store', 0)}")
    print(f"\ntrack0 steps visited (1-based): {[x + 1 for x in st['steps']]}")
    print("\nSTEP[0] writes:")
    for t, nm, pc, v in st["ev"]:
        if nm == "STEP[0]":
            tag = "  <-- CAVE" if 0x400D7400 <= pc < 0x400D7C3C else ""
            print(f"   t{t:4d} pc=0x{pc:08x} -> {v + 1}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: does our commit leave 0x80006638 stale against 0x80006628?

Found by reading timhastie/octatrick's direct-jump module, which writes BOTH. Stock writes
them as a PAIR with the same value at all three of its own sites:

    0x400a0622 / 0x400a0628      0x400a40b8 / 0x400a40be      0x400a44ea / 0x400a44f0

and 0x80006638 has two live readers:

    0x4009be88  movel 0x80006638,%d0 ; movew %d0,0x800065b4 ; addq #1 ; movew %d0,0x800065b2
                -> seeds MASTER_STEP, the bounded master playhead
    0x4009da88  lea 0x80006638,%a0 ; mulsl %a0@,%d0
                -> multiplied by ticks-per-step (the D7-style term)

Our Hook H (dj_d7) writes only 0x80006628 (MASTER_STEPS), so after an armed commit the two
can disagree. This measures whether they actually diverge, and whether either reader runs
while they are divergent -- a stale read being the thing that would matter.

Usage:
  python3 tools/diag_startoffset.py --project DIR --pattern N --to-pattern M [--image IMG]
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
A = 0x80006628          # MASTER_STEPS -- we write this
B = 0x80006638          # its stock-paired companion -- we do NOT
READERS = {0x4009BE88: "seeds MASTER_STEP (0x800065b2)",
           0x4009DA88: "multiplied by ticks-per-step"}
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
CAVE_LO, CAVE_HI = 0x400D7400, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--jumps", type=int, default=4)
    ap.add_argument("--ticks", type=int, default=300)
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

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_so_{tag}")
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

    st = dict(tick=0, njump=0, w=[], reads=[], diverged=[])
    targets = [a.to_pattern, a.pattern]

    rd32 = lambda ad: int.from_bytes(bytes(rt.uc.mem_read(ad, 4)), "big")

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1
        va = int.from_bytes(bytes(u.mem_read(A, 4)), "big")
        vb = int.from_bytes(bytes(u.mem_read(B, 4)), "big")
        if va != vb:
            if not st["diverged"] or st["diverged"][-1][1:] != (va, vb):
                st["diverged"].append((st["tick"], va, vb))

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        who = "CAVE(ours)" if CAVE_LO <= pc < CAVE_HI else "stock"
        # Unicorn's hook end is INCLUSIVE, so a begin=X,end=X+4 range also catches X+4 --
        # 0x8000662c for the A range. Label by the ACTUAL address, never by "not A".
        if addr == A:
            nm = "A 0x28"
        elif addr == B:
            nm = "B 0x38"
        else:
            nm = f"other {hex(addr)}"
        st["w"].append((st["tick"], nm, pc, who, value))

    def on_read(u, addr, size, user):
        vb = int.from_bytes(bytes(u.mem_read(B, 4)), "big")
        va = int.from_bytes(bytes(u.mem_read(A, 4)), "big")
        st["reads"].append((st["tick"], addr, va, vb))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=A, end=A + 3)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=B, end=B + 3)
    for pc in READERS:
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_read, begin=pc, end=pc)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"image={pathlib.Path(a.image).name} {a.pattern}<->{a.to_pattern} ticks={st['tick']}")
    print(f"\nwrites to 0x80006628 (A) and 0x80006638 (B):")
    for tk, which, pc, who, v in st["w"]:
        print(f"   t{tk:4d} {which}  pc=0x{pc:08x} [{who:10s}] = {v}")
    print(f"\nticks where A != B (divergence):")
    if st["diverged"]:
        for tk, va, vb in st["diverged"][:14]:
            print(f"   t{tk:4d}  0x28={va}  0x38={vb}   <-- STALE by {va - vb}")
    else:
        print("   none -- the two stayed equal for the whole run")
    print(f"\nexecutions of the 0x80006638 readers:")
    if not st["reads"]:
        print("   NEITHER READER RAN during this run")
    for tk, pc, va, vb in st["reads"][:14]:
        flag = "  <-- READ WHILE STALE" if va != vb else ""
        print(f"   t{tk:4d} pc=0x{pc:08x} ({READERS[pc]}) sees 0x38={vb} (0x28={va}){flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

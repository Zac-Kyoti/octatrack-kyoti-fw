#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: does STOCK code ever write DIRECT JUMP's scratch at 0x80006a40..4a?

Raised from the QLREC thread: a word at 0x80006a60 proved unreliable in practice, and
DIRECT JUMP's globals (0x80006a40..4a) and RELOAD3's (0x80006a50..55) are its immediate
neighbours. The justification for all of them was a static scan finding no ABSOLUTE-LONG
references -- which cannot see register-indirect writes (`move.b %d0,d16(%a0)` with the
base in a register). tools/diag_scratch_clobber.py already makes that point for RELOAD's
range; this is the DIRECT JUMP twin.

A clobber here would be INVISIBLE rather than absent: dj_a clears G_ARMED and
G_JUST_COMMITTED on its disarm path every tick and re-arms on every gesture, so a stray
write would be overwritten before anything obvious broke -- it would show up as
intermittent misbehaviour, not as a dead feature.

A MEM_WRITE hook sees every write regardless of addressing mode. Any writer whose PC is
outside our cave is a clobber.

  G_ARMED 0x80006a40   G_STEP 0x41   G_PCPAT 0x42   G_TOAST 0x44..47
  G_JUST_COMMITTED 0x80006a4a

Usage: python3 tools/diag_dj_scratch_clobber.py --project DIR --pattern N --to-pattern M
"""
import argparse
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
LO, HI = 0x80006A40, 0x80006A4B
CAVE_LO, CAVE_HI = 0x400D7400, 0x400D7C3C
NAMES = {0x80006A40: "G_ARMED", 0x80006A41: "G_STEP", 0x80006A42: "G_PCPAT",
         0x80006A44: "G_TOAST+0", 0x80006A45: "G_TOAST+1", 0x80006A46: "G_TOAST+2",
         0x80006A47: "G_TOAST+3", 0x80006A4A: "G_JUST_COMMITTED"}
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--jumps", type=int, default=6)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--dj", type=int, default=1)
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

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}_{a.dj}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_cl_{tag}")
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
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))
    # Poison, so a stray write that merely re-zeroes a byte is still visible as a change.
    rt.uc.mem_write(LO, bytes([0xAA]) * (HI - LO))

    st = dict(tick=0, njump=0, writes=[], pcs=collections.Counter())
    targets = [a.to_pattern, a.pattern]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["pcs"][pc] += 1
        if not (CAVE_LO <= pc < CAVE_HI):
            st["writes"].append((st["tick"], addr, size, pc, value))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=LO, end=HI)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"image={pathlib.Path(a.image).name}  DJ={'ON' if a.dj else 'OFF'}  "
          f"ticks={st['tick']}  jumps cued={st['njump']}")
    ours = sum(n for pc, n in st["pcs"].items() if CAVE_LO <= pc < CAVE_HI)
    print(f"\nwrites to 0x80006a40..4a: {sum(st['pcs'].values())} total, {ours} from OUR cave")
    print(f"writers by PC:")
    for pc, n in sorted(st["pcs"].items(), key=lambda kv: -kv[1]):
        who = "ours" if CAVE_LO <= pc < CAVE_HI else "** STOCK -- CLOBBER **"
        print(f"   pc=0x{pc:08x}  x{n:<5d} [{who}]")
    if st["writes"]:
        print(f"\n!! {len(st['writes'])} FOREIGN write(s) -- our scratch is NOT private:")
        for tk, addr, size, pc, v in st["writes"][:20]:
            print(f"   t{tk:4d} {NAMES.get(addr, hex(addr))} ({size} B) "
                  f"pc=0x{pc:08x} = {v}")
        return 1
    print("\nNo stock writer touched 0x80006a40..4a in this run.")
    print("NOTE: absence here is evidence, not proof -- it covers only the paths this run "
          "exercised (transport running, repeated armed pattern jumps). It does NOT cover "
          "sequence editing, menus, the arranger, or project load/save.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

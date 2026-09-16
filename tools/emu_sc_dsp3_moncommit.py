#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Isolated dynamic test of `moncommit` alone (patch_sc_dsp3.asm) -- the hook that
replaced the old proc-end `sctail` splice (NOTES.md Session 58). `moncommit` is
spliced at the DISPATCHER's per-track COMMIT step (payload A P:0x50e, payload B
P:0x303 -- both `move x:>$206,r0`), not inside the compressor module, and its
only inputs are MON_ON[track]/MON_KEY[track] (Y:0x800+track*0x80+0x40/0x41,
`scdet`'s publish -- see emu_sc_dsp3.py's "MON publish" tests) and the keybus
gen-1 slot those point at. It does NOT read the page-2 params (r6) at all,
unlike the old sctail -- so this test drives it purely through MON_ON/MON_KEY
and a seeded gen-1 signal, not through a params string.

This replaces emu_sc_dsp3_sctail.py, which tested the removed proc-end hook
and would silently test nothing meaningful against the new design (its setup
drove params that moncommit never reads).
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import emu_sc_dsp3 as base

KB_BASE = base.KB_BASE


def main():
    words, sctap, scdet, moncommit, gtab_off, ftab_off = base.assemble()
    if base.PATCHED:
        base.ensure_patched_mem(words)

    probe = base.base_mem(words, scdet, moncommit, False, None, None)
    r7 = base.r7_of(probe)
    print(f"r7 = X:0x{r7:05x}   moncommit = P:0x{moncommit:x}\n")

    MYTRACK = 5
    KEYTRACK = 2
    MON_ADDR = KB_BASE + MYTRACK * 0x80 + 0x40      # MON_ON/MON_KEY for MYTRACK
    GEN1 = KB_BASE + KEYTRACK * 0x80 + 0x20          # keybus[KEYTRACK] gen 1
    SIG = [(0x300000 + i * 0x1111) & 0xFFFFFF for i in range(0x20)]
    pk = ",".join(f"{GEN1 + i:x}={SIG[i]:x}" for i in range(0x20))

    fails = []

    def check(name, cond, detail=""):
        print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        if not cond:
            fails.append(name)

    # 1. MON_ON=1, MON_KEY=KEYTRACK -> X:0 must equal the seeded gen-1 signal.
    # MON_ON is seeded $10000, NOT 1: that's the actual value scdet publishes
    # for ON (dsp_asm's short-immediate-into-accumulator left-align quirk,
    # q2) -- moncommit now gates on an EXACT match to it (Session 59/60's
    # uninitialized-slot hazard fix, see moncommit's own header comment), not
    # "nonzero", so seeding literal 1 here would no longer exercise the ON
    # path at all.
    mem = base.base_mem(words, scdet, moncommit, False,
                         [(1, 0x420, [MYTRACK]), (1, 0, [0] * 0x20)],
                         [(2, MON_ADDR, [0x10000, KEYTRACK])])
    (x0,) = base.run(mem, moncommit, [('x', 0, 0x20)], "0,0,0,0,0,0,0,0,0,64,64,0", pokey=pk)
    check("MON_ON=1: X:0 == seeded gen-1 signal", x0 == SIG,
          f"got[:4]={[hex(v) for v in x0[:4]]} exp[:4]={[hex(v) for v in SIG[:4]]}")

    # dsp_host itself deposits harness noise at X:0x13/0x14 independent of
    # anything this cave does (see emu_sc_dsp3_sctail.py's since-removed note,
    # and the earlier fullbody probe) -- excluded here the same way.
    def clean(v):
        return v[:19] + v[21:]

    # 2. MON_ON=0 -> X:0 must stay untouched (still zero-seeded).
    mem = base.base_mem(words, scdet, moncommit, False,
                         [(1, 0x420, [MYTRACK]), (1, 0, [0] * 0x20)],
                         [(2, MON_ADDR, [0, KEYTRACK])])
    (x0,) = base.run(mem, moncommit, [('x', 0, 0x20)], "0,0,0,0,0,0,0,0,0,64,64,0", pokey=pk)
    check("MON_ON=0: X:0 untouched", all(v == 0 for v in clean(x0)),
          f"got={[hex(v) for v in x0]}")

    # 3. Different track's MON_ON must not leak into this track's commit --
    #    seed MYTRACK's own slot OFF while some OTHER track's slot is ON.
    OTHER = (MYTRACK + 1) % 8
    OTHER_ADDR = KB_BASE + OTHER * 0x80 + 0x40
    mem = base.base_mem(words, scdet, moncommit, False,
                         [(1, 0x420, [MYTRACK]), (1, 0, [0] * 0x20)],
                         [(2, MON_ADDR, [0, KEYTRACK]), (2, OTHER_ADDR, [0x10000, KEYTRACK])])
    (x0,) = base.run(mem, moncommit, [('x', 0, 0x20)], "0,0,0,0,0,0,0,0,0,64,64,0", pokey=pk)
    check("another track's MON_ON=1 does not leak into this track's commit",
          all(v == 0 for v in clean(x0)), f"got={[hex(v) for v in x0]}")

    # 4. UNINITIALIZED-SLOT HAZARD (Session 59/60): moncommit runs for EVERY
    # track's commit every frame, but MON_ON is only ever WRITTEN by scdet,
    # which only runs for the one track actively processing a COMPRESSOR.
    # For any other track this Y slot is real, never-zeroed DSP memory --
    # dumping the actual stock baseline (out/dsp/payload_B.mem, regenerated
    # straight from out/raw/section_3_MAIN_OS.bin, no patches) shows EVERY
    # track's slot already holds large nonzero garbage (~0x7fffff-ish, i.e.
    # Q23-scale audio residue), even on completely unmodified stock firmware.
    # Deliberately do NOT seed UNSEEDED's own MON_ON/MON_KEY here -- run
    # moncommit AS that track and let it read whatever base_mem's underlying
    # MEM_B snapshot really has there, to prove the fix (exact match against
    # scdet's $10000 ON sentinel, not "nonzero") holds against REAL garbage,
    # not just a synthetic non-$10000 value.
    UNSEEDED = 0
    assert UNSEEDED not in (MYTRACK, KEYTRACK, OTHER)
    real_garbage = base.load_mem(base.MEM_B)
    garbage_val = None
    ua = KB_BASE + UNSEEDED * 0x80 + 0x40
    for sp, addr, w in real_garbage:
        if sp == 1 and addr <= ua < addr + len(w):
            garbage_val = w[ua - addr]
    mem = base.base_mem(words, scdet, moncommit, False,
                         [(1, 0x420, [UNSEEDED]), (1, 0, [0] * 0x20)], None)
    (x0,) = base.run(mem, moncommit, [('x', 0, 0x20)], "0,0,0,0,0,0,0,0,0,64,64,0", pokey=pk)
    check(f"never-published track's own real garbage MON_ON ({garbage_val}) "
          "is NOT treated as on -- X:0 untouched",
          all(v == 0 for v in clean(x0)), f"got={[hex(v) for v in x0]}")

    print()
    if fails:
        print(f"FAIL -- {len(fails)}: " + ", ".join(fails))
        sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

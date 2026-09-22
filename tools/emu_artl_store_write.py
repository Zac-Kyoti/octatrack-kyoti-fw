#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 78: prove FUN_40042158 is the stored-p-lock writer, and that driving it with the
"not locked" sentinel 0xFF erases a real lock in the user's real ARTLTEST1.

FUN_40042158(track, param, value, step_override, cached) -- entry at the `linkw %fp,#-84`
right after FUN_40041bc4 ends, which is why earlier sessions never saw it as a separate
function. Decompiled, it:

  * guards on the PART byte, 0x460d172a != 0 (LIVE), 0x460d1a94 == 0, FUN_4009b290(track)==1
  * decodes (bank, pattern, step) via FUN_4009b2d4
  * `if (step_override != -1) step = step_override`      <- lets this script pick the step
    instead of needing a running playhead, which is what defeated Session 34
  * if NO trig-type layer owns the step (TRAC+0x00, +0x08, +0x10, +0x18 all clear at that
    bit) it CREATES a trigless lock: `TRAC+0x10 |= 1<<step`, plus PART payload and mirrors
  * either way: `#1[step][param] = value`, sets the dirty flags, and updates the
    stored-p-lock per-step bitmap 0x46c7d48c that the LED rebuild 0x400339d8 reads

That "create the trigless lock when writing a p-lock to an empty step" is the exact
inverse of the feature, at one instruction (0x400422ee, and its MIDI twin 0x400423e6),
with bank/pattern/step/track/param/value all live in registers.

Two assertions, both against ARTLTEST1's real two-lock trigless lock at step 6:

  A. erase one of two    -> #1[6][0x00] becomes 0xFF, #1[6][0x02] survives,
                            TRAC+0x10 bit 6 STAYS set (stock's bug -- this is what
                            the user sees as "LED still lit")
  B. erase the last one  -> #1[6] all 0xFF, and stock STILL leaves TRAC+0x10 bit 6 set

B failing to clear the bit is the bug being fixed, so this script PASSES when the bit
survives; it is a stock-behaviour baseline, not a test of the fix.

    python3 tools/emu_artl_store_write.py [project-dir]
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
DEFAULT_PROJECT = pathlib.Path.home() / "Desktop" / "ARTLTEST1"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath          # noqa: E402
import emu_rtos as er    # noqa: E402
import emu_card as ec    # noqa: E402
import unicorn           # noqa: E402
import unicorn.m68k_const as eb  # noqa: E402

PAT_STRIDE = er.PATTERN_STRIDE
TRAC_STRIDE = er.TRAC_STRIDE
PLOCK_IN_TRAC = 0x59
PAT, TRK, STEP = 0, 0, 6
UNLOCKED = 0xFF

STORE_WRITER = 0x40042158
GATE_LIVE = 0x460d172a
GATE_BLOCK = 0x460d1a94           # note: 0x1a94, not the 0x1a90 FUN_40041bc4 tests
ARG_CACHED = 0x46c7e956
CUR_TRACK = 0x80000000
TRACK_GATE_FN = 0x4009b290
TRACK_GATE_TBL = 0x80006500

LAYERS = ((0x00, "trig"), (0x08, "layerA"), (0x10, "TRIGLESS"), (0x18, "layerC"))


def main():
    project = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    if not project.exists():
        sys.exit(f"missing {project}")

    card, name = er.stage_project(str(project), "OCTABAM", None)
    r, rt = er.attach(str(STOCK), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)  [{project.name}]")

    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    trac = blob + PAT * PAT_STRIDE + TRK * TRAC_STRIDE

    def one():
        v = bytes(rt.uc.mem_read(trac + PLOCK_IN_TRAC + STEP * 32, 32))
        return {i: v[i] for i in range(32) if v[i] != UNLOCKED}

    def layers():
        out = {}
        for off, label in LAYERS:
            v = bytes(rt.uc.mem_read(trac + off, 8))
            out[label] = [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]
        return out

    def show(tag):
        print(f"  {tag:22} #1[{STEP}]={ {hex(k): hex(v) for k, v in one().items()} or 'EMPTY' }"
              f"   layers={layers()}")

    print(f"blob {blob:#x}  TRAC {trac:#x}")
    show("as loaded:")
    if one() != {0x00: 0x30, 0x02: 0x4e}:
        sys.exit(f"!! expected ARTLTEST1's two real locks {{0x0:0x30, 0x2:0x4e}}, got {one()} "
                 f"-- wrong project or the load did not take; stopping rather than "
                 f"reporting a result about the wrong state.")

    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.uc.mem_write(GATE_LIVE, struct.pack(">I", 1))
    rt.uc.mem_write(GATE_BLOCK, struct.pack(">I", 0))
    rt.uc.mem_write(CUR_TRACK, bytes([TRK]))
    for i in range(16):
        rt.uc.mem_write(TRACK_GATE_TBL + i, bytes([1]))
    rt.uc.mem_write(ARG_CACHED, struct.pack(">I", 0))
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)

    hits = []
    armed = [False]

    def on_write(u, acc, a, size, val, user):
        if armed[0]:
            hits.append((u.reg_read(eb.UC_M68K_REG_PC), a, size, val))
    rt.uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, on_write, begin=trac, end=trac + TRAC_STRIDE - 1)
    rt.uc.ctl_flush_tb()

    def erase(param):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        hits.clear()
        armed[0] = True
        try:
            rt.call_as_main(STORE_WRITER, args=(TRK, param, UNLOCKED, STEP, 0),
                            budget=1_500_000)
        finally:
            armed[0] = False
        for pc, a, size, v in hits:
            print(f"        {pc:#010x}  TRAC+{a - trac:#06x} <- {v:#x} ({size})")

    print(f"\nA. erase param 0x00 (PTCH) at step {STEP}")
    erase(0x00)
    show("after:")
    a_ok = one() == {0x02: 0x4e} and STEP in layers()["TRIGLESS"]

    print(f"\nB. erase param 0x02 (LEN) -- the LAST lock on the step")
    erase(0x02)
    show("after:")
    b_ok = one() == {} and STEP in layers()["TRIGLESS"]

    print(f"\nA (one of two erased, lock survives, bit stays)  : {'PASS' if a_ok else 'FAIL'}")
    print(f"B (last erased, row empty, bit STILL set = bug)   : {'PASS' if b_ok else 'FAIL'}")
    if a_ok and b_ok:
        print("\nStock baseline reproduced in the emulator: the erase empties `#1` but never")
        print("clears TRAC+0x10, so the step stays lit. That is exactly what the user reported")
        print("on hardware, and it is now reproducible without touching the unit.")
    return 0 if (a_ok and b_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())

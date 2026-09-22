#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 78: test whether FUN_4004271c / FUN_40042d1c are the stock primitive that
CLEARS the trigless-lock bit -- the operation this feature has been trying to write
by hand since Session 13.

Why they are suspected. Decompiled, FUN_4004271c(track, arg) refuses if any other
trig-type layer already owns the step (bit tests on TRAC+0x00, +0x18, +0x08, each
returning early), then bit-tests TRAC+0x10 -- the layer the user's four real exports
prove carries the trigless-lock flag -- and on the "already set" side does:

    TRAC+0x10 &= ~(1 << n)      <- clears it
    TRAC+0x14 &= ~(lo)
    TRAC+0x08 |= (1 << n)
    ... PART payload, 0x1001aaXX / 0x10016xxx mirrors, 0x4017d512 + 0x100f8598 dirty
    FUN_40027de4(); FUN_400418e0();      <- redraw

If that is what it does, the feature needs no hand-written mask arithmetic at all: it
can call stock's own primitive, which already maintains every mirror, dirty flag and
redraw that a hand-rolled cave would have to reproduce (and that patch_triglock.s did
not). This script asserts that behaviour instead of assuming it.

The bit index `n` is FUN_4009b2d4's third output byte. Session 33 labelled that byte a
"param-page descriptor"; here it is used unambiguously as a bit index into TRAC+0x00,
the note/sample trig mask, which is step-indexed -- so it should be the STEP. The sweep
over 0x46c775ce (the edit/playhead step base the decode subtracts from) tests that: if
`n` is the step, moving the base must move which bit of TRAC+0x10 changes.

    python3 tools/emu_artl_trigless_toggle.py [project-dir]
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

PAT_STRIDE = er.PATTERN_STRIDE    # 0x8ed8
TRAC_STRIDE = er.TRAC_STRIDE      # 0x91a
PLOCK_IN_TRAC = 0x59
PAT, TRK, STEP = 0, 0, 6

TOGGLE_A = 0x4004271c             # taken when 0x46c7dd26 != 0
TOGGLE_B = 0x40042d1c             # taken when 0x46c7dd26 == 0
GATE_LIVE = 0x460d172a
GATE_ARMED = 0x460d172e
GATE_BLOCK = 0x460d1a90
ARG3_GLOBAL = 0x46c7e956
STEP_BASE = 0x46c775ce            # the decode's edit/playhead step base
CUR_TRACK = 0x80000000
TRACK_GATE_FN = 0x4009b290
# FUN_4009b290(n) for n >= 0 returns the byte at 0x80006500 + (n & 15); Session 34's
# "0x80006508 + trk" was that same table reached with the track+8 form FUN_40041bc4 uses.
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

    def layers():
        out = {}
        for off, label in LAYERS:
            v = bytes(rt.uc.mem_read(trac + off, 8))
            out[label] = [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]
        return out

    def one():
        v = bytes(rt.uc.mem_read(trac + PLOCK_IN_TRAC + STEP * 32, 32))
        return {i: v[i] for i in range(32) if v[i] != 0xFF}

    print(f"blob {blob:#x}  TRAC {trac:#x}")
    print(f"pre : {layers()}   #1[{STEP}]={ {hex(k): hex(v) for k, v in one().items()} }")

    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.uc.mem_write(GATE_LIVE, struct.pack(">I", 1))
    rt.uc.mem_write(GATE_ARMED, struct.pack(">I", 0))
    rt.uc.mem_write(GATE_BLOCK, struct.pack(">I", 0))
    rt.uc.mem_write(CUR_TRACK, bytes([TRK]))
    for i in range(16):
        rt.uc.mem_write(TRACK_GATE_TBL + i, bytes([1]))
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    print(f"per-track gate FUN_4009b290({TRK}) -> "
          f"{rt.call_as_main(TRACK_GATE_FN, args=(TRK,), budget=200_000):#x}")
    # The other early-out: a PART byte of 4 for this track refuses the call outright.
    part_gate = blob + rt.uc.mem_read(0x100b14cf, 1)[0] * 0x18b2 + 0x8eda2 + TRK
    print(f"PART gate byte @ {part_gate:#x} = {rt.uc.mem_read(part_gate, 1)[0]}"
          f"   (4 would refuse)")

    hits = []
    armed = [False]

    def on_write(u, acc, a, size, val, user):
        if armed[0]:
            hits.append((u.reg_read(eb.UC_M68K_REG_PC), a, size, val))
    rt.uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, on_write, begin=trac, end=trac + TRAC_STRIDE - 1)
    rt.uc.ctl_flush_tb()

    for fn, sel in ((TOGGLE_A, 1), (TOGGLE_B, 0)):
        print(f"\n=== FUN_{fn:x}  (0x46c7dd26 := {sel}) ===")
        for base in (0, 1, 2, 6, 7, 8, 16):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.uc.mem_write(0x46c7dd26, struct.pack(">I", sel))
            rt.uc.mem_write(STEP_BASE, bytes([base]))
            rt.uc.mem_write(ARG3_GLOBAL, struct.pack(">I", 0))
            before = layers()
            hits.clear()
            armed[0] = True
            try:
                d0 = rt.call_as_main(fn, args=(TRK, 0), budget=1_500_000)
            except Exception as e:
                armed[0] = False
                print(f"  step-base {base:3}: fault {e}")
                continue
            armed[0] = False
            after = layers()
            delta = {k: (before[k], after[k]) for k in after if before[k] != after[k]}
            print(f"  step-base {base:3}: d0={d0 if d0 < 0x80000000 else d0 - 0x100000000:5}"
                  f"  TRAC writes={len(hits):3}"
                  f"  {'CHANGED ' + str(delta) if delta else 'no layer change'}")
            for pc, a, size, v in hits[:8]:
                print(f"        {pc:#010x}  TRAC+{a - trac:#06x} <- {v:#x} ({size})")

    print(f"\npost: {layers()}   #1[{STEP}]={ {hex(k): hex(v) for k, v in one().items()} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

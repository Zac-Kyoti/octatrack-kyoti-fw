#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 78: read what the `+0x48d8` 64-bit field actually CONTAINS for a real
hardware-authored trigless lock, instead of trusting a prior session's label for it --
the exact mistake that made patch_triglock.s inert on hardware (NOTES.md, "Session 78
continued a ninth time").

ARTLTEST1 (user's real MKI export) holds ONE trigless lock at bank 1 / pattern 1 /
track 1 (all 0-indexed 0), step 6, p-locked to two params: PTCH (`#1` byte 0x00) and
LEN (`#1` byte 0x02). Both `.strd` and `.work` currently carry that same 2-lock state.

That single state is decisive on its own:
    bit 6 set          -> the field is indexed by STEP
    bits 0 and 2 set   -> the field is indexed by PARAM (the old label)
No differential needed, and none is claimed: this script asserts what it observed rather
than inferring from a comparison whose premise it hasn't checked.

    python3 tools/emu_artl_fields.py [project-dir]
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

PAT_STRIDE = er.PATTERN_STRIDE    # 0x8ed8
TRAC_STRIDE = er.TRAC_STRIDE      # 0x91a
WRK_TRK_STRIDE = 0x8b0
PLOCK_IN_TRAC = 0x59
PAT, TRK, STEP = 0, 0, 6


def blob_base(rt):
    return struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]


def bits_set(v64):
    return [i for i in range(64) if (v64 >> i) & 1]


def main():
    project = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    if not project.exists():
        sys.exit(f"missing {project}")

    card, name = er.stage_project(str(project), "OCTABAM", None)
    r, rt = er.attach(str(STOCK), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)  [{project.name}]")

    blob = blob_base(rt)
    trac = blob + PAT * PAT_STRIDE + TRK * TRAC_STRIDE
    print(f"blob {blob:#x}   TRAC(pat{PAT},trk{TRK}) {trac:#x}\n")

    one = bytes(rt.uc.mem_read(trac + PLOCK_IN_TRAC + STEP * 32, 32))
    locked = [(i, one[i]) for i in range(32) if one[i] != 0xFF]
    print(f"#1[step {STEP}] locked bytes: "
          f"{[(hex(i), hex(v)) for i, v in locked] or 'none (all 0xFF)'}")
    if not locked:
        print("  !! no locks present in RAM -- wrong project/step, or the load didn't take;")
        print("     everything below would be meaningless. Stopping.")
        return 1

    print("\nTRAC step-masks (8 B each, byte[7-step/8] bit[step%8]):")
    for off, label in ((0x00, "note/sample trig"), (0x08, "type layer A"),
                       (0x10, "type layer B  <- trigless-lock flag"),
                       (0x18, "type layer C"), (0x20, "REC1"), (0x28, "REC2"), (0x30, "REC3")):
        v = bytes(rt.uc.mem_read(trac + off, 8))
        steps = [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]
        print(f"  +{off:#04x} {label:30} {v.hex(' ')}  steps={steps}")

    print("\nthe two 64-bit blob fields FUN_40041bc4 tests/clears:")
    for off in (0x48d8, 0x48e0):
        a = blob + PAT * PAT_STRIDE + TRK * WRK_TRK_STRIDE + off
        hi = struct.unpack(">I", rt.uc.mem_read(a, 4))[0]
        lo = struct.unpack(">I", rt.uc.mem_read(a + 4, 4))[0]
        # FUN_400a694c(0,1,n) shifts the pair left by n, so bit n lands with the FIRST
        # longword as the high half -- read the pair as (hi<<32)|lo to match.
        print(f"  +{off:#06x} @ {a:#x} = {hi:08x} {lo:08x}   bits set = {bits_set((hi << 32) | lo)}")

    live = bytes(rt.uc.mem_read(blob + PAT * PAT_STRIDE + TRK * WRK_TRK_STRIDE
                                + 0x4900 + STEP * 32, 32))
    print(f"\n+0x4900[step {STEP}] live scratch: {live.hex(' ')}")

    print(f"\n=== verdict ===")
    print(f"  locks are on #1 bytes {[hex(i) for i, _ in locked]}, at step {STEP}.")
    print(f"  If a field above shows bit {STEP} -> that field is STEP-indexed.")
    print(f"  If it shows bits {[i for i, _ in locked]} -> it is PARAM-indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

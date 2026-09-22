#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 78 continued: verify a real hardware-exported project through the REAL
firmware in the emulator (not a synthetic hand-patched bank, unlike Session 31's
--trigless test). `~/Desktop/ARTLTEST2` is a real MKI export where, on bank 1
pattern 1 track 1 step 6 (per tools/inspect_bank.py), the on-disk data shows:
  - #1 (TRAC+0x59 in RAM / TRAC+0x62 on disk) fully 0xFF -- no p-lock VALUE left.
  - the "trig-type layer" mask at TRAC+0x10 (RAM) / TRAC+0x19 (disk) still has
    its bit SET for step 6 -- a flag Session 31's synthetic test never saw set
    (it only cleared a note bit by hand; it never drove the real
    place-a-trigless-lock code path), and the kb's own file-format.md already
    flagged this exact mask as "carries the trigless lock bit" (still
    unconfirmed which of the three candidates, until now).

This loads that real export through the real firmware and calls the actual LED
rebuild (0x400339d8) to see whether LOCK_STORED (0x46c7d48c, what Session
27-32 established the dim-lock LED is painted from) comes back lit for
step 6/track 0 even though #1 is empty -- i.e. whether the persisting "ghost"
lock Section 13 is about is explained by this flag, not by any residual value
in #1.

    python3 tools/emu_artl_hwcheck.py ~/Desktop/ARTLTEST2
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
OUR_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")

import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath          # noqa: E402
import emu_rtos as er    # noqa: E402
import emu_card as ec    # noqa: E402

PATTERN_STRIDE = er.PATTERN_STRIDE   # 0x8ed8
TRAC_STRIDE = er.TRAC_STRIDE         # 0x91a
PLOCK_IN_TRAC = 0x59                 # RAM #1 (= disk TRAC+0x62 - 9)
CUR_PAT_MIRROR = 0x100b14d0
LOCK_LIVE = 0x46c7d2e4               # per-step bitmap, LIVE (+0x4900) lock presence
LOCK_STORED = 0x46c7d48c             # per-step bitmap, STORED (#1) lock presence
LOCK_REBUILD = 0x400339d8            # rebuilds both bitmaps from the blob


def blob_base(rt):
    return struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]


def trac_base(rt, pat, trk):
    return blob_base(rt) + pat * PATTERN_STRIDE + trk * TRAC_STRIDE


def steps_of_mask(v):
    return [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: emu_artl_hwcheck.py <project-dir>")
    project_dir = sys.argv[1]
    pat, trk, step = 0, 0, 6  # bank1(0)/pattern1(0)/track1(0), step 6 per inspect_bank.py

    card, name = er.stage_project(project_dir, "OCTABAM", None)
    r, rt = er.attach(str(OUR_IMAGE), card, tick=True)
    print(f"boot       : {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load       : mounted={mounted} posted={posted} "
          f"saved_bank={saved_bank} final_bank={final_bank} ({elapsed:.0f} ms)")

    tb = trac_base(rt, pat, trk)
    print(f"\nTRAC(bank1/pat1/trk1) @ {tb:#x}")

    plock = bytes(rt.uc.mem_read(tb + PLOCK_IN_TRAC + step * 32, 32))
    print(f"#1[step {step}] (32 B)        : {plock.hex(' ')}"
          f"   {'ALL 0xFF (empty)' if set(plock) == {0xFF} else 'HAS a locked byte'}")

    for base, label in ((0x08, "mask 0x08 (disk +0x11)"),
                         (0x10, "mask 0x10 (disk +0x19)"),
                         (0x18, "mask 0x18 (disk +0x21)")):
        v = bytes(rt.uc.mem_read(tb + base, 8))
        print(f"TRAC+{base:#04x} {label:<24}: {v.hex(' ')}   steps={steps_of_mask(v)}")

    note = bytes(rt.uc.mem_read(tb + 0x00, 8))
    print(f"TRAC+0x00 note/sample trig    : {note.hex(' ')}   steps={steps_of_mask(note)}")

    was = rt.uc.mem_read(CUR_PAT_MIRROR, 1)[0]
    rt.uc.mem_write(CUR_PAT_MIRROR, bytes([pat]))
    print(f"\ncur-pat mirror was {was:#x}; re-asserted {pat:#x} before the rebuild")

    d0 = rt.call_as_main(LOCK_REBUILD, args=(), budget=2_000_000)
    print(f"call 0x400339d8 (LED rebuild) : d0={d0!r}")

    live = bytes(rt.uc.mem_read(LOCK_LIVE, 64))
    stored = bytes(rt.uc.mem_read(LOCK_STORED, 64))
    print(f"\nLOCK_LIVE   [step {step}] = {live[step]:#04x}   bit{trk} set = {bool(live[step] & (1 << trk))}")
    print(f"LOCK_STORED [step {step}] = {stored[step]:#04x}   bit{trk} set = {bool(stored[step] & (1 << trk))}")
    print()
    if stored[step] & (1 << trk):
        print("==> VERDICT: the dim-lock LED bitmap comes back LIT for this step even though "
              "#1 is fully empty. The persisting lock is NOT explained by a residual #1 value "
              "-- something else (very likely the TRAC+0x10 trig-type-layer bit above) is what "
              "0x400339d8 (or a step downstream of it) actually keys off.")
    else:
        print("==> VERDICT: the dim-lock LED bitmap correctly comes back OFF for this step. "
              "0x400339d8's rebuild does NOT key off TRAC+0x10 -- the persisting on-hardware "
              "symptom must come from somewhere else (a bitmap not being refreshed, a different "
              "painter, or a live-view stat not shown here).")


if __name__ == "__main__":
    raise SystemExit(main())

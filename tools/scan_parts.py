#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 49 -- quick static reader for an OT bank file: pattern -> Part link (both the
`+0x8e57` and OctaLib `+0x8ee7` candidate offsets, side by side) + a best-effort
per-Part machine-type row. Static read of the on-CF format, no firmware/emulator.
Machine type: 0=STATIC 1=FLEX 2=THRU 3=NEIGHBOR 4=PICKUP.

    python3 tools/scan_parts.py "<bank01.work>" ["<bank01.strd>" ...]

KNOWN LIMITATION: the on-disk machine-type-row guess (tries part-tag offsets
0x22/0x0a/0x1a) did NOT decode cleanly on either the factory OT DEMO or a real
"Pickup"-project bank export this session -- prints "no clean machine row" for every
Part. The disk layout for machine-type bytes isn't pinned; don't trust this tool's
machine-type output without re-deriving the disk offset first. The pattern->Part link
dump (`+0x8e57` / `+0x8ee7`) is reliable and was cross-checked against the RAM blob via
`emu_rtos` in Session 49. For machine types, read them from RAM via `emu_rtos`
(`blob + PARTS_OFF + part*0x18b2 + 0x22 + track`, see `tools/diff_flex_static.py` /
`tools/emu_partswitch.py`) instead of this tool, until the disk offset is found.
"""
import sys
import pathlib
import glob

PAT1, PSTRIDE, PHDR = 0x16, 0x8EEC, 8
TRAC, MTRA = 0x922, 0x8B9
PART_TAG = b"PART"
MT = {0: "STAT", 1: "FLEX", 2: "THRU", 3: "NEIG", 4: "PICK"}


def pat_part_link(b, pat):
    base = PAT1 + PSTRIDE * pat
    return b[base + 0x8E57], b[base + 0x8EE7]


def scan(path):
    b = path.read_bytes()
    print(f"\n=== {path.parent.name}/{path.name}  ({len(b):#x} B) ===")
    parts = []
    off = 0
    while True:
        i = b.find(PART_TAG, off)
        if i < 0:
            break
        parts.append(i)
        off = i + 1
    print(f"PART tags at: {[hex(p) for p in parts]}")
    for pi, p in enumerate(parts):
        idx = b[p + 8]
        for cand in (0x22, 0x0A, 0x1A):
            row = b[p + cand: p + cand + 8]
            if all(x in MT for x in row):
                mt = " ".join(MT[x] for x in row)
                print(f"  PART#{pi} tag@{p:#x} idx={idx}  +{cand:#x}: {mt}")
                break
        else:
            print(f"  PART#{pi} tag@{p:#x} idx={idx}  (no clean machine row at 0x22/0x0a/0x1a)"
                  f"  bytes@+0x22: {b[p+0x22:p+0x2a].hex()}")
    print("  pattern -> part link (0x8e57 / 0x8ee7):")
    for pat in range(16):
        a, c = pat_part_link(b, pat)
        print(f"    P{pat+1:2d}: {a} / {c}")


def main(argv):
    for arg in argv:
        for f in sorted(glob.glob(arg)):
            scan(pathlib.Path(f))


if __name__ == "__main__":
    main(sys.argv[1:])

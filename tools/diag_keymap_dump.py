#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_keymap_dump -- dump the live key dispatch table and the is-held array.

Session 85. The RELOAD redesign needs the TRACK-button keycodes, and this repo
has never had a map: keycodes have been discovered one at a time and twice
recorded WRONG (the arrow pairing was corrected twice, Sessions 80 cont. 6 and 7).
So dump the whole thing once, from the running firmware, and group keycodes by
shared handler -- button families (trigs, tracks, arrows) share one handler, which
is what makes them identifiable without guessing.

Two runtime structures, both already relied on by patch_reload2.s:
  dispatch table : 0x46c7d8de, 24-byte stride, handler pointer at +0
  is-held array  : 0x46c7d8ee, 24-byte stride  (BANK_HELD_FLAG in patch_reload2.s
                   is 0x46c7dd56 = 0x46c7d8ee + 0x2f*24, which fixes the layout)

Usage: python3 tools/diag_keymap_dump.py [--max 0x40]
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402
er = erl.er

DISPATCH = 0x46C7D8DE
HELD = 0x46C7D8EE
STRIDE = 24
KNOWN = {0x20: "DOWN", 0x21: "L/R pair", 0x2E: "PTN", 0x2F: "BANK",
         0x31: "YES", 0x32: "NO", 0x33: "UP", 0x34: "L/R pair", 0x1B: "PAGE"}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=lambda x: int(x, 0), default=0x40)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.RELOAD_IMAGE), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    print(f"load : mounted={mounted} bank={final_bank}\n")

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    rows, fams = [], {}
    for code in range(a.max):
        h = u32(DISPATCH + code * STRIDE)
        rows.append((code, h))
        fams.setdefault(h, []).append(code)

    print("code  handler      held-flag    note")
    for code, h in rows:
        note = KNOWN.get(code, "")
        n = len(fams[h])
        if n > 1 and not note:
            note = f"(family of {n})"
        print(f" 0x{code:02x}  0x{h:08x}  0x{HELD + code*STRIDE:08x}  {note}")

    print("\n=== keycodes grouped by shared handler (families) ===")
    for h, codes in sorted(fams.items(), key=lambda kv: -len(kv[1])):
        if len(codes) < 2:
            continue
        names = ", ".join(f"0x{c:02x}" for c in codes)
        lbl = " / ".join(sorted({KNOWN[c] for c in codes if c in KNOWN}))
        print(f"  0x{h:08x}  x{len(codes):<3} {names}" + (f"   <- {lbl}" if lbl else ""))

    print("\n  (a family of exactly 8 that is NOT the 16 trigs is the TRACK buttons)")
    print(f"  BANK held-flag should be 0x46c7dd56: "
          f"0x{HELD + 0x2F*STRIDE:08x}  "
          f"{'OK' if HELD + 0x2F*STRIDE == 0x46C7DD56 else 'MISMATCH'}")
    print(f"  PTN  held-flag (code 0x2e)          : 0x{HELD + 0x2E*STRIDE:08x}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

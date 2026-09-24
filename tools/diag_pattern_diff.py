#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Byte-diff two loaded pattern blobs to locate a field by the UI control that writes it.

Session 79 cont.33. The DJTEST2 fixture was built so each probe pattern varies exactly one
setting, which turns "where does MASTER LENGTH live?" into a diff rather than a search.
DJTEST2 bank A: pattern 4 (A05) is identical to pattern 3 (A04) except MASTER LENGTH is 32
instead of 16 -- and the header scan showed `+0x8e53` reads 16 in BOTH, so MASTER LENGTH is
somewhere else. That field matters independently of Hook D: "steps before all tracks reset"
is what DIRECT JUMP's resume position has to be expressed against.

Reads both blobs straight out of emulator RAM after a real project load, so this measures the
firmware's own parsed representation rather than guessing at the on-card file format (a raw
byte-offset scan of bank files was tried in an earlier session and returned garbage).

Usage:
  python3 tools/diag_pattern_diff.py --project DIR --a 3 --b 4 [--bank N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

BLOB, BANK_STRIDE, PAT_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8
TRK_STRIDE, MIDI_OFF, MIDI_STRIDE = 0x91A, 0x48F8, 0x8B0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(STOCK))
    ap.add_argument("--project", required=True)
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--a", type=int, required=True)
    ap.add_argument("--b", type=int, required=True)
    ap.add_argument("--max-hits", type=int, default=60)
    ap.add_argument("--tree", default="out/_emu_patdiff")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3] if a.bank is None else a.bank

    base_a = BLOB + bank * BANK_STRIDE + a.a * PAT_STRIDE
    base_b = BLOB + bank * BANK_STRIDE + a.b * PAT_STRIDE
    blob_a = bytes(rt.uc.mem_read(base_a, PAT_STRIDE))
    blob_b = bytes(rt.uc.mem_read(base_b, PAT_STRIDE))

    print(f"project {a.project}  bank {bank}")
    print(f"pattern {a.a} @ {base_a:#x}   vs   pattern {a.b} @ {base_b:#x}")
    print(f"blob size {PAT_STRIDE:#x}")

    hits = [i for i in range(PAT_STRIDE) if blob_a[i] != blob_b[i]]
    print(f"\n{len(hits)} differing byte(s)")

    def where(off):
        """Describe an offset in terms of the known blob layout."""
        if off >= 0x8E00:
            return f"pattern header +{off:#x}"
        if off >= MIDI_OFF:
            t, o = divmod(off - MIDI_OFF, MIDI_STRIDE)
            if t < 8:
                return f"MIDI track {t} +{o:#x}"
        t, o = divmod(off, TRK_STRIDE)
        if t < 8:
            return f"audio track {t} +{o:#x}"
        return "?"

    for i in hits[:a.max_hits]:
        print(f"  +{i:#07x}  {blob_a[i]:3d} -> {blob_b[i]:3d}   "
              f"({blob_a[i]:#04x} -> {blob_b[i]:#04x})   {where(i)}")
    if len(hits) > a.max_hits:
        print(f"  ... {len(hits) - a.max_hits} more")

    # A single setting changed from 16 to 32 should show up as exactly that, so call it out.
    exact = [i for i in hits if blob_a[i] == 16 and blob_b[i] == 32]
    if exact:
        print("\n  bytes that went 16 -> 32 (the MASTER LENGTH change):")
        for i in exact:
            print(f"    pattern +{i:#x}   (absolute {BLOB + i:#x} + bank/pat strides)   "
                  f"{where(i)}")
    else:
        print("\n  no byte went exactly 16 -> 32; the field may be encoded "
              "(word, offset-by-one, or a count of something else)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

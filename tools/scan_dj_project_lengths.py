#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 79 continued a sixteenth time: before flashing the STEP_IN_PAT fix, test it
against a project with differently-scaled/differently-lengthed tracks first (the user's
own recommendation, which I made). Two earlier approaches here were both wrong and
retracted: a raw byte-offset scan of the bank .work files produced garbage (170/255
"length" values -- wrong container layout assumed); a live SCALE_IX/LEN_TBL probe via
seq_select_live() read a stale global that is only ever refreshed by a REAL switch-commit
tick (dj_scaleix_fix, 0x400a4220), not by direct pattern selection, and turned out to be
answering the wrong question anyway -- SCALE_IX/LEN_TBL is the MASTER pattern length,
not the PER-TRACK length dj_pertrack_fix (and hence the STEP_IN_PAT fix) actually uses.

This version reads each track's own LENGTH/SCALE bytes directly out of the loaded
pattern blob in emulator RAM, using the EXACT same address arithmetic
patch_directjump.s's dj_pertrack_fix already establishes as correct (it is the live
firmware's own addressing, not a re-derivation): base = 0x400e21e0 + bank*0x9b340 +
pat*0x8ed8 + track*0x91a; length byte at +0x50, scale byte at +0x51 (per-track SCALE,
used only when the pattern-level SCALE_MODE flag at pattern-block +0x8e55 is set;
otherwise every track shares the pattern-level scale index at +0x8e54). No pattern
selection, no clock running -- this is static project data already resident in RAM once
the project/bank is loaded, so it needs neither and cannot itself be wrong the way a
live global read can. Read-only throughout: never touches DIRECT JUMP state, never
fabricates or edits any project file.

Usage: python3 tools/scan_dj_project_lengths.py [--project DIR] [--bank N] [--patterns N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = ROOT / "out" / "mainos_directjump_v4.bin"
DEMO_PROJECT = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

LEN_TBL = 0x400aba50
PAT_BASE = 0x400e21e0
BANK_STRIDE = 0x9b340
PAT_STRIDE = 0x8ed8
TRK_STRIDE = 0x91a
TRK_LEN_OFF = 0x50
TRK_SCALE_OFF = 0x51
PAT_SCALE_MODE_OFF = 0x8e55   # nonzero -> per-track scale; else pattern-level
PAT_SCALE_DEFAULT_OFF = 0x8e54


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(DEMO_PROJECT))
    ap.add_argument("--bank", type=int, default=1)
    ap.add_argument("--patterns", type=int, default=16)
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged_name = er.stage_project(a.project, "OCTABAM", None,
                                          tree=f"out/_emu_dj_scan_tree_b{a.bank}")
    r, rt = er.attach(str(IMAGE), card,
                       ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged_name, run_ms=6000)
    if a.bank is not None and final_bank != a.bank:
        final_bank = rt.select_bank_live(a.bank)
    bank0 = final_bank - 1 if final_bank else 0

    def len_tbl(idx):
        return int.from_bytes(rt.uc.mem_read(LEN_TBL + idx * 4, 4), "big")

    print(f"project={a.project}  bank={final_bank}")
    header = f"{'pattern':>7}  " + "  ".join(f"t{t}" for t in range(8))
    print(header)
    any_nonuniform = False
    for pat in range(1, a.patterns + 1):
        pat0 = pat - 1
        pblk = PAT_BASE + bank0 * BANK_STRIDE + pat0 * PAT_STRIDE
        scale_mode = rt.uc.mem_read(pblk + PAT_SCALE_MODE_OFF, 1)[0]
        pat_default_scale = rt.uc.mem_read(pblk + PAT_SCALE_DEFAULT_OFF, 1)[0]
        lens = []
        for trk in range(8):
            tblk = pblk + trk * TRK_STRIDE
            raw_len = rt.uc.mem_read(tblk + TRK_LEN_OFF, 1)[0]
            if scale_mode:
                scale_ix = rt.uc.mem_read(tblk + TRK_SCALE_OFF, 1)[0]
            else:
                scale_ix = pat_default_scale
            master_len = len_tbl(scale_ix)
            lens.append((raw_len, scale_ix, master_len))
        row = "  ".join(f"{rl}/{si}/{ml}" for rl, si, ml in lens)
        uniform = len({ml for _, _, ml in lens}) == 1
        flag = "" if uniform else "  <-- PER-TRACK SCALE DIFFERS"
        if not uniform:
            any_nonuniform = True
        print(f"{pat:7d}  scale_mode={scale_mode}  {row}{flag}")
    print("\ncolumns: rawLenByte/scaleIdx/masterLenFromLEN_TBL, per track t0..t7")
    if not any_nonuniform:
        print("\nNo pattern in this bank has per-track scale/length differences.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

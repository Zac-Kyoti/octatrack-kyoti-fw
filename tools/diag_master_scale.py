#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 88: dump the PATTERN-LEVEL master fields of a project, which
scan_dj_project_lengths.py does not print.

The non-1x thread turns on MASTER SCALE (+0x8e52), which is a different byte from the
uniform pattern multiplier (+0x8e54); stock selects between them on SCALE_MODE (+0x8e55),
exactly as Hook D does. Printing per-track scales alone cannot tell those apart, which is
how the Session 84 fixture gap happened.

Read-only. No pattern selection, no clock. Usage:
  python3 tools/diag_master_scale.py [--project DIR] [--bank N] [--patterns N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = ROOT / "out" / "mainos_directjump_v4.bin"

LEN_TBL = 0x400ABA50
PAT_BASE = 0x400E21E0
BANK_STRIDE = 0x9B340
PAT_STRIDE = 0x8ED8
TRK_STRIDE = 0x91A

# pattern-block offsets, all from patch_directjump.s's measured equates
OFF_MLEN = 0x8E51     # MASTER LENGTH in steps
OFF_MSCALE = 0x8E52   # MASTER scale idx, used when SCALE_MODE != 0
OFF_LEN = 0x8E53      # pattern LENGTH in steps
OFF_SCALE = 0x8E54    # uniform pattern scale idx, used when SCALE_MODE == 0
OFF_SMODE = 0x8E55    # SCALE_MODE flag
OFF_TRK_LEN = 0x50
OFF_TRK_SCALE = 0x51


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--bank", type=int, default=1)
    ap.add_argument("--patterns", type=int, default=8)
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None,
                                    tree=f"out/_emu_mscale_b{a.bank}")
    r, rt = er.attach(str(IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    _, _, _, final_bank, _ = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    if a.bank is not None and final_bank != a.bank:
        final_bank = rt.select_bank_live(a.bank)
    bank0 = final_bank - 1 if final_bank else 0

    rd = lambda addr, n=1: rt.uc.mem_read(addr, n)
    len_tbl = [int.from_bytes(rd(LEN_TBL + i * 4, 4), "big") for i in range(8)]
    print(f"project={a.project}  bank={final_bank}")
    print("LEN_TBL (scaleIdx -> TICKS PER STEP):")
    for i, v in enumerate(len_tbl):
        print(f"    [{i}] = {v}")
    print()
    print(f"{'pat':>3} {'SMODE':>5} {'MLEN':>5} {'MSCALE':>6} {'LEN':>4} {'SCALE':>5} "
          f"{'effMasterTPS':>12}   per-track len/scaleIdx/tps")
    for pat in range(1, a.patterns + 1):
        pblk = PAT_BASE + bank0 * BANK_STRIDE + (pat - 1) * PAT_STRIDE
        smode = rd(pblk + OFF_SMODE)[0]
        mlen = rd(pblk + OFF_MLEN)[0]
        mscale = rd(pblk + OFF_MSCALE)[0]
        plen = rd(pblk + OFF_LEN)[0]
        pscale = rd(pblk + OFF_SCALE)[0]
        # stock's own D7 selection, per Hook D's measured comment
        eff_ix = mscale if smode else pscale
        eff_tps = len_tbl[eff_ix] if eff_ix < 8 else -1
        trks = []
        for t in range(8):
            tblk = pblk + t * TRK_STRIDE
            tl = rd(tblk + OFF_TRK_LEN)[0]
            ts = rd(tblk + OFF_TRK_SCALE)[0] if smode else pscale
            tps = len_tbl[ts] if ts < 8 else -1
            trks.append(f"{tl}/{ts}/{tps}")
        print(f"{pat:3d} {smode:5d} {mlen:5d} {mscale:6d} {plen:4d} {pscale:5d} "
              f"{eff_tps:12d}   " + " ".join(trks))
    print("\nMSCALE is live only when SMODE!=0; otherwise SCALE is. tps = ticks per step.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

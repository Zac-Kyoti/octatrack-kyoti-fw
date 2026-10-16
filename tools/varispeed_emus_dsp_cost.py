#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
VARISPEED_EMUS's DSP prices per voice: what the load guard budgets with.

Runs the kernel inside the stock voice module on dsp56kEmu with the engine check's
protocol (tools/varispeed_emus_dsp_engine_check.py: two hook visits per frame, a trig every
37 frames at a varying split, the four test signals at the five ratios) and counts,
per 16-output frame, the instructions executed INSIDE the cave and their datasheet
cycles (the emulator's opcodecycles table, as tools/varispeed_emus_dsp_profile.py prices
them; the probe's RK_FRAMECYC). The first frame (the one-time table copy, which
zqboot runs at boot on the unit) is left out.

  * S950 (S950) and SP12 (SP12): median and worst frame, per output sample;
  * the OT / stock exit (zqrp's mode check), which every voice pass on every
    track pays: per pass, plus the hook's bsr (outside the cave, priced here).

    python3 tools/varispeed_emus_dsp_cost.py [--form standalone|octabam] [--payload A|B|both] [--quick]

--form standalone (the default) is the kernel tools/build_varispeed_emus.py installs
(tools/varispeed_emus_dsp_src.py at cave_org); octabam is the generated vem_dsp.asm, its
tables in SPRING's X data (varispeed_emus_dsp_octabam_check's XS placement).
"""
import argparse
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import varispeed_emus_dsp_octabam_check as oc    # noqa: E402

ec = oc.ec
RATIOS = (1.0, 0.75, 1.5, 0.5, 1.99)
BSR_CYC = 5                               # the hook's `bsr` (Bsr_xxxx); the two stock moves it
                                          # displaced run in the cave (zqstk) and are counted there


def place(tag, form):
    """(org of the cave blob, entry) after writing the probe's cave and X-data files."""
    if form == "octabam":
        _, org, entry, _, _ = oc.build(tag, "XS")
        return org, entry
    n = len(ec.dsrc.assemble(0x1000, tag)[0])
    org = ec.dsrc.cave_org(tag, n)
    words, _, _ = ec.dsrc.assemble(org, tag)
    (ec.WORK / f"cave_{tag}.bin").write_bytes(b"".join(w.to_bytes(3, "little") for w in words))
    (ec.WORK / f"xdata_{tag}.txt").write_text("".join(f"{a:x} {w:x}\n" for a, w in sorted(ec.dsrc.x_data(tag).items())))
    return org, org


def frames(tag, base, hook, stop, org, b0, b1, mode, ratio, inp, name):
    inc = int(round(ratio * (1 << 24)))
    fc = ec.WORK / f"fc_{name}.txt"
    env = {**os.environ, "RK_FRAMECYC": str(fc)}
    ec.run_probe(tag, base, hook, stop, org, b0, b1, mode, inc >> 24, inc & 0xFFFFFF, inp,
                 ec.WORK / f"o_{name}.raw", ec.WORK / f"c_{name}.cnt", env=env)
    rows = [tuple(map(int, l.split())) for l in fc.read_text().splitlines()]
    return np.array(rows[1:], dtype=np.int64)          # frame 0: the one-time table copy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", default="standalone", choices=("standalone", "octabam"))
    ap.add_argument("--payload", default="both", choices=("A", "B", "both"))
    ap.add_argument("--quick", action="store_true", help="drum only, three ratios")
    a = ap.parse_args()
    ec.WORK = ROOT / f"out/varispeed_emus_dsp_cost_{a.form}"
    ec.WORK.mkdir(parents=True, exist_ok=True)
    ec.build_probe()
    ec.SCHED = ec.schedule(4000)
    (ec.WORK / "sched.txt").write_text("".join(f"{k:x} {f:x} {lv:x}\n" for k, f, lv in ec.SCHED))
    img = ec.chk.IMG.read_bytes()
    n_frames = int(1.0 * ec.SR)
    sigs = ec.signals(n_frames)
    if a.quick:
        sigs = {"drum": sigs["drum"]}
    ratios = (1.0, 0.75, 1.99) if a.quick else RATIOS
    res = {"S950": [], "SP12": []}
    stock = []
    for tag, va, ln, base, hook, stop in ec.chk.PAYLOADS:
        if a.payload not in ("both", tag):
            continue
        mod, _ = ec.chk.voice_module(img, va, ln, base)
        (ec.WORK / f"voice_{tag}.bin").write_bytes(mod)
        org, entry = place(tag, a.form)
        b0, b1 = ec.sc3.bsr_long(hook, entry)
        for sname, (L, R) in sigs.items():
            src = np.empty(2 * n_frames, dtype=np.int64)
            src[0::2], src[1::2] = ec.as24(L), ec.as24(R)
            inp = ec.WORK / f"{sname}.raw"
            inp.write_bytes(src.astype("<i4").tobytes())
            for ratio in ratios:
                for mode, mname in ((1, "S950"), (2, "SP12")):
                    res[mname].append(frames(tag, base, hook, stop, org, b0, b1, mode, ratio, inp,
                                             f"{tag}_{sname}_{ratio}_{mname}"))
            if sname == "drum":
                # mode 0 = OT: every pass takes zqrp's stock exit (two passes a frame)
                f = frames(tag, base, hook, stop, org, b0, b1, 0, 1.0, inp, f"{tag}_{sname}_OT")
                stock.append(f)
    print(f"VARISPEED_EMUS DSP prices, {a.form} kernel, payload {a.payload}; datasheet cycles "
          f"(dsp56kEmu opcodecycles), in-cave only\n")
    print(f"{'engine':6} {'frames':>7}  {'instr/sample':>22}  {'cycles/sample':>22}  {'worst frame':>16}")
    print(f"{'':6} {'':>7}  {'median':>10} {'worst':>11}  {'median':>10} {'worst':>11}  {'instr':>7} {'cyc':>8}")
    for mname, runs in res.items():
        allf = np.concatenate(runs)
        i, c = allf[:, 0] / 16.0, allf[:, 1] / 16.0
        print(f"{mname:6} {len(allf):7d}  {np.median(i):10.2f} {i.max():11.2f}  {np.median(c):10.2f} "
              f"{c.max():11.2f}  {allf[:, 0].max():7d} {allf[:, 1].max():8d}")
    s = np.concatenate(stock)
    pi, pc = s[:, 0] / 2.0, s[:, 1] / 2.0
    print(f"\nOT / stock exit (zqrp, every voice pass): {np.median(pi):.1f} instr, {np.median(pc):.1f} "
          f"cycles in the cave per pass (max {pi.max():.1f} / {pc.max():.1f}); + the hook's bsr "
          f"({BSR_CYC} cycles) = {np.median(pc) + BSR_CYC:.1f} cycles per pass")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Where REPITCH_REPEAT98_KYOTI's DSP kernel spends its time, per output sample.

Runs the octabam kernel (rpk_dsp.asm, its tables in SPRING REVERB's X data as
OBKYOTI11/12 place them) in tools/repitch_dsp_engine_check.py's probe with
RK_PCHIST, then prices every executed instruction three ways:

  instr   one per instruction executed (what the probe's .cnt and octabam's
          port count)
  cyc     MODELLED cycles: the emulator's datasheet table (dsp56kEmu
          opcodecycles), summed per executed instruction -- the load audit's
          unit (reference/handoffs/KYOTI_LOAD_AUDIT.md section 2), so its
          budget (about 60-75 per voice for four voices beside stock's
          heaviest FX on core 0) applies directly
  ~hw     an ESTIMATE from octabam docs/firmware/CHIP.md section 2's hardware
          measurements (probe 57): a one-word instruction 2.00 cycles, a
          one-word `(rN+disp)` access 3.98, a two-word displaced one 6.01 --
          modelled as 2 x words, + 2 for a displaced access. A floor; only a
          hardware burn measures the real figure.

    python3 tools/repitch_dsp_profile.py [--mode RPSP|RPS9] [--payload A|B] [--top N]
"""
import argparse
import os
import pathlib
import re
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dsp_xasm                           # noqa: E402
import repitch_dsp_octabam_check as oc    # noqa: E402

ec = oc.ec
ec.WORK = ROOT / "out/repitch_dsp_profile"
RATIOS = (0.75, 1.0, 1.5, 1.99)
DISP = re.compile(r"\(r\d\+[^)]*\)")      # (rN+disp); (rN+nN) is not a displacement


def est_hw(text, nwords):
    return 2 * nwords + (2 if DISP.search(text) else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="RPSP", choices=("RPSP", "RPS9"))
    ap.add_argument("--payload", default="A", choices=("A", "B"))
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    mode = {"RPS9": 1, "RPSP": 2}[a.mode]
    ec.WORK.mkdir(parents=True, exist_ok=True)
    ec.build_probe()
    ec.SCHED = ec.schedule(4000)
    (ec.WORK / "sched.txt").write_text("".join(f"{k:x} {f:x} {lv:x}\n" for k, f, lv in ec.SCHED))
    img = ec.chk.IMG.read_bytes()
    tag, va, ln, base, hook, stop = next(p for p in ec.chk.PAYLOADS if p[0] == a.payload)
    mod, _ = ec.chk.voice_module(img, va, ln, base)
    (ec.WORK / f"voice_{tag}.bin").write_bytes(mod)
    cave, org, entry, ncode, _ = oc.build(tag, "XS")
    _, syms = dsp_xasm.assemble(*oc_source(tag, entry))
    dis = dsp_xasm.disassemble(cave, entry)
    b0, b1 = ec.sc3.bsr_long(hook, entry)
    n_frames = int(1.0 * ec.SR)
    L, R = ec.signals(n_frames)["drum"]
    src = np.empty(2 * n_frames, dtype=np.int64)
    src[0::2], src[1::2] = ec.as24(L), ec.as24(R)
    inp = ec.WORK / "drum.raw"
    inp.write_bytes(src.astype("<i4").tobytes())
    hist, outputs = {}, 0
    for ratio in RATIOS:
        inc = int(round(ratio * (1 << 24)))
        h = ec.WORK / f"hist_{tag}_{a.mode}_{ratio}.txt"
        env = {**os.environ, "RK_PCHIST": str(h)}
        out = ec.run_probe(tag, base, hook, stop, org, b0, b1, mode, inc >> 24, inc & 0xFFFFFF, inp,
                           ec.WORK / f"o_{tag}_{a.mode}_{ratio}.raw", ec.WORK / "c.cnt", env=env)
        outputs += len(out) // 2
        for line in h.read_text().splitlines():
            pc, n, cy = line.split()
            pc, n, cy = int(pc, 16), int(n), int(cy)
            if entry <= pc < entry + ncode:
                n0, c0 = hist.get(pc, (0, 0))
                hist[pc] = (n0 + n, c0 + cy)
    labels = sorted((v, k) for k, v in syms.items() if entry <= v < entry + ncode)

    def region(pc):
        name = "?"
        for v, k in labels:
            if v <= pc:
                name = k
        return name

    rows = []
    for pc, (n, cy) in sorted(hist.items()):
        text, nw = dis.get(pc, ("nop", 1))
        rows.append((pc, region(pc), text, nw, n / outputs, cy / outputs, n * est_hw(text, nw) / outputs))
    tot_i = sum(r[4] for r in rows)
    tot_c = sum(r[5] for r in rows)
    tot_h = sum(r[6] for r in rows)
    print(f"{a.mode}, payload {tag}, drum at {', '.join(map(str, RATIOS))}x: {outputs} output samples")
    print(f"TOTAL  {tot_i:6.1f} instr  {tot_c:6.1f} modelled cycles  ~{tot_h:6.1f} hw-estimate, per output sample\n")
    print(f"{'region':10} {'instr':>7} {'cyc':>7} {'~hw':>7}  share(cyc)")
    by = {}
    for r in rows:
        i, c, h = by.get(r[1], (0, 0, 0))
        by[r[1]] = (i + r[4], c + r[5], h + r[6])
    for name, (i, c, h) in sorted(by.items(), key=lambda x: -x[1][1]):
        if c >= 0.05:
            print(f"{name:10} {i:7.1f} {c:7.1f} {h:7.1f}  {100 * c / tot_c:4.1f}%")
    print(f"\ntop {a.top} instructions by modelled cycles/sample:")
    for pc, name, text, nw, i, c, h in sorted(rows, key=lambda r: -r[5])[:a.top]:
        print(f"  P:{pc:05x} {name:7} {i:5.2f}x {c:6.2f}cyc  {nw}w  {text}")


def oc_source(tag, entry):
    """The source oc.build assembled for the XS placement (for its labels)."""
    src, _, (w1, w2), _, _ = oc.gen.generate()
    b1, b2 = oc.XS_BASES[tag]
    asm = src.replace(oc.MARK, f"${b1:x}").replace(oc.MARK2, f"${b2:x}")
    asm = "\n".join(l.split(";")[0].replace("p:(", "x:(") for l in asm.splitlines()) + "\n"
    return asm, entry


if __name__ == "__main__":
    main()

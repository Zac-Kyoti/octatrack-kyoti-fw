#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""Load-audit runner (KYOTI_LOAD_AUDIT.md): one ot_emu run of a real exported project, FX and
TSTR set by RUNTIME pokes (the Part bytes in the bank blob + the live FX id arrays
0x80000ec4/0x80000ecc) -- nothing on disk is edited -- with each DSP core's four-track loop
(B P:17a..333 = core 1, A P:372..53e = core 0) on the stopwatch, in executed instructions
and in datasheet cycles (opcodecycles.h, no memory stalls), plus optional extra stopwatches.

Setup (once): a SCRATCH copy of octabam (never the shared ~/Documents/octabam), base
36a056c5, with ot_emu_load_audit.patch applied and `cmake -B out/emu -S tools/emu/ot_emu`
built there; images in $LA_SCRATCH/img/<name>.bin, cards (tools/emu/ot_emu/stage_card.py)
in $LA_SCRATCH/img/<card>.img.

  LA_SCRATCH=/path la_run.py NAME --image stock --fx1 DJEQx8 --fx2 DARKx4,DJEQx4 --tstr 6x8

FX lists are 8 entries T1..T8 (names below or ids; 'keep' = the project's own). TSTR the
same (0..6: OFF AUTO NORM BEAT RPCH RPS9 RPSP; 'keep').
"""
import argparse, json, os, pathlib, statistics as st, subprocess, sys

S = pathlib.Path(os.environ.get("LA_SCRATCH", pathlib.Path(__file__).resolve().parent))
EMU = S / "octabam/out/emu/ot_emu"
IMG = {p.stem: p for p in (S / "img").glob("*.bin")}
FX = {"NONE": 0x00, "FLT": 0x04, "SPAT": 0x05, "EQ": 0x0c, "DJEQ": 0x0d, "PHS": 0x10, "FLG": 0x11,
      "CHO": 0x12, "COMB": 0x13, "COMP": 0x18, "LOFI": 0x1c, "DLY": 0x08, "PLT": 0x14, "SPR": 0x15,
      "DARK": 0x16}
BLOB = 0x400e21e0
PART0 = BLOB + 0x8ed80           # RAM part record, part 0 (FX1 ids +0, FX2 ids +8)
PART_STRIDE = 0x18b2
LIVE_FX1, LIVE_FX2 = 0x80000ec4, 0x80000ecc
# core 1 = payload B, tracks 1-4: loop P:17a..333 ; core 0 = payload A, tracks 5-8: P:372..53e
LOOPS = [(1, 0x17a, 0x333), (0, 0x372, 0x53e)]


def expand(spec):
    out = []
    for item in spec.split(","):
        v, _, n = item.partition("x")
        out += [v] * int(n or 1)
    assert len(out) == 8, (spec, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--image", default="stock")
    ap.add_argument("--card", default="otdemo")
    ap.add_argument("--set", default="KYOTI")
    ap.add_argument("--project", default="OTDEMO")
    ap.add_argument("--part", type=int, default=1, help="0-based part the playing pattern uses")
    ap.add_argument("--machine", type=int, default=1, help="0 STATIC / 1 FLEX: which TSTR byte")
    ap.add_argument("--fx1", default="keepx8")
    ap.add_argument("--fx2", default="keepx8")
    ap.add_argument("--tstr", default="keepx8")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--at", type=int, default=2, help="frame after transport start for the pokes")
    ap.add_argument("--extra", default="", help="extra stopwatches core:start:stop,...")
    ap.add_argument("--args", default="", help="extra ot_emu args")
    a = ap.parse_args()
    pk = []
    part = PART0 + a.part * PART_STRIDE
    for t, (f1, f2, ts) in enumerate(zip(expand(a.fx1), expand(a.fx2), expand(a.tstr))):
        for v, partoff, live in ((f1, 0, LIVE_FX1), (f2, 8, LIVE_FX2)):
            if v != "keep":
                i = FX[v] if v in FX else int(v, 0)
                pk += [f"{part + partoff + t:#x}={i:#x}", f"{live + t:#x}={i:#x}"]
        if ts != "keep":
            pk.append(f"{part + 0x1da + 30 * t + 6 * a.machine + 4:#x}={int(ts):#x}")
    run = S / "runs" / a.name
    run.mkdir(parents=True, exist_ok=True)
    sw = run / "sw.txt"
    extra = ",".join(f"{c}:{s:x}:{e:x}" for c, s, e in LOOPS[1:]) + ("," + a.extra if a.extra else "")
    cmd = [str(EMU), "--image", str(IMG[a.image]), "--card", str(S / f"img/{a.card}.img"),
           "--set", a.set, "--project", a.project, "--load-ms", "20000", "--sequencer",
           "--internal-clock", "--frames", str(a.frames), "--dsp", "--main-level", "64",
           "--dsp-stopwatch", "%d:%x:%x" % LOOPS[0]]
    if pk:
        cmd += ["--step", f"{a.at}:poke:" + ";".join(pk)]
    cmd += a.args.split()
    env = {**os.environ, "OT_SW_OUT": str(sw), "OT_SW_EXTRA": extra}
    with (run / "log.txt").open("w") as f:
        subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=3600)
    log = (run / "log.txt").read_text()
    ok = "run ended REACHED" in log
    d = {}; dc = {}
    for line in sw.read_text().split("\n") if sw.exists() else []:
        if line.strip():
            k, v, c = line.split()
            d.setdefault(int(k), []).append(int(v)); dc.setdefault(int(k), []).append(int(c))
    names = ["core1 loop", "core0 loop"] + (a.extra.split(",") if a.extra else [])
    res = dict(name=a.name, image=a.image, fx1=a.fx1, fx2=a.fx2, tstr=a.tstr, reached=ok, watches={})
    for k, v in sorted(d.items()):
        tail = v[-(a.frames - 100):] if len(v) > a.frames - 100 else v
        ct = dc[k][-len(tail):]
        res["watches"][names[k]] = dict(n=len(v), mean=st.mean(tail) / 16, peak=max(tail) / 16,
                                        mean_raw=st.mean(tail), peak_raw=max(tail),
                                        cmean=st.mean(ct) / 16, cpeak=max(ct) / 16)
    (run / "result.json").write_text(json.dumps(res, indent=1))
    (run / "cmd.json").write_text(json.dumps(cmd, indent=1))
    print(a.name, "REACHED" if ok else "NOT REACHED",
          " | ".join(f"{n}: i {w['mean']:.1f}/{w['peak']:.1f} c {w['cmean']:.1f}/{w['cpeak']:.1f}" for n, w in res["watches"].items()))


if __name__ == "__main__":
    main()

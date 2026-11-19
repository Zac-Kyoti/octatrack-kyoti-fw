#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
VARISPEED_EMUS -- a new build against the promoted FINAL one on the equivalence harness's matrix
(tools/varispeed_emus_harness.py: every VARI / AUTO / out-of-range scenario, OT / S950 / SP12, QUAN,
RATE, tempo), comparing what every DSP voice pass receives (x:$40 / y:$40 at the kernel entry, the
OT_VEM_LOG patch) bit for bit. The harness itself compares against the shipped predecessor image,
which this machine may not have; this asks the narrower question a fix to the guard has to answer:
does anything outside a Part switch play differently? (VEM11, 2026-11-18.)

  python3 tools/varispeed_emus_equiv.py [--project otdemo|mmtestdt] [--quick] [--jobs N]
      VEM_IMG_NEW  (default out/mainos_varispeed_emus.bin)
      VEM_IMG_BASE (default out/base_unit.bin: the FINAL unit, kept by hand before the change)
"""
import argparse, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="otdemo")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--frames", type=int, default=3000)
    a = ap.parse_args()
    os.environ["VEM_PROJECT"] = a.project
    os.environ.setdefault("VEM_EMU", str(ROOT / "out/emu/octabam/out/emu/ot_emu"))
    out = ROOT / f"out/vem/equiv_{a.project}"
    os.environ["VEM_OUT"] = str(out)
    sys.path.insert(0, str(ROOT / "tools"))
    import varispeed_emus_harness as H
    imgs = {"new": pathlib.Path(os.environ.get("VEM_IMG_NEW", ROOT / "out/mainos_varispeed_emus.bin")),
            "base": pathlib.Path(os.environ.get("VEM_IMG_BASE", ROOT / "out/base_unit.bin"))}
    sc = {**H.matrix(a.quick), **H.oor_matrix()}
    st = {n: H.scenario_steps(cfg, "new") for n, cfg in sc.items()}
    logs = {}
    for tag, img in imgs.items():
        H.IMAGES["new"] = img.resolve()
        print(f"running {tag} ({img.name}): {len(sc)} scenarios ...", flush=True)
        logs[tag] = H.run("new", st, a.frames, a.jobs, tag)
    bad = 0
    for n in sc:
        la, lb = logs["new"][n], logs["base"][n]
        reached = all("run ended REACHED" in p.read_text() for p in (la, lb))
        r = H.compare(H.parse(str(la) + ".vem"), H.parse(str(lb) + ".vem"), sc[n], f"{n} new vs FINAL")
        w = r.get("whole_run", [])
        same = r["ok"] and reached and not w
        bad += not same
        print(f"  {'IDENTICAL' if same else 'DIFFER   '} {n}"
              + ("" if reached else "  (a run did not reach its frame count)")
              + (f"  whole run: {len(w)} differing pass(es), first {w[:2]}" if w else ""))
    print(f"\n{len(sc) - bad}/{len(sc)} scenarios identical [{a.project}]")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

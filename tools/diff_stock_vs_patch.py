#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 79 continued a nineteenth time. The user reports the flashed DIRECT JUMP build
misbehaves with DIRECT JUMP toggled BOTH ON AND OFF -- frozen transport, audio reduced to
short clicks in time with the trigs. With DJ off, Hooks A/B/C/F are all gated off, so the
cause must be something that runs UNCONDITIONALLY: Hook D (dj_scaleix_fix, every switch
commit), Hook E (dj_abstick, every step tick), patch_trigscale, dj_ptnrel/dj_toggle, or
the PERSONALIZE pea changes.

This is the test that should have existed before ANY flash: with the feature OFF, is the
patched firmware behaviourally identical to stock? It attaches the SAME project to the
stock MAIN_OS section and to the patched one, runs plain playback with no pattern switch
and DJ_MODE left at its default 0, and diffs what the sequencer actually does --
every trig fire (FUN_400a536c, frame+track) and the master STEP over time.

Any divergence here is a bug that a DIRECT-JUMP-specific test can never catch, because
the feature is off in both runs.

Usage:
  python3 tools/diff_stock_vs_patch.py [--project DIR] [--bank N] [--pattern N]
                                       [--frames N] [--patched IMG] [--stock IMG]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
DEMO_PROJECT = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

TRIG_FIRE = 0x400a536c
STEP = 0x800065b6
STEP_IN_PAT = 0x800064f0
ACT_PAT = 0x800065be


def run_image(er, image, project, bank, pattern, frames, tree):
    card, staged = er.stage_project(project, "OCTABAM", None, tree=tree)
    r, rt = er.attach(str(image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000)
    if bank is not None and final_bank != bank:
        final_bank = rt.select_bank_live(bank)
    pat = pattern if pattern is not None else rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    fires = []

    def on_fire(u, addr, size, user):
        fires.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_D0) & 0xff))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=TRIG_FIRE, end=TRIG_FIRE)

    steps = []

    def sample():
        steps.append((rt.frame_count,
                      rt.uc.mem_read(STEP, 1)[0],
                      bytes(rt.uc.mem_read(STEP_IN_PAT, 8))))

    # Actually START the transport -- the first version of this script omitted this and
    # "passed" with ZERO trig fires in both runs, i.e. a vacuously identical result. That
    # is the same class of empty-green validation that let the hardware regression ship.
    # start_transport_live() is the route emu_directjump_dynamic.py itself uses (direct
    # FW_TRANSPORT/FW_START_TRACK; press_play_live() does not advance STEP on a real
    # project here -- see that file's own note at its transport start).
    rt.start_transport_live()
    target = rt.frame_count + frames
    while rt.frame_count < target:
        rt.run(ms=60)
        sample()
    return dict(fires=fires, steps=steps,
                act_pat=rt.uc.mem_read(ACT_PAT, 1)[0], bank=final_bank, pat=pat)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(DEMO_PROJECT))
    ap.add_argument("--bank", type=int, default=None)
    ap.add_argument("--pattern", type=int, default=None,
                    help="0-based pattern to play (default: the project's own)")
    ap.add_argument("--frames", type=int, default=1100)
    ap.add_argument("--patched", default=str(PATCHED))
    ap.add_argument("--stock", default=str(STOCK))
    a = ap.parse_args(argv)

    for p in (a.patched, a.stock):
        if not pathlib.Path(p).exists():
            sys.exit(f"missing image {p}")
    if not pathlib.Path(a.project).is_dir():
        sys.exit(f"missing project dir {a.project}")

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    print(f"{'=' * 70}\nSTOCK  {a.stock}\n{'=' * 70}")
    s = run_image(er, a.stock, a.project, a.bank, a.pattern, a.frames,
                  "out/_emu_diff_stock")
    print(f"  bank={s['bank']} pattern={s['pat']} ACT_PAT={s['act_pat']} "
          f"trig fires={len(s['fires'])}")

    print(f"\n{'=' * 70}\nPATCHED (DIRECT JUMP left OFF)  {a.patched}\n{'=' * 70}")
    p = run_image(er, a.patched, a.project, a.bank, a.pattern, a.frames,
                  "out/_emu_diff_patched")
    print(f"  bank={p['bank']} pattern={p['pat']} ACT_PAT={p['act_pat']} "
          f"trig fires={len(p['fires'])}")

    print(f"\n{'=' * 70}\nDIFF -- with the feature OFF these must be identical\n{'=' * 70}")
    ok_all = True

    if len(s["fires"]) != len(p["fires"]):
        ok_all = False
        print(f"  TRIG FIRE COUNT DIFFERS: stock={len(s['fires'])} patched={len(p['fires'])}")
    first_bad = None
    for i, (sf, pf) in enumerate(zip(s["fires"], p["fires"])):
        if sf != pf:
            first_bad = (i, sf, pf)
            break
    if first_bad:
        ok_all = False
        i, sf, pf = first_bad
        print(f"  FIRST DIVERGING TRIG FIRE at index {i}: "
              f"stock=(frame {sf[0]}, track {sf[1]})  patched=(frame {pf[0]}, track {pf[1]})")
        print("  context (stock | patched):")
        for j in range(max(0, i - 3), min(len(s["fires"]), i + 6)):
            sv = s["fires"][j] if j < len(s["fires"]) else None
            pv = p["fires"][j] if j < len(p["fires"]) else None
            mark = "  <<<" if j == i else ""
            print(f"    [{j:3d}] {str(sv):24s} | {str(pv):24s}{mark}")
    elif len(s["fires"]) == len(p["fires"]):
        print(f"  trig fires: IDENTICAL ({len(s['fires'])} events)")

    sdiff = [(sf, pf) for sf, pf in zip(s["steps"], p["steps"]) if sf != pf]
    if sdiff:
        ok_all = False
        print(f"  STEP / STEP_IN_PAT DIFFERS at {len(sdiff)} sample point(s); first 6:")
        for sf, pf in sdiff[:6]:
            print(f"    frame {sf[0]:7.1f}  stock STEP={sf[1]:3d} "
                  f"STEP_IN_PAT={sf[2].hex()}")
            print(f"    frame {pf[0]:7.1f}  patch STEP={pf[1]:3d} "
                  f"STEP_IN_PAT={pf[2].hex()}")
    else:
        print(f"  STEP / STEP_IN_PAT: IDENTICAL across {len(s['steps'])} sample points")

    print("\n  RESULT: " + ("IDENTICAL -- patch is inert with the feature off"
                            if ok_all else
                            "DIVERGES -- the patch changes stock behaviour with DJ OFF"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

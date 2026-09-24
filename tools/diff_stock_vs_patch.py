#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
With DIRECT JUMP OFF, is the patched firmware behaviourally identical to stock?

This is the test that should have existed before any flash. The user reported the flashed
build misbehaving with DIRECT JUMP toggled BOTH ON and OFF, which a DJ-specific test can
never catch because the feature is off in both runs.

REWRITTEN in Session 79 cont.22. The previous version was unfit twice over:

  1. Its first revision omitted start_transport_live() and "passed" with zero events in
     both runs -- a vacuously identical result, the same empty-green failure mode that let
     the hardware regression ship.
  2. Even after that fix it watched `0x400a536c` under the name TRIG_FIRE. Session 79
     cont.20 (commit a072eaf) measured that instruction: it is reached only when a track's
     step counter completes a FULL CYCLE of its length -- a track-wrap callback, not a
     per-trig or per-step event. At default settings that is ~96 ticks apart, so short runs
     legitimately see zero, and "0 == 0" proved nothing. The long-standing "total-fires=0 /
     the emulator never fires" conclusion was an artefact of this mislabelling:
     tools/diag_seq_activity.py shows the emulator runs the sequencer fine.

So this version compares what the sequencer actually does, per track, over time:
the per-track STEP / ticks-within-step / ARMED / SCALE arrays (16 entries each, audio 0-7
then MIDI 8-15), sampled on a fixed schedule, plus execution counts at named instructions
along the per-track path. All addresses measured -- see NOTES.md Session 79 cont.20/21.

A run that produces no sequencer activity is reported as FAILED, never as identical.

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

# per-track arrays, 16 entries each (audio 0-7, MIDI 8-15)
STEP_ARR = 0x800064D0          # per-track STEP position
TICKS_ARR = 0x800064F0         # per-track ticks elapsed within current step
ARMED_ARR = 0x80006500
SCALE_ARR = 0x8000663E         # per-track scale index
# Our scratch block. Outside the boot re-image (0x80000000 + 0x3e88) AND outside the
# zero-fill (to 0x80004000), therefore UNINITIALISED at power-on on real hardware.
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
MASTER_STEP = 0x800065B6
# Session 79 cont.30: SCALE_IX and BAR_CTR were NOT compared, which is a hole exactly
# where Hook D (dj_scaleix_fix) writes. Hook D is UNCONDITIONAL -- not gated on DJ_MODE --
# so it can change stock behaviour with the feature off, and this gate would have reported
# IDENTICAL regardless. Hook H also seeds BAR_CTR indirectly (it is the low word of the
# long at 0x80006628), though only when armed.
SCALE_IX = 0x8000663D          # master scale index -- Hook D's write target
BAR_CTR = 0x800065B2

PCS = [
    ("audio loop top", 0x400A3CD0),
    ("ARMED gate passed", 0x400A3CDA),
    ("TICKS_IN_STEP++", 0x400A3CE2),
    ("step boundary (wrap)", 0x400A3CF6),
    ("STEP++", 0x400A3D78),
    ("track-wrap callback", 0x400A3D98),
    ("MIDI loop top", 0x400A3DF6),
    ("stock rebuild loop", 0x400A4884),
]


def run_image(er, image, project, bank, pattern, frames, tree, poison=False):
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

    counts = {name: 0 for name, _ in PCS}

    def mk(name):
        def cb(u, addr, size, user):
            counts[name] += 1
        return cb

    for name, pc in PCS:
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(name), begin=pc, end=pc)

    trace = []

    def sample():
        trace.append((
            round(rt.frame_count),
            bytes(rt.uc.mem_read(STEP_ARR, 16)),
            bytes(rt.uc.mem_read(TICKS_ARR, 16)),
            bytes(rt.uc.mem_read(ARMED_ARR, 16)),
            bytes(rt.uc.mem_read(SCALE_ARR, 16)),
            rt.uc.mem_read(MASTER_STEP, 1)[0],
            rt.uc.mem_read(SCALE_IX, 1)[0],
            int.from_bytes(bytes(rt.uc.mem_read(BAR_CTR, 2)), 'big'),
        ))

    # Session 86: POISON the patch's own scratch block before the transport starts.
    #
    # This gate reported IDENTICAL on a build that locked the Octatrack up on hardware
    # within seconds of pressing PLAY, with DIRECT JUMP OFF. The reason it could not see it:
    # Unicorn zero-fills memory, so every uninitialised global reads 0 in the emulator and
    # a hook gated on one never fires. Real hardware does not. kb/memory-map.md:
    # FUN_4000f938 re-images 0x80000000 from ROM for 0x3e88 bytes then zero-fills only to
    # 0x80004000 -- so 0x80006a40.. is beyond BOTH and holds whatever was there at power-on.
    #
    # Filling it with 0xAA makes the emulator model that, and turns "the patch is inert with
    # the feature off" into a claim that survives a cold boot. Applied to the PATCHED run
    # only: these addresses are ours, stock neither reads nor writes them, so poisoning the
    # stock run would prove nothing and only risks confusing the baseline.
    if poison:
        rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))
    sample()
    rt.start_transport_live()
    target = rt.frame_count + frames
    while rt.frame_count < target:
        rt.run(ms=60)
        sample()

    moved = sum(1 for i in range(16)
                if len({t[1][i] for t in trace}) > 1
                or len({t[2][i] for t in trace}) > 1)
    return dict(counts=counts, trace=trace, bank=final_bank, pat=pat, moved=moved)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(DEMO_PROJECT))
    ap.add_argument("--bank", type=int, default=None)
    ap.add_argument("--pattern", type=int, default=None)
    ap.add_argument("--frames", type=int, default=6000,
                    help="default is long enough to cross a full 16-step pattern at 1x")
    ap.add_argument("--patched", default=str(PATCHED))
    ap.add_argument("--no-poison", action="store_true",
                    help="do NOT pre-fill our scratch block with 0xAA before the transport "
                         "starts. Poisoning is ON by default: Unicorn zero-fills memory, so "
                         "without it every uninitialised global reads 0 and a hook gated on "
                         "one can never fire -- which is exactly how this gate passed a "
                         "build that locked up real hardware seconds after PLAY.")
    ap.add_argument("--stock", default=str(STOCK))
    # Two concurrent invocations sharing one staging tree collide with FileExistsError --
    # a trap this repo already hit with the per-bank project scanners. Give every run its
    # own prefix so a second comparison can be launched while the first is still going.
    ap.add_argument("--tree-prefix", default="out/_emu_diff",
                    help="staging tree prefix; use a distinct one per concurrent run")
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

    bar = "=" * 70
    print(f"{bar}\nSTOCK  {a.stock}\n{bar}")
    s = run_image(er, a.stock, a.project, a.bank, a.pattern, a.frames,
                  a.tree_prefix + "_stock")
    print(f"  bank={s['bank']} pattern={s['pat']} samples={len(s['trace'])} "
          f"tracks-with-movement={s['moved']}/16")

    label = "PATCHED (DIRECT JUMP left OFF"
    label += ", scratch POISONED 0xAA)" if not a.no_poison else ")"
    print(f"\n{bar}\n{label}  {a.patched}\n{bar}")
    try:
        p = run_image(er, a.patched, a.project, a.bank, a.pattern, a.frames,
                      a.tree_prefix + "_patched", poison=not a.no_poison)
    except Exception as exc:
        # Session 86: a fault during the PATCHED run IS the result, not a tooling error.
        # The build that locked up real hardware raises UC_ERR_READ_UNMAPPED here under
        # poisoning -- the wild-address read its uninitialised gate flag let through.
        # Report it as a failure rather than a traceback, or the next person reads a crashed
        # gate as "the tool is broken" and re-runs it with --no-poison.
        print(f"\n  ** THE PATCHED IMAGE FAULTED: {type(exc).__name__}: {exc}")
        print("  ** With the feature OFF and the scratch block poisoned, the patch executed "
              "and faulted.")
        print("  ** This is the cold-boot failure mode: globals at 0x80006a40.. are NOT "
              "cleared by stock's boot\n  ** (re-image covers 0x80000000+0x3e88, zero-fill "
              "stops at 0x80004000), so any hook gated\n  ** on one of them can fire on the "
              "first tick with garbage. Gate it on DJ_MODE, which IS\n  ** deterministic at "
              "boot, and clear the flag from dj_a every tick.")
        print("\n  RESULT: FAILED -- patch is NOT inert with the feature off")
        return 1
    print(f"  bank={p['bank']} pattern={p['pat']} samples={len(p['trace'])} "
          f"tracks-with-movement={p['moved']}/16")

    print(f"\n{bar}\nDIFF -- with the feature OFF these must be identical\n{bar}")

    # Liveness precondition FIRST. Without it, any "identical" verdict is vacuous, which
    # is precisely how the last regression got a green light.
    if s["counts"]["audio loop top"] == 0 or p["counts"]["audio loop top"] == 0:
        print("  FAILED: the per-track sequencer loop never executed in one or both runs.")
        print("  No comparison is meaningful. Fix the harness before trusting any result.")
        return 2
    if s["moved"] == 0 or p["moved"] == 0:
        print("  FAILED: no per-track counter moved in one or both runs -- the sequencer "
              "produced no activity to compare.")
        return 2

    ok_all = True

    print("  instruction execution counts:")
    for name, _ in PCS:
        sv, pv = s["counts"][name], p["counts"][name]
        mark = "" if sv == pv else "   <<< DIFFERS"
        if sv != pv:
            ok_all = False
        print(f"    {name:24s} stock={sv:8d}  patched={pv:8d}{mark}")

    names = ("STEP", "TICKS", "ARMED", "SCALE")
    n = min(len(s["trace"]), len(p["trace"]))
    first_bad = None
    for i in range(n):
        st, pt = s["trace"][i], p["trace"][i]
        for k in range(1, 5):
            if st[k] != pt[k]:
                first_bad = (i, k, st, pt)
                break
        for k in (5, 6, 7):
            if first_bad is None and st[k] != pt[k]:
                first_bad = (i, k, st, pt)
        if first_bad:
            break

    if first_bad:
        ok_all = False
        i, k, st, pt = first_bad
        label = (names[k - 1] if k <= 4 else
                 {5: "master STEP", 6: "SCALE_IX", 7: "BAR_CTR"}[k])
        print(f"\n  FIRST DIVERGENCE at sample {i} (frame {st[0]}) in {label}:")
        if k <= 4:
            print(f"    stock   {st[k].hex()}")
            print(f"    patched {pt[k].hex()}")
            for t in range(16):
                if st[k][t] != pt[k][t]:
                    print(f"      track {t:2d}: stock={st[k][t]:3d}  patched={pt[k][t]:3d}")
        else:
            print(f"    stock={st[5]}  patched={pt[5]}")
    else:
        print(f"\n  per-track STEP/TICKS/ARMED/SCALE, master STEP, SCALE_IX, BAR_CTR: IDENTICAL "
              f"across {n} samples")

    print("\n  RESULT: " + ("IDENTICAL -- patch is inert with the feature off"
                            if ok_all else
                            "DIVERGES -- the patch changes stock behaviour with DJ OFF"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

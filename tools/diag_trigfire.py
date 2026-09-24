#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Does an armed DIRECT JUMP commit fire a track TWICE?  (Session 87)

Hardware report on the Session 86 build: with DIRECT JUMP on, trigs sound DOUBLED, and the
doubled copy drifts slightly in phase every pattern cycle. The DJ-ON-idle gate
(diff_stock_vs_patch.py --dj-on) is IDENTICAL to stock, so nothing is running ambiently --
the fault is in the commit path.

`0x400a536c` is called from exactly two places in the sequencer:
  0x400a3d98  the per-tick per-track loop, when that track's STEP counter WRAPS to 0
  0x400a4bde  the commit tail, when CNTDN_TBL[t] counts down to 0

So a doubled voice should show up as two calls for one track close together, and a drifting
double as a pair whose spacing changes cycle to cycle. This logs every call with its track
argument and the clock tick it happened on, for a run that commits an armed DIRECT JUMP, and
for a stock baseline that does not.

The suspicion being tested: stock's commit tail seeds STEP_ARR[t] at 0x400a4be6 from ITS OWN
tick-domain rebuild and arms CNTDN_TBL[t] against that; Hook P then overwrites STEP_ARR[t]
with AR's step-domain value at 0x400a4d36. If those disagree the track can wrap at a moment
stock did not intend, on top of the commit's own fire.

Usage:
  python3 tools/diag_trigfire.py [--image F] [--from-pattern N] [--to-pattern N] [--no-switch]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

DJ_MODE = 0x800000D8
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
ACT_PAT = 0x800065BE
STEP_ARR = 0x800064D0
TICK_PC = 0x400A3FDC
FIRE_PC = 0x400A536C          # reached from 0x400a3d98 (track wrap) and 0x400a4bde (commit)
WRAP_CALL = 0x400A3D98
COMMIT_CALL = 0x400A4BDE


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--from-pattern", type=int, default=6)
    ap.add_argument("--to-pattern", type=int, default=7)
    ap.add_argument("--dj", type=int, default=1)
    ap.add_argument("--no-switch", action="store_true", help="baseline: never cue a change")
    ap.add_argument("--pre", type=int, default=40)
    ap.add_argument("--dj-on-tick", type=int, default=-1,
                    help="Session 87: instead of DJ_MODE=1 from before the transport "
                         "starts (every earlier test here does that), start the transport "
                         "with DJ_MODE=0 and flip it to 1 at this clock tick, mid-playback, "
                         "matching what actually happens when a user presses the real "
                         "[PTN]+[YES] combo while a pattern is already looping. Implies "
                         "--no-switch is likely wanted too, to isolate 'enabling the "
                         "feature' from 'enabling it and also switching'.")
    ap.add_argument("--frames", type=int, default=14000)
    ap.add_argument("--tree", default="out/_emu_trigfire")
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
    bank = loaded[3]
    rt.seq_select_live(bank, a.from_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    initial_dj = 0 if a.dj_on_tick >= 0 else a.dj
    rt.uc.mem_write(DJ_MODE, initial_dj.to_bytes(4, "big"))

    st = dict(tick=0, cued=None, fires=[], acts=[], site=None, dj_flipped=None)

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if a.dj_on_tick >= 0 and st["dj_flipped"] is None and st["tick"] >= a.dj_on_tick:
            u.mem_write(DJ_MODE, (1).to_bytes(4, "big"))
            st["dj_flipped"] = st["tick"]
        if not a.no_switch and st["cued"] is None and st["tick"] >= a.pre:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
        ap_ = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap_:
            st["acts"].append((st["tick"], ap_))

    def mk_site(name):
        def h(u, addr, size, user):
            st["site"] = name
        return h

    def on_fire(u, addr, size, user):
        # the track index is the single long argument pushed before the jsr. Session 87:
        # this used to catch-and-hide any read failure as track=-1 -- which is what
        # happened on every single call in the first run, because the register name was
        # wrong (UC_M68K_REG_SP does not exist in this binding; it is UC_M68K_REG_A7). A
        # silently-swallowed exception here reads as "firmware data", not "broken tool".
        # Fail loud instead.
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        trk = int.from_bytes(bytes(u.mem_read(sp + 4, 4)), "big")
        st["fires"].append((st["tick"], trk, st["site"]))
        st["site"] = None

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk_site("wrap"), begin=WRAP_CALL, end=WRAP_CALL)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk_site("commit"), begin=COMMIT_CALL, end=COMMIT_CALL)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=FIRE_PC, end=FIRE_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    print(f"image   {a.image}")
    print(f"project {a.project}  bank {bank}  {a.from_pattern} -> "
          f"{'(no switch)' if a.no_switch else a.to_pattern}   DJ_MODE={a.dj}")
    print(f"ticks={st['tick']}  DJ_MODE flipped ON at tick={st['dj_flipped']}  "
          f"cued={st['cued']}  ACT_PAT changes {st['acts']}")

    print(f"\n0x400a536c calls: {len(st['fires'])}")
    print("  (tick, track, callsite)")
    for f in st["fires"][:60]:
        print(f"    {f}")

    # per-track spacing: a doubled voice shows as a short gap inside an otherwise regular one
    print("\nper-track call ticks and gaps:")
    for t in range(16):
        ticks = [f[0] for f in st["fires"] if f[1] == t]
        if not ticks:
            continue
        gaps = [b - aa for aa, b in zip(ticks, ticks[1:])]
        kind = f"T{t}" if t < 8 else f"M{t-8}"
        print(f"  {kind:>3}: ticks {ticks[:14]}")
        print(f"       gaps  {gaps[:13]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

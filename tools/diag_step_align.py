#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: after a DIRECT JUMP commit that CHANGES THE MASTER SCALE, do the track's step
boundaries still land on master step boundaries, or off-grid ("step-fractional")?

Hardware report on V5: tests 1 (1x baseline) and 2 (master 2x, no switch) pass, but jumping
between a 1x-master pattern and a 2x-master pattern still puts the sequence into a
"step-fractional state".

Mechanism under test. Master 2x = 3 ticks/step, a 1x track = 6 ticks/step, so the track
advances once every TWO master steps. Stock's commit tail zeroes TICKS_IN_STEP[t]
(0x400a4bf0), restarting the track's step at the commit instant. If the commit lands on a
master step of the wrong parity, every later track step sits half a track-step off the
master's grid -- permanently, with no drift, which is exactly what "fractional but steady"
sounds like.

Measurement: for each track advance (STEP_ARR[t] written by the per-tick advance at
0x400a3d78) record the master ticks-within-step counter TICK_CTR (0x800065b6) at that
instant. A track locked to the master grid advances at the SAME TICK_CTR value every time.
A change in that value across the commit is the bug, and its size is the fractional offset.

Usage:
  python3 tools/diag_step_align.py --project DIR --pattern N --to-pattern M [--image IMG]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
ADVANCE_PC = 0x400A3D78        # STEP_ARR[t] += 1, the per-tick advance
TAIL_PC = 0x400A4BE6           # commit reposition
TICK_CTR = 0x800065B6
SCALE_IX = 0x8000663D
STEP_ARR = 0x800064D0
LEN_TBL = 0x400ABA50
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--jumps", type=int, default=6)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--image", default=str(V5))
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_al_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1).to_bytes(4, "big"))
    rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, cued=None, commit=None, adv=[], six=[], njump=0, commits=[])
    targets = [a.to_pattern, a.pattern]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1
            if st["cued"] is None:
                st["cued"] = st["tick"]
        s = bytes(u.mem_read(SCALE_IX, 1))[0]
        if not st["six"] or st["six"][-1][1] != s:
            st["six"].append((st["tick"], s))

    def on_write(u, access, addr, size, value, user):
        if addr != STEP_ARR + a.track:
            return
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        tc = bytes(u.mem_read(TICK_CTR, 1))[0]
        if pc == ADVANCE_PC:
            ms = int.from_bytes(bytes(u.mem_read(0x800065B2, 2)), "big")
            st["adv"].append((st["tick"], tc, value & 0xFF, ms))
        elif pc == TAIL_PC:
            if st["commit"] is None:
                st["commit"] = st["tick"]
            if not st["commits"] or st["commits"][-1] != st["tick"]:
                st["commits"].append(st["tick"])

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP_ARR + a.track,
                   end=STEP_ARR + a.track + 1)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(8)]
    print(f"image={pathlib.Path(a.image).name}  {a.pattern} -> {a.to_pattern}  "
          f"track {a.track}  cued=t{st['cued']}  commit=t{st['commit']}")
    print(f"master SCALE_IX timeline (tick, idx, tps): "
          f"{[(t, s, tbl[s] if s < 8 else '?') for t, s in st['six']]}")
    if not st["adv"]:
        print("FAILED: no track advances observed -- run proves nothing")
        return 2
    ct = st["commit"]
    print(f"\ntrack {a.track} advances -- (tick, TICK_CTR at advance, new step):")
    for tk, tc, v, ms in st["adv"]:
        mark = "  <-- COMMIT was here" if ct and tk == ct else ""
        when = "before" if ct and tk < ct else "after "
        print(f"   t{tk:4d}  TICK_CTR={tc:2d}  MASTER_STEP={ms:3d}  step={v:3d}  [{when}]{mark}")
    # THE question: is each track advance on the same absolute-tick grid throughout?
    # A track at tps N must advance at ticks congruent mod N. If the congruence class
    # CHANGES at a commit, that commit re-phased the track off absolute time -- which is
    # the "fractional relative to the metronome" report.
    tps_t = 6
    print(f"\n  advance ticks mod {tps_t}, segmented by commit "
          f"(commits at {st['commits']}):")
    # Label each segment by the commit that OPENS it, not the one that closes it. The
    # previous form pushed the accumulated list when it saw the FIRST advance past a
    # commit, so every row was labelled with the commit that came after its contents.
    import bisect
    buckets = {}
    for tk, _tc, _v, _m in st["adv"]:
        k = bisect.bisect_right(st["commits"], tk)
        buckets.setdefault(k, []).append(tk)
    segs = [((st["commits"][k - 1] if k else None), buckets[k]) for k in sorted(buckets)]
    prev_class = None
    for after_commit, ticks in segs:
        if not ticks:
            continue
        classes = sorted({t % tps_t for t in ticks})
        tag = "before 1st" if after_commit is None else f"after t{after_commit}"
        shift = ""
        if prev_class is not None and classes != prev_class:
            shift = f"   <-- RE-PHASED (was {prev_class}, now {classes})"
        print(f"    {tag:>12}: ticks {ticks[:6]}{'...' if len(ticks) > 6 else ''} "
              f"-> mod {tps_t} = {classes}{shift}")
        prev_class = classes
    if ct:
        pre = [tc for tk, tc, _v, _m in st["adv"] if tk < ct]
        post = [tc for tk, tc, _v, _m in st["adv"] if tk > ct]
        # The question that matters: at the BAR boundary (MASTER_STEP wrapping to 0), is
        # the track at the start of its own sequence? Compare the (MASTER_STEP, step) pairs.
        print("\n  (MASTER_STEP -> track step) pairs, which must repeat identically each bar:")
        prep = [(m, v) for tk, _tc, v, m in st["adv"] if tk < ct]
        postp = [(m, v) for tk, _tc, v, m in st["adv"] if tk > ct]
        print(f"    before commit: {prep}")
        print(f"    after  commit: {postp[:10]}")
        print(f"\n  TICK_CTR at advance, BEFORE commit: {sorted(set(pre))}")
        print(f"  TICK_CTR at advance, AFTER  commit: {sorted(set(post))}")
        if len(set(post)) > 1:
            print("  -> NOT LOCKED: the track advances at varying sub-step positions")
        elif pre and post and set(pre) != set(post):
            print(f"  -> OFF-GRID: locked, but shifted from {sorted(set(pre))} to "
                  f"{sorted(set(post))} by the commit (this is the fractional offset)")
        elif post:
            print("  -> ALIGNED: same sub-step position before and after the commit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

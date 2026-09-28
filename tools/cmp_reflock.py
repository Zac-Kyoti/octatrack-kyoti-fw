#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 107/108 -- the V7 REFERENCE-LOCK oracle, comparer half (see diag_reflock.py).

  python3 tools/cmp_reflock.py RUN.json REF_A.json [REF_B.json ...]

For every segment of RUN during which ACT_PAT == P and a reference for P was given:
  * CLOCK   : metronome counters (beat-in-bar, tick-in-beat) must equal the reference's at
              every tick -- otherwise the two runs are not on the same clock and nothing
              else below means anything.
  * STATE   : the full engine vector (per-track STEP/STEP-1/TICKS/ARMED/CNTDN/RELOAD/SCALE,
              master step/tick/scale, first-fire/hold masks) vs the reference, per tick.
              Reports the first tick from which the segment is identical to the end ("locked
              from"), or LOCK FAILED.
  * SHIFT   : when not locked, the tick offset d that best explains the segment
              (RUN(t) == REF(t+d) for per-track STEP+TICKS): d = +6 at 1x = "one step late"
              = the author's audible step-shift.  Reported in ticks and in steps.
  * FIRES   : (track, fire-tick) events written into the audible fire table 0x80001904
              for fire times inside the segment, RUN vs REF (slots ignored).  EXTRA = RUN
              plays something the reference does not (e.g. the outgoing pattern's pending
              event -- the primacy rule says it must be purged); MISSING = the reverse.
"""
import collections
import json
import statistics
import sys

TICK_UNITS = 0x285FF0
STATE_KEYS_ARR = ["step", "step_m1", "ticks", "armed", "cntdn", "reload", "trk_scale"]
STATE_KEYS_SCL = ["m_step", "m_tick", "scale_ix", "ff_mask", "hold_mask"]


def load(p):
    d = json.load(open(p))
    d["by_t"] = {s["t"]: s for s in d["states"]}
    return d


def fire_events(d, t0, t1):
    """(track, fire_tick) for fire-table writes whose fire time lies in [t0, t1)."""
    sclk = {s["t"]: s["sclk"] for s in d["states"]}
    ev = collections.Counter()
    for t, idx, val, pc in d["fires"]:
        if t not in sclk:
            continue
        rel = ((val - sclk[t]) & 0xFFFFFFFF)
        if rel & 0x80000000:
            rel -= 1 << 32
        ft = t + rel / TICK_UNITS
        if t0 <= ft < t1:
            ev[(idx % 8, round(ft, 2))] += 1
    return ev


def vec(s, keys_arr, keys_scl):
    return tuple(tuple(s[k]) for k in keys_arr) + tuple(s[k] for k in keys_scl)


def main(argv):
    run = load(argv[0])
    refs = {}
    for p in argv[1:]:
        r = load(p)
        refs[r["meta"]["start"]] = r
    print(f"RUN {argv[0]}: start={run['meta']['start']} dj={run['meta']['dj']} "
          f"cues={run['cues']} commits={run['commits']}")
    # segments by ACT_PAT
    segs, cur, t0 = [], None, None
    ts = sorted(run["by_t"])
    for t in ts:
        p = run["by_t"][t]["act_pat"]
        if p != cur:
            if cur is not None:
                segs.append((cur, t0, t))
            cur, t0 = p, t
    segs.append((cur, t0, ts[-1] + 1))

    worst = "PASS"
    for pat, a, b in segs:
        ref = refs.get(pat)
        print(f"\n-- segment pattern {pat}  ticks [{a},{b})  ({b - a} ticks)")
        if ref is None:
            print("   (no reference for this pattern)")
            continue
        clock_bad = [t for t in range(a, b) if t in ref["by_t"] and
                     (run["by_t"][t]["met_beat"], run["by_t"][t]["met_tick"]) !=
                     (ref["by_t"][t]["met_beat"], ref["by_t"][t]["met_tick"])]
        print(f"   CLOCK : {'OK' if not clock_bad else f'MISMATCH at {len(clock_bad)} ticks, first t{clock_bad[0]}'}")
        eq = [t in ref["by_t"] and vec(run["by_t"][t], STATE_KEYS_ARR, STATE_KEYS_SCL) ==
              vec(ref["by_t"][t], STATE_KEYS_ARR, STATE_KEYS_SCL) for t in range(a, b)]
        locked_from = None
        for i in range(len(eq) - 1, -1, -1):
            if not eq[i]:
                break
            locked_from = a + i
        if locked_from is not None and locked_from <= a + 1:
            print(f"   STATE : LOCKED from t{locked_from} (segment start t{a}) -- identical to the reference")
        elif locked_from is not None:
            print(f"   STATE : locked only from t{locked_from} ({locked_from - a} ticks after segment start)")
            worst = "FAIL" if worst == "PASS" else worst
        else:
            worst = "FAIL"
            first_bad = a + eq.index(False)
            sr, sf = run["by_t"][first_bad], ref["by_t"][first_bad]
            diff = [k for k in STATE_KEYS_ARR + STATE_KEYS_SCL if sr[k] != sf[k]]
            print(f"   STATE : LOCK FAILED -- first mismatch t{first_bad}, fields {diff}")
            print(f"           run step[0..7]={sr['step'][:8]} ticks={sr['ticks'][:8]} m_step={sr['m_step']}")
            print(f"           ref step[0..7]={sf['step'][:8]} ticks={sf['ticks'][:8]} m_step={sf['m_step']}")
        # shift diagnosis on per-track STEP+TICKS (audio tracks)
        best = None
        for d in range(-120, 121):
            n = m = 0
            for t in range(a + 2, b):
                rs = ref["by_t"].get(t + d)
                if rs is None:
                    continue
                n += 1
                m += (run["by_t"][t]["step"][:8], run["by_t"][t]["ticks"][:8]) == (rs["step"][:8], rs["ticks"][:8])
            if n >= max(6, (b - a) // 3):
                score = m / n
                if best is None or score > best[1] or (score == best[1] and abs(d) < abs(best[0])):
                    best = (d, score, n)
        if best:
            tps = 6
            d, sc, n = best
            tag = "IN PHASE" if d == 0 else f"SHIFTED {d:+d} ticks = {d / tps:+.2f} steps at 1x"
            print(f"   SHIFT : best fit d={d:+d} ({sc:.0%} of {n} ticks match) -> {tag}")
        rf, ff = fire_events(run, a, b), fire_events(ref, a, b)
        extra, missing = rf - ff, ff - rf
        print(f"   FIRES : run {sum(rf.values())} ref {sum(ff.values())}  extra {sum(extra.values())}  missing {sum(missing.values())}")
        for tag_, c in (("extra", extra), ("missing", missing)):
            if c:
                print(f"           {tag_}: {sorted(c.elements())[:10]}{' ...' if sum(c.values()) > 10 else ''}")
        if extra or missing:
            worst = "FAIL"
    print(f"\nVERDICT: {worst}")
    return 0 if worst == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

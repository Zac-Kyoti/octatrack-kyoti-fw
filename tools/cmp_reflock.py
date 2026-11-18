#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Session 107/108 -- the V7 REFERENCE-LOCK oracle, comparer half (see diag_reflock.py).

  python3 tools/cmp_reflock.py [--cond] RUN.json REF_A.json [REF_B.json ...] [--ref-for P=REF.json ...]

A reference is keyed by the pattern it starts on; --ref-for P=REF.json keys it by P instead (a RESTART
reference: PLAY on A, a stock change straight to P -- RUN's P segment is compared tick by tick with it).

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
  * PENDING : what will actually SOUND.  Per tick, every live event (slot bit set in the
              track's mask -- stock's own cancellation rule, 0x400a43b6) in the two audio
              tables and the MIDI table, as (table, track, fire-tick, pattern, step), the
              content taken from the event builder's own arguments.  RUN vs REF at every
              tick of the segment.  EXTRA = RUN will play something the reference will not
              (e.g. the outgoing pattern's leftover -- primacy says purge it); MISSING = the
              reverse.  A landing that fires the right tick with the wrong step shows here.
  * COND    : (--cond, runs recorded with diag_reflock --cond) the trig-condition state: every
              track's A:B pass counter 0x46107918 vs the reference at every tick of the segment
              (part of the verdict), and the latch bytes 0x46107959 / 69 (FILL) / 79 (PRE)
              reported beside it (the latches are part of the verdict too, unless --cond-cnt).
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


def pending(d):
    """tick -> frozenset of live events (kind, trk, fire_tick, pat, step)."""
    calls = sorted(d.get("calls", []))
    content, ci, out = {}, 0, {}
    for s in d["states"]:
        t = s["t"]
        # a builder call runs in E, BEFORE the phase-G hook advances the tick label, so a
        # call made in the ISR sampled as t is labelled t-1: it belongs to samples > label.
        while ci < len(calls) and calls[ci][0] < t:
            ct, kind, trk, bank, pat, step, slot = calls[ci]
            content[(kind, trk % 8, slot)] = (pat, step)
            ci += 1
        ev = set()
        for kind in ("a", "b", "m"):
            if "ev_" + kind not in s:
                continue
            for trk in range(8):
                for slot in range(3):
                    if not (s["mask_" + kind][trk] >> slot) & 1:
                        continue
                    rel = (s["ev_" + kind][trk + 8 * slot] - s["sclk"]) & 0xFFFFFFFF
                    if rel & 0x80000000:
                        rel -= 1 << 32
                    c = content.get(("a" if kind == "b" else kind, trk, slot), (None, None))
                    ev.add((kind, trk, round(t + rel / TICK_UNITS, 2)) + c)
        out[t] = frozenset(ev)
    return out


def vec(s, keys_arr, keys_scl):
    return tuple(tuple(s[k]) for k in keys_arr) + tuple(s[k] for k in keys_scl)


def cond_check(run, ref, a, b, keys):
    """first tick from which RUN == REF on `keys` to the segment's end, and the first mismatch."""
    eq = [t in ref["by_t"] and all(run["by_t"][t][k] == ref["by_t"][t][k] for k in keys)
          for t in range(a, b)]
    locked_from = None
    for i in range(len(eq) - 1, -1, -1):
        if not eq[i]:
            break
        locked_from = a + i
    first_bad = a + eq.index(False) if False in eq else None
    return locked_from, first_bad


def main(argv):
    cond = "--cond" in argv or "--cond-cnt" in argv
    cond_latch = "--cond" in argv
    argv = [x for x in argv if x not in ("--cond", "--cond-cnt")]
    ref_for = []
    while "--ref-for" in argv:
        i = argv.index("--ref-for")
        pat, path = argv[i + 1].split("=", 1)
        ref_for.append((int(pat), path))
        del argv[i:i + 2]
    run = load(argv[0])
    refs = {}
    for p in argv[1:]:
        r = load(p)
        refs[r["meta"]["start"]] = r
    for pat, path in ref_for:
        refs[pat] = load(path)
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
    run_pend = pending(run)
    ref_pend = {k: pending(r) for k, r in refs.items()}
    for pat, a, b in segs:
        ref = refs.get(pat)
        print(f"\n-- segment pattern {pat}  ticks [{a},{b})  ({b - a} ticks)")
        if ref is None:
            print("   (no reference for this pattern)")
            continue
        last_ref = max(ref["by_t"])
        if b > last_ref + 1:
            print(f"   (reference ends at t{last_ref}: segment compared up to there)")
            b = last_ref + 1
        if b <= a:
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
        if cond:
            if "cond" not in run["states"][0] or "cond" not in ref["states"][0]:
                print("   COND  : not recorded (diag_reflock --cond) -- FAIL")
                worst = "FAIL"
            else:
                for keys, name, gating in ((["cond"], "A:B counters", True),
                                           (["c59", "c69"], "FILL latches 59/69", cond_latch),
                                           (["c79"], "PRE latch 79", cond_latch)):
                    lf, fb = cond_check(run, ref, a, b, keys)
                    if lf is not None and lf <= a + 1:
                        print(f"   COND  : {name}: LOCKED from t{lf} (segment start t{a})")
                        continue
                    sr, sf = run["by_t"][fb], ref["by_t"][fb]
                    k = keys[0] if sr[keys[0]] != sf[keys[0]] else keys[-1]
                    print(f"   COND  : {name}: " + (f"locked only from t{lf}" if lf is not None else "LOCK FAILED")
                          + f" -- first mismatch t{fb}: run {k}={sr[k]} ref {sf[k]}"
                          + ("" if gating else "   (reported, not graded)"))
                    if gating:
                        worst = "FAIL"
        if run["states"] and "ev_a" in run["states"][0] and "ev_a" in ref["states"][0]:
            rp = ref_pend[pat]
            bad_t = [t for t in range(a, b) if t in rp and run_pend.get(t) != rp[t]]
            extra = set().union(*[run_pend[t] - rp[t] for t in bad_t]) if bad_t else set()
            missing = set().union(*[rp[t] - run_pend[t] for t in bad_t]) if bad_t else set()
            if not bad_t:
                print(f"   PENDING: IDENTICAL at every tick of the segment (what will sound, with content)")
            else:
                print(f"   PENDING: {len(bad_t)} ticks differ (first t{bad_t[0]}, last t{bad_t[-1]}); "
                      f"distinct extra {len(extra)} missing {len(missing)}")
                for tag_, c in (("extra", extra), ("missing", missing)):
                    if c:
                        print(f"           {tag_}: {sorted(c, key=lambda e: (e[2], e[0], e[1]))[:8]}"
                              f"{' ...' if len(c) > 8 else ''}")
                worst = "FAIL"
        else:
            rf, ff = fire_events(run, a, b), fire_events(ref, a, b)
            extra, missing = rf - ff, ff - rf
            print(f"   FIRES (legacy, written events): run {sum(rf.values())} ref {sum(ff.values())}  "
                  f"extra {sum(extra.values())}  missing {sum(missing.values())}")
            if extra or missing:
                worst = "FAIL"
    print(f"\nVERDICT: {worst}")
    return 0 if worst == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

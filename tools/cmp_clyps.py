#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS phase 1 -- the landing oracle, comparer half (see diag_clyps_landing.py).

  python3 tools/cmp_clyps.py A.json B.json

A = the candidate (harness-side clyp), B = the reference (stock change to a pattern that
equals the playing one except in the clyp's track). Per tick, both runs' engine state (every
track's STEP/STEP-1/TICKS/ARMED/CNTDN/RELOAD/SCALE, master step/tick/scale, first-fire/hold
masks) and their live events (what will sound, with the builder's step as content) are
compared. The pattern number is ignored: B must play another slot to hold the same data.
PASS = identical from the landing on, and identical before it (same clock, same playback).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cmp_reflock import STATE_KEYS_ARR, STATE_KEYS_SCL, load, pending, vec  # noqa: E402


def strip(evs):
    return frozenset((k, trk, ft, step) for k, trk, ft, _pat, step in evs)


def main(argv):
    A, B = load(argv[0]), load(argv[1])
    print(f"A {argv[0]}: clyp={A.get('clyp')} commits={A['commits'][:6]}")
    print(f"B {argv[1]}: cues={B['cues']} commits={B['commits'][:6]}")
    landB = next((t for t in sorted(B["by_t"]) if B["by_t"][t]["act_pat"] != B["by_t"][1]["act_pat"]), None)
    landA = A["clyp"][0] if A.get("clyp") else None
    print(f"landing: A clyp applied at t{landA}; B act_pat changes at t{landB}")
    pa, pb = pending(A), pending(B)
    ts = sorted(set(A["by_t"]) & set(B["by_t"]))
    bad = []
    for t in ts:
        sa, sb = A["by_t"][t], B["by_t"][t]
        fs = [k for k in STATE_KEYS_ARR + STATE_KEYS_SCL if sa[k] != sb[k]]
        if (sa["met_beat"], sa["met_tick"]) != (sb["met_beat"], sb["met_tick"]):
            fs.append("CLOCK")
        if strip(pa[t]) != strip(pb[t]):
            fs.append("PENDING")
        if fs:
            bad.append((t, fs))
    if not bad:
        print(f"IDENTICAL at all {len(ts)} ticks (t{ts[0]}..t{ts[-1]})")
        print("VERDICT: PASS")
        return 0
    first, last = bad[0][0], bad[-1][0]
    print(f"{len(bad)} ticks differ: first t{first}, last t{last}")
    for t, fs in bad[:12]:
        sa, sb = A["by_t"][t], B["by_t"][t]
        print(f"  t{t}: {fs}")
        for k in STATE_KEYS_ARR:
            if k in fs:
                trk = [i for i in range(16) if sa[k][i] != sb[k][i]]
                print(f"      {k}: tracks {trk}  A={[sa[k][i] for i in trk]}  B={[sb[k][i] for i in trk]}")
        if "PENDING" in fs:
            ea, eb = strip(pa[t]), strip(pb[t])
            print(f"      A only: {sorted(ea - eb)[:6]}")
            print(f"      B only: {sorted(eb - ea)[:6]}")
    locked = last + 1 if last < ts[-1] else None
    print(f"locked from t{locked}" if locked else "never locks")
    print("VERDICT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

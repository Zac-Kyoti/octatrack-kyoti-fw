#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT JUMP V7.3 (2026-11-16, the author's option (b)): the time origin is the last RESTART -- PLAY or a stock
pattern switch -- for the landing and the trig conditions, the moment RELOAD_FROM_PROJECT (rl_creset) and Clyps
(cl_creset) count from. This grades the two counts together in a combined image:

    PLAY on A -> a STOCK change to X (DIRECT JUMP off) -> DIRECT JUMP on, a jump to Y -> a one-track load:
    RELOAD [PTN] + [TRACK] (KYOTI V1.8, tools/diag_reload_lock.py --cond) or a Clyps load (KYOTI V1.8C,
    tools/diag_dj_clyps_overlap.py --cond).

The jump sets every untouched track's A:B pass counter (dj_cond); the load sets the loaded track's (rl_cond /
cl_cond, F(now) - F(the restart)). RULE: from the tick after each load until the next pattern change or load,
the loaded track's counter equals every untouched audio track's of the same length and live scale, every tick.
(Before V7.3 the jump counted from PLAY and the load from the stock switch: they differ by the passes before
the switch.) Also printed: the COND_RESET calls / watched PCs, so a run whose switch was not a stock one shows.

  python3 tools/check_dj_restart_cond.py RUN.json [...]
"""
import json
import sys


def views(d):
    """tick -> (act, cond[16], lens[8], scale[16]); landings [(tick, track, kind)]; pattern-change ticks."""
    by_t, lands = {}, []
    if d["states"] and isinstance(d["states"][0], dict):          # diag_dj_clyps_overlap
        for s in d["states"]:
            by_t[s["t"]] = (s["act"], s.get("cond"), s["lens"], None)
        for c in d["calls"]:
            if c[1] == "cl_landone" and c[3] < 8:
                lands.append((c[0], c[3], "clyps"))
    else:                                                          # diag_reload_lock --cond rows
        for r in d["states"]:
            if len(r) < 13:
                sys.exit("not recorded with --cond (and the playing lengths): re-run diag_reload_lock --cond")
            by_t[r[0]] = (r[11], r[7], r[12], r[6])
        for l in d["lands"]:
            lands.append((l[0], l[1], "reload " + l[2]))
    ts = sorted(by_t)
    changes = [t for a, t in zip(ts, ts[1:]) if by_t[a][0] != by_t[t][0]]
    return by_t, sorted(lands), changes, ts


def main(argv):
    worst = "PASS"
    for path in argv:
        d = json.load(open(path))
        by_t, lands, changes, ts = views(d)
        print(f"== {path}: ops {d['meta'].get('ops')}  pattern changes at {changes}  "
              f"switch ops {d.get('switches') or d.get('opslog')}")
        if d.get("cresets") is not None:
            print(f"   COND_RESET calls (tick, arg, return): {[(c[0], hex(c[1]), hex(c[2])) for c in d['cresets']]}")
        if d.get("watch") is not None:
            print(f"   watched PCs (tick, pc): {[(t, hex(w)) for t, w in d['watch']]}")
        if not changes:
            print("   no pattern change: nothing to grade -- FAIL")
            worst = "FAIL"
            continue
        graded = 0
        for i, (tl, trk, kind) in enumerate(lands):
            last_change = max([c for c in changes if c <= tl], default=None)
            if last_change is None:
                continue
            end = min([c for c in changes if c > tl] + [l[0] for l in lands[i + 1:] if l[0] > tl] + [ts[-1] + 1])
            touched = {l[1] for l in lands if last_change <= l[0] <= tl}
            act, cond, lens, scl = by_t[tl + 1] if tl + 1 in by_t else by_t[tl]
            if cond is None:
                sys.exit(f"{path}: not recorded with --cond")
            peers = [u for u in range(8) if u not in touched and lens[u] == lens[trk]
                     and (scl is None or scl[u] == scl[trk])]
            if not peers:
                print(f"   load t{tl} track {trk + 1} ({kind}): no untouched track of its length -- not graded")
                continue
            bad = []
            for t in range(tl + 1, end):
                if t not in by_t:
                    continue
                c = by_t[t][1]
                if any(c[trk] != c[u] for u in peers):
                    bad.append((t, c[trk], [c[u] for u in peers]))
            graded += 1
            c1 = by_t.get(tl + 1, by_t[tl])[1]
            verdict = "OK" if not bad else "MISMATCH"
            print(f"   load t{tl} track {trk + 1} ({kind}), pattern {act}, len {lens[trk]}: ticks {tl + 1}..{end - 1}; "
                  f"counter {c1[trk]} vs untouched tracks {[u + 1 for u in peers]} {[c1[u] for u in peers]} -> {verdict}"
                  + (f" ({len(bad)} ticks, first t{bad[0][0]}: {bad[0][1]} vs {bad[0][2]})" if bad else ""))
            if bad:
                worst = "FAIL"
        if not graded:
            print("   no load after a pattern change was graded -- FAIL")
            worst = "FAIL"
    print(f"\nVERDICT: {worst}")
    return 0 if worst == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

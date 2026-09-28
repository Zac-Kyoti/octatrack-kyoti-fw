#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 107/108 -- V7 step 2: MODEL FIRST.  Does a closed-form "position since START"
reproduce the engine's own never-switched reference trace, tick for tick?

    python3 tools/model_reflock.py out/rl_ref3.json [more refs ...]

Nothing about the pattern is assumed: per-track tps comes from TRK_SCALE via LEN_TBL,
the master's from SCALE_IX, lengths from where each counter wraps in the trace itself.
The model under test (measured on the 1x NORMAL references, sample point = phase-G
entry of the ISR counted t = 1, 2, ... from the first running tick):

    track  t : step  = (floor(t / tps_t) + 1) mod len_t      ticks = t mod tps_t
    master   : mstep = (floor((t-1) / tps_M) + 1) mod mlen   mtick = (t-1) mod tps_M

A reference whose engine does something else (PER-TRACK master-length resets, slower
tracks restarting mid-step, INF) shows up here as a mismatch -- that is the point: the
ColdFire must implement whatever THIS tool passes, not what reasoning suggests.
"""
import json
import sys

LEN_TBL = [3, 4, 6, 8, 12, 24, 48, 96, 48, 24]


def infer_len(seq):
    """Length from wrap points: the value before each drop to 0, +1."""
    tops = [seq[i - 1] + 1 for i in range(1, len(seq)) if seq[i] == 0 and seq[i - 1] != 0]
    return max(tops) if tops else None


def main(argv):
    worst = 0
    for path in argv:
        d = json.load(open(path))
        S = d["states"]
        s0 = S[0]
        tpsM = LEN_TBL[s0["scale_ix"]]
        mlen = infer_len([s["m_step"] for s in S])
        print(f"=== {path}  start={d['meta']['start']}  tps_M={tpsM}  mlen={mlen} "
              f"(inferred)  ticks={len(S)}")
        bad_m = [s["t"] for s in S if mlen and (
            s["m_step"] != ((s["t"] - 1) // tpsM + 1) % mlen or s["m_tick"] != (s["t"] - 1) % tpsM)]
        print(f"   master : {'MODEL OK' if not bad_m else f'{len(bad_m)} mismatches, first t{bad_m[0]}'}"
              + ("" if mlen else "  (no master wrap observed: mlen unknown)"))
        worst |= bool(bad_m)
        for trk in range(16):
            if not any(s["armed"][trk] for s in S):
                continue
            tps = LEN_TBL[s0["trk_scale"][trk]]
            ln = infer_len([s["step"][trk] for s in S])
            bad = []
            for s in S:
                t = s["t"]
                exp_step = (t // tps + 1) % ln if ln else (t // tps + 1)
                if s["ticks"][trk] != t % tps or (ln and s["step"][trk] != exp_step):
                    bad.append(t)
            tag = "MODEL OK" if not bad else f"{len(bad)} mismatches, first t{bad[0]}"
            if bad:
                s = next(x for x in S if x["t"] == bad[0])
                t = s["t"]
                tag += (f"  (engine step={s['step'][trk]} ticks={s['ticks'][trk]}; model "
                        f"step={(t // tps + 1) % ln if ln else '?'} ticks={t % tps})")
            print(f"   trk{trk:<2} tps={tps:<3} len={ln if ln else '?':<3}: {tag}"
                  + ("" if ln else "  (no wrap in trace: step only checked for ticks)"))
            worst |= bool(bad)
    print(f"\nMODEL VERDICT: {'FAIL' if worst else 'PASS'}")
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

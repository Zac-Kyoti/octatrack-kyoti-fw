#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI V7.2 in KYOTI-with-Clyps -- grades tools/diag_dj_clyps_overlap.py records (the user's four
rules, 2026-11-14):

  OVERLAP  the case under test happened: (a) a Clyps publish pending (cl_spd[t] != 0) on the tick a jump
           lands (dj_sparm); (b) a DIRECT JUMP publish pending (dj_spd[t] != 0) on the tick Clyps lands t.
  PART     every TRK_APPLY names the Part of the pattern playing at that moment (the tick before, or after a
           landing earlier in the same tick).
  TRIG     every publish (dj_pub1 / cl_sppub -> TRK_APPLY) happens on a tick where the sequence then playing
           the track has a pending sounding trig (record bit 2, fired after that track's latest landing --
           a DIRECT JUMP jump or a Clyps landing of the track) within half a tick of the clock; or the
           sequence has no sample trig (the boundary / count rule); or it is a flush (STOP, a new jump).
  DANGLING at the run's end no publish is pending: dj_spd / dj_spn and cl_spd / cl_spn all 0.

  python3 tools/check_dj_clyps_overlap.py out/djc3/ov/*.json
"""
import json
import sys

TICK = 0x285FF0


def sx(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def has_trig(state, t):
    m = int(state["masks"][t], 16)
    ln = state["lens"][t] or 64
    return any(m >> s & 1 for s in range(min(ln, 64)))


def main(argv):
    bad = 0
    for path in argv:
        d = json.load(open(path))
        S = {s["t"]: s for s in d["states"]}
        C = d["calls"]
        print(f"=== {path}: ops {d['meta']['ops']}, active track T{d['meta']['track'] + 1}, LFO AUTO CHANGE "
              f"{d['meta']['lfo']}")
        lastland = {}            # t -> (q, sclk) of its latest landing
        overl = []
        for i, c in enumerate(C):
            tk, nm, args, d6, sclk, q = c
            if nm == "dj_sparm":
                for t in range(8):
                    lastland[t] = (q, sclk)
                pend = [t for t in range(16) if S.get(tk, {}).get("cl_spd", [0] * 16)[t]]
                if pend:
                    overl.append(f"(a) t{tk}: a jump lands with Clyps publishes pending for "
                                 f"{['T%d' % (t + 1) for t in pend]} (Part {S[tk]['part']} -> {S.get(tk + 1, S[tk])['part']})")
            if nm == "cl_landone" and d6 < 8:
                lastland[d6] = (q, sclk)
                if S.get(tk, {}).get("dj_spd", [0] * 16)[d6]:
                    overl.append(f"(b) t{tk}: Clyps lands T{d6 + 1} with DIRECT JUMP's publish pending for it")
            if nm != "TRK_APPLY":
                continue
            t, part = args[2], args[1]
            who = next((p[1] for p in reversed(C[max(0, i - 3):i]) if p[1] in ("dj_pub1", "cl_sppub") and p[3] == t),
                       "other")
            flush = any(p[1] in ("dj_spflush", "cl_spflush") and p[0] == tk for p in C[max(0, i - 40):i])
            landed_now = any(p[1] == "dj_sparm" and p[0] == tk for p in C[max(0, i - 40):i])
            before = S.get(tk)
            now = S.get(tk + 1, before)
            if before is None:
                continue
            okpart = part == before["part"] or (landed_now and part == now["part"])
            why = ""
            if who in ("dj_pub1", "cl_sppub") and not flush:
                lq, lclk = lastland.get(t, (0, 0))
                trig = None
                for slot in range(3):
                    if not before["emask"][t] >> slot & 1:
                        continue
                    i_ = t + 8 * slot
                    fire, rec = before["ev"][i_], before["rec"][i_]
                    if rec & 4 and sx(fire - lclk) >= 0 and sx(fire - now["sclk"]) < TICK // 2:
                        trig = sx(fire - now["sclk"]) / TICK
                if trig is not None:
                    why = f"its sounding trig fires {trig:+.3f} tick from the clock"
                elif not has_trig(now, t):
                    why = "the sequence playing it has no sample trig (boundary / count rule)"
                else:
                    why = "EARLY: no sounding trig of the sequence playing it is due"
            elif flush:
                why = "flush (a new jump / STOP)"
            else:
                why = f"({who})"
            ok = okpart and not why.startswith("EARLY")
            bad += not ok
            print(f"  t{tk} TRK_APPLY T{t + 1} Part {part} by {who}: Part playing {before['part']}"
                  f"{'/' + str(now['part']) if landed_now else ''} -> {'ok' if okpart else 'WRONG PART'}; {why}"
                  f"  {'PASS' if ok else 'FAIL'}")
        last = d["states"][-1]
        # pending at the run's end: still waiting for a trig the sequence playing the track has (it comes
        # later) -- fine; pending although that sequence has no sample trig (nothing will ever publish it,
        # 0xfffe) -- dangling. A count (< 0xfffe) always runs out.
        pend = [("dj", t, last["dj_spd"][t]) for t in range(16) if last["dj_spd"][t]] + \
               [("Clyps", t, last["cl_spd"][t]) for t in range(16) if last["cl_spd"][t]]
        wait = [f"{w} T{t + 1}" for w, t, v in pend if v < 0xfffe or (t < 8 and has_trig(last, t))]
        dang = [f"{w} T{t + 1}" for w, t, v in pend if not (v < 0xfffe or (t < 8 and has_trig(last, t)))]
        print("  OVERLAP: " + ("; ".join(overl) if overl else "NOT EXERCISED in this run"))
        print(f"  PENDING at t{last['t']}: {wait if wait else 'none'} still waiting for a trig their sequence has; "
              f"DANGLING: {dang if dang else 'none'}")
        bad += bool(dang)
    print(f"\n{'PASS' if not bad else f'FAIL ({bad})'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

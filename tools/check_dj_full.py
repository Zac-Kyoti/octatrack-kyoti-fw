#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI V7.2 -- each track's incoming Part reaches the engine on its first SOUNDING trig (the
user, 2026-11-13, Clyps' FULL rule).  Grades tools/diag_dj_partpub.py --trace records made with
--sym dj_sparm=.. --sym dj_pub1=.. --sym dj_spflush=.. (the way tools/check_clyps_full.py grades Clyps):

  per landing (a dj_sparm call) and track t, from the recorded pending-event tables:
    the first tick whose phase D sees an event of t that is a sounding trig (record bit 2) of the new
    sequence (fire time >= the landing clock + half a tick) firing within half a tick of the clock;
    a track with no such event before the next landing / the run's end: none expected;
  and the tick DIRECT JUMP published t (dj_pub1 with d6 = t, or a dj_spflush).
  PASS when every published track was published on its expected tick, and the trig it was published
  for sounds on a step boundary of the new sequence (the event's fire time is a whole tick).

Tracks that publish on the boundary tick (no sample trig, START SILENT) are listed separately.

  python3 tools/check_dj_full.py out/djc3/full_*.json
"""
import json
import sys

TICK_A, TICK_M = 0x285FF0, 16800


def sx(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def main(argv):
    bad = 0
    for path in argv:
        d = json.load(open(path))
        fr = {f["t"]: f for f in d["frames"]}
        ts = sorted(fr)
        calls = [c + [i] for i, c in enumerate(d["calls"])]          # + call order
        lands = [c for c in calls if c[1] == "dj_sparm"]
        pubs = [c for c in calls if c[1] == "dj_pub1"]
        flush = [c for c in calls if c[1] == "dj_spflush"]
        print(f"=== {path}: Parts {d['meta']['parts']}  cues {d['cues']}  landings at {[c[0] for c in lands]}")
        for li, ln in enumerate(lands):
            L = ln[0]                         # label of the landing's phase D (ISR L + 1)
            nxt = lands[li + 1][0] if li + 1 < len(lands) else ts[-1] + 1
            i0 = ln[-1]
            i1 = lands[li + 1][-1] if li + 1 < len(lands) else 1 << 30   # a new landing flushes first
            base = fr.get(L + 1)
            if base is None:
                continue
            thr = {"a": base["sclk"] + TICK_A // 2, "m": base["mclk"] + TICK_M // 2}
            for t in range(16):
                kind, idx, clk, unit = ("a", t, "sclk", TICK_A) if t < 8 else ("m", t - 8, "mclk", TICK_M)
                want = None
                for n in ts:
                    if n <= L or n >= nxt:
                        continue
                    prev = fr.get(n - 1)
                    if prev is None or kind not in prev["ev"]:
                        continue
                    masks = prev["ev"][kind][24]
                    now = fr[n][clk]
                    for slot in range(3):
                        if not masks[idx] >> slot & 1:
                            continue
                        fire, rec = prev["ev"][kind][idx + 8 * slot]
                        if not rec & 4 or sx(fire - thr[kind]) < 0:
                            continue
                        if sx(fire - now) < unit // 2:
                            want = (n - 1, sx(fire - now) / unit)
                            break
                    if want:
                        break
                got = [c[0] for c in pubs if c[5] == t and i0 < c[-1] < i1]
                fl = [c[0] for c in flush if i0 < c[-1] < i1]
                if not got:
                    tag = f"flushed t{fl[0]} (STOP / DJ off / the next jump)" if fl else "not published"
                    print(f"  land t{L} T{t + 1}: first sounding trig {want}: {tag}")
                    if want and not fl:
                        bad += 1
                    continue
                g = got[0]
                if want is None:
                    early = "boundary" if g <= L + 1 else f"t{g}"
                    print(f"  land t{L} T{t + 1}: published t{g} ({early}; no sounding trig of the new sequence before t{nxt})")
                    continue
                ok = g == want[0]
                bad += not ok
                print(f"  land t{L} T{t + 1}: first sounding trig due t{want[0]} (fire - clock {want[1]:+.3f} tick), "
                      f"published t{g}: {'PASS' if ok else 'FAIL'}")
    print(f"\n{'PASS' if not bad else f'FAIL ({bad})'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

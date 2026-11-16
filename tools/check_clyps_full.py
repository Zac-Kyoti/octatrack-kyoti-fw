#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- a FULL load's Part slice reaches the engine when the incoming sequence first TRIGGERS its sample (the
user, 2026-11-12: "a user should simply never hear the incoming sequence's track settings applied to what they
are changing away from"). Grades tools/diag_clyps_lock.py records (they log TRK_APPLY): per T1 FULL landing,
the incoming sequence's first sample trig from the landing step (its trig mask from the project's bank file,
TRAC +0x09, bit s = step s, big-endian), the tick that step sounds, and the TRK_APPLY tick -- PASS when equal.

  python3 tools/check_clyps_full.py --project DIR out/clyps/full27/F*.json
"""
import json, pathlib, sys

LEN_TBL = [3, 4, 6, 8, 12, 24, 48]


def main(argv):
    proj = pathlib.Path(argv[argv.index("--project") + 1]).expanduser()
    files = [a for a in argv if a.endswith(".json")]
    bad = 0
    for path in files:
        d = json.load(open(path))
        m = d["meta"]
        raw = (proj / f"bank{m['bank'] + 1:02d}.work").read_bytes()
        fire_of = {(x[4], x[1]): x for x in d["fires"]}
        print(f"=== {path}: dj {m['dj']} pokes {m['pokes']} ops {m['ops']}")
        for lt, k, where, ms, mt, lq in d["lands"]:
            if k != 0:
                continue
            rq = [x for x in d["reqs"] if x[1] == 0 and x[6] < lq][-1]
            if not rq[2] & 0x10000:
                continue                              # not a FULL load
            src = rq[2] & 0xFF
            b = 0x16 + src * 0x8EEC + 8               # the source pattern's T1 TRAC block
            mask = int.from_bytes(raw[b + 9:b + 17], "big")
            snap = next(p for t, p in d["snaps"] if t >= lt)
            ln, sc = snap["trk"][0][0], snap["trk"][0][1]
            tps = LEN_TBL[sc] if sc <= 6 else 6
            nb = next(((bt, bs, fire_of.get((bq, 0))) for bt, bk, bs, bq in d["builds"] if bk == 0 and bq > lq), None)
            if not nb or not nb[2]:
                print(f"  t{lt}: no new build"); bad += 1; continue
            snd, k0 = nb[0] + nb[2][3] - 1, nb[1]
            dd = next((j for j in range(ln) if mask >> ((k0 + j) % ln) & 1), 0)
            want = snd + dd * tps
            nxt = min([x[5] for x in d["lands"] if x[1] == 0 and x[5] > lq] + [1 << 30])
            sl = [1 for t, nm, args, sclk, q in d["applies"] if nm == "cl_slice" and lq <= q < nxt
                  and args[1] & 0xF0000000 == 0x40000000]          # the Part in the blob (not the UI's mirror)
            if not sl:
                print(f"  req t{rq[0]} FULL from slot {src + 1} -> landed t{lt}: its slice already plays, nothing to publish")
                continue
            ap = [t for t, nm, args, sclk, q in d["applies"] if nm == "TRK_APPLY" and args[2] == 0 and lq <= q < nxt]
            got = ap[0] if ap else None
            if got is None and want > d["states"][-1][0]:
                print(f"  req t{rq[0]} FULL from slot {src + 1} -> landed t{lt}: its first trig (t{want}) is past the run's end")
                continue
            ok = got == want
            bad += not ok
            print(f"  req t{rq[0]} (m{rq[4]}.{rq[5]}) FULL from slot {src + 1} -> landed t{lt} ({where}); new step {k0} "
                  f"sounds t{snd}; first trig {dd} step(s) later -> t{want}; TRK_APPLY t{got}: {'PASS' if ok else 'FAIL'}")
    print(f"\n{'PASS' if not bad else f'FAIL ({bad})'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

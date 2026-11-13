#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT -- a FULL reload's Part slice reaches the engine when the incoming sequence first TRIGGERS its
sample (Clyps' rule, the user 2026-11-12: "a user should simply never hear the incoming sequence's track settings
applied to what they are changing away from"; Clyps' tools/check_clyps_full.py, adapted 2026-11-13). Grades
tools/diag_reload_lock.py records (they log TRK_APPLY and every armed publish): per audio-track landing whose
publish was armed (rl_pubt, deferred), the incoming sequence's first sample trig from the landing's first new step
(its trig mask: the landed record's first 8 bytes, big-endian, bit s = step s), the tick that step sounds (a build
sounds at its tick + its ahead - 1), and the track's TRK_APPLY tick -- PASS when equal. No apply before it either.

  python3 tools/check_reload_full.py out/rlcp/lock/F*.json
"""
import json, sys

LEN_TBL = [3, 4, 6, 8, 12, 24, 48]


def main(argv):
    files = [a for a in argv if a.endswith(".json")]
    bad = n = 0
    for path in files:
        d = json.load(open(path))
        m = d["meta"]
        fire_of = {(x[4], x[1]): x for x in d["fires"]}
        print(f"=== {path}: pokes {m['pokes']} ops {m['ops']}")
        L = sorted(d["lands"], key=lambda x: x[5])
        for lt, k, where, ms, mt, lq, mask in L:
            if k > 7:
                continue
            nxt = min([x[5] for x in L if x[1] == k and x[5] > lq] + [1 << 30])
            prv = max([x[5] for x in L if x[1] == k and x[5] < lq] + [0])
            armed = [x for x in d["applies"] if x[1] == "rl_pubt" and x[2][0] == k and x[2][1] == 1 and prv < x[4] <= lq + 1]
            if not armed:
                continue                              # not a FULL landing whose slice changed: nothing to publish
            snap = next((p for t, p in d["snaps"] if t >= lt), d["snaps"][-1][1])
            ln, sc = (snap["trk"][k][0], snap["trk"][k][1]) if snap["mode"] else (snap["len"], snap["scale"])
            ln = ln or 16
            tps = LEN_TBL[sc] if sc <= 6 else 6
            nb = next(((bt, bs, fire_of.get((bq, k))) for bt, bk, bs, bq in d["builds"] if bk == k and bq > lq), None)
            n += 1
            if not nb or not nb[2]:
                print(f"  T{k + 1} t{lt}: no new build"); bad += 1; continue
            snd, k0 = nb[0] + nb[2][3] - 1, nb[1]
            mk = int(mask, 16)
            dd = next((j for j in range(ln) if mk >> ((k0 + j) % ln) & 1), None)
            if dd is None:
                want = lt + 1                         # no sample trig at all: the boundary tick
            else:
                want = snd + dd * tps
            ap = [t for t, nm, args, sclk, q in d["applies"] if nm == "TRK_APPLY" and args[2] == k and lq <= q < nxt]
            got = ap[0] if ap else None
            if got is None and want > d["states"][-1][0]:
                print(f"  T{k + 1} landed t{lt}: its first trig (t{want}) is past the run's end"); n -= 1
                continue
            ok = got == want
            bad += not ok
            print(f"  T{k + 1} landed t{lt} ({where}, m{ms}.{mt}); new step {k0} sounds t{snd}; first trig "
                  f"{dd} step(s) later -> t{want}; TRK_APPLY t{got} (all {ap[:3]}): {'PASS' if ok else 'FAIL'}")
    print(f"\n{n} FULL publish(es) graded: {'PASS' if not bad else f'FAIL ({bad})'}")
    return 1 if bad or not n else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

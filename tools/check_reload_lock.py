#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT -- the REF-LOCK oracle, grader half (tools/diag_reload_lock.py records; Clyps'
tools/check_clyps_lock.py in the trkseq worktree, adapted to RELOAD's requests 2026-11-13). Grades a run
against DIRECT JUMP V7's position model (tools/model_reflock.py, tick-exact on the engine's never-switched runs):

    master   : mstep = (floor((t-1)/tps_M) + 1) mod mlen          mtick = (t-1) mod tps_M
    track    : t' = ((t + tps_M - 1) mod C) - (tps_M - 1)  (C = mlen * tps_M; INF: t' = t)
               a fast track (tps_t < tps_M) with t' in [-(tps_M-1), -tps_t] runs its previous cycle (t' + C)
               step = (floor(t'/tps_t) + 1) mod len_t             ticks = t' mod tps_t

with each track's length / scale and the master's from the slab, piecewise: a track's new rate counts from
its landing. PASS = every track, every tick, STEP and TICKS equal the model (outside the landing tick).
Per landing it also prints the LATENCY: the track's step boundaries that sounded the OLD sequence after the
request before the new one sounds (a build sounds at its tick + its `ahead` - 1; DIRECT JUMP's own landing
= the next boundary, 0). A request here is the moment the reload is ARMED for the tick (the card read done).

--rules (Clyps' CL25/CL26 rules, RELOAD_CLYPS_PORT.md 1 + 3): every tick landing on the first tick at or after
the request whose t' (= its t0 + 2) is >= 0 and 0 mod the track's old and new tps (a whole pattern, or a change
of the master's rate: every audio track's and the master's too), the new step sounding on the boundary (ahead 2),
the old boundary event purged, and the landed track's A:B counter equal to an untouched track's of the same rate.

  python3 tools/check_reload_lock.py [--rules] out/rlcp/lock/L1.json [...]
"""
import json, sys

LEN_TBL = [3, 4, 6, 8, 12, 24, 48]


def rate(p, k):
    pt = p["mode"] != 0
    msc = p["mscale"] if pt else p["scale"]
    tpsM = LEN_TBL[msc] if msc <= 6 else 6
    mlen = (None if p["mlen"] in (0xFFFF, 0) else p["mlen"]) if pt else p["len"]
    if k is None:
        return tpsM, mlen
    l, s, _ = p["trk"][k]
    if not pt:
        l, s = p["len"], p["scale"]
    tps = LEN_TBL[s] if s <= 6 else tpsM
    return tpsM, mlen, tps, l


def model(t, tpsM, mlen, tps, ln):
    C = mlen * tpsM if mlen else None
    tl = ((t + tpsM - 1) % C) - (tpsM - 1) if C else t
    if C and tps < tpsM and t > C - tpsM and -(tpsM - 1) <= tl <= -tps:
        tl += C
    return (tl // tps + 1) % ln if ln else tl // tps + 1, tl % tps, tl


def grade(path):
    d = json.load(open(path))
    m = d["meta"]
    S, B, F, L, R, P = d["states"], d["builds"], d["fires"], d["lands"], d["reqs"], d["snaps"]
    L = [x for x in L if x[2] == "tick"] + [x for x in L if x[2] != "tick"]
    L.sort(key=lambda x: x[5])
    P_ = d.get("purges", [])
    bad_rules = []
    print(f"=== {path}: dj {m['dj']} pokes {m['pokes']} ops {m['ops']}")
    p0 = P[0][1]
    # the params in force per track from a tick on: P[i] was taken after op i-1's landing settled; a track's
    # new params count from its landing tick (the land event), the master's from the first landing of the op
    marks = []   # (tick, params)
    li = 0
    for i in range(1, len(P)):
        tk, p = P[i]
        prev = [x for x in L if x[0] <= tk and (not marks or x[0] > marks[-1][0])]
        marks.append((prev[0][0] if prev else tk, p))

    def pars(t):
        p = p0
        for tk, q in marks:
            if t > tk:
                p = q
        return p
    # calibrate the tick offset on the run before the first landing (every track); a STOP + PLAY (op X,
    # d["restarts"] = [stop tick, play tick]) starts the model again: each segment gets its own offset, calibrated
    # before its first landing with the params in force then, and the stopped ticks are not graded
    RS = d.get("restarts", [])
    segs = [0] + [pl for _, pl in RS]
    stopped = lambda t0: any(a < t0 <= b for a, b in RS)
    seg_of = lambda t0: max(sg for sg in segs if sg < t0 or sg == 0)   # a PLAY at tick sg: its first tick is sg + 1
    offs = {}
    for sg in segs:
        nxt_sg = min([x for x in segs if x > sg] + [S[-1][0] + 1])
        first = min([x[0] for x in L if sg < x[0] < nxt_sg] or [nxt_sg])
        pz = pars(sg + 1) if sg else p0
        best = None
        for off in range(-8, 9):
            bad = 0
            for st in S:
                t = st[0] - sg + off
                if not sg < st[0] < first or t < 1 or stopped(st[0]):
                    continue
                tpsM, mlen = rate(pz, None)
                for k in range(8):
                    _, _, tps, ln = rate(pz, k)
                    es, et, _ = model(t, tpsM, mlen, tps, ln)
                    bad += st[4][k] != es or st[5][k] != et
            if best is None or bad < best[1]:
                best = (off, bad)
        offs[sg] = best[0] - sg
        print(f"   tick offset {best[0]} from tick {sg} (pre-landing mismatches {best[1]})")
    off = offs[0]
    land_ticks = {x[0] for x in L}
    fails = {}
    for st in S:
        t0 = st[0]
        if t0 in land_ticks or t0 + 0 < 1 or stopped(t0) or t0 in [b + 1 for _, b in RS]:
            continue
        t = t0 + offs[seg_of(t0)]
        p = pars(t0)
        tpsM, mlen = rate(p, None)
        for k in range(8):
            _, _, tps, ln = rate(p, k)
            es, et, tl = model(t, tpsM, mlen, tps, ln)
            if st[4][k] != es or st[5][k] != et:
                fails.setdefault(k, []).append((t0, st[1], st[2], st[4][k], st[5][k], es, et))
    for k, fl in sorted(fails.items()):
        print(f"   T{k + 1}: {len(fl)} ticks off the model, first {fl[:4]}  (tick, mstep, mtick, STEP, TICKS, "
              f"model STEP, model TICKS)")
        # contiguous spans
        spans, s0, prev = [], fl[0][0], fl[0][0]
        for x in fl[1:]:
            if x[0] != prev + 1:
                spans.append((s0, prev)); s0 = x[0]
            prev = x[0]
        spans.append((s0, prev))
        print(f"       spans {spans[:12]}{' ...' if len(spans) > 12 else ''}")
    if not fails:
        print("   every track on the model at every tick: PASS")
    # latency per landing
    fire_of = {(x[4], x[1]): x for x in F}           # (build q, track) -> fire
    for lt, k, where, ms, mt, lq, _mask in L:
        if k > 7:
            continue
        req = [x for x in R if x[1] == k and x[6] < lq]
        rq = req[-1] if req else None
        bl = []
        for bt, bk, bs, bq in B:
            if bk != k:
                continue
            f = fire_of.get((bq, bk))
            if f:
                bl.append((bt + f[3] - 1, bs, bq > lq, bt, f[3]))
        after = sorted(x for x in bl if rq and x[0] > rq[0])
        newf = next((x for x in sorted(bl, key=lambda y: y[3]) if x[2]), None)
        if not rq or not newf:
            print(f"   landing T{k + 1} at {lt} ({where}): no request / no new build")
            continue
        olds = sorted({x[0] for x in after if not x[2] and x[0] < newf[0]})
        p = pars(lt + 1)
        tpsM, mlen = rate(p, None)
        _, _, tps, ln = rate(p, k)
        _, _, tln = model(newf[0] + offs[seg_of(newf[0])], tpsM, mlen, tps, ln)
        print(f"   landing T{k + 1}: request t{rq[0]} (m {rq[4]}.{rq[5]}, code {rq[2]:#x} now {rq[3]}) -> landed t{lt} "
              f"in {where} (m {ms}.{mt}); new sound from t{newf[0]} step {newf[1]} (ahead {newf[4]}; t' {tln}); "
              f"old steps heard after the request: {len(olds)} {olds}")
        # CL25 rules (--rules): the landing tick DIRECT JUMP's rule picks, the new step sounding on it, the
        # old boundary event purged, the trig conditions
        if RULES:
            kind = 1                                      # RELOAD: every landing is in place
            pb = pars(rq[0])
            tpsM0, mlen0 = rate(pb, None)
            _, _, tps0, _ = rate(pb, k)
            from math import gcd
            lcm = lambda x, y: x * y // gcd(x, y)
            L_ = lcm(tps0, tps)
            if rq[2] & 0x20000 or (tpsM0, mlen0) != (tpsM, mlen):
                # a whole pattern (RELOAD lands all its tracks on one tick) or a change of the master's rate:
                # every audio track's old and new rate, and the master's when it changes
                for j in range(8):
                    L_ = lcm(lcm(L_, rate(pb, j)[2]), rate(p, j)[2])
                if (tpsM0, mlen0) != (tpsM, mlen):
                    L_ = lcm(lcm(L_, tpsM0), tpsM)
            exp = None
            if kind:
                for tt in range(rq[0], rq[0] + 400):         # the next ISR may land it (DJ: "a request on a boundary tick lands that tick")
                    _, _, tl_ = model(tt + 1 + offs[seg_of(tt + 1)], tpsM0, mlen0, tps0, 1)   # phase D of the next tick
                    tl_ += 1                                  # CL26: the boundary it aims at is the tick after
                    if tl_ >= 0 and tl_ % L_ == 0:
                        exp = tt
                        break
            if kind and where == "tick":
                ok = exp == lt and newf[0] == lt + 1 and newf[4] == 2   # fired for the boundary, ahead 2
                print(f"      RULE landing: kind {kind}, expected t{exp}, landed t{lt}, new sound t{newf[0]}: "
                      f"{'PASS' if ok else 'FAIL'}")
                bad_rules.append(None) if ok else bad_rules.append(("land", lt))
            pg = [x for x in P_ if x[0] == lt and x[1] == k]
            if where == "tick":
                okp = bool(pg) and pg[0][2] != pg[0][3] or not any(
                    b_[2] for b_ in [(x[3], x[0], x[2] <= lq) for x in B if x[1] == k and lt - tps <= x[0] < lt])
                print(f"      RULE purge: {pg[:1]} {'PASS' if pg else 'FAIL (no purge)'}")
                if not pg:
                    bad_rules.append(("purge", lt))
            if "conds" in d and where == "tick":     # Clyps CL34: an instant landing's PRE latch starts again at 1
                cs_ = [c for c in d["conds"] if c[0] == lt and c[1] == k]
                okc = bool(cs_) and cs_[-1][5] == 1
                print(f"      RULE PRE latch: {'PASS' if okc else 'FAIL'} (rl_cond out: counter, FILL, FILL2, PRE "
                      f"{cs_[-1][2:] if cs_ else None})")
                if not okc:
                    bad_rules.append(("pre", lt))
            if len(S[0]) > 7:
                nxt = min([x[0] for x in L if x[0] > lt and x[1] == k] + [S[-1][0]])
                pl = pars(lt + 2)
                ref = [j for j in range(8) if j != k and rate(pl, j)[2:] == rate(pl, k)[2:]
                       and not any(x[1] == j for x in L)]
                rows = [st for st in S if lt + 2 <= st[0] < nxt - 1]
                if kind and ref:
                    badc = [(st[0], st[7][k], st[7][ref[0]]) for st in rows if st[7][k] != st[7][ref[0]]]
                    print(f"      RULE conditions (instant, as T{ref[0] + 1}): "
                          f"{'PASS' if not badc else 'FAIL ' + str(badc[:4])} over {len(rows)} ticks")
                    if badc:
                        bad_rules.append(("cond", lt))
                elif not kind:
                    first = rows[0][7][k] if rows else None
                    print(f"      RULE conditions (cued, restarted): counter {first} after the landing: "
                          f"{'PASS' if first == 0 else 'FAIL'}")
                    if first != 0:
                        bad_rules.append(("cond", lt))
                else:
                    print("      RULE conditions: no untouched reference track of that rate")
    nb = [x for x in bad_rules if x]
    if RULES:
        print(f"   RULES: {'PASS' if not nb else 'FAIL ' + str(nb)}")
    return 0 if not fails and not nb else 1


RULES = "--rules" in sys.argv
if __name__ == "__main__":
    sys.exit(max(grade(p) for p in sys.argv[1:] if not p.startswith("--")))

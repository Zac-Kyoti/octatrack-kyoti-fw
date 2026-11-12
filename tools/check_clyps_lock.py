#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- the REF-LOCK oracle, grader half (tools/diag_clyps_lock.py records). Grades a run against DIRECT
JUMP V7's position model (tools/model_reflock.py, tick-exact on the engine's never-switched runs):

    master   : mstep = (floor((t-1)/tps_M) + 1) mod mlen          mtick = (t-1) mod tps_M
    track    : t' = ((t + tps_M - 1) mod C) - (tps_M - 1)  (C = mlen * tps_M; INF: t' = t)
               a fast track (tps_t < tps_M) with t' in [-(tps_M-1), -tps_t] runs its previous cycle (t' + C)
               step = (floor(t'/tps_t) + 1) mod len_t             ticks = t' mod tps_t

with each track's length / scale and the master's from the slab, piecewise: a track's new rate counts from
its landing. PASS = every track, every tick, STEP and TICKS equal the model (outside the landing tick).
Per landing it also prints the LATENCY: the track's step boundaries that sounded the OLD sequence after the
request before the new one sounds (a build sounds at its tick + its `ahead` - 1; DIRECT JUMP's own landing
= the next boundary, 0).

  python3 tools/check_clyps_lock.py out/clyps/lock/R1.json [...]
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
    print(f"=== {path}: dj {m['dj']} chain {m['chain']} pokes {m['pokes']} ops {m['ops']}")
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
    # calibrate the tick offset on the run before the first landing (every track)
    first = min([x[0] for x in L] or [S[-1][0]])
    best = None
    for off in range(-8, 9):
        bad = 0
        for st in S:
            t = st[0] + off
            if st[0] >= first or t < 1:
                continue
            tpsM, mlen = rate(p0, None)
            for k in range(8):
                _, _, tps, ln = rate(p0, k)
                es, et, _ = model(t, tpsM, mlen, tps, ln)
                bad += st[4][k] != es or st[5][k] != et
        if best is None or bad < best[1]:
            best = (off, bad)
    off = best[0]
    print(f"   tick offset {off} (pre-landing mismatches {best[1]})")
    land_ticks = {x[0] for x in L}
    fails = {}
    for st in S:
        t0 = st[0]
        if t0 in land_ticks or t0 + 0 < 1:
            continue
        t = t0 + off
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
    for lt, k, where, ms, mt, lq in L:
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
        _, _, tln = model(newf[0] + off, tpsM, mlen, tps, ln)
        print(f"   landing T{k + 1}: request t{rq[0]} (m {rq[4]}.{rq[5]}, code {rq[2]:#x} now {rq[3]}) -> landed t{lt} "
              f"in {where} (m {ms}.{mt}); new sound from t{newf[0]} step {newf[1]} (ahead {newf[4]}; t' {tln}); "
              f"old steps heard after the request: {len(olds)} {olds}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(max(grade(p) for p in sys.argv[1:]))

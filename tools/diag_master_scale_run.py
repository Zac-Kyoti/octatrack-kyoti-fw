#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 88: reproduce the hardware MASTER SCALE report, with NO pattern switch.

Hardware report (MKI, image 0657157f, DJ ON): one track, 16 steps, MASTER LENGTH 16,
MASTER SCALE 2x, one trig on step 1. AR plays steps 1..8 in order. OT plays
1, 3, 4, 7, 9, 10, 11, 12.

Expected-by-construction: master tps 3 * MLEN 16 = 48 ticks per master cycle; a 1x track
advances one step per 6 ticks, so it gets through 48/6 = 8 of its own steps before the
master wraps it. Hence AR's 1..8.

DJTEST2 bank 1 index 5 (A06) is that case exactly: SMODE=1 MLEN=16 MSCALE=0(3 ticks),
all tracks len 16 scale 2 (6 ticks). Index 3 (A04) is identical but MSCALE=2 (6 ticks) --
the 1x control, which must stay byte-identical across every configuration.

Samples once per clock tick at 0x400a3fdc (NOT a detour site -- see NOTES.md S87 rule 1:
a Unicorn code hook fires before its instruction, so hooking one of our own jsr sites
would measure the state before the hook ran).

Usage:
  python3 tools/diag_master_scale_run.py [--project DIR] [--pattern IDX] [--ticks N]
"""
import argparse
import pathlib
import os
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC           # the per-clock-tick increment; once per tick
MASTER_STEP = 0x800065B2       # word, bounded master playhead
TICK_CTR = 0x800065B6          # master ticks-within-step
STEP_ARR = 0x800064D0          # per-track STEP position
TICKS_ARR = 0x800064F0         # per-track ticks-within-step
CNTDN_TBL = 0x800065C3         # per-track countdown -- the array under investigation
NEXT_STEP = 0x800065E4         # per-track quotient (word each)
SCALE_IX = 0x8000663D          # live MASTER scale index
TRK_SCALE_IX = 0x8000663E      # live per-track scale index
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
ACT_PAT = 0x800065BE
G_ARMED = 0x80006A40


def run_one(er, project, pat, dj, image, ticks, tree, poison=True,
            to_pattern=None, cue_at=24):
    import time
    t0 = time.time()
    def log(m):
        print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)
    log("staging project")
    card, staged = er.stage_project(project, "OCTABAM", None, tree=tree)
    log("staged; attaching")
    r, rt = er.attach(str(image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    log("attached; gating")
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    log("gated; loading project")
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    log(f"loaded bank={bank}; selecting pattern {pat}")
    rt.seq_select_live(bank, pat)
    log("pattern selected")
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1 if dj else 0).to_bytes(4, "big"))
    # handoff rule 8.2 -- see diag_step_writers.py
    if poison:
        rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, rows=[], cued=None, armed_seen=False, commit=None, acts=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        # Cue a REAL DIRECT JUMP: Hook A arms only when PEND_PAT != -1 and differs from
        # ACT_PAT/ACT_BANK. seq_select_live() writes ACT_PAT directly and never cues, so a
        # run that only calls it measures stock behaviour with the feature merely enabled
        # (NOTES.md S79 cont., "CORRECTION -- rt.seq_select_live() cannot arm DIRECT JUMP").
        if to_pattern is not None and st["cued"] is None and st["tick"] >= cue_at:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([to_pattern]))
            st["cued"] = st["tick"]
        if bytes(u.mem_read(G_ARMED, 1))[0] not in (0, 0xAA):
            st["armed_seen"] = True
        ap = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap:
            st["acts"].append((st["tick"], ap))
            if st["cued"] is not None and st["commit"] is None and len(st["acts"]) > 1:
                st["commit"] = st["tick"]
        if st["tick"] > ticks:
            return
        rd = lambda ad, n: bytes(u.mem_read(ad, n))
        st["rows"].append(dict(
            t=st["tick"],
            ms=int.from_bytes(rd(MASTER_STEP, 2), "big"),
            tc=rd(TICK_CTR, 1)[0],
            s0=rd(STEP_ARR, 1)[0],
            ti0=rd(TICKS_ARR, 1)[0],
            cd0=rd(CNTDN_TBL, 1)[0],
            ns0=int.from_bytes(rd(NEXT_STEP, 2), "big"),
            six=rd(SCALE_IX, 1)[0],
            tix=rd(TRK_SCALE_IX, 1)[0],
        ))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    log("hook installed; starting transport")
    rt.start_transport_live()
    log("transport started")
    spins = 0
    while st["tick"] < ticks:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        log(f"  spin {spins}: ticks={st['tick']}")
        if st["tick"] == before:
            log("  no tick progress -- stopping")
            break
        if spins > 60:
            log("  spin cap reached")
            break
    return st["rows"], st


def visited(rows):
    """The sequence of distinct STEP values the track actually lands on, in order."""
    out = []
    for r in rows:
        if not out or out[-1] != r["s0"]:
            out.append(r["s0"])
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--pattern", type=int, default=5, help="0-indexed; 5=A06 2x, 3=A04 1x")
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-poison", action="store_true")
    ap.add_argument("--to-pattern", type=int, default=None,
                    help="cue a REAL direct jump to this 0-indexed pattern mid-run")
    ap.add_argument("--cue-at", type=int, default=24)
    ap.add_argument("--only", choices=["stock", "off", "on"],
                    help="run a single configuration (so the three can go in parallel)")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    all_configs = {
        "stock": ("stock            ", STOCK, False),
        "off": ("patched DJ OFF   ", PATCHED, False),
        "on": ("patched DJ ON    ", PATCHED, True),
    }
    configs = ([all_configs[a.only]] if a.only
               else [all_configs[k] for k in ("stock", "off", "on")])
    results = {}
    for name, img, dj in configs:
        rows, meta = run_one(er, a.project, a.pattern, dj, img, a.ticks,
                       tree=f"out/_emu_ms_p{a.pattern}_{name.strip().replace(' ', '_')}",
                       poison=not a.no_poison, to_pattern=a.to_pattern, cue_at=a.cue_at)
        if a.to_pattern is not None:
            print(f"   cued at t{meta['cued']}  committed at t{meta['commit']}  "
                  f"ACT_PAT timeline={meta['acts']}  "
                  f"G_ARMED ever set: {'YES' if meta['armed_seen'] else 'NO -- RUN IS VOID'}")
        results[name] = rows
        v = visited(rows)
        print(f"{name} ticks={len(rows):4d}  SCALE_IX={rows[0]['six'] if rows else '?'} "
              f"TRK_SCALE_IX[0]={rows[0]['tix'] if rows else '?'}")
        print(f"                   track0 steps visited (1-based), full: "
              f"{[x + 1 for x in v]}")
        # master-cycle boundaries: MASTER_STEP wrapping back to 0
        cyc, prev = [], None
        for r in rows:
            if prev is not None and r["ms"] < prev:
                cyc.append(r["t"])
            prev = r["ms"]
            
        print(f"                   master-cycle wraps at ticks: {cyc}")
        # steps occupied within each master cycle
        seg, cur, lastms = [], [], None
        for r in rows:
            if lastms is not None and r["ms"] < lastms:
                seg.append(cur); cur = []
            cur.append(r["s0"]); lastms = r["ms"]
        seg.append(cur)
        for i, sg in enumerate(seg):
            dedup = []
            for x in sg:
                if not dedup or dedup[-1] != x:
                    dedup.append(x)
            print(f"                     cycle {i}: {[x + 1 for x in dedup]}")
        if a.verbose:
            for r in rows[:96]:
                print(f"    t{r['t']:3d} ms={r['ms']:3d} tc={r['tc']:2d} "
                      f"step0={r['s0']:3d} ticksInStep0={r['ti0']:3d} "
                      f"cntdn0={r['cd0']:3d} nextStep0={r['ns0']:5d}")
        print()

    if a.only:
        return 0
    base = visited(results["stock            "])
    for name, _, _ in configs[1:]:
        v = visited(results[name])
        same = v == base
        print(f"{name} vs stock: {'IDENTICAL' if same else 'DIFFERS'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

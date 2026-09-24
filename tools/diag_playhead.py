#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Is `0x800065b2` OT's analogue of AR's bounded playhead `0x405666e4`?  (Session 83)

The user has settled the cont.38 specification fork: port AR, drop our absolute-time model.
AR's whole position model is two lines (MECHANISM.md section 5, measured):

    new_step = masterStep mod newPatternLen          # masterStep = DAT_405666e4
    pos_t    = new_step mod trackLen_t

so the port needs OT's `masterStep`. `0x800065b2` is the candidate: measured (Session 82)
incrementing once per master step at `0x400a423a`. Before building anything on it, three
things have to be known, and only one of them is visible statically:

  1. Its RANGE. AR's wraps at the pattern length. If OT's free-runs, `x mod newLen` is still
     the right expression but means something slightly different, and the difference shows up
     exactly when two patterns have different lengths.
  2. Whether it is the METRONOME's source. `0x400a4264`-`0x400a42b2` derive beat flags from
     it (bit tables at `0x400abae4`/`0x400abacc` plus a `mod 3` test at `0x400a428a`). If the
     metronome comes from this counter, then seeding the resume position FROM this counter
     makes pattern and metronome agree BY CONSTRUCTION -- which is the user's actual
     complaint about the current build: the patterns drift against the steady 1-2-3-4.
  3. That it is live and correct at Hook H's site (`0x400a47f6`), which runs BEFORE stock
     reseeds it from `0x8000662a` at `0x400a483a`.

Reports its value at every master step boundary alongside the absolute tick count, so its
period is directly readable.

Usage:
  python3 tools/diag_playhead.py [--project DIR] [--pattern N] [--frames N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

MASTER_STEP = 0x800065B2       # candidate playhead (word)
PREV_STEP = 0x800065B4         # its "previous" shadow, written at 0x400a422c
TICK_CTR = 0x800065B6          # master ticks-within-step
SCALE_IX = 0x8000663D
LEN_TBL = 0x400ABA50
TICK_PC = 0x400A3FDC           # once per clock tick
STEP_PC = 0x400A4220           # once per master step (start of the step body)
BLOB, BANK_STRIDE, PAT_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(STOCK))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--pattern", type=int, default=6)
    ap.add_argument("--frames", type=int, default=9000)
    ap.add_argument("--tree", default="out/_emu_playhead")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = a.bank if a.bank is not None else loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    st = dict(tick=0, rows=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1

    def on_step(u, addr, size, user):
        ms = int.from_bytes(bytes(u.mem_read(MASTER_STEP, 2)), "big")
        pv = int.from_bytes(bytes(u.mem_read(PREV_STEP, 2)), "big")
        st["rows"].append((st["tick"], ms, pv))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_step, begin=STEP_PC, end=STEP_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    base = BLOB + bank * BANK_STRIDE + a.pattern * PAT_STRIDE
    smode = rd(base + 0x8E55, 1)[0]
    mlen = rd(base + 0x8E51, 1)[0] if smode else rd(base + 0x8E53, 1)[0]
    six = rd(SCALE_IX, 1)[0]
    tps = tbl[six] if six < 12 else None

    print(f"image   {a.image}")
    print(f"project {a.project}  bank {bank} pattern {a.pattern}")
    print(f"SCALE_MODE={smode}  MASTER LENGTH={mlen}  tps_master={tps}")
    vals = [r[1] for r in st["rows"]]
    print(f"\nmaster step boundaries: {len(st['rows'])}")
    print(f"  0x800065b2 at each:   {vals[:40]}")
    print(f"  (tick, 0x65b2, prev): {st['rows'][:12]}")
    if vals:
        print(f"\n  range: min={min(vals)} max={max(vals)}")
        wrapped = [i for i in range(1, len(vals)) if vals[i] < vals[i - 1]]
        if wrapped:
            periods = [wrapped[0]] + [b - a2 for a2, b in zip(wrapped, wrapped[1:])]
            print(f"  WRAPS at indices {wrapped[:8]} -> period {periods[:8]} steps; "
                  f"MASTER LENGTH is {mlen}")
            print(f"  -> BOUNDED playhead, like AR's 0x405666e4"
                  if periods and periods[-1] == mlen else
                  f"  -> wraps, but NOT at MASTER LENGTH -- investigate")
        else:
            print(f"  NEVER wraps over {len(vals)} steps -> FREE-RUNNING counter, "
                  f"unlike AR's bounded 0x405666e4. `x mod newLen` is still the right "
                  f"expression; the difference appears when lengths differ.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

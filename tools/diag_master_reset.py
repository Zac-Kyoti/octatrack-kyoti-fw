#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Does MASTER LENGTH actually reset every track to step 1 on the Octatrack?  (Session 79 cont.37)

This decides whether the DIRECT JUMP resume position is correct.

The user's description of the control is "master length (length in steps before all tracks
reset to step 1)". If that is what the firmware does, then a track whose own length does not
divide the master length never completes free cycles -- a 7-step track under master 16 plays
7, 7, then 2 steps and is cut off -- so its behaviour is periodic in the MASTER cycle, not in
its own length. The resume position for a jump would then be fully determined by
`absolute mod masterLength`, which is exactly what AR computes
(`new_step = masterStep mod patternLen`, then `new_step mod trackLen` per track).

Our Hook H currently feeds the raw absolute counter, i.e. `pos_t = (absTicks / tps_t) mod
len_t`, with no master reduction. On DJTEST2 A07 at absolute step 26 that puts the 7-step
track on 5, where respecting a master reset would put it on 3.

So: run STOCK, with no DIRECT JUMP involved at all, and simply watch the per-track STEP
counters advance. If the 7-step track's STEP is seen to jump back to 0 at master-cycle
boundaries rather than only after its own 7 steps, the master reset is real and our resume
position is wrong.

Reports each track's observed STEP sequence and, for the odd-length track, whether it ever
restarts early.

Usage:
  python3 tools/diag_master_reset.py [--project DIR] [--pattern N] [--frames N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

STEP_ARR = 0x800064D0
SCALE_ARR = 0x8000663E
MASTER_STEP = 0x800065B6
BLOB, BANK_STRIDE, PAT_STRIDE, TRK_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
LEN_TBL = 0x400ABA50
STEP_ADVANCE_PC = 0x400A3D78          # per-track STEP++ (once per step, per track)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(STOCK))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--pattern", type=int, default=6)
    ap.add_argument("--frames", type=int, default=9000)
    ap.add_argument("--tree", default="out/_emu_mreset")
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

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    base = BLOB + bank * BANK_STRIDE + a.pattern * PAT_STRIDE
    mlen = rd(base + 0x8E51, 1)[0]
    smode = rd(base + 0x8E55, 1)[0]
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    fields = [(rd(base + t * TRK_STRIDE + 0x50, 1)[0],
               rd(base + t * TRK_STRIDE + 0x51, 1)[0]) for t in range(8)]

    print(f"project {a.project}  bank {bank} pattern {a.pattern}")
    print(f"SCALE_MODE={smode}  MASTER LENGTH (+0x8e51)={mlen}")
    for t, (ln, sc) in enumerate(fields):
        print(f"  T{t}: LEN={ln}  MULT idx={sc} (tps={tbl[sc] if sc < 12 else '?'})")

    # Record the sequence of values each per-track STEP counter takes, sampled at the
    # instruction that advances it -- far finer than polling from the main loop.
    seq = [[] for _ in range(16)]

    def on_adv(u, addr, size, user):
        s = bytes(u.mem_read(STEP_ARR, 16))
        for i in range(16):
            if not seq[i] or seq[i][-1] != s[i]:
                seq[i].append(s[i])
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_adv,
                   begin=STEP_ADVANCE_PC, end=STEP_ADVANCE_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    print("\n=== observed STEP sequences (stock, no DIRECT JUMP) ===")
    for t in range(8):
        ln, sc = fields[t]
        s = seq[t][:40]
        print(f"  T{t} (LEN={ln:2d}): {s}")

    print("\n=== verdict ===")
    for t in range(8):
        ln, sc = fields[t]
        if ln == 0 or ln >= mlen:
            continue
        hi = max(seq[t]) if seq[t] else -1
        # If the master reset is real, a track whose length does not divide the master
        # length should be seen restarting before reaching len-1 at least once.
        early = False
        for i in range(1, len(seq[t])):
            if seq[t][i] == 0 and seq[t][i - 1] != ln - 1:
                early = True
                break
        print(f"  T{t} LEN={ln}: highest STEP seen={hi} (its own max would be {ln - 1}); "
              f"restarts before completing its length: {early}")
        if ln and mlen % ln:
            print(f"     -- {ln} does NOT divide master {mlen}: this is the deciding track. "
                  f"{'Master reset IS real -> our resume position is wrong.' if early else 'No early restart seen -> the track free-runs; our model stands.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

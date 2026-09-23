#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_undo -- does our reload leave the CLEAR/UNDO toast primed on UNDO?

WHY THIS EXISTS
---------------
Session 80 continued (9) hardware report: after a RELOAD2 TRK SEQ reload, doing
FUNC+PLAY (Clear) shows "UNDO TRACK TRIGS" instead of "CLEAR TRACK TRIGS" -- as
if the OS thinks there is already a pending undo, even though the user never
manually cleared anything.

Found the decision point by objdump (not guessed): the Clear handler at
0x4005f0a0ff calls

    jsr 0x4002a4dc(mvzb 0x100b14cc, mvzb 0x100b14d0, 0xa)   -- QUERY
        d0 != 0  -> show "UNDO TRACK TRIGS", do nothing else
        d0 == 0  -> perform the clear, jsr 0x40039df4(1, ...) to mark undo
                    available, show "CLEAR TRACK TRIGS"

0x100b14cc / 0x100b14d0 turned out to be extremely widely referenced (1004 and
484 xrefs respectively) -- too general to be "the track index" specifically;
almost certainly CUR_BANK/CUR_PART-class mirrors used throughout the firmware,
not something safe to reverse-engineer further by reading alone.

The mark function (0x40039df4) computes an address using EXACTLY our own
worker's stride constants (0x91a = TRAC_A, 0x8ed8 = PATSTRIDE) into the
0x1001xxxx region neighbouring the live pattern cache -- suggestive, but not
proof of what our patch specifically does versus what stock's OWN whole-bank
reload (which our worker's job still triggers, per "(4)"/"(5)") already does on
its own, unpatched.

WHAT THIS MEASURES
-------------------
The query function called EXACTLY as the Clear handler calls it, at three
points:
  1. right after boot+load, before anything            (baseline)
  2. after driving ordinary playback, no reload at all  (rules out "just
     playing sets it")
  3. after one TRK SEQ reload via rl_arm_trk             (the reported trigger)

If (1)/(2) already read nonzero, this is NOT something our patch introduces --
it is either a pre-existing condition from LOAD PROJECT itself, or the query
needs different/track-specific args than the Clear handler's own two globals
(in which case this script's read is incomplete, not proof of innocence).
If (3) flips 0->nonzero while (1)/(2) do not, our reload is the cause.

Usage:   python3 tools/diag_reload2_undo.py
(Slow -- full-RTOS boot + a real card load.)
"""
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402

er = erl.er

# CLEAR_HANDLER = 0x4005F0A0  # ** DO NOT USE / DO NOT CALL **. Verified WRONG:
# 0x4005f0a0 is the MIDDLE of an instruction (objdump confirms the true
# boundary is elsewhere, not yet located), left here only as a record of a
# mistake -- calling it directly would jsr into garbage.
UNDO_QUERY = 0x4002A4DC       # (g1@100b14cc, g2@100b14d0, kind) -> d0 != 0: undo pending
G1 = 0x100B14CC
G2 = 0x100B14D0
KIND = 0xA                    # the exact constant the Clear handler passes
CHANGE_KIND_FIELD = 0x460C80F0


def u32(rt, a):
    return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]


def call1(rt, addr, args):
    """jsr addr(args...) via call_as_main, re-parking at MAIN_SPIN first."""
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    return rt.call_as_main(addr, args=args, budget=1_000_000)


def query(rt, label):
    g1 = rt.uc.mem_read(G1, 1)[0]
    g2 = rt.uc.mem_read(G2, 1)[0]
    d0 = call1(rt, UNDO_QUERY, (g1, g2, KIND))
    kind = u32(rt, CHANGE_KIND_FIELD)
    print(f"   {label:<40} g1(0x100b14cc)={g1} g2(0x100b14d0)={g2} "
          f"query->{d0}  change_kind_field=0x{kind:08x}  "
          f"=> {'UNDO (unexpected!)' if d0 else 'CLEAR (normal)'}")
    return d0


WATCH_LO, WATCH_HI = 0x10010000, 0x10020000  # covers 0x1001614e (live cache)
                                              # and 0x100169a7 (undo-mark base)


PARSEPAT = 0x4008CEBC


def main():
    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    rl_arm_trk = erl2._sym("rl_arm_trk")

    rt = erl.boot_and_load()
    T, P = 3, 0
    curbank = rt.uc.mem_read(er.CUR_BANK, 1)[0]
    rt.seq_select_live(curbank, P)
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.internal_clock()
    rt.press_play_live()
    rt.run(ms=250)

    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    print("\n===== undo/clear query at three points =====")
    query(rt, "1. right after boot+load")

    rt.run(ms=500)
    query(rt, "2. after 500ms of ordinary playback (no reload)")

    # Direct measurement, sidestepping any uncertainty about the query's exact
    # args: watch EVERY write into the region containing the live pattern cache
    # (0x1001614e) and the undo-mark base (0x100169a7) during the reload. If
    # our reload (or the stock whole-bank reload it still triggers) writes
    # anywhere in the undo-mark's own neighbourhood, that shows up here
    # regardless of whether the query-side reasoning above is exactly right.
    writes = []

    def watch(u, access, addr, size, value, x):
        if WATCH_LO <= addr < WATCH_HI:
            writes.append((addr, size, value))

    h = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, watch, begin=WATCH_LO, end=WATCH_HI - 1)
    # BUG FOUND AND FIXED while writing this test: ctl_flush_tb() was only
    # called earlier (before this hook existed), at line ~115. Unicorn does
    # not retroactively re-instrument already-cached translation blocks for a
    # NEW hook -- any code that ran once during boot+load (very plausibly
    # including shared deserialiser routines the reload path also calls) would
    # stay un-instrumented, producing a false "0 writes" negative regardless of
    # what actually happens. Must flush AGAIN right after adding the hook.
    rt.uc.ctl_flush_tb()

    parse_count = [0]
    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                    lambda u, a, sz, x: parse_count.__setitem__(0, parse_count[0] + 1),
                    begin=PARSEPAT, end=PARSEPAT)

    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065BE, bytes([P]))
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([T]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")
    rt.uc.mem_write(erl.G_KIND, b"\x00")
    faulted = None
    try:
        rt.call_as_main(rl_arm_trk, args=(), budget=900_000)
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"
    # SECOND BUG FOUND AND FIXED while writing this test: draining only until
    # G_KIND==0 is the EXACT documented gotcha from "(4)"'s own investigation --
    # G_KIND clears at rl_job's ENTRY, long before stock's downstream whole-bank
    # reload (the slow part, and the only place writes into the watched region
    # could plausibly happen) actually finishes. Drain until the pattern parser
    # has run the full expected count (1 ours + 16 stock's whole-bank re-parse
    # = 17, per "(4)"/"(5)"'s own measurements) instead, with margin.
    for _ in range(60):
        try:
            rt.run(ms=100)
        except Exception as e:
            faulted = faulted or f"{type(e).__name__}: {e}"
            break
        if rt.uc.mem_read(erl.G_KIND, 1)[0] == 0 and parse_count[0] >= 17:
            break
    print(f"   parse_pattern fired {parse_count[0]}x "
          f"({'full stock reload completed' if parse_count[0] >= 17 else 'INCOMPLETE -- drain ended early'})")
    rt.uc.hook_del(h)
    print(f"   (reload fault: {faulted}, G_KIND settled: "
          f"{rt.uc.mem_read(erl.G_KIND, 1)[0]})")
    print(f"\n   writes into 0x{WATCH_LO:08x}-0x{WATCH_HI:08x} during the reload: "
          f"{len(writes)}")
    seen_addrs = sorted(set(a for a, sz, v in writes))
    # collapse into contiguous runs for a readable summary
    runs = []
    for a in seen_addrs:
        if runs and a <= runs[-1][1] + 4:
            runs[-1][1] = a
        else:
            runs.append([a, a])
    for lo, hi in runs[:30]:
        print(f"      0x{lo:08x} .. 0x{hi:08x}")
    UNDO_MARK_BASE = 0x100169A7
    near_undo = [a for a in seen_addrs if abs(a - UNDO_MARK_BASE) < 0x2000]
    print(f"\n   writes within 0x2000 of the undo-mark base (0x{UNDO_MARK_BASE:08x}): "
          f"{len(near_undo)}" + (f"  first: {[hex(a) for a in near_undo[:10]]}" if near_undo else ""))

    query(rt, "3. after one TRK SEQ reload")


if __name__ == "__main__":
    main()

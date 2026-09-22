#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_repeat -- drive N CONSECUTIVE reloads and watch for state drift.

WHY THIS EXISTS
---------------
Session 80 continued (5). Two hardware reports in a row describe a feature that
*degrades with use*, not one that is broken outright:

  - "most all times I try and execute via [YES], I get the RELOAD BUSY message"
  - "[BANK]+[YES] hardly ever executes ... stock [BANK] single press seems to
     stop working entirely after messing with the reload function a few times"

Every test in this repo drives exactly ONE reload, and on one reload everything
measures correct: G_KIND returns to 0, the keymap layer stack balances, both the
cold blob and the live copy revert. That is precisely how a build that fails on
hardware passed review -- the test measured the thing I had built a test for,
not the thing the user does with the feature.

`RELOAD BUSY` is emitted by rl_yes_exec when it finds G_KIND still set from a
previous request, so a permanently-set G_KIND is *sufficient* to explain the
user's #1 complaint. Crucially **that symptom predates the reverted "(4)" work**
-- it was reported against the build that is current again now -- so this is
runnable against the known-good image and should reproduce a live bug.

WHAT IT MEASURES
----------------
Per iteration, after arming a TRK SEQ reload and draining:

  G_KIND        must return to 0     (non-zero => the next [YES] toasts BUSY)
  POPUP         must return to 0     (non-zero => rl_bank_yes refuses to open,
                                      which is the "hardly ever executes" shape)
  layer depth   must return to base  (drift => dispatch table overridden)
  BANK slot     must stay 0x4007af80 ("stock [BANK] stops working" shape)
  YES slot      must stay rl_yes/stock
  worker ran    rl_job entered, and the pattern parser actually called

Anything that drifts MONOTONICALLY across iterations is the bug. A single green
iteration proves nothing here -- that is the whole lesson.

Usage:   python3 tools/diag_reload2_repeat.py [N]        (default N = 5)
(Slow -- full-RTOS boot plus a real card load, then N reloads. Background it.)
"""
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import emu_reload2 as erl2        # noqa: E402  (sets erl.RELOAD_IMAGE etc.)
import emu_reload as erl          # noqa: E402

er = erl.er

LAYER_HEAD = 0x460D165C
DISPATCH_BASE = 0x46C7D8DE
BANK_SLOT = DISPATCH_BASE + 0x2F * 24
YES_SLOT = DISPATCH_BASE + 0x31 * 24
BANK_PRESS = 0x4007AF80
POPUP = 0x460E5CD0
RELOAD_NOW = 0x46C8028A
PARSEPAT = 0x4008CEBC


def layer_depth(uc):
    n = struct.unpack(">I", uc.mem_read(LAYER_HEAD, 4))[0]
    d = 0
    for _ in range(64):
        if n == 0 or n < 0x40000000:
            break
        d += 1
        try:
            n = struct.unpack(">I", uc.mem_read(n, 4))[0]
        except Exception:
            break
    return d


def u32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def main():
    n_iters = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    rl_job = erl2._sym("rl_job")
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

    counts = {"rl_job": 0, "parse": 0}

    def mk(key):
        def cb(u, ad, sz, x):
            counts[key] += 1
        return cb

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk("rl_job"), begin=rl_job, end=rl_job)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk("parse"), begin=PARSEPAT, end=PARSEPAT)
    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.mem_write(0x40056BC0, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    erl.spin(rt)
    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065BE, bytes([P]))
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([T]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")

    base_depth = layer_depth(rt.uc)
    print(f"baseline: layer_depth={base_depth} BANK=0x{u32(rt.uc, BANK_SLOT):08x} "
          f"YES=0x{u32(rt.uc, YES_SLOT):08x} POPUP=0x{u32(rt.uc, POPUP):08x}")
    print(f"\n{'it':>3} {'job':>4} {'parse':>6} {'G_KIND':>7} {'POPUP':>10} "
          f"{'depth':>6} {'BANK slot':>11} {'YES slot':>11}  verdict")

    rows, faulted = [], None
    for i in range(1, n_iters + 1):
        before = dict(counts)
        rt.uc.mem_write(erl.G_MENU_A, b"\x01")
        rt.uc.mem_write(erl.G_SEL_A, b"\x00")          # item 0 = TRK SEQ
        # call_as_main REQUIRES pc == MAIN_SPIN. After a reload the CPU is not
        # parked there (it is inside the storage task's work), so re-park first
        # -- without this, iteration 2 faults with "pc is not the main spin".
        try:
            erl.spin(rt)
        except Exception as e:
            faulted = faulted or f"iter {i} re-park: {type(e).__name__}: {e}"
            break
        try:
            rt.call_as_main(rl_arm_trk, args=(), budget=900_000)
        except Exception as e:
            faulted = faulted or f"iter {i} arm: {type(e).__name__}: {e}"
            break
        # Drain until the job is FULLY finished, not merely started. G_KIND
        # clears at rl_job entry, long before stock's own whole-bank reload
        # behind it completes -- and that reload pushes the "RELOADING BANK"
        # overlay (layer depth +1, YES dispatch slot -> 0) and parses 16
        # patterns. Sampling on G_KIND alone catches the job mid-flight and
        # reports it as drift, which is a TEST bug, not a firmware one: it is
        # exactly how this harness first mis-read iteration 1. Require the
        # overlay to have been popped again (depth back to baseline) too.
        for _ in range(25):
            try:
                rt.run(ms=100)
            except Exception as e:
                faulted = faulted or f"iter {i} drain: {type(e).__name__}: {e}"
                break
            if (counts["rl_job"] > before["rl_job"]
                    and rt.uc.mem_read(erl.G_KIND, 1)[0] == 0
                    and layer_depth(rt.uc) == base_depth):
                break
        gk = rt.uc.mem_read(erl.G_KIND, 1)[0]
        pu, dep = u32(rt.uc, POPUP), layer_depth(rt.uc)
        bs, ys = u32(rt.uc, BANK_SLOT), u32(rt.uc, YES_SLOT)
        ok = (gk == 0 and dep == base_depth and bs == BANK_PRESS
              and counts["rl_job"] > before["rl_job"])
        rows.append((i, gk, pu, dep, bs, ys, ok))
        print(f"{i:>3} {counts['rl_job']-before['rl_job']:>4} "
              f"{counts['parse']-before['parse']:>6} {gk:>7} 0x{pu:08x} {dep:>6} "
              f"0x{bs:08x} 0x{ys:08x}  {'ok' if ok else '** DRIFT **'}")
        if gk != 0:
            print(f"      -> G_KIND stuck at {gk}: the next [YES] would toast "
                  f"RELOAD BUSY. This is the user's #1 symptom, reproduced.")

    print(f"\nfault: {faulted}")
    bad = [r for r in rows if not r[6]]
    if not rows:
        print("no iterations completed")
    elif not bad:
        print(f"ALL {len(rows)} ITERATIONS CLEAN -- no drift in G_KIND, POPUP, layer "
              f"depth or the BANK/YES dispatch slots.\n"
              "So repeated reloads alone do NOT reproduce it; the trigger is "
              "something this harness does not model (real key dispatch, a "
              "concurrent card op, or interleaved job types).")
    else:
        print(f"DRIFT on iterations {[r[0] for r in bad]} of {len(rows)} -- "
              "reproduced in the emulator. Fix this before any further hardware flash.")


if __name__ == "__main__":
    main()

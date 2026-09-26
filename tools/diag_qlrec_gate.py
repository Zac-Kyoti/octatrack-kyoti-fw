#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 93/94: the toast-gated QLREC flip NEVER FIRES on hardware.

  "The key combo brings up the initial QLREC state toast. Subsequent presses of
   PLAY while REC is held are not switching the feature on and off."

The cave assembles exactly as written (checked), so the wrong thing is my model
of the firmware.  The flip gate is

    G_OWN == MAGIC  &&  *0x460d1e70 != 0  &&  *0x460d1e6c > 0

so this probe asks the REAL firmware, after a REAL project load, three things:

  A.  After NOTIFY(text, LIVE_DUR), what are the handle and countdown actually
      set to?
  B.  How fast does the countdown really tick, and how long does the toast
      actually stay open in emulated milliseconds?  This settles the 60 Hz vs
      120 Hz question left open in Session 93 -- and therefore whether 0x30 is
      0.8 s or 0.4 s.
  C.  Press 1 of the gesture falls through to stock, which STARTS LIVE
      RECORDING and tail-jumps to FUN_4007e998(4) -- a mode-enter dispatcher
      ending in a full redraw (jmp 0x400136a8).  That runs AFTER our toast is
      opened.  Does it destroy the toast (clearing the handle) and so shut the
      gate before the user's second press can ever reach it?

C is the prime suspect: it would leave the toast visible-then-gone and the gate
permanently shut, which is exactly the reported behaviour.

Usage:  python3 tools/diag_qlrec_gate.py
"""
import os
import pathlib
import re
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED_IMAGE = ROOT / "out" / "mainos_qlrec.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402

NOTIFY = 0x4005A2B8
NOTIF_H = 0x460D1E70          # window handle: 0 == nothing on screen
NOTIF_T = 0x460D1E6C          # remaining duration: 0 == expired
MODE_ENTER = 0x4007E998       # stock's live-rec-start tail: FUN_4007e998(mode)
LIVE_REC = 0x460D172A


def _sym(name):
    nm = (ROOT / "out/patch_qlrec.elf")
    import subprocess
    out = subprocess.run(["m68k-elf-nm", str(nm)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    sys.exit(f"symbol {name} not found -- run tools/build_qlrec.py")


def _equ(name):
    src = (ROOT / "tools/patch_qlrec.s").read_text()
    m = re.search(rf"^\s*\.equ\s+{name},\s*(0x[0-9a-fA-F]+|\d+)", src, re.M)
    return int(m.group(1), 0)


MSG_ON = _sym("qlr_msg_on")
LIVE_DUR = _equ("LIVE_DUR")


def rd(rt, a):
    return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]


def rds(rt, a):
    return struct.unpack(">i", rt.uc.mem_read(a, 4))[0]


def boot(tag):
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(PATCHED_IMAGE), card, tick=True)
    print(f"\n=== {tag} ===")
    mounted, *_rest, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"  project load: mounted={mounted} ({elapsed:.0f} ms)")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    return rt


def part_ab():
    """A: what NOTIFY actually sets.  B: how fast it really ticks."""
    rt = boot("A+B: open a toast and watch the OS count it down")
    print(f"  before NOTIFY:  handle=0x{rd(rt, NOTIF_H):08x}  countdown={rds(rt, NOTIF_T)}")
    rt.call_as_main(NOTIFY, args=(MSG_ON, LIVE_DUR), budget=4_000_000)
    h0, t0 = rd(rt, NOTIF_H), rds(rt, NOTIF_T)
    print(f"  after  NOTIFY:  handle=0x{h0:08x}  countdown={t0}  (LIVE_DUR={LIVE_DUR})")
    if h0 == 0 or t0 != LIVE_DUR:
        print("  !! the handle/countdown are NOT what the gate assumes -- stop here")
        return None

    t_start = rt.sample
    samples = []
    closed_at = None
    for _ in range(400):
        rt.run(ms=25)
        ms = (rt.sample - t_start) / er.SAMPLE_HZ * 1000.0
        h, t = rd(rt, NOTIF_H), rds(rt, NOTIF_T)
        samples.append((ms, h, t))
        if h == 0 or t <= 0:
            closed_at = ms
            break
    print("\n     elapsed ms   handle      countdown")
    for ms, h, t in samples[:6]:
        print(f"     {ms:9.1f}   0x{h:08x}  {t}")
    if len(samples) > 8:
        print("        ...")
        for ms, h, t in samples[-3:]:
            print(f"     {ms:9.1f}   0x{h:08x}  {t}")

    ticked = [s for s in samples if s[2] != t0]
    if not ticked:
        print(f"\n  !! the countdown NEVER MOVED in {samples[-1][0]:.0f} ms of emulated time.")
        print("     The OS is not ticking it in this state -- the gate would stay OPEN,")
        print("     not shut, so this alone does not explain the hardware report.")
        return None
    if closed_at:
        rate = LIVE_DUR / (closed_at / 1000.0)
        print(f"\n  toast closed after {closed_at:.1f} ms  ->  {rate:.1f} ticks/s")
        print(f"  so LIVE_DUR={LIVE_DUR} is really {closed_at / 1000.0:.3f} s on screen")
    return closed_at


def part_c():
    """C: does stock's live-rec mode-enter destroy our toast?"""
    rt = boot("C: does FUN_4007e998(4) -- stock's live-rec tail -- kill the toast?")
    rt.call_as_main(NOTIFY, args=(MSG_ON, LIVE_DUR), budget=4_000_000)
    h0, t0 = rd(rt, NOTIF_H), rds(rt, NOTIF_T)
    print(f"  toast open:            handle=0x{h0:08x}  countdown={t0}")

    try:
        rt.call_as_main(MODE_ENTER, args=(4,), budget=8_000_000)
    except Exception as e:
        print(f"  FUN_4007e998(4) did not return cleanly: {type(e).__name__}: {e}")
    h1, t1 = rd(rt, NOTIF_H), rds(rt, NOTIF_T)
    print(f"  after FUN_4007e998(4): handle=0x{h1:08x}  countdown={t1}")

    rt.run(until=lambda r: r.pc == er.MAIN_SPIN, max_bursts=200000)
    h2, t2 = rd(rt, NOTIF_H), rds(rt, NOTIF_T)
    print(f"  after it settles:      handle=0x{h2:08x}  countdown={t2}")

    print()
    if h1 == 0 or h2 == 0:
        print("  *** CONFIRMED: entering live-rec mode DESTROYS the notification.")
        print("      Press 1 opens the toast and then stock tears it down, so by the")
        print("      time press 2 arrives the gate is shut -- exactly the report.")
    else:
        print("  Toast SURVIVES the mode-enter; this is not the cause.")
    return h1, h2


def main():
    if not PATCHED_IMAGE.exists():
        sys.exit(f"missing {PATCHED_IMAGE} -- run tools/build_qlrec.py first")
    print(f"LIVE_DUR = {LIVE_DUR}   qlr_msg_on = 0x{MSG_ON:08x}")
    part_ab()
    part_c()


if __name__ == "__main__":
    main()

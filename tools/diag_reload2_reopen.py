#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Diagnostic for the user's hardware report (Session 80 continued): after RELOAD2
successfully executes one TRK SEQ reload, holding [PTN] again stops opening the
picker at all -- permanently, regardless of further saves/reloads/edits.

v3 -- v1 (x2) and v2 were all invalidated by tooling mistakes, in order:
  - a race with a concurrent rebuild;
  - forgetting emu_reload2.py's own OUR_IMAGE reassignment (booted stock, not
    the patched image);
  - reusing cmd_trk's rl_arm_trk-direct shortcut, which never runs rl_yes's
    real close logic, so G_MENU was stuck at 1 from the TEST's own setup, not
    from anything real;
  - call_as_main(rl_yes, ...) right after cmd_trk faulted immediately --
    `pc is 0x40004826, not the main spin` -- because call_as_main REQUIRES
    self.pc == MAIN_SPIN as a precondition (checked at its very first line,
    per its own docstring: "run with until=lambda r: r.pc == MAIN_SPIN
    first"), and cmd_trk's own run()-based drain loop does not leave the CPU
    parked there;
  - v2 then called drain(rt, ms=3000) unconditionally even after that fault,
    which ran for 38+ minutes of real wall-clock time before being killed --
    NOT a hang, just requesting far more emulated time in one rt.run() call
    than this full-system (scheduler + every task) emulator can chew through
    quickly. That drain step was also unnecessary: G_MENU clears SYNCHRONOUSLY
    inside rl_yes's own body (clr.b G_MENU + jsr CLOSE_CB, both well before
    jsr rl_arm_trk posts the job and returns) -- nothing about whether the
    SECOND reload's storage-task job later completes affects G_MENU at all,
    so there was never a reason to drain anything here.

v3: re-parks the CPU at MAIN_SPIN (rt.run(until=...)) before the real [YES]
press, drops the unneeded drain, and prints eagerly so a genuinely slow step
is visible rather than silent. Run this WITHOUT piping through `tail` when
backgrounding -- `tail` (no -f) buffers an entire pipe until EOF, so nothing
is visible until the process exits; read the raw output file directly
instead.

STATUS: v3 still never reached a verdict. Re-parking at MAIN_SPIN after
cmd_trk's own reload cost ~5 minutes of real wall-clock time PER 100ms of
emulated time (residual storage-task/deserializer work from cmd_trk's own
reload still unwinding -- pc bounced between FUN_4008ded0 and other real
kernel addresses across iterations, making no fast forward progress toward
the spin), so it was killed after ~19 minutes rather than let run for
what could have been a very long time with no guaranteed end.

This was abandoned in favour of a cheaper, more decisive approach that
actually led to a fix: a static disassembly of FUN_40022778 (the storage-
task job poster) found it always builds its message in ONE FIXED scratch
buffer (0x460bd912) rather than a per-call queue slot -- a second post
before the first is drained is a real, plausible way for a request to get
silently overwritten/coalesced (fully confirming that would need tracing
the kernel post primitive 0x40000c3c itself, not attempted). Rather than
keep chasing an exact repro, patch_reload2.s / build_reload2.py were changed
to make G_KIND's stuck-state UNRECOVERABLE-BY-DESIGN impossible instead:
rl_ptn no longer gates opening the picker on G_KIND at all (so a stuck flag
can never again permanently lock out the feature, matching the user's
"stops working entirely, no recovery" report), and the re-entrancy guard
moved to rl_yes_exec (refuses to arm+post a NEW request while G_KIND is
still nonzero, toasts "RELOAD BUSY" instead of silently corrupting or doing
nothing). See patch_reload2.s's own Session-80-continued comments and
NOTES.md for the full writeup. tools/emu_reload.py's cmd_combo now covers
both new behaviours in isolation (fast, no full-RTOS boot needed).

Kept here, not deleted, as a record of what was tried and why it doesn't
work as constructed -- if a future session wants a REAL dynamic repro of
the exact FUN_40022778 coalescing race, this is the starting point, but
expect it to need either a much bigger time budget or a smarter way to
skip past the residual storage-task work than brute-force re-parking.

Usage: python3 tools/diag_reload2_reopen.py
"""
import sys

import emu_reload2 as erl2         # noqa: E402  (sets erl.RELOAD_IMAGE etc.)
import emu_reload as erl           # noqa: E402

G_KIND, G_PAT, G_MENU, G_SEL = 0x80006a50, 0x80006a51, 0x80006a52, 0x80006a53
POPUP, ARR_ACT, RUNNING = 0x460e5cd0, 0x460d1aec, 0x800065b8
PTN_MODE = 0x460d1742


def g(rt, a, n=1):
    return int.from_bytes(rt.uc.mem_read(a, n), "big")


def main():
    if not erl2._ELF.exists() or not erl.RELOAD_IMAGE.exists():
        sys.exit("missing build outputs -- run python3 tools/build_reload2.py first")
    erl.OUR_IMAGE = erl.RELOAD_IMAGE   # emu_reload2.py's own main() normally does this
    rl_ptn = erl2._sym("rl_ptn")
    rl_yes = erl2._sym("rl_yes")

    rt = erl.boot_and_load()

    print("\n===== step 1: real end-to-end TRK SEQ reload (cmd_trk, known ALL GOOD) =====")
    ok1 = erl.cmd_trk(rt)
    print(f"gates after cmd_trk: G_MENU={g(rt, G_MENU)} G_KIND={g(rt, G_KIND)}  "
          f"(G_MENU=1 here is cmd_trk's OWN test artifact -- it calls rl_arm_trk "
          f"directly and never runs rl_yes's close logic; not evidence of anything yet)")

    print("\n===== step 2: re-park at MAIN_SPIN, then a REAL [YES] press =====")
    # Small ms-sized increments (same chunk size cmd_trk's own drain loop uses,
    # empirically tractable) instead of one large run() call -- a single
    # rt.run(ms=3000) earlier cost 38+ minutes of real wall-clock time before
    # being killed, and a single until=/max_bursts=2_000_000 call left pc still
    # inside FUN_4008ded0 (the bank deserialiser -- still-in-flight storage-task
    # work from cmd_trk's own reload), so this re-parks incrementally with
    # visible per-iteration progress instead of one more blind, possibly-huge
    # blocking call.
    MAIN_SPIN = erl.er.MAIN_SPIN
    for i in range(100):
        if rt.pc == MAIN_SPIN:
            break
        rt.run(ms=100)
        print(f"  re-park iter {i}: pc={rt.pc:#x}", flush=True)
    print(f"re-park result: pc={rt.pc:#x} (want {MAIN_SPIN:#x})")
    if rt.pc != MAIN_SPIN:
        sys.exit("could not re-park at MAIN_SPIN within budget -- can't safely call_as_main")

    rt.uc.mem_write(G_MENU, b"\x01")
    rt.uc.mem_write(G_SEL, b"\x00")     # TRK SEQ highlighted
    faulted = None
    try:
        rt.call_as_main(rl_yes, args=(0x31, 1), budget=900_000)
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"
    print(f"immediately after real [YES]: G_MENU={g(rt, G_MENU)} G_KIND={g(rt, G_KIND)} fault={faulted}")

    print(f"\ngates before the 2nd [PTN] hold: G_MENU={g(rt, G_MENU)} G_KIND={g(rt, G_KIND)} "
          f"POPUP={g(rt, POPUP, 4)} ARR_ACT={g(rt, ARR_ACT, 4)} RUNNING={g(rt, RUNNING, 4)} "
          f"PTN_MODE={g(rt, PTN_MODE, 4)}")

    print("\n===== step 3: a SECOND real [PTN] hold press (via _run_cave_fn, matching cmd_combo) =====")
    calls = []
    end = erl._run_cave_fn(rt, rl_ptn, 0x2e, 2, calls)
    gm2 = g(rt, G_MENU)
    print(f"end={end}  G_MENU={gm2}  G_SEL={g(rt, G_SEL)}  popup2_called={0x4005a0e0 in calls}  "
          f"PTN_USED={g(rt, 0x460d173e, 4)}")

    reopened = gm2 == 1 and 0x4005a0e0 in calls
    print(f"\n{'PICKER REOPENED -- bug NOT reproduced in emulation' if reopened else 'PICKER DID NOT REOPEN -- bug reproduced'}")
    if not reopened:
        blockers = []
        if g(rt, G_MENU) not in (0, 1):
            blockers.append(f"G_MENU={g(rt, G_MENU)} (unexpected)")
        elif g(rt, G_MENU) == 1:
            blockers.append("G_MENU already 1 going in (the close in step 2 didn't take)")
        if g(rt, POPUP, 4) != 0:
            blockers.append("POPUP != 0")
        if g(rt, ARR_ACT, 4) != 0:
            blockers.append("ARR_ACT != 0")
        if g(rt, G_KIND) != 0:
            blockers.append(f"G_KIND={g(rt, G_KIND)} != 0 (still armed/latched)")
        print("likely blocking gate(s):", ", ".join(blockers) if blockers else
              "NONE OF THE KNOWN GATES -- something else is wrong (or this doesn't reproduce here)")

    return ok1 and reopened


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)

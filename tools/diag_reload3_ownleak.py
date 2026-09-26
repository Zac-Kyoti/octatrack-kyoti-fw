#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_ownleak -- a FAILED reload must not disable stock's own RELOAD BANK.

Session 90, hardware report #13: "the sequence data was reloaded as empty, and from that
point on, any reload action would not bring back the CF card-saved sequence. In fact, in
that state, even the OT's stock 'Reload current bank' from the project menu, would not
bring back the saved sequence data. Reloading the project did restore it."

THE DIAGNOSIS IS IN THAT LAST SENTENCE
rl_own is the one-shot "the whole-bank reload this job is about to do is redundant,
suppress it" flag. It used to be set EARLY in rl_job, before the file was even opened.
But stock's doneFn only reaches rl_done on its SUCCESS path (0x40023c0e `bge.s
0x40023c62`), so a failed job -- FOPEN, FREAD or PARSEPAT -- left the flag SET forever.
The next type-0x14 job from ANY source then hit rl_done, saw the stale flag, and skipped
the whole-bank reload at 0x40023b68 entirely, INCLUDING the user's own stock RELOAD
CURRENT BANK. Reloading the project does not use that doneFn, which is why only that
recovered. And each new chord re-set the flag, so the state stuck rather than costing a
single reload.

FIX UNDER TEST: clear rl_own at job start, set it ONLY after the copy has succeeded.

** CORRECTION, made while writing this test's first draft. ** I initially claimed a
failed job would leave stock's own whole-bank reload (0x40023b68) to run as a fallback --
"self-heals by the slow path". That is WRONG, and tracing doneFn's actual branch
(0x40023bf4) disproves it: it tests OUR job's own result code (the arg at sp+12, called
d2 here) and takes the 0x40023c62 (whole-bank reload) path ONLY when d2 >= 0. On failure
(d2 == -12, or any other negative) it shows a STOCK ERROR TOAST instead -- "THIS BANK HAS
NEVER BEEN SAVED!" for -12, a generic one otherwise -- and never falls through to the
reload at all. This is the right design on stock's part: 0x40023b68 reads the SAME bank
file our job just failed to read, so a genuine open/read failure would fail there too;
retrying via that path could not have helped.

So the fix's real and only claim is narrower: a failed job must not leave rl_own STUCK
for every SUBSEQUENT job. Before the fix, rl_own was set unconditionally at job start,
so any failure left it set forever -- and the NEXT type-0x14 job, from ANY source
(including the user's own stock RELOAD CURRENT BANK), would see the stale flag and be
wrongly suppressed. That is the exact hardware report: "even the OT's stock 'Reload
current bank'... would not bring back the saved sequence data."

WHAT IS ASSERTED
  success: the copy happens, rl_own ends at 0, and 0x40023b68 does NOT run (the
           6852-read optimisation is still in force)
  FAILURE: forced by stubbing FOPEN to return -1. rl_own must end at 0 -- NOT because
           anything reloads on this attempt (nothing does, and nothing should), but
           because the flag must not be left set for whatever job comes next
  then:    a THIRD, unrelated success must suppress normally -- proving the failure
           left nothing stranded to interfere with it. This is the assertion that
           actually matches the hardware report, not "failure self-heals".

Usage:
  python3 tools/diag_reload3_ownleak.py [--track N]
"""
import argparse
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE = 0x2E
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

WHOLE_BANK = 0x40023B68        # the reload rl_done suppresses
FOPEN = 0x40016864
G_KIND = 0x80006A50


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, default=3)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(rt.uc.mem_read(0x80000002, 1)[0], P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : pattern={P}")

    nm = subprocess.run(["m68k-elf-nm", "out/patch_reload3.elf"],
                        capture_output=True, text=True, cwd=ROOT).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines())
           if len(q) == 3}
    RL_OWN = sym["rl_own"]
    print(f"rl_own @ {RL_OWN:#x}")

    C = {"job": 0, "done": 0, "whole": 0, "copy": 0}

    def bump(k):
        return lambda u, ad, sz, x: C.__setitem__(k, C[k] + 1)
    for addr, k in ((sym["rl_job"], "job"), (sym["rl_done"], "done"),
                    (WHOLE_BANK, "whole"), (sym["rlj_setflag"], "copy")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, bump(k), begin=addr, end=addr)
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    for _ in range(20):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def fire():
        key(PTN_CODE, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(PTN_CODE, RELEASE)
        for _ in range(250):
            rt.run(ms=10)
            if rt.uc.mem_read(G_KIND, 1)[0] == 0:
                break
        for _ in range(12):
            rt.run(ms=60)

    def own():
        return rt.uc.mem_read(RL_OWN, 1)[0]

    def snap():
        return dict(C)

    def d(b):
        return {k: C[k] - b[k] for k in C}

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    # ---------- 1. the healthy case ----------
    print("\n--- SUCCESS: our copy runs, stock's whole-bank reload is suppressed ---")
    b = snap()
    fire()
    dd = d(b)
    print(f"   job={dd['job']} copy={dd['copy']} rl_done={dd['done']} "
          f"wholebank={dd['whole']} rl_own={own()}")
    chk(dd["copy"] >= 1, f"our copy path ran (x{dd['copy']})")
    chk(dd["whole"] == 0,
        f"stock's whole-bank reload was suppressed (x{dd['whole']}) -- the "
        f"6852-read saving is intact")
    chk(own() == 0, f"rl_own consumed, back to 0 (={own()})")

    # ---------- 2. the reported failure ----------
    print("\n--- FAILURE (FOPEN stubbed to -1): stock's reload MUST take over ---")
    save = bytes(rt.uc.mem_read(FOPEN, 4))
    rt.uc.mem_write(FOPEN, bytes([0x70, 0xFF, 0x4E, 0x75]))   # moveq #-1,d0 ; rts
    rt.uc.ctl_flush_tb()
    b = snap()
    fire()
    dd = d(b)
    print(f"   job={dd['job']} copy={dd['copy']} rl_done={dd['done']} "
          f"wholebank={dd['whole']} rl_own={own()}")
    chk(dd["job"] >= 1, f"the job still ran (x{dd['job']}) -- gate: the test is live")
    chk(dd["copy"] == 0,
        f"our copy did NOT happen (x{dd['copy']}) -- gate: the failure is real")
    chk(own() == 0,
        f"** rl_own NOT left set after a failed job (={own()}) ** -- this is the "
        f"stranded flag that disabled stock RELOAD BANK on the NEXT attempt")
    chk(dd["whole"] == 0,
        f"stock's whole-bank reload did NOT run here either (x{dd['whole']}) -- "
        f"correctly: it reads the same file, which just failed the same way. "
        f"doneFn's own branch (0x40023c0e) never reaches it on a negative result.")

    # ---------- 3. no flag stranded: the next job behaves normally again ----------
    print("\n--- RECOVERY: un-stub, and the next reload must suppress again ---")
    rt.uc.mem_write(FOPEN, save)
    rt.uc.ctl_flush_tb()
    b = snap()
    fire()
    dd = d(b)
    print(f"   job={dd['job']} copy={dd['copy']} wholebank={dd['whole']} "
          f"rl_own={own()}")
    chk(dd["copy"] >= 1, f"our copy ran again (x{dd['copy']})")
    chk(dd["whole"] == 0,
        f"and is suppressed again (x{dd['whole']}) -- nothing was stranded either way")
    chk(own() == 0, f"rl_own back to 0 (={own()})")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- a failed reload leaves stock's own reload free to run, and "
          "no flag is stranded in either direction.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

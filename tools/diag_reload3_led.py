#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_led -- EMPTY the active pattern, reload, and ask the FIRMWARE whether the
CF-saved trigs came back. Repeat. The user's own test design, and a better one than mine.

THE USER'S FRAMING (hardware report #14 follow-up)
  "run a number of reloads in the emulator, with a test project that has a single trig on
   step 1, and check the trig led state after every reload (on = success, off = fail) ...
   the SAVED pattern has a trig on step 1, and the active pattern has no trigs placed ...
   SAVED pattern = what is on the CF card"

WHY THIS BEATS WHAT I HAD BEEN RUNNING
  diag_reload3_repeat.py dirties the pattern with `mask ^ 0xFF` and then compares BYTES.
  Two problems, both mine:
    1. XOR turns 00000001.. into fffffffe.. -- MORE trigs plus garbage, not the "no trigs
       placed" state the user actually reloads from. Nothing tested the empty -> populated
       direction, which is the one a cached "this pattern is empty" would break.
    2. A byte compare reads the INTERMEDIATE. The user reads the LED. If the data is
       restored but nothing recomputes the display/content state, my check passes and the
       user sees nothing change -- exactly the reported symptom.
  This repo has already found one stock bug in precisely that machinery: Session 48,
  FUN_4009a464 computed pattern-content from trig masks only, so a p-lock-only pattern
  read as EMPTY and its PTN grid LED stayed unlit (tools/patch_pattern_led.s).

WHAT IS ASSERTED, PER ITERATION
  empty    clear EVERY track's trig masks in the active pattern, then GATE on the
           firmware's own predicate HAS_CONTENT (0x4009a464) returning 0 -- the firmware
           must AGREE the pattern is empty, or the reload has nothing to prove.
  reload   fire the chord, wait for the worker's own success point (rlj_setflag), not a
           fixed delay.
  led      HAS_CONTENT must return non-zero again -- "on = success, off = fail".
  bytes    and the track's masks must match the CF-saved values, so a pass cannot come
           from HAS_CONTENT reacting to something else.

LIMITATION, STATED PLAINLY: HAS_CONTENT is invoked as a cold call, so it RECOMPUTES.
If the real defect is a cached LED byte that nothing ever recomputes, this recompute
would hide it. This test therefore proves the DATA and the PREDICATE agree; it cannot
prove the panel was repainted. That would need the UI's own cached byte, which is not
yet identified in this repo.

Usage: python3 tools/diag_reload3_led.py [-n N] [--track N] [--chord ptn|bank]
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
from cave_syms import syms        # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE, BANK_CODE, TRACK0 = 0x2E, 0x2F, 0x10
PRESS, RELEASE = 1, 0
HAS_CONTENT = 0x4009A464       # the firmware's pattern-content predicate (grid LED)

BLOB = 0x400E21E0
BANKSTRIDE, PATSTRIDE = 0x9B340, 0x8ED8
TRAC_A, MIDI_BASE, TRAC_M = 0x91A, 0x48D0, 0x8B0
MASK_LEN = 0x10
PLAY_BANK, ACT_PAT = 0x800065BD, 0x800065BE


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--chord", choices=("ptn", "bank"), default="ptn")
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail[:150])

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    b0 = rt.uc.mem_read(0x80000002, 1)[0]
    rt.seq_select_live(b0, P)
    rt.internal_clock(); rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD; rt.exact_clock()
    rt.start_transport_live()
    for _ in range(10):
        rt.run(ms=60)

    S = syms()
    SETFLAG = S["rlj_setflag"]
    bank, pat = rt.uc.mem_read(PLAY_BANK, 1)[0], rt.uc.mem_read(ACT_PAT, 1)[0]
    slab = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE
    tmask = slab + a.track * TRAC_A
    saved = bytes(rt.uc.mem_read(tmask, MASK_LEN))
    print(f"load : bank={bank} pattern={pat} track={a.track+1} chord={a.chord}")
    print(f"   CF-saved trig masks for this track = {saved.hex()}")
    if saved == b"\x00" * MASK_LEN:
        sys.exit("GATE FAIL: the CF-saved masks for this track are EMPTY, so 'the trigs "
                 "came back' is unprovable. Choose a track with trigs via --track.")

    # every track's mask window, so the pattern can be made genuinely empty
    windows = [slab + t * TRAC_A for t in range(8)]
    windows += [slab + MIDI_BASE + t * TRAC_M for t in range(8)]
    originals = {w: bytes(rt.uc.mem_read(w, MASK_LEN)) for w in windows}

    okflag = {"n": 0}
    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                   lambda u, ad, sz, x: okflag.__setitem__("n", okflag["n"] + 1),
                   begin=SETFLAG, end=SETFLAG)

    def spin():
        rt.run(until=lambda s: s.pc == er.MAIN_SPIN)

    def has_content():
        spin()
        return rt.call_as_main(HAS_CONTENT, args=(pat & 0xFFFFFFFF, bank & 0xFFFFFFFF))

    def key(c, e):
        spin()
        rt.call_as_main(SET_KEY_STATE, args=(c, e), budget=4_000_000)

    hold = PTN_CODE if a.chord == "ptn" else BANK_CODE
    fails, rows = [], []

    for it in range(1, a.n + 1):
        # ---- make the ACTIVE pattern empty: no trigs placed, on any track ----
        for w in windows:
            rt.uc.mem_write(w, b"\x00" * MASK_LEN)
        before_ok = okflag["n"]
        empty_pred = has_content()
        if empty_pred:
            fails.append(f"iter {it}: GATE -- the firmware still reports content "
                         f"({empty_pred}) after clearing every trig mask, so 'the trigs "
                         f"came back' below would prove nothing. Content must live "
                         f"somewhere these 16 windows do not cover.")
            break

        key(hold, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(hold, RELEASE)
        # wait for the worker's OWN success point, not a fixed delay
        for _ in range(300):
            rt.run(ms=20)
            if okflag["n"] > before_ok:
                break
        for _ in range(4):
            rt.run(ms=60)

        got = bytes(rt.uc.mem_read(tmask, MASK_LEN))
        led = has_content()
        row = {"it": it, "led": led, "bytes_ok": got == saved,
               "succeeded": okflag["n"] - before_ok, "got": got.hex()}
        rows.append(row)
        print(f"   iter {it}: LED={'ON ' if led else 'OFF'}  "
              f"trigs_restored={row['bytes_ok']}  worker_succeeded={row['succeeded']}  "
              f"masks={row['got']}")

    print("\n--- verdict ---")
    if rows:
        off = [r["it"] for r in rows if not r["led"]]
        badb = [r["it"] for r in rows if not r["bytes_ok"]]
        nosucc = [r["it"] for r in rows if r["succeeded"] == 0]
        if nosucc:
            fails.append(f"the worker never reached rlj_setflag on iteration(s) {nosucc} "
                         f"-- gate: any verdict there is meaningless")
        if off:
            fails.append(f"** the LED read OFF after iteration(s) {off} of {len(rows)} -- "
                         f"the reload did not bring the CF-saved trigs back. Report #14 "
                         f"item 1 REPRODUCED. **")
        if badb:
            fails.append(f"the trig masks did not match the CF-saved bytes on "
                         f"iteration(s) {badb}")
        if not (off or badb or nosucc):
            print(f"   all {len(rows)} reloads: LED ON and masks match the CF-saved bytes")

    print()
    if fails:
        print(f"   {len(fails)} FINDING(S):")
        for f in fails:
            print(f"     - {f}")
        return 1
    print(f"   ALL GOOD -- empty -> reload -> trigs back, {len(rows)} times.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

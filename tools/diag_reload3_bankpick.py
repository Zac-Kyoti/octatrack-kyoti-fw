#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_bankpick -- hardware report #14 item 2, the exact reported gesture.

  "when holding bank > select a bank trig > select a pattern trig > release bank, the
   'select bank' toast with countdown appears. I don't want this -- selecting a pattern
   should disable the on-release bank behavior."

WHY diag_reload3_bankdefer.py DOES NOT COVER THIS
  That test only ever presses [BANK] and [TRACK n]. It never presses a TRIG while [BANK]
  is held, so BANK_SEL (0x460e73c6) is 0 on every one of its releases -- the one value
  for which the fix changes nothing. It passed before the fix and after it. This file
  drives the trigs.

THE FIX UNDER TEST (tools/patch_reload3.s, rl3_bank_rel)
  Stock's release 0x4007b3e0 opens `cmpl 0x460e73c6,#2 ; beq -> DISMISS` BEFORE testing
  BANK_COMMIT. Session 86 inverted that order, so a pick during the hold was never
  noticed -- BANK_COMMIT is set by the pick itself (0x4007b33c) as well as by the hold
  handler (0x4007af24). The fix restores stock's ordering: `tst.l BANK_SEL ; bne ->
  r3r_stock`.

BANK_SEL, measured at the [BANK]-overlay trig handler 0x4007b2fc:
  0  nothing picked      (the show tail 0x4007af30 clears it on every press)
  1  a BANK was picked   (0x4007b276; also a "SELECT PATTERN IN BANK x" window of its own)
  2  a PATTERN picked    (0x4007b3d2)

WHAT IS ASSERTED
  * the reported gesture (bank trig THEN pattern trig) shows SELECT BANK zero times.
  * the un-reported half -- bank trig only, no pattern -- also shows it zero times.
  * GATES, so a pass cannot be vacuous:
      - a plain [BANK] tap DOES still show it (the hook works, and zero above is real)
      - the bank pick actually TOOK (BANK_SEL advanced past 0); a pick can be refused at
        0x4007b30c when the bank is unavailable, and then the test proves nothing
  * the [BANK] overlay is not left linked afterwards (octalab's stranded-overlay mode).

Usage:
  python3 tools/diag_reload3_bankpick.py [--bank N] [--pattern N]
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
BANK_CODE = 0x2F
PRESS, RELEASE = 1, 0

SHOW_WIN = 0x40059F8C          # FUN_40059f8c(text, dur, flag, onClose)
BANK_TEXT = 0x400B7302         # "SELECT BANK"
BANK_SEL = 0x460E73C6          # LONGWORD -- stock uses movel/tstl/cmpl on it
                               # (0x4007b276, 0x4007b3d2, 0x4007b3e2). Reading it
                               # as ONE BYTE returns the big-endian TOP byte, i.e.
                               # 0 for values 1 and 2 -- which is exactly how this
                               # test first reported a vacuous-gate failure while
                               # the firmware was behaving correctly.
BANK_COMMIT = 0x460E73C2
BANK_LAYER = 0x400CFF14
LAYER_HEAD = 0x460D165C        # the keymap layer list head (MEASURED value
                               # diag_reload3_bankdefer.py uses; my first guess
                               # 0x460e7624 is the BANK_UI head, a DIFFERENT list)
BANK_AVAIL = 0x4017D516        # per-bank word the trig handler tests at
                               # 0x4007b30c: non-zero -> the pick is REFUSED
BANK_REFUSED_TOAST = 0x400B7322
CUR_BANK = 0x80000002
BANKSTRIDE = 0x9B340


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=int, default=1)
    ap.add_argument("--pattern", type=int, default=2)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        print(f"!! emac_selftest FAILED: {detail[:120]}")
        print("!! continuing anyway -- this test exercises keymap/window code, not EMAC "
              "arithmetic. Recorded so the result is not mistaken for a clean-harness pass.")

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    bank = rt.uc.mem_read(CUR_BANK, 1)[0]
    rt.seq_select_live(bank, P)
    print(f"load : bank={bank} pattern={P}")

    shows = {"n": 0, "other": 0}

    def on_show(uc, address, size, ud):
        # arg1 = text pointer, at 4(sp) on entry. m68k's stack pointer is A7 -- there is
        # no UC_M68K_REG_SP. Same hook body diag_reload3_bankdefer.py has used since
        # Session 86, reused rather than reinvented.
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        txt = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
        if txt == BANK_TEXT:
            shows["n"] += 1
        else:
            shows["other"] += 1

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_show, begin=SHOW_WIN, end=SHOW_WIN)

    # ---- trace every write to BANK_SEL, with the PC that did it ----
    # Only three writers exist in stock: 0x4007af30 (clr, the show tail), 0x4007b276
    # (=1, bank picked) and 0x4007b3d2 (=2, pattern picked). A read of 0 right after an
    # accepted pick means the show tail ran in between -- this says which, and when.
    trace = []

    def on_sel_write(uc, access, address, size, value, ud):
        trace.append((uc.reg_read(er.eb.UC_M68K_REG_PC), value))
        return True

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_sel_write,
                   begin=BANK_SEL, end=BANK_SEL + 3)

    def dump_trace(tag):
        names = {0x4007AF30: "show-tail CLR", 0x4007B276: "bank picked =1",
                 0x4007B3D2: "pattern picked =2"}
        print(f"   BANK_SEL writes during {tag}:")
        if not trace:
            print("      (none)")
        for pc, v in trace:
            print(f"      pc={pc:#010x} -> {v}   {names.get(pc & ~1, names.get(pc, '?'))}")
        trace.clear()

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def drain(n=4, ms=60):
        for _ in range(n):
            rt.run(ms=ms)

    def rb(ad):
        return rt.uc.mem_read(ad, 1)[0]

    def u32(ad):
        return int.from_bytes(rt.uc.mem_read(ad, 4), "big")

    def bank_layer_linked():
        # the list is singly linked through offset 0, NOT +4 -- same walk
        # diag_reload3_bankdefer.py has used since Session 86. My own first version
        # followed +4 and died on UC_ERR_READ_UNMAPPED.
        node, n, seen = u32(LAYER_HEAD), 0, False
        while node and n < 64:
            if node == BANK_LAYER:
                seen = True
            node = u32(node)
            n += 1
        return seen

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    # ---------- GATE: a plain tap must still show it ----------
    print("\n--- GATE: a plain [BANK] tap must STILL show SELECT BANK on release ---")
    shows["n"] = 0
    key(BANK_CODE, PRESS); drain(4)
    key(BANK_CODE, RELEASE); drain(6)
    chk(shows["n"] == 1,
        f"plain tap showed SELECT BANK exactly once (n={shows['n']}) -- GATE: proves the "
        f"hook fires and that a zero below is a real absence, not a blind detector")
    key(BANK_CODE, PRESS); drain(3); key(BANK_CODE, RELEASE); drain(6)   # toggle back off

    # ---------- the REPORTED gesture ----------
    print(f"\n--- REPORTED: hold [BANK], bank trig {a.bank}, pattern trig {a.pattern}, "
          f"release ---")
    shows["n"] = 0
    key(BANK_CODE, PRESS); drain(4)
    key(a.bank, PRESS); key(a.bank, RELEASE); drain(4)
    sel_after_bank = u32(BANK_SEL)
    dump_trace("the BANK press + bank trig")
    key(a.pattern, PRESS); key(a.pattern, RELEASE); drain(4)
    sel_after_pat = u32(BANK_SEL)
    dump_trace("the pattern trig")
    print(f"   BANK_SEL: after bank trig={sel_after_bank}, after pattern trig="
          f"{sel_after_pat}  (BANK_COMMIT={u32(BANK_COMMIT)})")
    avail = u32(BANK_AVAIL + a.bank * BANKSTRIDE)
    print(f"   availability word for bank {a.bank} (0x4007b30c's test, "
          f"{BANK_AVAIL + a.bank * BANKSTRIDE:#x}) = {avail:#x}  "
          f"-> {'REFUSED (non-zero)' if avail else 'accepted (zero)'}")
    print(f"   non-SELECT-BANK windows seen during the gesture: {shows['other']}")
    if sel_after_bank == 0:
        print("   >> the pick did NOT take, so 'SELECT BANK not shown' below is VACUOUS: "
              "BANK_SEL==0 is the one value for which the fix changes nothing. Reported "
              "as a gate failure, not a pass.")
    chk(sel_after_bank != 0,
        f"the BANK pick actually TOOK (BANK_SEL={sel_after_bank} != 0) -- GATE: a pick can "
        f"be refused at 0x4007b30c when the bank is unavailable, and the assert below "
        f"would then pass for the wrong reason")
    key(BANK_CODE, RELEASE); drain(8)
    chk(shows["n"] == 0,
        f"** SELECT BANK was NOT shown on release (n={shows['n']}) ** -- report #14 item 2")
    chk(not bank_layer_linked(),
        "the [BANK] overlay is not left linked -- no stranded trig remap")

    # ---------- the UN-REPORTED half: bank only, no pattern ----------
    print(f"\n--- UN-REPORTED half: hold [BANK], bank trig {a.bank} only, release ---")
    shows["n"] = 0
    key(BANK_CODE, PRESS); drain(4)
    key(a.bank, PRESS); key(a.bank, RELEASE); drain(4)
    sel_only = u32(BANK_SEL)
    key(BANK_CODE, RELEASE); drain(8)
    print(f"   BANK_SEL after the bank trig = {sel_only}")
    chk(shows["n"] == 0,
        f"SELECT BANK not drawn over 'SELECT PATTERN IN BANK x' (n={shows['n']}) -- the "
        f"half the user did not report, fixed by the same test")

    print()
    if fails:
        print(f"   {len(fails)} FAILURE(S):")
        for f in fails:
            print(f"     - {f}")
        return 1
    print("   ALL GOOD -- a pick during the hold cancels the release show, both variants.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

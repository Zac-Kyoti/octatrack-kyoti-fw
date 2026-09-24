#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_bankdefer -- SELECT BANK must open on the [BANK] RELEASE, not the press.

Session 86, hardware report #9 item 2: "A BANK tap still brings up SELECT BANK
countdown on press, not release. I want it on release, like PTN does."

** This is the item that already failed on hardware once ** (Session 80 continued
(3)/(7)), so it gets its own harness rather than riding on the chord suite. What was
different then: that build also carried the picker, its own keymap layer and a poked
YES slot. Here the only moving part is the show itself. That is an argument for
retrying, not evidence that it works -- hence the assertions below.

THE STOCK STATE MACHINE, measured (see patch_reload3.s for the full decode):
  press  0x4007af80 -> BANK_COMMIT = (0x460e73bc == 0)  [a TOGGLE] -> shared tail
  tail   0x4007af30 -> clears BANK_SEL/0x460e73b8/0x460e73bc, SHOW_WIN, LAYER_PUSH,
                       two more UI calls, then `lea 28(sp),sp ; rts`
  rel    0x4007b3e0 -> BANK_SEL==2 or BANK_COMMIT==0 ? dismiss : commit-and-stick

WHAT IS ASSERTED
  * while [BANK] is HELD, the 16 TRIG keys must be REMAPPED off their base handler
    0x40060ce0 -- i.e. the overlay layer is pushed on the PRESS even though the window
    is not shown. ** This is the assertion that matters most. ** Deferring the window
    naively means skipping stock's whole press tail, which also skips its LAYER_PUSH --
    and then "hold [BANK], tap a trig to pick a bank" silently EDITS THE SEQUENCE
    instead. That is the most plausible reading of why the Session 80 attempt was
    rejected on hardware, and nothing else in this suite would notice it.
  * a [BANK] PRESS shows SELECT BANK zero times                        (the ask)
  * the [BANK] RELEASE shows it exactly once                           (positive
    control -- it also proves the hook can fire, so the zero above is a measurement
    and not a dead hook)
  * the keymap-layer list NEVER grows across repeated taps. This is the failure mode
    the deferral risks: replaying the tail could double-link the [BANK] overlay. Stock
    LAYER_PUSH is idempotent (0x400314b4/0x400314b8) -- this checks that claim rather
    than trusting it.
  * the TOGGLE still toggles: tap 1 opens, tap 2 must NOT re-open (it dismisses).
  * [BANK] + [TRACK] shows SELECT BANK ZERO times on press AND on release -- the
    whole point of the deferral for the chord.
  * the dispatch table's [BANK] press slot still points at stock, since we splice the
    shared tail and must never repoint the key itself.

Usage:
  python3 tools/diag_reload3_bankdefer.py [--iters N] [--track N]
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
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

SHOW_WIN    = 0x40059F8C
BANK_TEXT   = 0x400B7302        # "SELECT BANK"
LAYER_PUSH  = 0x40031494
LAYER_POP   = 0x4003146C
LAYER_HEAD  = 0x460D165C
BANK_LAYER  = 0x400CFF14
BANK_COMMIT = 0x460E73C2
BANK_STICKY = 0x460E73BC
POPUP       = 0x460E5CD0
DISPATCH    = 0x46C7D8DE
BANK_PRESS_H = 0x4007AF80
TRIG_BASE_H  = 0x40060CE0       # the BASE handler for trig keys 0x00..0x0f
G_KIND      = 0x80006A50


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=4)
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
    mounted, posted, sb, bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(bank, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : bank={bank} pattern={P}")

    C = {"showbank": 0, "showother": 0, "push": 0, "pop": 0}

    def on_show(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        text = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
        C["showbank" if text == BANK_TEXT else "showother"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_show, begin=SHOW_WIN, end=SHOW_WIN)
    for fn, k in ((LAYER_PUSH, "push"), (LAYER_POP, "pop")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                       (lambda kk: lambda u, ad, sz, x: C.__setitem__(kk, C[kk] + 1))(k),
                       begin=fn, end=fn)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def drain(n=12):
        for _ in range(n):
            rt.run(ms=60)

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    def layer_depth():
        """length of the keymap layer list, and whether the [BANK] layer is in it"""
        n, seen, node = 0, False, u32(LAYER_HEAD)
        while node and n < 64:
            if node == BANK_LAYER:
                seen = True
            node = u32(node)
            n += 1
        return n, seen

    def snap():
        return dict(C)

    def d(b):
        return {k: C[k] - b[k] for k in C}

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    base_depth, _ = layer_depth()
    print(f"idle : layer list depth={base_depth}")
    chk(u32(DISPATCH + BANK_CODE * 24) == BANK_PRESS_H,
        f"[BANK] press slot still stock 0x{BANK_PRESS_H:08x} "
        f"(is 0x{u32(DISPATCH + BANK_CODE*24):08x})")

    # ---------- 1. a plain tap: nothing on press, the window on release ----------
    print("\n--- plain [BANK] tap: press must show NOTHING, release must show it ---")
    b = snap()
    key(BANK_CODE, PRESS); drain(6)
    on_press = d(b)
    chk(on_press["showbank"] == 0,
        f"press showed no SELECT BANK (showbank={on_press['showbank']})")
    dep_press, press_in = layer_depth()
    chk(press_in,
        f"press DID push the overlay layer (depth {dep_press}, idle {base_depth}) -- "
        f"the window is deferred, the keymap is not")

    # ---- the assertion that the naive deferral would fail ----
    trig_slot = u32(DISPATCH + 0x00 * 24)
    chk(trig_slot != TRIG_BASE_H,
        f"with [BANK] held, trig 1 is REMAPPED off the base trig handler "
        f"(slot=0x{trig_slot:08x}, base=0x{TRIG_BASE_H:08x}) -- so hold-[BANK]+trig "
        f"still selects a bank instead of editing the sequence")
    dep_held, held_in = layer_depth()
    chk(held_in, f"the [BANK] overlay IS linked while held (depth={dep_held})")

    b2 = snap()
    key(BANK_CODE, RELEASE); drain(6)
    on_rel = d(b2)
    chk(on_rel["showbank"] == 1,
        f"release showed SELECT BANK exactly once (showbank={on_rel['showbank']}) "
        f"-- also proves the hook fires, so the zero above is real")
    dep_rel, in_list = layer_depth()
    chk(in_list, f"the [BANK] overlay is now linked (depth={dep_rel})")

    # ---------- 2. the toggle must still toggle ----------
    print("\n--- tap 2 must NOT re-open (stock's toggle: it dismisses) ---")
    b = snap()
    key(BANK_CODE, PRESS); drain(4)
    key(BANK_CODE, RELEASE); drain(8)
    t2 = d(b)
    chk(t2["showbank"] == 0,
        f"the second tap opened nothing (showbank={t2['showbank']})")
    dep2, in2 = layer_depth()
    chk(not in2,
        f"the toggle-off tap POPPED the [BANK] overlay (linked={in2}, depth={dep2})")

    # ---------- 3. repeated taps must not leak layers ----------
    print(f"\n--- {a.iters} more tap pairs: the layer list must never grow ---")
    depths = []
    for _ in range(a.iters):
        key(BANK_CODE, PRESS); drain(4)
        key(BANK_CODE, RELEASE); drain(8)
        depths.append(layer_depth()[0])
    print(f"   depths after each pair: {depths}")
    chk(max(depths) <= base_depth + 1,
        f"no layer leak across {a.iters} pairs (max depth {max(depths)}, "
        f"idle {base_depth})")

    # ---------- 4. the chord must show nothing at all ----------
    print(f"\n--- [BANK] + [TRACK {a.track + 1}] must show SELECT BANK ZERO times ---")
    # settle any window still up from the taps above
    drain(30)
    b = snap()
    key(BANK_CODE, PRESS)
    key(TRACK0 + a.track, PRESS)
    key(TRACK0 + a.track, RELEASE)
    key(BANK_CODE, RELEASE)
    for _ in range(200):
        rt.run(ms=10)
        if rt.uc.mem_read(G_KIND, 1)[0] == 0:
            break
    drain(10)
    ch = d(b)
    chk(ch["showbank"] == 0,
        f"the chord never showed SELECT BANK (showbank={ch['showbank']})")
    # ** The assertion that must be exact, not tolerant. ** Total depth can legitimately
    # be >idle here because the two-line MLNOTIFY box pushes a layer of its OWN while it
    # is up. What must NOT be linked is the [BANK] overlay: the chord's release is the
    # only thing that can pop it (no window was ever shown to own it), so if it is still
    # in the list the deferral has stranded it -- the exact failure mode this item risks.
    dep3, bank_in3 = layer_depth()
    print(f"   after the chord: depth={dep3} bankLayerLinked={bank_in3} "
          f"POPUP={u32(POPUP):#x} BANK_COMMIT={u32(BANK_COMMIT):#x} "
          f"sticky={u32(BANK_STICKY):#x}")
    chk(not bank_in3,
        f"the [BANK] overlay was POPPED by the chord's release "
        f"(linked={bank_in3}) -- any residual depth is another dialog's own layer")

    # ---- and it must come back off: no layer left linked once idle ----
    drain(60)
    dep_final, final_in = layer_depth()
    print(f"   settled: depth={dep_final} bankLayerLinked={final_in} (idle was {base_depth})")
    chk(not final_in,
        f"the [BANK] overlay is not linked once everything has settled "
        f"(linked={final_in}, depth={dep_final})")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- SELECT BANK is a RELEASE gesture, the toggle survives, "
          "no layer leaks, and the chord is silent.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

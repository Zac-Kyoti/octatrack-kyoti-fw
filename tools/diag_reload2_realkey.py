#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_realkey -- drive RELOAD2 through the REAL key dispatch path.

WHY THIS EXISTS
---------------
Session 80 continued (6). Every test in this repo reaches the reload by calling
`rl_arm_trk` directly. None has ever gone through the actual key path, and
`emu_reload.py`'s own `cmd_trk` says why:

    "Driving the full rl_yes for TRK SEQ runs a real sprintf (the "T3 SEQ"
     toast) that opens a scheduling window in which the posted worker starts
     *inside* call_as_main and the borrowed idle slot never cleanly returns to
     MAIN_SPIN."

So the workaround was adopted years-deep and the real path was never revisited.
That is the ONE difference between the emulator (5 consecutive reloads: no drift
in G_KIND, POPUP, layer depth or the dispatch slots) and hardware, where the user
reports a permanently stuck G_KIND -- `RELOAD BUSY` on nearly every [YES], and
it does NOT clear by waiting, which kills the "storage task is merely busy"
explanation.

What the direct-arm shortcut skips, and what only this can exercise:
  * the runtime dispatch table lookup itself -- the [BANK] overlay layer
    redirecting the YES slot to rl_bank_yes, which IS the gesture;
  * rl_bank_yes / rl_yes / rl_yes_exec, including the G_KIND busy guard and the
    popup open/close (CLOSE_CB 0x40056bc0, stubbed to `rts` in every other
    harness here, so the real close has never run in a test);
  * [BANK] release and its teardown route.

HOW
---
`set_key_state` 0x40031734 is the sole per-key dispatcher: set_key_state(code,
event) looks the keycode up in the runtime table at 0x46c7d8de (24-byte stride)
and calls that record's handler as handler(code@4, event@8). Driving IT, rather
than a handler directly, is what makes this the real path -- octabam's own
`press_key_live` calls handlers directly with a different signature (action(edge))
and so would skip the table entirely.

The gesture driven per iteration is the user's actual one:
    [BANK] press -> [YES] press (opens picker) -> [YES] press (executes, which
    only works because of the "(6)" fix) -> [BANK] release -> drain

If call_as_main faults mid-gesture, that is REPORTED, not hidden -- it is the
very scheduling problem the old comment describes, and knowing exactly which
step trips it is itself the finding.

Usage:   python3 tools/diag_reload2_realkey.py [iterations]    (default 3)
(Slow -- full-RTOS boot + a real card load. Background it.)
"""
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402

er = erl.er

SET_KEY_STATE = 0x40031734
BANK_CODE, YES_CODE, NO_CODE = 0x2F, 0x31, 0x32
PRESS, RELEASE = 1, 0

LAYER_HEAD = 0x460D165C
DISPATCH_BASE = 0x46C7D8DE
BANK_SLOT = DISPATCH_BASE + BANK_CODE * 24
YES_SLOT = DISPATCH_BASE + YES_CODE * 24
BANK_PRESS_H = 0x4007AF80
POPUP = 0x460E5CD0
POPUP_HANDLE = 0x460D1E64
PARSEPAT = 0x4008CEBC
BANK_LAYER = 0x400CFF14       # the [BANK]-held overlay layer struct
OUR_LAYER = None              # our picker's own layer struct (resolved at runtime)
NO_SLOT = DISPATCH_BASE + 0x32 * 24
BANK_LAYER_NO = 0x4007B25C    # that layer's own NO handler -- knows nothing of our picker


def u32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def layer_walk(uc):
    """(depth, bank_overlay_linked). Depth ALONE is not enough: depth returning
    to baseline does NOT prove the [BANK] overlay was popped -- a different layer
    could have popped while ours stayed linked. Measuring identity is what
    distinguishes 'the slot was never restored' from 'the overlay is stranded',
    and those have completely different fixes."""
    n = u32(uc, LAYER_HEAD)
    d, bank = 0, False
    ours = False
    for _ in range(64):
        if n == 0 or n < 0x40000000:
            break
        d += 1
        if n == BANK_LAYER:
            bank = True
        if OUR_LAYER is not None and n == OUR_LAYER:
            ours = True
        try:
            n = u32(uc, n)
        except Exception:
            break
    return d, bank, ours


def layer_depth(uc):
    return layer_walk(uc)[0]


def ours_linked(uc):
    return layer_walk(uc)[2]


def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    rl_job = erl2._sym("rl_job")
    rl_bank_yes = erl2._sym("rl_bank_yes")
    global OUR_LAYER
    OUR_LAYER = erl2._sym("rl_layer")
    print(f"our picker layer struct = 0x{OUR_LAYER:08x}")

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

    counts = {"rl_job": 0, "parse": 0, "bank_yes": 0}

    def mk(k):
        def cb(u, ad, sz, x):
            counts[k] += 1
        return cb

    for a, k in ((rl_job, "rl_job"), (PARSEPAT, "parse"), (rl_bank_yes, "bank_yes")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(k), begin=a, end=a)
    # NB: CLOSE_CB is deliberately NOT stubbed here -- letting the real popup
    # close run is half the point of this harness.
    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065BE, bytes([P]))
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([T]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")

    base_depth = layer_depth(rt.uc)
    print(f"baseline: depth={base_depth} BANK=0x{u32(rt.uc, BANK_SLOT):08x} "
          f"YES=0x{u32(rt.uc, YES_SLOT):08x} POPUP=0x{u32(rt.uc, POPUP):08x} "
          f"handle=0x{u32(rt.uc, POPUP_HANDLE):08x}")
    print(f"rl_bank_yes=0x{rl_bank_yes:08x}\n")

    def key(code, event, label):
        """set_key_state(code,event) -- the real dispatcher."""
        try:
            rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
            rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=2_000_000)
            return None
        except Exception as e:
            return f"{label}: {type(e).__name__}: {e}"

    for i in range(1, iters + 1):
        print(f"--- iteration {i} ---")
        before = dict(counts)
        # Session 80 continued (8): a real "tap YES twice while holding BANK"
        # gesture is press-RELEASE-press-RELEASE, not press-press. The first
        # version of this harness sent [YES] press, [YES] press with NO release
        # between them -- a gesture no physical key can produce -- and that is
        # suspected to be why the dispatch table's YES slot looked "stuck": the
        # firmware's own held-key bookkeeping (set_key_state links/unlinks each
        # code's runtime record on a per-key "held" list on press/release; see
        # NOTES.md for the disassembly) never got the release that would let it
        # settle between taps. Test the REAL gesture before concluding anything
        # about firmware behaviour.
        steps = [
            (BANK_CODE, PRESS, "[BANK] press"),
            (YES_CODE, PRESS, "[YES] press (open picker)"),
            (YES_CODE, RELEASE, "[YES] release"),
            (YES_CODE, PRESS, "[YES] press (execute)"),
            (YES_CODE, RELEASE, "[YES] release"),
            (BANK_CODE, RELEASE, "[BANK] release"),
        ]
        errs = []
        for code, ev, label in steps:
            e = key(code, ev, label)
            gm = rt.uc.mem_read(erl.G_MENU_A, 1)[0]
            gk = rt.uc.mem_read(erl.G_KIND, 1)[0]
            dep, bank_linked, mine = layer_walk(rt.uc)
            print(f"   {label:<28} G_MENU={gm} G_KIND={gk} "
                  f"YES=0x{u32(rt.uc, YES_SLOT):08x} NO=0x{u32(rt.uc, NO_SLOT):08x} "
                  f"depth={dep} BANK={'L' if bank_linked else '-'} "
                  f"OURlayer={'LINKED' if mine else 'unlinked'}"
                  + (f"   !! {e}" if e else ""))
            if e:
                errs.append(e)
                break
        if errs:
            print(f"   -> gesture aborted: {errs[-1]}")
            print("   (this IS the scheduling problem cmd_trk's comment describes;"
                  " which step trips it is the finding)")
            break
        for _ in range(25):
            try:
                rt.run(ms=100)
            except Exception as e:
                print(f"   drain fault: {type(e).__name__}: {e}")
                break
            if (counts["rl_job"] > before["rl_job"]
                    and rt.uc.mem_read(erl.G_KIND, 1)[0] == 0
                    and layer_depth(rt.uc) == base_depth):
                break
        gk = rt.uc.mem_read(erl.G_KIND, 1)[0]
        print(f"   settled: G_KIND={gk} POPUP=0x{u32(rt.uc, POPUP):08x} "
              f"handle=0x{u32(rt.uc, POPUP_HANDLE):08x} depth={layer_depth(rt.uc)} "
              f"BANK=0x{u32(rt.uc, BANK_SLOT):08x} "
              f"rl_job+{counts['rl_job']-before['rl_job']} "
              f"parse+{counts['parse']-before['parse']} "
              f"bank_yes+{counts['bank_yes']-before['bank_yes']}")
        if gk != 0:
            print("   ** G_KIND STUCK -- the next [YES] would toast RELOAD BUSY. "
                  "This is the user's #1 symptom, reproduced through the real "
                  "key path. **")
            break

        # The YES dispatch slot was observed still pointing at rl_bank_yes AFTER
        # [BANK] release and after the overlay layer had been popped (depth back
        # to baseline). If that is real rather than a stale read, [YES] ALONE now
        # means "open the reload picker" for the rest of the session, and stock
        # [YES] is gone -- a serious regression that would also make the whole
        # feature feel erratic. Test it the only way that settles it: press
        # [YES] with no [BANK] held and see whether the picker opens.
        ys, ns = u32(rt.uc, YES_SLOT), u32(rt.uc, NO_SLOT)
        dep, bank_linked, mine = layer_walk(rt.uc)
        if mine:
            print("   ** OUR LAYER IS STILL LINKED AFTER THE GESTURE -- a push "
                  "without a matching pop. This WEDGES THE KEYBOARD on hardware. **")
        print(f"   after release: YES=0x{ys:08x} NO=0x{ns:08x} depth={dep} "
              f"BANKlayer={'LINKED -- STRANDED' if bank_linked else 'popped'}")
        if bank_linked:
            print("   -> the overlay is STILL LINKED, so the YES/NO slots point at "
                  "its handlers legitimately. The bug is a stranded layer, NOT an "
                  "unrestored slot -- different fix entirely.")
        if ns == BANK_LAYER_NO:
            print("   -> NO slot is the overlay's own 0x4007b25c, which cannot "
                  "close our picker: [NO] is dead and the picker is uncancellable.")
        if ys == rl_bank_yes:
            e = key(YES_CODE, PRESS, "[YES] alone, no [BANK]")
            gm = rt.uc.mem_read(erl.G_MENU_A, 1)[0]
            print(f"   [YES] alone -> G_MENU={gm} "
                  f"bank_yes+{counts['bank_yes']-before['bank_yes']}"
                  + (f"   !! {e}" if e else ""))
            if gm != 0:
                print("   ** CONFIRMED BUG: [YES] on its own opens the RELOAD "
                      "picker, because the YES dispatch slot is never restored "
                      "after the [BANK] overlay is popped. Stock [YES] is dead "
                      "from the first [BANK] press onward. **")
                # leave the picker closed for the next iteration
                key(NO_CODE, PRESS, "[NO] to close")
            else:
                print("   -> picker did NOT open; the slot value is stale/benign "
                      "(some other gate refused), so this is not the bug.")


def test_no_cancel():
    """Session 80 continued (8): the [NO] cancel path through REAL dispatch.
    The execute path is covered by main()'s iterations; this covers the other
    exit rl_yes_exec's shared pop-layer logic does NOT run through -- rl_no_exec
    has its own call to rl_pop_layer, a separate code path that needs its own
    proof, not an inference from the YES path being clean."""
    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    rl_job = erl2._sym("rl_job")
    global OUR_LAYER
    OUR_LAYER = erl2._sym("rl_layer")

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
    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065BE, bytes([P]))
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([T]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")

    base_depth = layer_depth(rt.uc)
    print(f"baseline: depth={base_depth}\n")

    def key(code, event, label):
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=2_000_000)
        dep, bank_linked, mine = layer_walk(rt.uc)
        print(f"   {label:<24} G_MENU={rt.uc.mem_read(erl.G_MENU_A,1)[0]} "
              f"YES=0x{u32(rt.uc, YES_SLOT):08x} depth={dep} "
              f"OURlayer={'LINKED' if mine else 'unlinked'}")
        return dep, mine

    print("--- [NO] cancel gesture: BANK press -> YES (open) -> release -> NO -> release -> BANK release ---")
    key(BANK_CODE, PRESS, "[BANK] press")
    key(YES_CODE, PRESS, "[YES] press (open)")
    key(YES_CODE, RELEASE, "[YES] release")
    dep, mine = key(NO_CODE, PRESS, "[NO] press (cancel)")
    key(NO_CODE, RELEASE, "[NO] release")
    dep, mine = key(BANK_CODE, RELEASE, "[BANK] release")

    if mine:
        print("\n** FAIL: our layer is still linked after [NO] cancel. Push/pop "
              "imbalance on the cancel path. **")
    elif dep != base_depth:
        print(f"\n** FAIL: depth {dep} != baseline {base_depth} after cancel. **")
    else:
        print("\nPASS: [NO] cancel pops our layer cleanly; depth back to baseline.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--no-cancel":
        test_no_cancel()
    else:
        main()

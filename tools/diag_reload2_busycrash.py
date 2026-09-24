#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_busycrash -- reproduce hardware report #7's HARD CRASH.

Report: in the "RELOAD BUSY locked" state, pressing arrow UP/DOWN crashes the
whole unit -- no exception message, LEDs frozen, no controls. A silent lock, not
a VEC:04.

This does NOT need the clobber's root cause. The locked state is observable
(G_KIND stuck non-zero => BUSY on every [YES]), so model that directly by
setting G_KIND, then drive the user's actual gesture through the REAL
set_key_state dispatcher and see what the arrows do.

Prime suspect, from reading the code: rl_draw indexes a THREE-entry table with
an unchecked byte --

    move.b  G_SEL,%d0            | 0..255
    lea     rl_menu_tbl,%a0
    move.l  (%a0,%d0.l*4),%a0    | up to 1KB past the table
    jsr     POPUP2               | dereferences whatever that was

so any G_SEL >= N_ITEMS hands POPUP2 a wild pointer. `--gsel N` forces G_SEL to
test that directly; the in-range run is the control.

Usage:
  python3 tools/diag_reload2_busycrash.py [--gsel N] [--kind K]
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
BANK_CODE, YES_CODE = 0x2F, 0x31
UP_CODE, DOWN_CODE = 0x33, 0x20
PRESS, RELEASE = 1, 0
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsel", type=int, default=None,
                    help="force G_SEL to this value after the picker opens")
    ap.add_argument("--kind", type=int, default=3)
    ap.add_argument("--recovery", action="store_true",
                    help="Session 84: verify the BUSY recovery. First [YES] must "
                         "toast BUSY and leave G_KIND alone; a SECOND deliberate "
                         "[YES] must treat it as stale, clear it and arm.")
    ap.add_argument("--arrows-open", action="store_true",
                    help="skip the BUSY press: leave the picker OPEN, force "
                         "--gsel, then press arrows. This is the only state in "
                         "which rl_draw's unchecked rl_menu_tbl index can fire.")
    ap.add_argument("--real-toast", action="store_true",
                    help="do NOT stub FUN_4005a2b8. Every RELOAD2 harness stubs "
                         "TOAST to rts, so the BUSY path's actual firmware call "
                         "has never run in a test -- this exercises it.")
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.RELOAD_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    pat = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    for _ in range(30):
        rt.run(ms=60)
    print(f"load : bank={final_bank} pattern={pat}  transport running")

    # where rl_draw's table read lands, for interpreting a fault
    tbl = erl2._sym("rl_menu_tbl")
    draw = erl2._sym("rl_draw")
    print(f"     : rl_menu_tbl=0x{tbl:08x} (3 entries, ends 0x{tbl+12:08x})  "
          f"rl_draw=0x{draw:08x}")
    if a.real_toast:
        print("     : TOAST 0x4005a2b8 NOT stubbed -- the real firmware toast runs")
    else:
        rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    def st():
        return (rt.uc.mem_read(erl.G_KIND_A, 1)[0], rt.uc.mem_read(erl.G_MENU_A, 1)[0],
                rt.uc.mem_read(erl.G_SEL_A, 1)[0])

    def key(code, event, label):
        try:
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        except Exception as e:
            print(f"   {label:<34} ** FAULT while settling: {e} **")
            return False
        try:
            rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)
        except Exception as e:
            pc = rt.uc.reg_read(er.eb.UC_M68K_REG_PC)
            print(f"   {label:<34} ** FAULT: {e}  pc=0x{pc:08x} "
                  f"({'in our cave' if CAVE_LO <= pc < CAVE_HI else 'outside'}) **")
            return False
        k, m, s = st()
        print(f"   {label:<34} G_KIND={k} G_MENU={m} G_SEL={s}")
        return True

    # --- put the unit in the reported locked state ---
    rt.uc.mem_write(erl.G_KIND_A, bytes([a.kind]))
    print(f"\nforced G_KIND={a.kind} (the 'BUSY locked' state the user reports)")

    print("--- gesture: BANK+YES opens, YES gives BUSY, then arrows ---")
    key(BANK_CODE, PRESS, "[BANK] press")
    key(YES_CODE, PRESS, "[YES] press (open picker)")
    key(YES_CODE, RELEASE, "[YES] release")
    if a.gsel is not None:
        rt.uc.mem_write(erl.G_SEL_A, bytes([a.gsel & 0xFF]))
        print(f"   forced G_SEL={a.gsel}")
    if a.arrows_open:
        print("   (--arrows-open: picker left OPEN, no BUSY press)")
    else:
        key(YES_CODE, PRESS, "[YES] press (expect BUSY)")
        key(YES_CODE, RELEASE, "[YES] release")
    key(BANK_CODE, RELEASE, "[BANK] release")

    if a.recovery:
        print("--- recovery: a second deliberate BANK+YES must reclaim it ---")
        k0 = rt.uc.mem_read(erl.G_KIND_A, 1)[0]
        key(BANK_CODE, PRESS, "[BANK] press")
        key(YES_CODE, PRESS, "[YES] press (open picker)")
        key(YES_CODE, RELEASE, "[YES] release")
        key(YES_CODE, PRESS, "[YES] press (2nd refusal -> stale override)")
        key(YES_CODE, RELEASE, "[YES] release")
        key(BANK_CODE, RELEASE, "[BANK] release")
        for _ in range(60):
            rt.run(ms=60)
        k1 = rt.uc.mem_read(erl.G_KIND_A, 1)[0]
        print(f"\n   G_KIND before recovery attempt = {k0}, after = {k1}")
        if k1 == k0 and k0 != 0:
            print("   ** FAIL: still locked at the same value -- no recovery. **")
            return 1
        print("   PASS: the stale flag was reclaimed; the feature is usable again.")
        return 0

    print("--- now the arrows, in the locked state ---")
    okall = True
    for code, nm in ((UP_CODE, "UP"), (DOWN_CODE, "DOWN"), (UP_CODE, "UP again")):
        okall &= key(code, PRESS, f"{nm} press")
        okall &= key(code, RELEASE, f"{nm} release")

    print()
    if okall:
        print("   no fault reproduced in this configuration.")
        return 0
    print("   ** REPRODUCED a fault. **")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

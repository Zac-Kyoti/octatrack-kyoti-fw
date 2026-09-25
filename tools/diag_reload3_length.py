#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_length -- a reload must restore the SAVED step count in NORMAL scale mode.

Session 89, hardware report #12: "in NORMAL mode (not per track) reloads are not
respecting the pattern length that was set in the CF-saved version (ie, if the CF-saved
version is 16 steps, and the user sets the active track to 12 steps and reloads, the
track remains at 12 steps). Per Track mode does not have this problem."

WHY THE TWO MODES DIFFERED -- the asymmetry is the diagnosis
  * PER TRACK: a track's length/scale live INSIDE its record, at +0x50/+0x51 of the
    0x91a slice the reload already copies. Restored for free; hence already correct.
  * NORMAL: the step count is not a track field at all. It is the PATTERN's, at slab
    +0x8e53 (scale at +0x8e54), OUTSIDE every track slice -- so nothing restored it.

Offsets confirmed against stock's own load-time clamp FUN_4009a670: +0x8e53 clamped to
2..64 (a step count, 0x4009aada), +0x8e54 to 0..6 (a scale index, 0x4009ab06), +0x8e55
the scale-MODE flag the step engine tests at 0x400a2720.

WHAT IS ASSERTED
  * NORMAL mode: scribble the pattern length, reload, and it must come back to the saved
    value. Gated -- the run aborts if the scribble did not actually change the byte,
    because then the check could pass without the fix doing anything.
  * NORMAL mode: the pattern SCALE is restored too (its sibling; the per-track path
    restores both, so this path should as well).
  * PER TRACK mode: the pattern-level length must be left ALONE (it is not what governs
    there, and that mode was already correct -- this guards against "fixing" it twice).
  * PER TRACK mode: the TRACK's own length byte IS restored.
  * the LIVE master scale cache SCALE_IX (0x8000663d) follows the restored scale. Stock
    refreshes that cache only on a transport cycle, the whole-bank re-home, or a
    pattern-switch commit -- and Session 86 deliberately stopped arming the re-home --
    so without this the restored rate would not take effect until the user stopped/
    started or changed pattern. Carried over from the DIRECT JUMP thread, which paid
    for the same class of bug twice.
  * and it is left ALONE when the scale did not change, because poking it mid-cycle
    re-phases the master for a step and report #9 asked for undisturbed time.

Usage:
  python3 tools/diag_reload3_length.py [--track N]
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
PTN_CODE = 0x2E
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

BLOB = 0x400E21E0
BANKSTRIDE, PATSTRIDE = 0x9B340, 0x8ED8
TRAC_A = 0x91A
OFF_LEN, OFF_SCALE, OFF_SMODE = 0x8E53, 0x8E54, 0x8E55
TRK_LEN_OFF = 0x50            # a track's own length byte, inside its record
SCALE_IX = 0x8000663D         # LIVE master scale cache -- not refreshed per wrap
OUR_WRITE_PC = 0x400D6A58     # rlj_trk_copy's OWN conditional `move.b %d0,SCALE_IX`
                              # (m68k-elf-nm out/patch_reload3.elf); hook the
                              # INSTRUCTION, not the address -- stock's own step
                              # engine (0x400a4220) rewrites the same address on
                              # every pattern loop-around, independent of us
CUR_BANK = 0x80000002
ACT_PAT = 0x800065BE
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
    bank = rt.uc.mem_read(CUR_BANK, 1)[0]
    rt.seq_select_live(bank, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    pat = rt.uc.mem_read(ACT_PAT, 1)[0]
    slab = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE
    print(f"load : bank={bank} pattern={pat} slab={slab:#x}")

    def rb(ad):
        return rt.uc.mem_read(ad, 1)[0]

    def wb(ad, v):
        rt.uc.mem_write(ad, bytes([v & 0xFF]))

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def reload_track():
        key(PTN_CODE, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(PTN_CODE, RELEASE)
        for _ in range(250):
            rt.run(ms=10)
            if rb(G_KIND) == 0:
                break
        for _ in range(10):
            rt.run(ms=60)

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    rt.start_transport_live()
    for _ in range(20):
        rt.run(ms=60)

    saved_len = rb(slab + OFF_LEN)
    saved_scale = rb(slab + OFF_SCALE)
    trk_len_addr = slab + a.track * TRAC_A + TRK_LEN_OFF
    saved_trk_len = rb(trk_len_addr)
    print(f"saved: pattern len={saved_len} scale={saved_scale}  "
          f"track{a.track+1} len={saved_trk_len}")

    # ---------- NORMAL mode: the reported bug ----------
    print("\n--- NORMAL scale mode: the saved PATTERN length must come back ---")
    wb(slab + OFF_SMODE, 0)                      # NORMAL
    bad_len = 12 if saved_len != 12 else 13
    bad_scale = (saved_scale + 1) % 7
    wb(slab + OFF_LEN, bad_len)
    wb(slab + OFF_SCALE, bad_scale)
    if rb(slab + OFF_LEN) != bad_len or rb(slab + OFF_LEN) == saved_len:
        sys.exit("GATE FAIL: could not make the live length differ from the saved one; "
                 "the check below would pass without proving anything.")
    print(f"   scribbled: len {saved_len} -> {bad_len}, scale {saved_scale} -> "
          f"{bad_scale} (SMODE=0)")
    reload_track()
    got_len, got_scale = rb(slab + OFF_LEN), rb(slab + OFF_SCALE)
    chk(got_len == saved_len,
        f"pattern LENGTH restored to the saved value ({got_len} == {saved_len}) -- "
        f"report #12's exact case")
    chk(got_scale == saved_scale,
        f"pattern SCALE restored too ({got_scale} == {saved_scale})")
    chk(rb(SCALE_IX) == saved_scale,
        f"the LIVE master scale cache followed it (SCALE_IX={rb(SCALE_IX)} == "
        f"{saved_scale}) -- stock never refreshes it per wrap, so the restored rate "
        f"would otherwise not take effect until a stop/start or pattern change")

    # ---------- scale UNCHANGED: OUR write instruction must not fire ----------
    # ** Corrected TWICE now. ** v1 poked SCALE_IX with a sentinel that differed from
    # the true saved scale, then complained when the firmware "fixed" it back -- but
    # that IS correct (the live cache SHOULD match what CF has saved). v2 hooked the
    # ADDRESS via UC_HOOK_MEM_WRITE -- but stock's OWN step engine also refreshes this
    # same cache on every pattern loop-around while the transport runs (0x400a4220, part
    # of the per-step commit tail), independently of our patch, so an address-level hook
    # cannot tell "we wrote it" from "stock's routine tick wrote it" -- both write the
    # correct value 2 repeatedly during the drain window, which is what v2 actually
    # measured (values were never wrong, just multiply counted). The only unambiguous
    # proof is to hook OUR SPECIFIC INSTRUCTION's address, not the memory it targets.
    print("\n--- scale unchanged: OUR conditional write must not execute ---")
    wb(slab + OFF_SMODE, 0)
    wb(slab + OFF_LEN, bad_len)           # length differs, scale does NOT
    wb(SCALE_IX, saved_scale)             # live cache ALREADY correct
    if rb(slab + OFF_SCALE) != saved_scale or rb(SCALE_IX) != saved_scale:
        sys.exit("GATE FAIL: could not set up the 'already matches' precondition.")
    fires = [0]
    def on_our_write(u, ad, sz, x):
        fires[0] += 1
    h = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_our_write,
                       begin=OUR_WRITE_PC, end=OUR_WRITE_PC)
    reload_track()
    rt.uc.hook_del(h)
    chk(rb(slab + OFF_LEN) == saved_len,
        f"length still restored ({rb(slab + OFF_LEN)} == {saved_len})")
    chk(fires[0] == 0,
        f"our conditional write NEVER executed (fires={fires[0]}) -- no needless "
        f"mid-cycle re-phase, even though stock's own step engine keeps rewriting the "
        f"same address on every pattern loop-around")

    # ---------- scale CHANGED: OUR write instruction fires exactly once ----------
    print("\n--- scale changed: OUR conditional write fires exactly once ---")
    wb(slab + OFF_SMODE, 0)
    wb(slab + OFF_SCALE, bad_scale)
    wb(SCALE_IX, bad_scale)               # live cache tracks the (wrong) blob for now
    fires[0] = 0
    h = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_our_write,
                       begin=OUR_WRITE_PC, end=OUR_WRITE_PC)
    reload_track()
    rt.uc.hook_del(h)
    chk(fires[0] == 1,
        f"our write fires exactly once (fires={fires[0]})")
    chk(rb(SCALE_IX) == saved_scale,
        f"and the live cache ends at the saved value ({rb(SCALE_IX)} == {saved_scale})")

    # ---------- PER TRACK mode: must be left alone ----------
    print("\n--- PER TRACK mode: the pattern-level length must NOT be touched ---")
    wb(slab + OFF_SMODE, 1)                      # PER TRACK
    wb(slab + OFF_LEN, bad_len)
    wb(trk_len_addr, (saved_trk_len + 3) & 0x3F)
    poked_trk = rb(trk_len_addr)
    if rb(slab + OFF_LEN) != bad_len:
        sys.exit("GATE FAIL: could not scribble the pattern length for the control.")
    print(f"   scribbled: pattern len -> {bad_len}, track len "
          f"{saved_trk_len} -> {poked_trk} (SMODE=1)")
    reload_track()
    chk(rb(slab + OFF_LEN) == bad_len,
        f"pattern length left ALONE in PER TRACK mode ({rb(slab + OFF_LEN)} == "
        f"{bad_len}) -- it is not what governs there")
    chk(rb(trk_len_addr) == saved_trk_len,
        f"the TRACK's own length was restored ({rb(trk_len_addr)} == {saved_trk_len}) "
        f"-- it rides inside the copied slice, which is why this mode already worked")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- NORMAL mode restores the saved pattern length/scale, "
          "PER TRACK is untouched and still restores the track's own.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

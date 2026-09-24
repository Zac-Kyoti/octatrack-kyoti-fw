#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_timing -- a reload must not disturb the clock.

Session 86, hardware report #9 item 3: "Reloading restarts the track sequence from
step 1, AND the internal (master) metronome is also restarted. The track, pattern,
and the internal metronome should remain in undisturbed time while any reload
occurs."

MEASURED ROOT CAUSE (static, then confirmed dynamically here). rl_job used to arm
RELOAD_NOW (0x46c8028a). The step engine polls it once per step at 0x400a2530, and
the block it gates -- 0x400a253a..0x400a28b4 -- is stock's WHOLE-BANK re-home, which
is POSITIONAL:

    0x400a26fe  movew #0,0x800065b4    previous master step
    0x400a2704  movew #0,0x800065b2    THE MASTER PLAYHEAD      -> sequence restart
    0x400a2658  moveb LEN_TBL[..]-1,0x800065b6                  -> wrap on next tick
    0x400a27e2  movel #1,0x800065b8    RUNNING = 1              -> starts playback

0x800065b2 is the bounded master playhead (DIRECT JUMP's MASTER_STEP / BAR_CTR,
measured there), and the metronome's beat flags are derived from it by masking
against 0x400abae4 / 0x400abacc at 0x400a4264..0x400a42a0. So one write explains
BOTH reported symptoms.

** NAMING TRAP, do not repeat it. ** diag_reload2_transport.py calls 0x800065b6
"MASTER_STEP". It is not; DIRECT JUMP's Session 82 measured 0x800065b6 as the
TICKS-WITHIN-STEP counter and 0x800065b2 as the actual playhead. A timing test that
watches 0x800065b6 is watching the wrong word.

WHAT THIS ASSERTS
  * the re-home block is ENTERED ZERO TIMES across a reload (hook on 0x400a253a,
    the first instruction inside it -- so this counts real entries, not polls)
  * nothing writes a non-zero value to RELOAD_NOW (memory-write hook, so it catches
    any writer, not just ours)
  * the playhead keeps ADVANCING across the reload, and its forward progress in the
    reload window matches a quiet control window -- i.e. time neither froze nor jumped
  * --stopped: with the transport stopped, RUNNING must still read 0 afterwards.
    That is the old "reload while stopped starts playback" bug (Session 80 cont. (2)),
    which the removed RUNNING gate was only papering over.

DETECTOR-LIVENESS GATE (this thread's own rule: a test that cannot fail is not
evidence). Two gates, and the run REFUSES to report if either is unmet:
  1. the sequencer must actually be stepping -- the playhead must change on its own
  2. the re-home hook must be PROVEN able to fire -- at the end we poke RELOAD_NOW=1
     ourselves and require the counter to go up. Session 84's diag_scratch_clobber
     reported a vacuous "0 writes" precisely because it never proved it could see one.

Usage:
  python3 tools/diag_reload3_timing.py [--chord ptn|bank] [--stopped] [--frames N]
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
PTN_CODE, BANK_CODE = 0x2E, 0x2F
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

PLAYHEAD   = 0x800065B2      # bounded master playhead (word). NOT 0x800065b6.
PREV_STEP  = 0x800065B4
TICKS_STEP = 0x800065B6      # ticks-within-step -- the one the old harness misnamed
RUNNING    = 0x800065B8
RELOAD_NOW = 0x46C8028A
REHOME_IN  = 0x400A253A      # first insn INSIDE the re-home block (past the poll)
G_KIND     = 0x80006A50


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--chord", choices=("ptn", "bank"), default="ptn")
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--stopped", action="store_true",
                    help="control: transport stopped; RUNNING must stay 0")
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

    C = {"rehome": 0, "rn_nonzero": 0, "rn_writes": []}
    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                   lambda u, ad, sz, x: C.__setitem__("rehome", C["rehome"] + 1),
                   begin=REHOME_IN, end=REHOME_IN)

    def on_write(u, access, addr, size, value, x):
        C["rn_writes"].append(value)
        if value:
            C["rn_nonzero"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write,
                   begin=RELOAD_NOW, end=RELOAD_NOW + 3)

    def w16(ad):
        return struct.unpack(">H", rt.uc.mem_read(ad, 2))[0]

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def sample(n, ms=6):
        """run n slices of `ms` emulated ms, returning the playhead trace"""
        tr = []
        for _ in range(n):
            rt.run(ms=ms)
            tr.append(w16(PLAYHEAD))
        return tr

    def progress(tr, modulus):
        """total FORWARD movement of a bounded counter, wraps counted as forward"""
        tot = 0
        for i in range(1, len(tr)):
            d = tr[i] - tr[i - 1]
            if d < 0:
                d += modulus          # a wrap is forward motion, not a jump back
            tot += d
        return tot

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    if not a.stopped:
        rt.start_transport_live()
        rt.run(ms=250)

    # ---- gate 1: is the sequencer actually stepping? ----
    warm = sample(a.frames)
    modulus = max(warm) + 1 if max(warm) else 1
    ctrl = progress(warm, modulus)
    print(f"\ncontrol window : playhead trace {warm[0]}..{warm[-1]} "
          f"distinct={len(set(warm))} modulus~{modulus} forward={ctrl}")
    if not a.stopped:
        if len(set(warm)) < 3:
            sys.exit("LIVENESS FAIL: the playhead is not moving -- this run would be "
                     "vacuous, so it reports nothing. (Is start_transport_live working?)")
    else:
        chk(u32(RUNNING) == 0, f"transport genuinely stopped (RUNNING={u32(RUNNING)})")

    base_rehome = C["rehome"]

    # ---- the reload ----
    print(f"\n--- [{a.chord.upper()}] + [TRACK {a.track + 1}] with the transport "
          f"{'STOPPED' if a.stopped else 'RUNNING'} ---")
    mod = PTN_CODE if a.chord == "ptn" else BANK_CODE
    key(mod, PRESS)
    key(TRACK0 + a.track, PRESS)
    key(TRACK0 + a.track, RELEASE)
    key(mod, RELEASE)
    # let the storage task actually run the job
    for _ in range(200):
        rt.run(ms=10)
        if rt.uc.mem_read(G_KIND, 1)[0] == 0:
            break
    during = sample(a.frames)
    dur = progress(during, modulus)
    print(f"reload window  : playhead trace {during[0]}..{during[-1]} forward={dur}")

    chk(C["rehome"] - base_rehome == 0,
        f"the re-home block was never entered (entries={C['rehome'] - base_rehome})")
    chk(C["rn_nonzero"] == 0,
        f"nobody armed RELOAD_NOW (non-zero writes={C['rn_nonzero']})")

    if a.stopped:
        chk(u32(RUNNING) == 0,
            f"the reload did NOT start playback (RUNNING={u32(RUNNING)})")
    else:
        chk(len(set(during)) >= 3, "the playhead kept moving across the reload")
        # time neither froze nor jumped: forward progress within 25% of the control
        lo, hi = ctrl * 0.75, ctrl * 1.25
        chk(lo <= dur <= hi,
            f"forward progress matches the quiet control ({dur} vs {ctrl}, "
            f"tolerance {lo:.0f}..{hi:.0f})")

    # ---- gate 2: prove the detector CAN fire ----
    print("\n--- detector liveness: arm RELOAD_NOW by hand, the hook must see it ---")
    before = C["rehome"]
    rt.uc.mem_write(RELOAD_NOW, struct.pack(">I", 1))
    if a.stopped:
        rt.start_transport_live()
    rt.run(ms=1500)
    fired = C["rehome"] - before
    if fired == 0:
        sys.exit("DETECTOR-LIVENESS FAIL: poking RELOAD_NOW=1 did not enter the "
                 "re-home block, so a zero count above proves NOTHING. Do not record "
                 "this run as evidence.")
    print(f"   [ok ] hook fires when the flag IS armed (entries={fired}) -- so the "
          f"zero above is a real measurement")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- the reload leaves the playhead, the metronome and the "
          "transport untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

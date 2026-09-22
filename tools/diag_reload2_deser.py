#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_deser -- what actually runs AFTER a RELOAD2 slice copy?

WHY THIS EXISTS
---------------
Two user-reported hardware symptoms are still unexplained (issues #2 and #6):

  #2  a reloaded TRK SEQ plays 1-3 steps, PAUSES for "just under a second",
      then RESTARTS sequence playback;
  #6  G_KIND gets stuck, so the next [YES] toasts "RELOAD BUSY" -- and the
      user's latest report ties the gesture's "works most of the time" to
      exactly that stuck state.

A static read says our worker should be clear of stock's bank-load work.
`rl_job` rejoins the stock type-0x14 case at JOB14_EXIT 0x400858a8, which is
AFTER stock's own `jsr 0x400a69e0` and `jsr 0x4008f0b0`; the whole-bank
deserialiser 0x4008ded0 has exactly one caller image-wide, 0x4009072a, inside
that skipped subtree. So nothing of stock's bank load should run.

But emu_reload.py's own cmd_trk hooks 0x4008ded0 and calls it "the residual
whole-bank deser", stopping the emulator the moment it is entered -- and
--trk reports deser_seen=True on every run. So it IS reached. cmd_trk halts
there, which is fine for measuring the slice, but it means NOTHING in our test
suite has ever observed what happens after that point. On hardware there is no
such halt: whatever that is, it runs, and a full bank deserialise from CF is a
very plausible "just under a second" pause that also resets the sequencer --
i.e. symptom #2 exactly.

WHAT THIS DOES
--------------
Drives one real TRK SEQ reload (same arming path as --trk: rl_arm_trk posts the
job, the storage task runs rl_job) and then keeps running WITHOUT halting at the
deserialiser, tracing the order of the interesting calls and, for the
deserialiser, WHO called it (return address off the stack).

Also traces keymap layer push/pop (0x40031494 / 0x4003146c). Session 80
continued (3) established that on the [BANK] side a window owns a keymap layer,
and an earlier session noted stock's job-completion dance tears down a
"RELOADING BANK" overlay including a layer pop. If a reload leaves the layer
stack unbalanced, that is a strong candidate for the [YES] key going dead --
which is what "works maybe 1 in 5" and a stuck G_KIND would both look like.

Nothing here asserts. It is a measurement; read the trace.

Usage:   python3 tools/diag_reload2_deser.py
(Slow -- full-RTOS boot + a real card load. Run it in the background.)
"""
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import emu_reload2 as erl2        # noqa: E402  (sets erl.RELOAD_IMAGE etc.)
import emu_reload as erl          # noqa: E402

er = erl.er

DESER = 0x4008DED0            # whole-bank deserialiser (1 caller: 0x4009072a)
STOCK_BANKLOAD = 0x4008F0B0   # stock 0x14 case's own loader -- we should SKIP this
STOCK_A69E0 = 0x400A69E0      # ditto
JOB14_EXIT = 0x400858A8       # where rl_job rejoins stock
JOB_BEGIN = 0x40023230
JOB_DONE = 0x40023BF4
PUSH_LAYER = 0x40031494
POP_LAYER = 0x4003146C
PARSEPAT = 0x4008CEBC
DONE_STEP1 = 0x40022E04       # doneFn's FIRST tail call (bsr.w, before our site)
BANKLOAD_844 = 0x40080844     # doneFn's SECOND tail call -- the one we detour


def main():
    erl.OUR_IMAGE = erl.RELOAD_IMAGE      # emu_reload2.main() normally does this
    rl_job = erl2._sym("rl_job")
    rl_arm_trk = erl2._sym("rl_arm_trk")

    rt = erl.boot_and_load()

    T, P = 3, 0
    curbank = rt.uc.mem_read(erl.CUR_BANK, 1)[0] if hasattr(erl, "CUR_BANK") \
        else rt.uc.mem_read(er.CUR_BANK, 1)[0]
    rt.seq_select_live(curbank, P)
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.internal_clock()
    rt.press_play_live()
    rt.run(ms=250)

    # Scribble the target track's p-lock window in BOTH the cold blob and the
    # live playing copy. Our worker writes only the cold blob; the question that
    # decides whether suppressing stock's whole-bank reload is safe is whether
    # anything still refreshes the LIVE copy afterwards. If the live copy stays
    # scribbled, the reload is inaudible and the suppression broke the feature.
    LIVE_COPY = 0x1001614E
    blob = erl.part_ptr(rt)
    pP = blob + P * erl.PAT_STRIDE
    lP = LIVE_COPY + P * erl.PAT_STRIDE
    WOFF = T * erl.TRAC_STRIDE + erl.PLOCK_IN_TRAC + 0x40
    WLEN = 64

    def scr(a, n):
        rt.uc.mem_write(a, bytes(b ^ 0x5A for b in erl.rd(rt, a, n)))

    scr(pP + WOFF, WLEN)
    scr(lP + WOFF, WLEN)
    cold_scribbled = erl.rd(rt, pP + WOFF, WLEN)
    live_scribbled = erl.rd(rt, lP + WOFF, WLEN)

    trace = []
    names = {rl_job: "rl_job", PARSEPAT: "parse_pattern", JOB14_EXIT: "JOB14_EXIT",
             DESER: "WHOLE_BANK_DESER", STOCK_BANKLOAD: "stock_bankload_0x4008f0b0",
             STOCK_A69E0: "stock_0x400a69e0", JOB_BEGIN: "job_beginFn",
             JOB_DONE: "job_doneFn", PUSH_LAYER: "PUSH_LAYER", POP_LAYER: "POP_LAYER",
             # Which of doneFn's two tail calls actually performs the reload?
             DONE_STEP1: "doneFn_step1_0x40022e04",
             BANKLOAD_844: "bankload_0x40080844"}
    try:
        names[erl2._sym("rl_done")] = "rl_done(OUR suppression hook)"
    except KeyError:
        pass

    def mk(nm):
        def cb(u, ad, sz, x):
            entry = f"{nm}"
            if nm in ("WHOLE_BANK_DESER", "PUSH_LAYER", "POP_LAYER"):
                sp = u.reg_read(er.eb.UC_M68K_REG_A7)
                try:
                    ret = struct.unpack(">I", u.mem_read(sp, 4))[0]
                    arg = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
                    entry += f"  (called from 0x{ret:08x}, arg=0x{arg:08x})"
                except Exception:
                    pass
            trace.append((rt.sample, entry))
        return cb

    for a, nm in names.items():
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(nm), begin=a, end=a)
    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.mem_write(0x40056BC0, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    erl.spin(rt)
    rt.uc.mem_write(erl.PTN_HELD, struct.pack(">I", 1))
    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065BE, bytes([P]))
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([T]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")
    rt.uc.mem_write(erl.G_KIND, b"\x00")
    rt.uc.mem_write(erl.G_MENU_A, b"\x01")
    rt.uc.mem_write(erl.G_SEL_A, b"\x00")          # item 0 = TRK SEQ

    print("===== arming one TRK SEQ reload, then running WITHOUT halting =====")
    faulted = None
    try:
        rt.call_as_main(rl_arm_trk, args=(), budget=900_000)
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"

    t_arm = rt.sample
    # Run PAST the point cmd_trk halts at, but not indefinitely: this emulator
    # costs roughly 5 real minutes per 100 ms emulated, so an unbounded drain is
    # a multi-hour run. The question here is answered the instant the
    # deserialiser is entered (the hook records its caller), so keep going only
    # a short way past that to catch the layer pops and the settled G_KIND.
    # Stop shortly after the job's doneFn, NOT after the deserialiser: once the
    # suppression works the deserialiser never runs, and waiting for it would
    # burn the full cap (hours of wall clock). doneFn fires on both builds, and
    # the whole reload tail happens in the same run window, so +2 covers it.
    tail = None
    for i in range(30):
        try:
            rt.run(ms=100)
        except Exception as e:
            faulted = faulted or f"{type(e).__name__}: {e}"
            break
        if tail is None and any(e.startswith("job_doneFn") for _, e in trace):
            tail = i
        if tail is not None and i - tail >= 2:
            break

    gk = rt.uc.mem_read(erl.G_KIND, 1)[0]
    cold_now = erl.rd(rt, pP + WOFF, WLEN)
    live_now = erl.rd(rt, lP + WOFF, WLEN)
    print(f"\nfault      : {faulted}")
    print(f"G_KIND after: {gk}   (0 = worker consumed it, non-zero = STUCK)")
    print(f"cold blob  : {'REVERTED (worker wrote it)' if cold_now != cold_scribbled else 'still scribbled'}")
    print(f"LIVE copy  : {'REVERTED (audible)' if live_now != live_scribbled else 'STILL SCRIBBLED -- reload would be inaudible'}")
    try:
        own = rt.uc.mem_read(erl2._sym("rl_own"), 1)[0]
        print(f"rl_own     : {own}   (1 = set but never consumed; 0 = consumed or never set)")
    except KeyError:
        pass
    print(f"\n----- call trace ({len(trace)} events), t=ms after arming -----")
    seen = {}
    for s, e in trace:
        ms = (s - t_arm) / er.SAMPLE_RATE * 1000.0 if hasattr(er, "SAMPLE_RATE") else 0
        key = e.split("  ")[0]
        seen[key] = seen.get(key, 0) + 1
        print(f"  {ms:9.1f} ms  {e}")
    print("\n----- counts -----")
    for k, v in sorted(seen.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}x {k}")
    print("\nlayer balance: PUSH_LAYER - POP_LAYER = "
          f"{seen.get('PUSH_LAYER',0) - seen.get('POP_LAYER',0)}"
          "   (non-zero after a settled reload = unbalanced keymap stack)")


if __name__ == "__main__":
    main()

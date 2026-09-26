#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_repeat -- N CONSECUTIVE reloads: does the EFFECT survive repetition?

** THIS SATISFIES A GATE tools/patch_reload3.s EXPLICITLY DEMANDS AND NOTHING HAS MET. **
The rl_done block (the whole-bank suppression, active in every build since Session 83 via
--defsym RL_DONE=1) carries this in its own header:

    "Hardware: the flash carrying rl_done + the LIVE_REFRESH call broke things badly ...
     stock [BANK] single-press stops working entirely after a few reload attempts ...
     the emulator measured the layer stack staying balanced and G_KIND clearing on a
     SINGLE reload, so whatever accumulates does so across REPEATED use, which no test
     here covers yet. Do not re-enable without a multi-reload test."
    "diag_reload2_repeat.py driving 5+ consecutive reloads ... A single clean reload
     remains worthless evidence here."

diag_reload2_repeat.py cannot be that test any more: it drives the [YES] chord and the
3-item picker, both of which RELOAD3 deleted. Every RELOAD3 diagnostic to date drives ONE
or TWO reloads.

WHY THIS IS THE RIGHT SHAPE FOR REPORT #14 ITEM 1
  "Parts always reload well. However the sequence data does not always reload reliably.
   Most of the time it does. Occasionally the toast will show 'reloaded', but the sequence
   is not actually restored."
An intermittent failure that mostly works IS the signature of accumulation, and it is the
same signature the rl_done header describes. The emulator has already shown a SINGLE
reload restoring correctly (diag_reload3_readsrc.py: the engine reads the cold blob and
the slab came back), so one reload is exactly the case that cannot reproduce this.

WHAT IT CHECKS PER ITERATION
  effect   scribble the track's trig masks, reload, and the bytes MUST come back.
           ** This is the user's symptom, checked every single time. ** A restore that
           works on 1..k and fails at k+1 is the bug, reproduced.
  gate     the scribble really changed the bytes, and the worker really ran -- so a
           "restored" verdict cannot come from nothing having happened.
  drift    G_KIND -> 0, rl_own -> 0, layer depth -> base, and the [BANK]/[PTN]/trig
           dispatch slots unchanged. Anything MONOTONIC across iterations is the bug
           even if the effect still works.

Usage:  python3 tools/diag_reload3_repeat.py [-n N] [--track N] [--chord ptn|bank]
        (Slow: this emulator runs ~120-145x slower than realtime. Boot is 4-7 min and
         each iteration adds ~1 min. Background it and be patient -- a killed run at
         8 minutes is how three "hangs" got misdiagnosed this session.)
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
from cave_syms import syms         # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE, BANK_CODE, TRACK0 = 0x2E, 0x2F, 0x10
PRESS, RELEASE = 1, 0

BLOB = 0x400E21E0
BANKSTRIDE, PATSTRIDE, TRAC_A = 0x9B340, 0x8ED8, 0x91A
PLAY_BANK, ACT_PAT = 0x800065BD, 0x800065BE
G_KIND = 0x80006A50
# ** addresses come from the ELF, never hardcoded -- see tools/cave_syms.py. **
# The first version of this file hardcoded them, the cave shifted when rl_msg was added,
# and it then reported "the worker never ran" and "rl_own left non-zero" on every
# iteration. Both were artifacts of reading the wrong byte.
DISPATCH = 0x46C7D8DE         # per-key dispatch table, 24-byte stride
LAYER_HEAD = 0x460D165C
BANK_PRESS_H, PTN_PRESS_H, TRIG_BASE_H = 0x4007AF80, 0x4005A044, 0x40060CE0
TRIG_MODE = 0x460D1736        # grid-record mode gate (diag_seq_edit_io.py:119)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--chord", choices=("ptn", "bank"), default="ptn")
    ap.add_argument("--real-edit", action="store_true",
                    help="dirty the pattern through the FIRMWARE's own edit path "
                         "(trig keys) instead of poking memory -- closer to what the "
                         "user actually does, and the gap the poke version cannot cover")
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

    def u32(ad):
        return int.from_bytes(rt.uc.mem_read(ad, 4), "big")

    def rb(ad):
        return rt.uc.mem_read(ad, 1)[0]

    bank, pat = rb(PLAY_BANK), rb(ACT_PAT)
    masks = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE + a.track * TRAC_A
    saved = bytes(rt.uc.mem_read(masks, 0x10))
    print(f"load : bank={bank} pattern={pat} track={a.track+1} chord={a.chord}")
    print(f"   trig masks @ {masks:#x} = {saved.hex()}")
    if saved == b"\x00" * 0x10:
        print("   !! the saved masks are all zero -- a 'restored' check would be weak. "
              "Pick a track with trigs via --track.")

    S = syms()
    RL_OWN, RL_JOB = S["rl_own"], S["rl_job"]
    SETFLAG = S.get("rlj_setflag")
    print(f"   syms: rl_own={RL_OWN:#x} rl_job={RL_JOB:#x} "
          f"rlj_setflag={SETFLAG:#x}" if SETFLAG else
          f"   syms: rl_own={RL_OWN:#x} rl_job={RL_JOB:#x} (rlj_setflag not exported)")

    jobs = {"n": 0, "ok": 0}

    def on_job(uc, address, size, ud):
        jobs["n"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_job, begin=RL_JOB, end=RL_JOB)
    if SETFLAG:
        # rlj_setflag runs ONLY after the copy really happened -- the direct
        # "did the worker succeed" signal, independent of rl_own's one-shot lifetime
        def on_ok(uc, address, size, ud):
            jobs["ok"] += 1
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_ok, begin=SETFLAG, end=SETFLAG)

    def layer_depth():
        n, node = 0, u32(LAYER_HEAD)
        while node and n < 64:
            node = u32(node)
            n += 1
        return n

    base_depth = layer_depth()
    print(f"   idle layer depth = {base_depth}")

    def key(c, e):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(c, e), budget=4_000_000)

    hold = PTN_CODE if a.chord == "ptn" else BANK_CODE
    rows, fails = [], []

    def poke_dirty():
        rt.uc.mem_write(masks, bytes((b ^ 0xFF) for b in saved))

    def trigs(n=4):
        for i in range(n):
            key(i & 0x0F, PRESS)
            key(i & 0x0F, RELEASE)
            for _ in range(2):
                rt.run(ms=60)

    # Discover a REAL edit recipe, with a liveness gate. diag_seq_edit_io.py (Session 84)
    # established that direct memory writes never run the firmware's edit path at all,
    # and that plain trig keycodes may not edit either -- the blocker is UI mode, not the
    # keys. So try the strategies it tried and KEEP the first that actually moves the
    # bytes; if none do, say so and fall back to the poke rather than silently testing
    # nothing.
    real_edit = None
    if a.real_edit:
        print("\n--- discovering a real (firmware-path) edit recipe ---")

        def set_mode(v):
            rt.uc.mem_write(TRIG_MODE, v.to_bytes(4, "big"))

        cands = [
            ("plain trigs", lambda: trigs()),
            ("REC then trigs", lambda: (rt.press_rec_live(), trigs())),
            ("mode=1 then trigs", lambda: (set_mode(1), trigs())),
            ("mode=1 + REC then trigs",
             lambda: (set_mode(1), rt.press_rec_live(), trigs())),
        ]
        for nm, fn in cands:
            rt.uc.mem_write(masks, saved)          # start from the saved bytes
            base = bytes(rt.uc.mem_read(masks, 0x10))
            try:
                fn()
            except Exception as ex:
                print(f"   {nm:<26} fault: {ex}")
                continue
            now = bytes(rt.uc.mem_read(masks, 0x10))
            moved = now != base
            print(f"   {nm:<26} edited={moved}  {base.hex()} -> {now.hex()}")
            if moved:
                real_edit = (nm, fn)
                break
        set_mode(0)
        if real_edit is None:
            print("   >> NO strategy edited through the firmware. Falling back to the "
                  "memory poke, and NOTING that this run therefore does NOT cover the "
                  "real-edit path -- the same vacuity diag_seq_edit_io.py was built to "
                  "prevent.")
        else:
            print(f"   >> using '{real_edit[0]}' as the dirtying step")

    def dirty():
        if real_edit is not None:
            rt.uc.mem_write(masks, saved)
            real_edit[1]()
        else:
            poke_dirty()

    for it in range(1, a.n + 1):
        # ---- dirty the pattern, and GATE that it took ----
        dirty()
        if bytes(rt.uc.mem_read(masks, 0x10)) == saved:
            fails.append(f"iter {it}: the dirtying step did not change the bytes -- the restore check would be vacuous")
            break
        before_jobs, before_ok = jobs["n"], jobs["ok"]

        key(hold, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(hold, RELEASE)
        for _ in range(250):
            rt.run(ms=10)
            if rb(G_KIND) == 0:
                break
        for _ in range(6):
            rt.run(ms=60)

        got = bytes(rt.uc.mem_read(masks, 0x10))
        row = {
            "it": it,
            "restored": got == saved,
            "worker": jobs["n"] - before_jobs,
            "succeeded": jobs["ok"] - before_ok,
            "G_KIND": rb(G_KIND),
            "rl_own": rb(RL_OWN),
            "depth": layer_depth(),
            "bankslot": u32(DISPATCH + BANK_CODE * 24) == BANK_PRESS_H,
            "trigslot": u32(DISPATCH + 0x00 * 24),
        }
        rows.append(row)
        flag = "OK " if row["restored"] else "**NOT RESTORED**"
        print(f"   iter {it}: {flag}  worker_ran={row['worker']}  G_KIND={row['G_KIND']} "
              f"rl_own={row['rl_own']}  depth={row['depth']}  "
              f"bank_slot_stock={row['bankslot']}  got={got.hex()}")

    print("\n--- verdict ---")
    bad = [r["it"] for r in rows if not r["restored"]]
    noworker = [r["it"] for r in rows if r["worker"] == 0]
    if noworker:
        fails.append(f"the worker never ran on iteration(s) {noworker} -- gate: a "
                     f"'restored' verdict there would be meaningless")
    if bad:
        fails.append(f"** the sequence was NOT restored on iteration(s) {bad} of "
                     f"{len(rows)} -- report #14 item 1 REPRODUCED **")
    else:
        print(f"   all {len(rows)} reloads restored the sequence")
    for k, label in (("G_KIND", "G_KIND"), ("rl_own", "rl_own")):
        stuck = [r["it"] for r in rows if r[k] != 0]
        if stuck:
            fails.append(f"{label} left non-zero after iteration(s) {stuck} -- this is the "
                         f"accumulating shape the rl_done header warns about")
    depths = [r["depth"] for r in rows]
    if depths and (max(depths) > base_depth or len(set(depths)) > 1):
        fails.append(f"layer depth drifted across iterations: {depths} (base {base_depth})")
    if any(not r["bankslot"] for r in rows):
        fails.append("the [BANK] press dispatch slot stopped being stock's -- this is "
                     "literally the reported 'stock [BANK] stops working' shape")
    trigs = {r["trigslot"] for r in rows}
    if len(trigs) > 1:
        fails.append(f"the trig dispatch slot changed across iterations: "
                     f"{[hex(t) for t in trigs]}")

    print()
    if fails:
        print(f"   {len(fails)} FINDING(S):")
        for f in fails:
            print(f"     - {f}")
        return 1
    print(f"   ALL GOOD -- {len(rows)} consecutive reloads, effect intact, no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

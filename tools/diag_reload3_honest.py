#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_honest -- the reload message must appear ONLY when the reload SUCCEEDED.

Hardware report #14 item 1: "the toast will show 'reloaded', but the sequence is not
actually restored."  The toast was OPTIMISTIC BY CONSTRUCTION: the key handler drew it the
moment the chord was recognised, before the job was even dequeued, so it could not reflect
an outcome. Session 93 moves it to rl_done, which stock's doneFn reaches only on the
SUCCESS path (0x40023c0e's bge gates it) and only with rl_own set, which rlj_setflag sets
only after the copy really happened.

WHY THIS MATTERS MORE THAN COSMETICS
  Nothing in this repo can reproduce the user's intermittent failure: the harness cannot
  fail a card read, cannot stream audio off the card while reloading, and cannot drive the
  firmware's own edit path (measured again this session -- all four Session 84 edit
  strategies still move zero bytes). An honest message turns the user's own hardware into
  the instrument:
      no toast, or stock's error  -> the worker FAILED      (card I/O: the open or parse)
      toast but no change         -> the worker SUCCEEDED    (something downstream lost it)
  One bit, and it halves the search space.

WHAT IS ASSERTED, BOTH DIRECTIONS
  * SUCCESS: the two-line message still draws exactly once for [BANK]+[TRACK], and the
    one-line one for [PTN]+[TRACK].
  * FAILURE (FOPEN stubbed to return -1): our message must NOT draw at all. Gated -- the
    run also proves the failure was real (our copy did not happen), so a silent pass
    cannot come from the chord having been ignored.
  * RECOVERY: un-stub, and the message draws again -- so the failure path did not leave
    the one-shot rl_msg stranded (the same class of bug as report #13's rl_own leak).

Usage: python3 tools/diag_reload3_honest.py [--track N]
"""
import argparse
import pathlib
import struct
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
FOPEN = 0x40016864
TOAST = 0x4005A2B8            # stock's 1-line block toast
G_KIND = 0x80006A50
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C6A


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
    print(f"load : bank={b0} pattern={P} track={a.track+1}")

    C = {"msg": 0, "copy": 0}
    # our own message draws go through WIN_NEW from the cave (2-line) or stock TOAST
    # (1-line). Count both, attributing only calls made FROM our cave.
    def on_toast(uc, address, size, ud):
        C["msg"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_toast, begin=TOAST, end=TOAST)
    WIN_NEW = 0x4005829C

    def on_win(uc, address, size, ud):
        # only count windows our cave creates (rl3_toast2); stock's own dialogs are not ours
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        ret = struct.unpack(">I", uc.mem_read(sp, 4))[0]
        if CAVE_LO <= ret < CAVE_HI:
            C["msg"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_win, begin=WIN_NEW, end=WIN_NEW)

    # ** Read cave symbols from the ELF via cave_syms, never hardcode or re-derive them. **
    # This file originally rolled its own m68k-elf-nm parse into a local dict named `syms`,
    # so the later `syms()` call in the liveness phase hit "'dict' object is not callable".
    # Removing the dict then produced "name 'syms' is not defined", because the import had
    # never been added here in the first place -- only to diag_reload3_repeat.py and
    # diag_reload3_led.py. Two failed runs, ~15 min of emulator time, for one missing line.
    # See tools/cave_syms.py for why hardcoding the addresses is worse than either.
    S = syms()
    RL_OWN, RL_MSG = S["rl_own"], S["rl_msg"]
    RL_DONE, RL_JOB, SETFLAG = S["rl_done"], S["rl_job"], S["rlj_setflag"]
    print(f"   symbols: rl_own={RL_OWN:#x} rl_msg={RL_MSG:#x} rl_done={RL_DONE:#x} "
          f"rl_job={RL_JOB:#x} rlj_setflag={SETFLAG:#x}")

    # trace the decision points so a non-draw is explained, not just observed
    T = {"job": 0, "done": 0, "skip": 0}
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, lambda u, ad, sz, x: T.__setitem__("job", T["job"] + 1),
                   begin=RL_JOB, end=RL_JOB)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, lambda u, ad, sz, x: T.__setitem__("done", T["done"] + 1),
                   begin=RL_DONE, end=RL_DONE)

    def key(c, e):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(c, e), budget=4_000_000)

    def chord(hold):
        C["msg"] = 0
        T["job"] = T["done"] = 0
        key(hold, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(hold, RELEASE)
        # ** Wait on rl_done ENTRY, not on rl_msg reaching 0. ** rl_msg only clears on
        # the "ours" branch (rld_skip); if rl_own is 0 when rl_done runs, execution falls
        # straight through to DONE_RESUME and rl_msg is untouched -- so polling rl_msg
        # cannot distinguish "still running" from "took the other branch", and a v1 of
        # this test misread the second case as a timeout on the [BANK] chord (a false
        # "settled=False, msg=2" that contradicted diag_reload3_repeat.py's clean 4/4
        # BYTE-LEVEL restore on that exact chord). rl_done's OWN entry is unambiguous:
        # doneFn reaches it exactly once per job, on every path. Same signal
        # diag_reload3_repeat.py already validated.
        settled = False
        for _ in range(300):
            rt.run(ms=20)
            if T["done"] > 0:
                settled = True
                break
        for _ in range(10):
            rt.run(ms=60)          # fixed settle tail: let the message actually draw
        C["settled"] = settled
        print(f"      trace: settled={C.get('settled')}  rl_job entered={T['job']}  "
              f"rl_done entered={T['done']}  "
              f"rl_own={rt.uc.mem_read(RL_OWN, 1)[0]}  rl_msg={rt.uc.mem_read(RL_MSG, 1)[0]}"
              f"  msgs_drawn={C['msg']}")
        return C["msg"]

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    print("\n--- SUCCESS: the message must still draw ---")
    n_ptn = chord(PTN_CODE)
    chk(n_ptn >= 1, f"[PTN]+[TRACK] drew its message ({n_ptn}) -- deferring it to the "
                    f"completion did not lose it")
    n_bank = chord(BANK_CODE)
    chk(n_bank >= 1, f"[BANK]+[TRACK] drew its message ({n_bank})")

    print("\n--- FAILURE (FOPEN stubbed to -1): the message must NOT draw ---")
    save = bytes(rt.uc.mem_read(FOPEN, 4))
    rt.uc.mem_write(FOPEN, bytes([0x70, 0xFF, 0x4E, 0x75]))   # moveq #-1,d0 ; rts
    n_fail = chord(PTN_CODE)
    own_after = rt.uc.mem_read(RL_OWN, 1)[0]
    chk(own_after == 0,
        f"the job really FAILED (rl_own={own_after}, set only after a real copy) -- GATE: "
        f"proves the absence below is caused by failure, not by the chord being ignored")
    chk(n_fail == 0,
        f"** no success message on a FAILED reload (drew {n_fail}) ** -- the toast can no "
        f"longer say RELOADED when nothing was reloaded")

    print("\n--- RECOVERY: un-stub; the message must come back ---")
    rt.uc.mem_write(FOPEN, save)
    n_rec = chord(PTN_CODE)
    chk(n_rec >= 1,
        f"the message draws again ({n_rec}) -- the failure did not strand the one-shot "
        f"rl_msg (report #13's rl_own leak, same class)")

    # ---- DETECTOR LIVENESS for the new self-verify: force a mismatch ----
    # Without this, "no false positive" is untested in the failing direction -- the new
    # rld_vloop could be dead code and every assertion above would still pass.
    # rlj_setflag runs AFTER the copy and BEFORE doneFn, so corrupting the snapshot there
    # makes rl_done's compare fail exactly as a real overwrite would.
    print("\n--- DETECTOR LIVENESS: corrupt the snapshot, expect 'SEQ RELOAD LOST' ---")
    VSNAP = S["rl_vsnap"]
    texts = []

    def on_draw(uc, address, size, ud):
        # WIN_DRAW1(handle, bottomText, topText, font) -- grab bottomText at 8(sp)
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        try:
            ptr = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
            raw = uc.mem_read(ptr, 24)
            texts.append(raw.split(b"\x00")[0].decode("latin1"))
        except Exception:
            pass
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=0x40057008, end=0x40057008)

    corrupt = {"done": False}

    def on_setflag(uc, address, size, ud):
        if not corrupt["done"]:
            uc.mem_write(VSNAP, b"\xA5" * 16)     # not what was written
            corrupt["done"] = True
    h_sf = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_setflag, begin=SETFLAG, end=SETFLAG)
    texts.clear()
    n_lost = chord(PTN_CODE)
    rt.uc.hook_del(h_sf)
    print(f"      lines drawn: {texts}")
    chk(corrupt["done"], "the snapshot really was corrupted at rlj_setflag -- GATE")
    chk(any("LOST" in t or "RESTORED" in t for t in texts),
        f"** the self-verify FIRED and drew the LOST message ({texts}) ** -- so the check "
        f"is live code, and a clean run's success message is a real negative")
    chk(n_lost >= 1, f"a message still drew ({n_lost}) -- the user is told something")

    print()
    if fails:
        print(f"   {len(fails)} FAILURE(S):")
        for f in fails:
            print(f"     - {f}")
        return 1
    print("   ALL GOOD -- the message now reports the worker's real outcome.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

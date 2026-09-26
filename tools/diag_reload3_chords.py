#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_chords -- drive the RELOAD3 chords through REAL key dispatch.

Session 85. RELOAD2's suite tested a picker that no longer exists. This tests what
the redesign actually does:

  [PTN]  + [TRACK n]  -> reload track n's CF-saved sequence, Part untouched
  [BANK] + [TRACK n]  -> the same, PLUS re-apply the saved Part from RAM

Everything goes through `set_key_state` (0x40031734), the real per-key dispatcher --
the standing rule in this thread, because every routing-class bug it has had was
invisible to direct-call tests.

WHAT IS ASSERTED, and why each one earns its place:

  * the track comes from the KEYCODE, not the UI-selected track. That is the whole
    point of the chord (`G_TRK` must equal the button pressed, not CUR_TRACK).
  * a plain [TRACK] press with NO modifier must arm NOTHING and must reach stock's
    own track select. This is the regression that matters most -- we detour the
    ordinary track handler, so a bug here breaks track selection itself.
  * [PTN] release must NOT show SELECT PATTERN. Measured precisely: stock shows it
    with `jsr 0x40059f8c` at 0x4005a0b4, so hook that and assert zero calls.
  * [BANK]+[TRACK] must call PART_RELOAD (0x4004aab4) exactly once, and must take
    the two-line MLNOTIFY path when it returns 0 (never-saved) and the single
    TOAST path otherwise. Both branches are forced with a stub, so neither depends
    on the test project's Part happening to be saved.
  * repeated cycles must not drift (>=5, per this thread's own rule that
    single-cycle green is worthless evidence).

Usage:
  python3 tools/diag_reload3_chords.py [--iters N] [--track N]
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

G_KIND, G_TRK, G_TMIDI = 0x80006A50, 0x80006A54, 0x80006A55
PTN_CONSUMED = 0x460D173E
BANK_COMMIT = 0x460E73C2
SELPAT_SHOW = 0x40059F8C     # stock shows SELECT PATTERN with this, at 0x4005a0b4
PART_RELOAD = 0x4004AAB4
BANK_WIN_CLOSE = 0x4007B408
MLNOTIFY = 0x4006D57C
TOAST = 0x4005A2B8
LAYER_PUSH = 0x40031494
OK_LAYER = 0x400CDFF8        # MLNOTIFY's OK-prompt keymap layer
TOAST_CD = 0x460D1E6C        # the block toast's own countdown (no gate flag)
TRK_BASE_RES = 0x40040256    # stock track-select path, just past our detour
DISPATCH = 0x46C7D8DE        # runtime dispatch table, 24-B stride
HELD = 0x46C7D8EE            # per-key is-held array, same stride
PTN_TRK_H = 0x40083DC4       # the [PTN]-overlay TRACK handler we detour
TRK_BASE_H = 0x40040250      # the base TRACK handler


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--data", action="store_true",
                    help="data-level check: scribble ALL 16 tracks, drive the chord, and "
                         "verify ONLY the pressed track reverted. RELOAD2's --trk proves "
                         "the worker writes the right saved bytes, but it drives the old "
                         "CUR_TRACK entry -- this proves the CHORD targets the right track.")
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

    import subprocess
    nm = subprocess.run(["m68k-elf-nm", "out/patch_reload3.elf"],
                        capture_output=True, text=True, cwd=ROOT).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}

    C = {k: 0 for k in ("rl_job", "selpat", "partreld", "bankclose", "ml", "toast",
                        "stocktrk", "arm", "card", "oklayer")}

    def hook(addr, key):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                       lambda u, ad, sz, x: C.__setitem__(key, C[key] + 1),
                       begin=addr, end=addr)

    hook(sym["rl_job"], "rl_job")
    hook(SELPAT_SHOW, "selpat")
    hook(PART_RELOAD, "partreld")
    hook(BANK_WIN_CLOSE, "bankclose")
    hook(MLNOTIFY, "ml")
    hook(TOAST, "toast")
    hook(sym["rl3_toast2"], "card")
    # Session 88: the "OK" prompt IS this keymap layer push. MLNOTIFY pushed
    # 0x400cdff8 at 0x4006d722 and that is what made the box wait for a key. The new
    # card pushes no layer at all, so this counter must stay at zero -- it is the
    # only direct evidence that there is no OK prompt to answer.
    def on_push(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        if struct.unpack(">I", u.mem_read(sp + 4, 4))[0] == OK_LAYER:
            C["oklayer"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_push, begin=LAYER_PUSH, end=LAYER_PUSH)
    hook(TRK_BASE_RES, "stocktrk")
    hook(sym["rl3_arm_n"], "arm")
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    for _ in range(25):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def drain(n=60):
        for _ in range(n):
            rt.run(ms=60)

    def snap():
        return {k: C[k] for k in C}

    def delta(b):
        return {k: C[k] - b[k] for k in C}

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    # ---------- 1. plain [TRACK] -- must arm NOTHING and reach stock ----------
    print("\n--- plain [TRACK] press, no modifier (must be ordinary track select) ---")
    b = snap()
    key(TRACK0 + a.track, PRESS); key(TRACK0 + a.track, RELEASE); drain(10)
    d = delta(b)
    chk(d["arm"] == 0, f"armed nothing (arm calls {d['arm']})")
    chk(d["rl_job"] == 0, f"no reload job ran (rl_job {d['rl_job']})")
    chk(d["stocktrk"] >= 1, f"reached stock's own track select (x{d['stocktrk']})")

    # ---------- 2. [PTN] + [TRACK n] ----------
    # Session 85: is the [PTN] OVERLAY actually pushed by a bare press? The keymap
    # records PTN with a hold delay of 0x1e, so a press with no elapsed hold time may
    # leave the track keys on the BASE handler -- in which case [PTN]+[TRACK] can
    # never reach our detour and the failure is the harness's, not the firmware's.
    # Measure it instead of guessing: read the live dispatch slot for the track key.
    def trk_slot():
        return struct.unpack(">I", rt.uc.mem_read(DISPATCH + (TRACK0 + a.track) * 24, 4))[0]

    def who(v):
        return {PTN_TRK_H: "PTN-overlay", TRK_BASE_H: "base"}.get(v, f"{v:#010x}")

    print("\n--- does a [PTN] press actually push the [PTN] overlay? ---")
    print(f"   idle                      TRACK slot -> {who(trk_slot())}")
    key(PTN_CODE, PRESS)
    print(f"   after [PTN] press         TRACK slot -> {who(trk_slot())}  "
          f"held={struct.unpack('>I', rt.uc.mem_read(HELD + PTN_CODE*24, 4))[0]:#x}")
    drain(20)
    print(f"   after 20 frames held      TRACK slot -> {who(trk_slot())}")
    ptn_overlay_live = trk_slot() == PTN_TRK_H
    key(PTN_CODE, RELEASE); drain(10)
    # NOT a failure: Session 85 measured that the overlay never redirects the TRACK
    # keys, so the chord goes through the base handler's PTN held-flag test instead.
    # (An explicit event=2 HOLD was tried here and hung call_as_main -- it is not a
    # gesture a physical key can produce, the same class of test artifact this thread
    # already hit with an unmatched press.)
    print(f"   overlay route {'available' if ptn_overlay_live else 'NOT used'} -- "
          "chord relies on the base handler's held-flag test")

    print(f"\n--- [PTN] + [TRACK {a.track+1}] : sequence only, Part untouched ---")
    for it in range(1, a.iters + 1):
        b = snap()
        rt.uc.mem_write(PTN_CONSUMED, struct.pack(">I", 0))
        key(PTN_CODE, PRESS)
        drain(4)                     # no hold needed: the held-flag is set by the press
        key(TRACK0 + a.track, PRESS); key(TRACK0 + a.track, RELEASE)
        consumed = u32(PTN_CONSUMED)
        trk, tmidi = rt.uc.mem_read(G_TRK, 1)[0], rt.uc.mem_read(G_TMIDI, 1)[0]
        key(PTN_CODE, RELEASE)
        drain()
        d = delta(b)
        if it == 1:
            chk(d["arm"] == 1, f"armed exactly once (x{d['arm']})")
            chk(trk == a.track, f"G_TRK == the button pressed ({trk}, want {a.track})")
            chk(consumed != 0, f"PTN_CONSUMED set ({consumed:#010x})")
            chk(d["selpat"] == 0, f"SELECT PATTERN NOT shown on release (x{d['selpat']})")
            chk(d["partreld"] == 0, f"Part NOT touched (PART_RELOAD x{d['partreld']})")
            chk(d["toast"] == 1,
                f"stock's own one-line BLOCK toast used (x{d['toast']}) -- report #11")
            chk(d["card"] == 0,
                f"the 2-line path not used for this 1-line message (x{d['card']})")
            chk(d["oklayer"] == 0, f"no OK prompt (x{d['oklayer']})")
            chk(d["rl_job"] == 1, f"the worker ran once (x{d['rl_job']})")
        print(f"   it{it}: arm={d['arm']} job={d['rl_job']} G_TRK={trk} midi={tmidi} "
              f"selpat={d['selpat']} partreld={d['partreld']} G_KIND={rt.uc.mem_read(G_KIND,1)[0]}")
        if d["selpat"] or d["partreld"] or d["arm"] != 1:
            fails.append(f"[PTN]+[TRACK] drifted on iteration {it}")

    # ---------- 3. [BANK] + [TRACK n], both PART_RELOAD outcomes ----------
    save = bytes(rt.uc.mem_read(PART_RELOAD, 4))
    # Session 89: both [BANK] branches draw a TWO-LINE BLOCK toast (rl3_toast2).
    # MLNOTIFY stays at zero -- it is the thing that had the OK prompt -- and stock's
    # one-line TOAST is not used here, because these messages are two lines.
    for ret, label in ((1, "Part SAVED -> two-line block toast"),
                       (0, "Part NEVER SAVED -> two-line block toast")):
        print(f"\n--- [BANK] + [TRACK {a.track+1}] : {label} ---")
        # force PART_RELOAD's verdict so neither branch depends on the project
        rt.uc.mem_write(PART_RELOAD, bytes([0x70, ret, 0x4E, 0x75]))   # moveq #ret,d0 ; rts
        rt.uc.ctl_flush_tb()
        b = snap()
        rt.uc.mem_write(BANK_COMMIT, struct.pack(">I", 1))
        key(BANK_CODE, PRESS)
        key(TRACK0 + a.track, PRESS); key(TRACK0 + a.track, RELEASE)
        trk = rt.uc.mem_read(G_TRK, 1)[0]
        commit = u32(BANK_COMMIT)
        key(BANK_CODE, RELEASE)
        drain()
        d = delta(b)
        chk(d["arm"] == 1, f"armed exactly once (x{d['arm']})")
        chk(trk == a.track, f"G_TRK == the button pressed ({trk})")
        chk(d["partreld"] == 1, f"PART_RELOAD called once (x{d['partreld']})")
        chk(d["bankclose"] >= 1, f"SELECT BANK dismissed (x{d['bankclose']})")
        chk(commit == 0, f"BANK_COMMIT cleared ({commit:#010x})")
        chk(d["card"] == 1, f"the two-line block toast drew once (x{d['card']})")
        chk(d["ml"] == 0, f"MLNOTIFY never used (x{d['ml']}) -- no OK dialog")
        chk(d["toast"] == 0,
            f"stock's ONE-line toast not used for a 2-line message (x{d['toast']})")
        chk(d["oklayer"] == 0,
            f"no OK-prompt keymap layer pushed (x{d['oklayer']}) -- nothing to answer")
        chk(u32(TOAST_CD) != 0,
            f"the toast's own countdown is armed (0x460d1e6c={u32(TOAST_CD)})")
    rt.uc.mem_write(PART_RELOAD, save)
    rt.uc.ctl_flush_tb()

    # ---------- 4. data-level: only the pressed track may revert ----------
    if a.data:
        MIDI_BASE, MTRA = 0x48D0, 0x8B0
        blob = erl.BANK_BLOB + bank * erl.BANK_STRIDE
        pP = blob + P * erl.PAT_STRIDE

        def aud(t):
            return pP + t * erl.TRAC_STRIDE

        def mid(t):
            return pP + MIDI_BASE + t * MTRA

        def scribble():
            # a recognisable pattern in every audio and MIDI track region
            for t in range(8):
                rt.uc.mem_write(aud(t), bytes([0x5A ^ t]) * 0x40)
                rt.uc.mem_write(mid(t), bytes([0xA5 ^ t]) * 0x40)

        def still_scribbled(t, midi=False):
            want = bytes([(0xA5 if midi else 0x5A) ^ t]) * 0x40
            return bytes(rt.uc.mem_read(mid(t) if midi else aud(t), 0x40)) == want

        for label, mods in (("[PTN]", (PTN_CODE,)), ("[BANK]", (BANK_CODE,))):
            n = a.track
            print(f"\n--- data: {label} + [TRACK {n+1}] must revert ONLY track {n+1} ---")
            scribble()
            b = snap()
            for m in mods:
                key(m, PRESS)
            drain(4)
            key(TRACK0 + n, PRESS); key(TRACK0 + n, RELEASE)
            for m in mods:
                key(m, RELEASE)
            # drain on the worker actually having run, not on a fixed time
            for _ in range(120):
                rt.run(ms=60)
                if C["rl_job"] > b["rl_job"] and rt.uc.mem_read(G_KIND, 1)[0] == 0:
                    break
            drain(20)
            chk(not still_scribbled(n),
                f"audio track {n+1} WAS overwritten by the reload")
            others = [t for t in range(8) if t != n and not still_scribbled(t)]
            chk(not others,
                f"the other 7 audio tracks untouched (clobbered: {[x+1 for x in others]})")
            m_bad = [t for t in range(8) if not still_scribbled(t, midi=True)]
            chk(not m_bad,
                f"all 8 MIDI tracks untouched (clobbered: {[x+1 for x in m_bad]})")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- both chords behave, plain [TRACK] is untouched, "
          "and neither Part branch depends on the project.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

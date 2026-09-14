#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Isolation-exercise the QUANTIZE LIVE REC front-panel toggle (build_qlrec.py).

Session 50: the toast used to be a one-shot "persistent" (dur<=0)
FUN_4005a2b8 call, closed explicitly on [REC] release.  That HUNG a real MKI --
dur<=0 registers on what real disassembly shows is a modal window stack, so the
OS's input dispatch stopped reaching our own [REC]-release handler at all.
Fixed by periodically RE-ARMING a short dur>0 (self-timing, non-modal) call
instead.  Flashed post-fix: no hang. Six follow-up requests, folded in here as
Session 51 (see tools/patch_qlrec.s's header + NOTES.md "Session 51" for the
full story):

  qlr_play   @ detour of 0x40061778  ([PLAY] press, keycode 0x28)
       - REC not held              -> stock ([PLAY] resumes at 0x4006177e)
       - REC held, very 1st press  -> stock (stock starts LIVE REC), G_CNT := 1,
                                       G_WINDOW := MAX_GAP
       - REC held, later press,
         G_WINDOW > 0 (fast enough)-> completes the pair: flip 0x800000ac +
                                       shadow + re-checksum, NOTIFY(text,
                                       REARM_DUR), G_ARM := 1, G_WINDOW reset,
                                       swallow
       - REC held, later press,
         G_WINDOW <= 0 (too slow)  -> discard the stale pairing attempt, THIS
                                       press becomes the new reference
                                       (G_WINDOW reset, no flip), swallow
       Session 51 item 6: the shown string is now INVERTED vs the raw bit --
       HW-confirmed the PERSONALIZE menu's checked glyph is raw 0, not raw 1.

  qlr_recrel @ detour of 0x4004883a  ([REC] release)
       - always clears REC_HELD + G_CNT
       - Session 51 item 4: if G_ARM, clears it AND calls NOTIFY_CLOSE for an
         instant close (safe now that dur is never <=0, unlike pre-Session-50)

  qlr_tick   @ detour of 0x400522ca  (per-control-frame tick, jsr-kind)
       - Session 51 item 1 (new): while REC_HELD and a hold is in progress
         (G_CNT != 0), decrements G_WINDOW once per tick (independent of
         toast/G_ARM state) -- this is what makes the pairing window actually
         expire over time.
       - G_ARM == 0               -> just replay the displaced `lea`, rts
       - G_ARM != 0, G_RTICKS > 1 -> decrement G_RTICKS, replay+rts (not time yet)
       - G_ARM != 0, G_RTICKS <= 1 (post-decrement) -> re-issue
         NOTIFY(G_LASTMSG, REARM_DUR), reset G_RTICKS, THEN replay+rts

The full keymap dispatch is not modelled -- these are the three cave routines run
against the real assembled bytes with the OS calls stubbed to `rts`.  What this
harness CANNOT show: whether the real FUN_4005a2b8/FUN_40056bec bodies behave as
assumed -- see tools/emu_notify_probe.py for the full-firmware dynamic check of
that (Session 50's actual hang-finding tool).

Run after:  python3 tools/build_qlrec.py
Usage:      python3 tools/emu_qlrec.py
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
_bin = ROOT / "out/patch_qlrec.bin"
_elf = ROOT / "out/patch_qlrec.elf"
if not _bin.exists():
    sys.exit(f"missing {_bin.name} -- run: python3 tools/build_qlrec.py")
STUB = _bin.read_bytes()
LOAD = 0x400d7400
_nm = subprocess.run(["m68k-elf-nm", str(_elf)], capture_output=True, text=True).stdout
SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
QLR_PLAY = SYM["qlr_play"]
QLR_RECREL = SYM["qlr_recrel"]
QLR_TICK = SYM["qlr_tick"]
MSG_ON, MSG_OFF = SYM["qlr_msg_on"], SYM["qlr_msg_off"]

CKSUM = 0x4001f23c
NOTIFY = 0x4005a2b8
NOTIFY_CLOSE = 0x40056bec
PROJ_GATE = 0x4009b5c0
PLAY_RESUME = 0x4006177e
WATCHDOG_A2 = 0x46c7dfba   # displaced `lea` target at the qlr_tick detour site
SENTINEL = 0x40200000      # synthetic return address (a swallowed key `rts`es here)

REC_HELD = 0x460d1726
QLR = 0x800000ac
QLR_SH = 0x100fff3c
G_CNT = 0x80006a5c
G_ARM = 0x80006a60
G_RTICKS = 0x80006a64
G_LASTMSG = 0x80006a68
G_WINDOW = 0x80006a6c      # Session 51: double-tap pairing window (ticks remaining)
G_PEND = 0x80006a70        # Session 51-bis: is a press currently waiting for its FRESH partner
REARM_DUR = 0x20
REARM_INTERVAL = 0x10
MAX_GAP = 0x10

fails = []


def check(name, cond, detail=""):
    print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(LOAD, STUB)
    for a in (CKSUM, NOTIFY, NOTIFY_CLOSE, PROJ_GATE):
        uc.mem_write(a, b"\x4e\x75")           # rts -- record the call, return
    uc.mem_write(PLAY_RESUME, b"\x4e\x75")     # marker for the stock-play resume
    return uc


def run_play(rec_held, cnt=0, qlr=0, sh=0xdead, arm=0, window=MAX_GAP, pend=1):
    uc = mk()
    uc.mem_write(REC_HELD, struct.pack(">I", rec_held))
    uc.mem_write(QLR, struct.pack(">I", qlr))
    uc.mem_write(QLR_SH, struct.pack(">I", sh))
    uc.mem_write(G_CNT, struct.pack(">I", cnt))
    uc.mem_write(G_ARM, struct.pack(">B", arm))
    uc.mem_write(G_WINDOW, struct.pack(">i", window))
    uc.mem_write(G_PEND, struct.pack(">B", pend))
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", SENTINEL, 0x28, 1))   # ret, keycode, event
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = dict(cksum=False, notify=None, notify_dur=None,
              proj_gate=False, resume=False, swallowed=False)

    def hook(uc, addr, size, u):
        if addr == CKSUM:
            st["cksum"] = True
        elif addr == NOTIFY:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["notify"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            st["notify_dur"] = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
        elif addr == PROJ_GATE:
            st["proj_gate"] = True
        elif addr == PLAY_RESUME:
            st["resume"] = True
            uc.emu_stop()
        elif addr == SENTINEL:
            st["swallowed"] = True
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(QLR_PLAY, 0, count=20000)
    except UcError:
        pass
    uc.hook_del(h)
    st["qlr"] = struct.unpack(">I", uc.mem_read(QLR, 4))[0]
    st["sh"] = struct.unpack(">I", uc.mem_read(QLR_SH, 4))[0]
    st["cnt"] = struct.unpack(">I", uc.mem_read(G_CNT, 4))[0]
    st["arm"] = uc.mem_read(G_ARM, 1)[0]
    st["rticks"] = struct.unpack(">i", uc.mem_read(G_RTICKS, 4))[0]
    st["lastmsg"] = struct.unpack(">I", uc.mem_read(G_LASTMSG, 4))[0]
    st["window"] = struct.unpack(">i", uc.mem_read(G_WINDOW, 4))[0]
    st["pend"] = uc.mem_read(G_PEND, 1)[0]
    return st


def run_recrel(rec_held=1, cnt=3, arm=1, pend=1):
    uc = mk()
    uc.mem_write(REC_HELD, struct.pack(">I", rec_held))
    uc.mem_write(G_CNT, struct.pack(">I", cnt))
    uc.mem_write(G_ARM, struct.pack(">B", arm))
    uc.mem_write(G_PEND, struct.pack(">B", pend))
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", SENTINEL, 0x29, 0))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = dict(close=False)

    def hook(uc, addr, size, u):
        if addr == NOTIFY_CLOSE:
            st["close"] = True
        elif addr == SENTINEL:
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(QLR_RECREL, 0, count=20000)
    except UcError:
        pass
    uc.hook_del(h)
    st["rec_held"] = struct.unpack(">I", uc.mem_read(REC_HELD, 4))[0]
    st["cnt"] = struct.unpack(">I", uc.mem_read(G_CNT, 4))[0]
    st["arm"] = uc.mem_read(G_ARM, 1)[0]
    st["pend"] = uc.mem_read(G_PEND, 1)[0]
    return st


def run_tick(arm=0, rticks=REARM_INTERVAL, lastmsg=None, rec_held=0, cnt=0, window=MAX_GAP, pend=0):
    uc = mk()
    uc.mem_write(G_ARM, struct.pack(">B", arm))
    uc.mem_write(G_RTICKS, struct.pack(">i", rticks))
    uc.mem_write(G_LASTMSG, struct.pack(">I", lastmsg if lastmsg is not None else MSG_ON))
    uc.mem_write(REC_HELD, struct.pack(">I", rec_held))
    uc.mem_write(G_CNT, struct.pack(">I", cnt))
    uc.mem_write(G_WINDOW, struct.pack(">i", window))
    uc.mem_write(G_PEND, struct.pack(">B", pend))
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">I", SENTINEL))   # jsr-kind: only a return addr on entry
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = dict(notify=None, notify_dur=None, a2=None)

    def hook(uc, addr, size, u):
        if addr == NOTIFY:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["notify"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            st["notify_dur"] = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
        elif addr == SENTINEL:
            st["a2"] = uc.reg_read(UC_M68K_REG_A2)
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(QLR_TICK, 0, count=20000)
    except UcError:
        pass
    uc.hook_del(h)
    st["rticks"] = struct.unpack(">i", uc.mem_read(G_RTICKS, 4))[0]
    st["window"] = struct.unpack(">i", uc.mem_read(G_WINDOW, 4))[0]
    return st


def test_play():
    print("qlr_play  ([REC] held + [PLAY]) ------------------------------")

    r = run_play(rec_held=0, qlr=0)
    check("REC not held -> stock resume (0x4006177e)", r["resume"] and r["proj_gate"])
    check("REC not held -> no flip / no toast", r["qlr"] == 0 and r["notify"] is None)
    check("REC not held -> counter untouched", r["cnt"] == 0)

    r = run_play(rec_held=1, cnt=0, qlr=0)
    check("very 1st press -> stock resume (stock starts LIVE REC)", r["resume"] and r["proj_gate"])
    check("very 1st press -> counter = 1", r["cnt"] == 1)
    check("very 1st press -> arms the pairing window", r["window"] == MAX_GAP)
    check("very 1st press -> sets G_PEND", r["pend"] == 1)
    check("very 1st press -> no flip / no toast", r["qlr"] == 0 and r["notify"] is None)

    r = run_play(rec_held=1, cnt=1, qlr=0, sh=0xdead, window=5)
    check("2nd press, FAST (window still > 0) -> QLR 0 -> 1", r["qlr"] == 1)
    check("2nd press, fast -> shadow 0x100fff3c = 1", r["sh"] == 1)
    check("2nd press, fast -> re-checksum called", r["cksum"])
    check('2nd press, fast, QLR now 1 -> NOTIFY the OFF string (menu-inverted label, item 6)',
          r["notify"] == MSG_OFF, f"got 0x{(r['notify'] or 0):08x} want 0x{MSG_OFF:08x}")
    check("2nd press, fast -> NOTIFY dur = REARM_DUR (self-timing, NEVER 0 -- Session 50)",
          r["notify_dur"] == REARM_DUR, str(r["notify_dur"]))
    check("2nd press, fast -> G_LASTMSG = the OFF string", r["lastmsg"] == MSG_OFF)
    check("2nd press, fast -> G_RTICKS armed to REARM_INTERVAL", r["rticks"] == REARM_INTERVAL)
    check("2nd press, fast -> G_ARM set", r["arm"] == 1)
    check("2nd press, fast -> G_PEND cleared (a flip does NOT pre-arm a new pending press)",
          r["pend"] == 0)
    check("2nd press, fast -> [PLAY] swallowed (no resume, no transport gate)",
          r["swallowed"] and not r["resume"] and not r["proj_gate"])
    check("2nd press, fast -> counter = 2", r["cnt"] == 2)

    r = run_play(rec_held=1, cnt=1, qlr=0, window=0)
    check("2nd press, TOO SLOW (window <= 0) -> no flip", r["qlr"] == 0 and r["notify"] is None)
    check("2nd press, too slow -> discarded, becomes the new reference (window re-armed)",
          r["window"] == MAX_GAP)
    check("2nd press, too slow -> swallowed, not sent to stock",
          r["swallowed"] and not r["resume"] and not r["proj_gate"])

    r = run_play(rec_held=1, cnt=1, qlr=0, window=-3)
    check("2nd press, window already very negative -> still treated as too slow (no flip)",
          r["qlr"] == 0 and r["notify"] is None and r["window"] == MAX_GAP)

    r = run_play(rec_held=1, cnt=2, qlr=1, window=5)
    check("3rd press, fast, QLR now 0 -> NOTIFY the ON string", r["notify"] == MSG_ON)
    check("3rd press, fast -> QLR 1 -> 0", r["qlr"] == 0)

    # --- HW-confirmed bug fix: a fast press right after a flip must NOT
    # complete a "pair" with the flip itself (G_PEND cleared by the flip) ---
    r = run_play(rec_held=1, cnt=5, qlr=1, window=MAX_GAP, pend=0)
    check("press right after a flip (G_PEND=0, window freshly re-armed) -> "
          "NOT flipped, even though the window itself looks fast enough",
          r["qlr"] == 1 and r["notify"] is None)
    check("that press becomes the new pending reference", r["pend"] == 1 and r["window"] == MAX_GAP)

    r = run_play(rec_held=1, cnt=5, qlr=1, window=5, pend=1)
    check("a GENUINE pending press, fast -> still flips normally", r["notify"] == MSG_ON)
    check("a genuine flip clears G_PEND again (require a fresh pair for the next one)",
          r["pend"] == 0)


def test_recrel():
    print("qlr_recrel  ([REC] release) ---------------------------------")

    r = run_recrel(rec_held=1, cnt=3, arm=1, pend=1)
    check("clears REC_HELD (0x460d1726)", r["rec_held"] == 0)
    check("clears the press counter", r["cnt"] == 0)
    check("clears G_PEND", r["pend"] == 0)
    check("toast was armed -> NOTIFY_CLOSE called (Session 51 item 4: instant close)",
          r["close"])
    check("toast was armed -> G_ARM cleared", r["arm"] == 0)

    r = run_recrel(rec_held=1, cnt=1, arm=0)
    check("not armed -> NOTIFY_CLOSE NOT called (nothing to close)", not r["close"])
    check("not armed -> still clears REC_HELD + counter, no crash",
          r["rec_held"] == 0 and r["cnt"] == 0 and r["arm"] == 0)


def test_tick():
    print("qlr_tick  (per-control-frame re-arm + pairing-window countdown) --------")

    r = run_tick(arm=0)
    check("not armed -> no NOTIFY call", r["notify"] is None)
    check("not armed -> displaced `lea 0x46c7dfba,%a2` still replayed",
          r["a2"] == WATCHDOG_A2, f"a2=0x{(r['a2'] or 0):08x}")

    r = run_tick(arm=1, rticks=5)
    check("armed, ticks remaining -> no NOTIFY call yet", r["notify"] is None)
    check("armed, ticks remaining -> G_RTICKS decremented", r["rticks"] == 4)
    check("armed, ticks remaining -> displaced lea still replayed",
          r["a2"] == WATCHDOG_A2)

    r = run_tick(arm=1, rticks=1, lastmsg=MSG_ON)
    check("armed, ticks hit 0 -> NOTIFY re-issued with the last message",
          r["notify"] == MSG_ON)
    check("armed, ticks hit 0 -> dur = REARM_DUR (still self-timing, never 0)",
          r["notify_dur"] == REARM_DUR, str(r["notify_dur"]))
    check("armed, ticks hit 0 -> G_RTICKS reset to REARM_INTERVAL",
          r["rticks"] == REARM_INTERVAL)
    check("armed, ticks hit 0 -> displaced lea still replayed after the re-arm",
          r["a2"] == WATCHDOG_A2)

    r = run_tick(arm=1, rticks=1, lastmsg=MSG_OFF)
    check("re-arm uses whatever G_LASTMSG currently holds (OFF string here)",
          r["notify"] == MSG_OFF)

    r = run_tick(arm=1, rticks=0, lastmsg=MSG_ON)
    check("G_RTICKS already at/below 0 (stale) -> still re-arms, doesn't wait forever",
          r["notify"] == MSG_ON)

    # --- Session 51 item 1: the pairing-window countdown ---
    r = run_tick(rec_held=0, cnt=1, window=5, pend=1)
    check("REC not held -> window NOT decremented (nothing pending without REC)",
          r["window"] == 5)

    r = run_tick(rec_held=1, cnt=1, window=5, pend=0)
    check("REC held but G_PEND=0 (Session 51-bis: e.g. right after a flip) -> "
          "window NOT decremented", r["window"] == 5)

    r = run_tick(rec_held=1, cnt=1, window=5, pend=1)
    check("REC held, a press genuinely pending -> window decremented once", r["window"] == 4)

    r = run_tick(rec_held=1, cnt=1, window=0, pend=1)
    check("window already at 0 -> keeps counting down (goes negative, not stuck)",
          r["window"] == -1)

    r = run_tick(rec_held=1, cnt=1, window=5, pend=1, arm=0)
    check("window countdown is independent of G_ARM/toast state", r["window"] == 4)


def test_string_len():
    print("toast strings ----------------------------------------------")
    on = STUB[MSG_ON - LOAD:STUB.index(b"\0", MSG_ON - LOAD)].decode()
    off = STUB[MSG_OFF - LOAD:STUB.index(b"\0", MSG_OFF - LOAD)].decode()
    check(f'"{on}" ({len(on)})', on == "QUANT LIVE REC ON")
    check(f'"{off}" ({len(off)})', off == "QUANT LIVE REC OFF")
    # FUN_4005a2b8 sizes the window to textpx+15; "QUANT LIVE REC OFF" (18 ch)
    # is well inside 128 px.  Still worth an eyeball on HW.
    check("toast strings <= 18 chars (fit the 128 px screen)", len(on) <= 18 and len(off) <= 18)


if __name__ == "__main__":
    test_play()
    test_recrel()
    test_tick()
    test_string_len()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

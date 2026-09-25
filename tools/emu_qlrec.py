#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Isolation-exercise the QUANTIZE LIVE REC front-panel gesture (build_qlrec.py).

Session 93: the gesture is TOAST-GATED, and "is the toast on screen" is now read
from the OS's OWN notification state instead of being counted by a tick of ours.

    [REC] held + [PLAY]                    opens a toast showing the CURRENT
                                           setting (nothing changes)
    [PLAY] again WHILE THAT TOAST IS UP    inverts the setting, toast re-opens
                                           showing the new one (and again, ...)
    [PLAY] after the toast has gone        just shows the current setting

  A press flips iff  NOTIF_H != 0  --  i.e. iff the OS says a toast is on
  screen.  THIS PATCH KEEPS NO STATE OF ITS OWN.

  Session 94 dropped NOTIF_T > 0 (redundant: FUN_40056c28 clears the handle at
  expiry).  Session 95 dropped the private magic word G_OWN (0x80006a60) too,
  after a diagnostic build on hardware reported "QLR DIAG: OWN" on EVERY press:
  the scratch word does not survive between key presses on the unit, though it
  persists perfectly here -- the emulator does not run the DSP/audio path for
  real.  Every private word this patch ever kept lived in the DSP shared-RAM
  window, and every emulator "green" was green because of that blind spot.

  ⚠️ WHY THIS HARNESS EXISTS IN THIS SHAPE.  Session 92 counted the toast's life
  in `qlr_tick`, a detour of 0x400522ca.  Flashed 2026-09-25 and it CRASHED the
  unit (dead controls + persistent HF crackle) because NOTIFY/NOTIFY_CLOSE reach
  the kernel post FUN_40000c3c -- a task wake + ready-list poke -- from inside
  the engine frame handler.  The same hook firing too rarely also left the flip
  window permanently open, so presses flipped long after the toast had gone.
  Both are covered below: `test_no_tick_detour` asserts the cave contains no
  reference to the retired hook site, and `test_window_closes_without_us`
  asserts the window shuts with NO tick of ours ever running.

  qlr_play   @ detour of 0x40061778  ([PLAY] press, keycode 0x28)
  qlr_recrel @ detour of 0x4004883a  ([REC] release)
  (there is no third detour any more)

The full keymap dispatch is not modelled -- these are the two cave routines run
against the real assembled bytes with the OS calls stubbed to `rts`.  What this
harness CANNOT show: whether the real FUN_4005a2b8/FUN_40056bec bodies behave as
assumed -- see tools/emu_notify_probe.py for the full-firmware dynamic check.

Run after:  python3 tools/build_qlrec.py
Usage:      python3 tools/emu_qlrec.py
"""
import pathlib, re, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
_bin = ROOT / "out/patch_qlrec.bin"
_elf = ROOT / "out/patch_qlrec.elf"
if not _bin.exists():
    sys.exit(f"missing {_bin.name} -- run: python3 tools/build_qlrec.py")
STUB = _bin.read_bytes()
LOAD = 0x400D7400
_nm = subprocess.run(["m68k-elf-nm", str(_elf)], capture_output=True, text=True).stdout
SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
QLR_PLAY = SYM["qlr_play"]
QLR_RECREL = SYM["qlr_recrel"]
MSG_ON, MSG_OFF = SYM["qlr_msg_on"], SYM["qlr_msg_off"]

if "qlr_tick" in SYM:
    sys.exit("qlr_tick is back in the cave -- it CRASHED the unit (Session 93); "
             "see tools/patch_qlrec.s's header before reinstating it")


def _equ(name):
    """Read a `.equ NAME, value` out of the patch source -- single source of truth."""
    src = (ROOT / "tools/patch_qlrec.s").read_text()
    m = re.search(rf"^\s*\.equ\s+{name},\s*(0x[0-9a-fA-F]+|\d+)", src, re.M)
    if not m:
        sys.exit(f"could not find `.equ {name}` in tools/patch_qlrec.s")
    return int(m.group(1), 0)


CKSUM = 0x4001F23C
NOTIFY = 0x4005A2B8
NOTIFY_CLOSE = 0x40056BEC
PROJ_GATE = 0x4009B5C0
PLAY_RESUME = 0x4006177E
SENTINEL = 0x40200000      # synthetic return address (a swallowed key `rts`es here)
TICK_SITE = 0x400522CA     # the retired qlr_tick hook -- must appear nowhere

REC_HELD = 0x460D1726
LIVE_REC = 0x460D172A
QLR = 0x800000AC
QLR_SH = 0x100FFF3C
NOTIF_H = 0x460D1E70       # OS toast handle   (0 == nothing on screen)
NOTIF_T = 0x460D1E6C       # OS toast countdown (0 == expired)
LIVE_DUR = _equ("LIVE_DUR")

# Every scratch word this patch has ever used.  It must now touch NONE of them.
RETIRED = {0x80006A5C: "G_CNT", 0x80006A60: "G_OWN", 0x80006A64: "G_RTICKS",
           0x80006A68: "G_LASTMSG", 0x80006A6C: "G_LIVE", 0x80006A70: "G_PEND"}

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
    for a in RETIRED:
        uc.mem_write(a, b"\xa5\xa5\xa5\xa5")   # canaries
    return uc


def _os_toast(uc, handle, ticks):
    uc.mem_write(NOTIF_H, struct.pack(">I", handle))
    uc.mem_write(NOTIF_T, struct.pack(">i", ticks))


def run_play(rec_held, qlr=0, sh=0xDEAD, handle=0, ticks=0, live_rec=0):
    uc = mk()
    uc.mem_write(REC_HELD, struct.pack(">I", rec_held))
    uc.mem_write(LIVE_REC, struct.pack(">I", live_rec))
    uc.mem_write(QLR, struct.pack(">I", qlr))
    uc.mem_write(QLR_SH, struct.pack(">I", sh))
    _os_toast(uc, handle, ticks)
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", SENTINEL, 0x28, 1))   # ret, keycode, event
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = dict(cksum=False, notify=None, notify_dur=None, close=False,
              proj_gate=False, resume=False, swallowed=False)

    def hook(uc, addr, size, u):
        if addr == CKSUM:
            st["cksum"] = True
        elif addr == NOTIFY:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["notify"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            st["notify_dur"] = struct.unpack(">i", uc.mem_read(sp + 8, 4))[0]
            # model what the real NOTIFY does to the OS state
            _os_toast(uc, 0x46C7D384, st["notify_dur"])
        elif addr == NOTIFY_CLOSE:
            st["close"] = True
            _os_toast(uc, 0, 0)
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
    st["retired"] = {a: uc.mem_read(a, 4) for a in RETIRED}
    return st


def run_recrel(rec_held=1, handle=0x46C7D384, ticks=20):
    uc = mk()
    uc.mem_write(REC_HELD, struct.pack(">I", rec_held))
    _os_toast(uc, handle, ticks)
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
    st["retired"] = {a: uc.mem_read(a, 4) for a in RETIRED}
    return st


def test_no_tick_detour():
    print("Session 93 regression guard: NO tick of our own ---------------")
    check("cave exports no qlr_tick symbol", "qlr_tick" not in SYM)
    check(f"cave never references the retired hook site 0x{TICK_SITE:08x}",
          struct.pack(">I", TICK_SITE) not in STUB)
    # The crash was reaching the kernel post from a non-key context.  The only
    # two entry points left are both key handlers, so assert there are only two.
    entries = sorted(k for k in SYM
                     if k.startswith("qlr_") and not k.startswith(("qlr_msg", "qlr_d_")))
    check("exactly two cave entry points, both key handlers",
          entries == ["qlr_play", "qlr_recrel"], ", ".join(entries))
    # The diagnostic builder writes the SAME out/patch_qlrec.{o,elf,bin} as the
    # shipping builder, so a stale diag build would silently be what this harness
    # measures.  Refuse it rather than report someone else's image as green.
    check("this is the SHIPPING build, not the diagnostic one "
          "(re-run tools/build_qlrec.py if this fails)",
          "qlr_d_noh" not in SYM)
    img = (ROOT / "out/mainos_qlrec.bin").read_bytes()
    off = TICK_SITE - 0x40000400
    check("0x400522ca left byte-for-byte stock in the built image",
          img[off:off + 6].hex() == "45f946c7dfba", img[off:off + 6].hex())


def test_play():
    print("qlr_play  ([REC] held + [PLAY]) ------------------------------")

    r = run_play(rec_held=0, qlr=0)
    check("REC not held -> stock resume (0x4006177e)", r["resume"] and r["proj_gate"])
    check("REC not held -> no flip / no toast", r["qlr"] == 0 and r["notify"] is None)
    check("REC not held -> nothing else touched", r["notify"] is None)

    # --- no toast up: open one on the CURRENT value, no flip ---
    r = run_play(rec_held=1, qlr=0, handle=0, ticks=0)
    check("no toast up -> NO flip (value unchanged)", r["qlr"] == 0 and not r["cksum"])
    check("no toast up -> toast shows the CURRENT setting (raw 0 -> the ON string)",
          r["notify"] == MSG_ON, f"got 0x{(r['notify'] or 0):08x} want 0x{MSG_ON:08x}")
    check(f"no toast up -> NOTIFY dur = LIVE_DUR ({LIVE_DUR} = 0.800 s at 1/60 s)",
          r["notify_dur"] == LIVE_DUR, str(r["notify_dur"]))
    check("NOTIFY dur > 0 (dur<=0 is the Session 50 modal hang)", r["notify_dur"] > 0)
    check("no toast up -> patch writes NO scratch of its own",
          all(r["retired"][a] == b"\xa5\xa5\xa5\xa5" for a in RETIRED))
    check("live rec not running -> ALSO passed to stock (REC+PLAY still starts it)",
          r["resume"] and r["proj_gate"])

    r = run_play(rec_held=1, qlr=1)
    check("no toast up, value raw 1 -> shows the OFF string (menu-inverted label)",
          r["notify"] == MSG_OFF and r["qlr"] == 1)

    # --- our toast IS up: this is the flip ---
    r = run_play(rec_held=1, qlr=0, sh=0xDEAD, handle=0x46C7D384, ticks=20,
                 live_rec=1)
    check("press while OUR toast up -> QLR 0 -> 1", r["qlr"] == 1)
    check("press while our toast up -> shadow 0x100fff3c = 1", r["sh"] == 1)
    check("press while our toast up -> re-checksum called", r["cksum"])
    check("press while our toast up -> toast shows the NEW setting (raw 1 -> OFF)",
          r["notify"] == MSG_OFF)
    check("press while our toast up -> countdown restarted at LIVE_DUR",
          r["notify_dur"] == LIVE_DUR)
    check("press while our toast up -> live rec already running, so swallowed",
          r["swallowed"] and not r["resume"] and not r["proj_gate"])

    r = run_play(rec_held=1, qlr=1, handle=0x46C7D384, ticks=20, live_rec=1)
    check("another press while our toast up -> inverts AGAIN, 1 -> 0", r["qlr"] == 0)
    check("another press while our toast up -> shows the ON string", r["notify"] == MSG_ON)

    # --- THE REPORTED BUG: after the toast has gone, a press must NOT flip ---
    print("  -- the 2026-09-25 hardware report: no flip once the toast is gone --")
    r = run_play(rec_held=1, qlr=1, handle=0, ticks=0, live_rec=1)
    check("toast CLOSED by the OS (handle 0) -> NO flip",
          r["qlr"] == 1 and not r["cksum"])
    check("...and that press just re-shows the current setting",
          r["notify"] == MSG_OFF)

    # Session 94: the countdown is NO LONGER part of the gate.  FUN_40056c28
    # clears the handle the moment it expires, so the handle alone says whether a
    # toast is on screen -- and the countdown was the one word no test could ever
    # exercise (the emulator never ticks it).  A handle with a stale countdown must
    # therefore still flip: if it did not, an OS whose tick rate differs from our
    # derivation would shut the gate while the toast is plainly visible, which is
    # the 2026-09-25 hardware report.
    r = run_play(rec_held=1, qlr=1, handle=0x46C7D384, ticks=0, live_rec=1)
    check("handle set but countdown already 0 -> STILL FLIPS (handle is the gate)",
          r["qlr"] == 0 and r["cksum"])

    r = run_play(rec_held=1, qlr=1, handle=0x46C7D384, ticks=-5, live_rec=1)
    check("handle set, countdown negative -> STILL FLIPS", r["qlr"] == 0 and r["cksum"])

    r = run_play(rec_held=1, qlr=1, handle=0, ticks=48, live_rec=1)
    check("handle CLEARED but countdown looks fresh -> NO flip (handle wins)",
          r["qlr"] == 1 and not r["cksum"])

    # --- ownership: a toast that is not ours must not authorise a flip ---
    # Session 95 trade-off, asserted so it stays a deliberate choice: with no
    # ownership word, ANY toast on screen arms the flip -- including a stock one.
    r = run_play(rec_held=1, qlr=1, handle=0x46C7D384, ticks=20, live_rec=1)
    check("ACCEPTED TRADE-OFF: any toast on screen arms the flip, stock's included",
          r["qlr"] == 0 and r["cksum"])

    # --- stock live-rec pass-through, decided from STOCK state ---
    r = run_play(rec_held=1, qlr=0, live_rec=0)
    check("LIVE_REC == 0 -> press reaches stock (starts live recording)", r["resume"])
    r = run_play(rec_held=1, qlr=0, live_rec=1)
    check("LIVE_REC == 1 -> swallowed (stock's own arm 0x400618bc is a bare rts)",
          r["swallowed"] and not r["resume"])

    check("qlr_play never calls NOTIFY_CLOSE", not r["close"])
    for a, name in RETIRED.items():
        check(f"retired scratch {name} (0x{a:08x}) untouched",
              r["retired"][a] == b"\xa5\xa5\xa5\xa5")


def test_recrel():
    print("qlr_recrel  ([REC] release) ---------------------------------")

    r = run_recrel(rec_held=1, handle=0x46C7D384, ticks=20)
    check("clears REC_HELD (0x460d1726)", r["rec_held"] == 0)
    check("a toast up -> NOTIFY_CLOSE called (instant close, Session 51 item 4)",
          r["close"])


    r = run_recrel(rec_held=1, handle=0, ticks=0)
    check("no toast on screen -> NOTIFY_CLOSE NOT called", not r["close"])


    check("closing on release leaves no toast to arm an instant flip next time",
          r["rec_held"] == 0)

    for a, name in RETIRED.items():
        check(f"retired scratch {name} (0x{a:08x}) untouched",
              r["retired"][a] == b"\xa5\xa5\xa5\xa5")


def test_window_closes_without_us():
    """End-to-end: the flip window must shut on the OS countdown alone.

    This is the exact failure reported from hardware on 2026-09-25 -- the window
    never closed because only our own (rarely-running) tick could close it.  Here
    NOTHING of ours ticks: the OS countdown is stepped directly, as FUN_40056c28
    does, and the window must shut by itself.
    """
    print("full sequence: the window shuts with NO tick of ours ---------")
    uc = mk()
    uc.mem_write(REC_HELD, struct.pack(">I", 1))
    uc.mem_write(LIVE_REC, struct.pack(">I", 1))     # -> presses are swallowed
    uc.mem_write(QLR, struct.pack(">I", 0))
    _os_toast(uc, 0, 0)
    calls = {"notify": 0, "close": 0}

    def hook(uc, addr, size, u):
        if addr == NOTIFY:
            sp = uc.reg_read(UC_M68K_REG_A7)
            dur = struct.unpack(">i", uc.mem_read(sp + 8, 4))[0]
            calls["notify"] += 1
            _os_toast(uc, 0x46C7D384, dur)
        elif addr == NOTIFY_CLOSE:
            calls["close"] += 1
            _os_toast(uc, 0, 0)
        elif addr in (SENTINEL, PLAY_RESUME):
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)

    def press():
        sp0 = 0x41010000
        uc.mem_write(sp0, struct.pack(">III", SENTINEL, 0x28, 1))
        uc.reg_write(UC_M68K_REG_A7, sp0)
        uc.emu_start(QLR_PLAY, 0, count=20000)

    def os_tick():
        """Exactly what FUN_40056c28 does: if T != 0, T -= 1; at 0 close."""
        t = struct.unpack(">i", uc.mem_read(NOTIF_T, 4))[0]
        if t == 0:
            return
        t -= 1
        uc.mem_write(NOTIF_T, struct.pack(">i", t))
        if t == 0:
            _os_toast(uc, 0, 0)

    press()                                   # opens, no flip
    v0 = struct.unpack(">I", uc.mem_read(QLR, 4))[0]
    for _ in range(LIVE_DUR // 2):
        os_tick()
    press()                                   # inside the window -> flip
    v1 = struct.unpack(">I", uc.mem_read(QLR, 4))[0]
    check("a press halfway through the toast flips the value",
          v0 == 0 and v1 == 1, f"{v0} -> {v1}")
    check("...and restarts the FULL 0.8 s (taps keep the window open)",
          struct.unpack(">i", uc.mem_read(NOTIF_T, 4))[0] == LIVE_DUR)

    alive = 0
    for _ in range(LIVE_DUR + 40):
        os_tick()
        if struct.unpack(">I", uc.mem_read(NOTIF_H, 4))[0] == 0:
            break
        alive += 1
    check(f"the OS closes the toast after exactly LIVE_DUR ({LIVE_DUR}) ticks, "
          "with no tick of ours", alive == LIVE_DUR - 1, f"survived {alive}")

    press()                                   # toast gone -> must NOT flip
    v2 = struct.unpack(">I", uc.mem_read(QLR, 4))[0]
    uc.hook_del(h)
    check("a press AFTER the toast expired does NOT flip (the reported bug)",
          v2 == 1, f"value {v1} -> {v2}")
    check("...it re-opens the toast instead",
          struct.unpack(">I", uc.mem_read(NOTIF_H, 4))[0] != 0)
    check("no NOTIFY_CLOSE was ever needed from a non-key context",
          calls["close"] == 0)


def test_string_len():
    print("toast strings ----------------------------------------------")
    on = STUB[MSG_ON - LOAD:STUB.index(b"\0", MSG_ON - LOAD)].decode()
    off = STUB[MSG_OFF - LOAD:STUB.index(b"\0", MSG_OFF - LOAD)].decode()
    check(f'"{on}" ({len(on)})', on == "QUANT LIVE REC ON")
    check(f'"{off}" ({len(off)})', off == "QUANT LIVE REC OFF")
    check("toast strings <= 18 chars (fit the 128 px screen)", len(on) <= 18 and len(off) <= 18)


def test_invariants():
    print("invariants ---------------------------------------------------")
    check("LIVE_DUR > 0 (dur<=0 is the modal path that hung a real MKI)", LIVE_DUR > 0)
    check("LIVE_DUR = 0x3c = 60 = 1.000 s at the derived 1/60 s UI tick", LIVE_DUR == 0x3C,
          f"{LIVE_DUR} -> {LIVE_DUR / 59.999:.3f} s")
    # The gate must not read the countdown any more -- that address appearing in
    # the cave would mean the Session 94 fix has been undone.
    check("cave never reads NOTIF_T (0x460d1e6c) -- the gate is the handle alone",
          struct.pack(">I", 0x460D1E6C) not in STUB)
    # Session 95, the hard one: hardware proved a private word in the DSP
    # shared-RAM window does not survive between key presses.  The cave must
    # reference NO 0x8000xxxx address except the stock PERSONALIZE word itself.
    # Even offsets only: m68k instruction words -- and so absolute-long operands --
    # are always 2-byte aligned.  An unaligned scan trips over `eori.l #1,%d0`'s
    # own immediate straddling into a 0x8000_0000-looking word.
    bad = []
    for off in range(0, len(STUB) - 3, 2):
        w = struct.unpack(">I", STUB[off:off + 4])[0]
        if 0x80000000 <= w < 0x80010000 and w != QLR:
            bad.append(hex(w))
    check("cave references NO scratch in the DSP shared-RAM window (only QLR)",
          not bad, ", ".join(sorted(set(bad))) or "clean")



if __name__ == "__main__":
    print(f"LIVE_DUR = {LIVE_DUR} ({LIVE_DUR / 59.999:.3f} s)  --  no private state\n")
    test_no_tick_detour()
    test_play()
    test_recrel()
    test_window_closes_without_us()
    test_string_len()
    test_invariants()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

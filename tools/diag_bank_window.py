#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_bank_window -- the [BANK] window/keymap-layer lifecycle, measured.

WHY THIS EXISTS
---------------
Session 80 continued (3): the user asked for the stock SELECT BANK window to be
deferred from [BANK] PRESS to [BANK] RELEASE (mirroring what stock [PTN] already
does), so a RELOAD2 gesture ([BANK]+[YES]) never flashes it underneath the
picker.

A static read said the window and the keymap overlay layer are entangled:

    0x4007af30 (press tail, private -- zero xrefs, fallen into by bra.s):
        clr.l 0x460e73c6 / 0x460e73b8 / 0x460e73bc
        pea  0x4007b408            <- onClose callback
        clr.l -(sp) ; pea 0xf0 ; pea 0x400b7302 ("SELECT BANK")
        jsr  FUN_40059f8c          <- SHOW the window
        pea  0x400cff14 ; jsr FUN_40031494     <- PUSH the keymap layer
        pea  0x400cff28 ; jsr 0x4007e760
        clr.l -(sp)     ; jsr 0x4007e998
        lea  28(sp),sp ; rts

    0x4007b408 (onClose, private -- only pc-relative `pea`s reach it):
        clr.l 0x460e73bc
        pea  0x400cff14 ; jsr 0x4003146c       <- POP the keymap layer
        pea  0x400cff28 ; jsr 0x4007e81c
        clr.l -(sp)     ; jsr 0x4007e998
        lea  12(sp),sp ; rts

NOTES.md "Session 80 continued (2)" claims [BANK] release pops the layer at
0x4007b40e. That is WRONG: 0x4007b408 is the window's callback, not part of the
release handler (which ends at 0x4007b406). --stock below measures the truth.

Rather than infer the lifecycle -- inferring is exactly what produced the
RUNNING-gate regression one session earlier -- both halves are measured through
the REAL handlers under Unicorn.

WHAT IT SHOWS
-------------
  --stock    Q1 does press push the layer AND show the window?
             Q2 does RELEASE pop the layer, or does the window own it?
             Q3 does calling teardown directly pop it cleanly?
  --patched  the three release routes of rl_bank_rel, plus a stack-balance
             check on rl_bank_press (it reserves 16 B rather than pushing the
             4 window args, so the press tail's own `lea 28(sp),sp` must still
             land exactly).

Hardware I/O the cave would touch (0x4007e760 / 0x4007e81c / 0x4007e998) is
stubbed to `rts` so the routines run to completion and A7 can be compared;
0x40031200 / 0x40056a70 (the release handler's two stock exits) are stubbed for
the same reason. Those stubs mean this measures the LIFECYCLE, not what those
routines themselves do.

Usage:   python3 tools/diag_bank_window.py [--stock] [--patched]   (default: both)
"""
import pathlib
import struct
import sys

from unicorn import (UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc,
                     UcError)
from unicorn.m68k_const import UC_M68K_REG_A7

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "out/raw/section_3_MAIN_OS.bin"
PATCHED = ROOT / "out/mainos_reload2.bin"
BASE = 0x40000400

BANK_PRESS = 0x4007AF80
BANK_REL = 0x4007B3E0
BANK_TRIG = 0x4007B2FC
BANK_TEARDOWN = 0x4007B408
SHOW_WIN = 0x40059F8C
PUSH_LAYER = 0x40031494
POP_LAYER = 0x4003146C

BANK_LAYER = 0x400CFF14
BASE_LAYER_SEL = 0x400C090A
LAYER_HEAD = 0x460D165C
DISPATCH_BASE = 0x46C7D8DE
YES_SLOT = DISPATCH_BASE + 0x31 * 24
BANK_CODE = 0x2F
BANK_TEXT = 0x400B7302

BANK_COMMIT = 0x460E73C2
BANK_SEL = 0x460E73C6
BANK_WIN = 0x460E73BC

G_MENU = 0x80006A52
G_KIND = 0x80006A50
G_SEL = 0x80006A53

STOCK_YES_HANDLER = 0x4005E4C8
STUBS = (0x4007E760, 0x4007E81C, 0x4007E998, 0x40031200, 0x40056A70, 0x400346EC)

TRACE = {SHOW_WIN: "SHOW_WINDOW", PUSH_LAYER: "PUSH_LAYER",
         POP_LAYER: "POP_LAYER", BANK_TEARDOWN: "TEARDOWN"}

FAILED = []


def check(name, cond, detail=""):
    print(f"   [{'x' if cond else ' '}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def mk(path):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x800000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(BASE, path.read_bytes())
    for a in (LAYER_HEAD, BANK_COMMIT, BANK_SEL, BANK_WIN):
        uc.mem_write(a, b"\x00\x00\x00\x00")
    for a in (G_MENU, G_KIND, G_SEL):
        uc.mem_write(a, b"\x00")
    for a in STUBS:                       # hardware / shared exits -> rts
        uc.mem_write(a, b"\x4e\x75")
    return uc


def call(uc, addr, args):
    """jsr addr(args...); returns (log, sp_balanced, returned_cleanly)."""
    ret, sp = 0x41010000, 0x41012000
    uc.mem_write(ret, b"\x4e\x71")
    for i, a in enumerate(args):
        uc.mem_write(sp + 4 + i * 4, struct.pack(">I", a))
    uc.mem_write(sp, struct.pack(">I", ret))
    uc.reg_write(UC_M68K_REG_A7, sp)
    log, done = [], {"ok": False}

    def hook(uc_, pc, size, u):
        if pc == ret:
            done["ok"] = True
            done["sp"] = uc_.reg_read(UC_M68K_REG_A7)
            uc_.emu_stop()
        elif pc in TRACE:
            name = TRACE[pc]
            if name == "SHOW_WINDOW":
                s = uc_.reg_read(UC_M68K_REG_A7)
                txt, dur, flag, cb = struct.unpack(">IIII", uc_.mem_read(s + 4, 16))
                name += f"(text=0x{txt:08x} dur=0x{dur:x} onClose=0x{cb:08x})"
            log.append(name)

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(addr, 0, count=2_000_000)
    except UcError as e:
        log.append(f"!!UcError {e}")
    uc.hook_del(h)
    # sp is popped past the return address by the final rts -> sp+4
    return log, done.get("sp") == sp + 4, done["ok"]


def layer_live(uc):
    n = struct.unpack(">I", uc.mem_read(LAYER_HEAD, 4))[0]
    for _ in range(16):
        if n == 0 or n < 0x40000000:
            return False
        if n == BANK_LAYER:
            return True
        try:
            n = struct.unpack(">I", uc.mem_read(n, 4))[0]
        except UcError:
            return False
    return False


def yes_slot(uc):
    return struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]


def shown(log):
    return [e for e in log if e.startswith("SHOW_WINDOW")]


def run_stock():
    print("\n##### STOCK -- what the [BANK] window/layer lifecycle actually is #####")
    uc = mk(STOCK)
    call(uc, PUSH_LAYER, [BASE_LAYER_SEL])
    check("base layer: YES slot = stock handler", yes_slot(uc) == STOCK_YES_HANDLER,
          hex(yes_slot(uc)))

    log, bal, ok = call(uc, BANK_PRESS, [BANK_CODE, 1])
    print(f"      press  -> {log}")
    check("press SHOWS the window", bool(shown(log)))
    check("press pushes the overlay layer", "PUSH_LAYER" in log and layer_live(uc))
    check("press leaves YES slot dead (0) -- the slot we poke", yes_slot(uc) == 0,
          hex(yes_slot(uc)))
    check("press returns with the stack balanced", bal and ok)

    log, _, _ = call(uc, BANK_REL, [BANK_CODE, 0])
    print(f"      release-> {log}")
    check("RELEASE pops NOTHING (the window owns the layer)",
          "POP_LAYER" not in log and layer_live(uc))

    log, _, _ = call(uc, BANK_TEARDOWN, [])
    print(f"      onClose-> {log}")
    check("teardown called directly pops the layer", "POP_LAYER" in log and not layer_live(uc))
    check("teardown restores the YES slot to stock", yes_slot(uc) == STOCK_YES_HANDLER,
          hex(yes_slot(uc)))


def patched_press(uc):
    call(uc, PUSH_LAYER, [BASE_LAYER_SEL])
    return call(uc, BANK_PRESS, [BANK_CODE, 1])


def run_patched(rl_bank_yes):
    print("\n##### PATCHED -- window deferred to release #####")

    print("\n-- press: window suppressed, layer still pushed --")
    uc = mk(PATCHED)
    log, bal, ok = patched_press(uc)
    print(f"      press  -> {log}")
    check("press shows NO window", not shown(log))
    check("press STILL pushes the overlay layer", "PUSH_LAYER" in log and layer_live(uc))
    check("press returns with the stack balanced (the lea -16(sp) reservation)",
          bal and ok, "A7 restored" if bal else "A7 MISMATCH")
    check("YES slot now resolves to rl_bank_yes", yes_slot(uc) == rl_bank_yes,
          hex(yes_slot(uc)))

    print("\n-- release, plain tap: the deferred window appears HERE --")
    log, bal, ok = call(uc, BANK_REL, [BANK_CODE, 0])
    print(f"      release-> {log}")
    w = shown(log)
    check("release shows the SELECT BANK window", bool(w), w[0] if w else "")
    check("...with stock's own text + onClose",
          bool(w) and f"0x{BANK_TEXT:08x}" in w[0] and f"0x{BANK_TEARDOWN:08x}" in w[0])
    check("layer still live (the window owns it, as on stock)", layer_live(uc))
    check("release returns cleanly", ok)

    print("\n-- release during a RELOAD gesture: swallowed entirely --")
    uc = mk(PATCHED)
    patched_press(uc)
    uc.mem_write(G_MENU, b"\x01")                 # our picker is open
    uc.mem_write(BANK_COMMIT, b"\x00\x00\x00\x00")  # rl_bank_yes clears it
    log, bal, ok = call(uc, BANK_REL, [BANK_CODE, 0])
    print(f"      release-> {log}")
    check("NO window is shown", not shown(log))
    check("teardown runs, layer popped now", "POP_LAYER" in log and not layer_live(uc))
    check("YES slot restored to stock after teardown", yes_slot(uc) == STOCK_YES_HANDLER,
          hex(yes_slot(uc)))
    check("release returns cleanly", ok)

    print("\n-- release after a trig picked a bank: trig's own toast owns teardown --")
    uc = mk(PATCHED)
    patched_press(uc)
    uc.mem_write(BANK_SEL, b"\x00\x00\x00\x01")   # trig handler sets this
    log, bal, ok = call(uc, BANK_REL, [BANK_CODE, 0])
    print(f"      release-> {log}")
    check("NO second window shown", not shown(log))
    check("NO teardown here (the trig toast carries it)",
          "POP_LAYER" not in log and layer_live(uc))
    check("release returns cleanly", ok)


def main():
    args = sys.argv[1:]
    do_stock = "--stock" in args or not args
    do_patched = "--patched" in args or not args
    if do_stock:
        if not STOCK.exists():
            sys.exit(f"missing {STOCK}")
        run_stock()
    if do_patched:
        if not PATCHED.exists():
            sys.exit(f"missing {PATCHED} -- run python3 tools/build_reload2.py")
        import subprocess
        nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_reload2.elf")],
                            capture_output=True, text=True).stdout
        syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines())
                if len(p) == 3}
        run_patched(syms["rl_bank_yes"])

    print("\n" + ("ALL GOOD" if not FAILED else f"FAILED: {FAILED}"))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()

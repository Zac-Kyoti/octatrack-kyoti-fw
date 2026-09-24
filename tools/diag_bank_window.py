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


def run_patched(rl_bank_yes, syms):
    """Session 80 continued (7): the window DEFERRAL IS REVERTED. These checks
    now assert the press path is behaviourally STOCK again -- the window shows on
    press, the layer is pushed, and [BANK] release is untouched -- while the one
    thing we still do there (snapshotting the YES dispatch slot for rl_bank_yes's
    delegate guard) happens correctly."""
    print("\n##### PATCHED -- deferral reverted; press path must be stock again #####")

    print("\n-- press: stock window STILL shown, layer pushed, slot snapshotted --")
    uc = mk(PATCHED)
    call(uc, PUSH_LAYER, [BASE_LAYER_SEL])
    pre = yes_slot(uc)
    log, bal, ok = call(uc, BANK_PRESS, [BANK_CODE, 1])
    print(f"      press  -> {log}")
    w = shown(log)
    check("press SHOWS the SELECT BANK window again (deferral reverted)", bool(w),
          w[0] if w else "")
    check("...with stock's own text + onClose",
          bool(w) and f"0x{BANK_TEXT:08x}" in w[0] and f"0x{BANK_TEARDOWN:08x}" in w[0])
    check("press pushes the overlay layer", "PUSH_LAYER" in log and layer_live(uc))
    check("press returns with the stack balanced", bal and ok,
          "A7 restored" if bal else "A7 MISMATCH")
    check("YES slot now resolves to rl_bank_yes", yes_slot(uc) == rl_bank_yes,
          hex(yes_slot(uc)))
    saved = struct.unpack(">I", uc.mem_read(syms["rl_yes_save"], 4))[0]
    check("rl_yes_save holds the PRE-push slot (the delegate guard needs it)",
          saved == pre, f"saved=0x{saved:08x} pre=0x{pre:08x}")

    print("\n-- release: byte-for-byte stock, so stock's own teardown owns it --")
    log, bal, ok = call(uc, BANK_REL, [BANK_CODE, 0])
    print(f"      release-> {log}")
    check("release shows no window of its own", not shown(log))
    check("release pops nothing (the window owns the layer, as on stock)",
          "POP_LAYER" not in log and layer_live(uc))
    check("release returns cleanly", ok)

    print("\n-- the window's onClose still tears down cleanly --")
    log, _, _ = call(uc, BANK_TEARDOWN, [])
    print(f"      onClose-> {log}")
    check("teardown pops the layer", "POP_LAYER" in log and not layer_live(uc))


def layer_depth(uc):
    """How many layers are linked into the layer list, and how many of them are
    the [BANK] overlay. A stranded (or double-popped) overlay is the thing that
    would break stock [BANK] entirely, by leaving the dispatch table overridden."""
    n = struct.unpack(">I", uc.mem_read(LAYER_HEAD, 4))[0]
    depth, banks = 0, 0
    for _ in range(64):
        if n == 0 or n < 0x40000000:
            break
        depth += 1
        if n == BANK_LAYER:
            banks += 1
        try:
            n = struct.unpack(">I", uc.mem_read(n, 4))[0]
        except UcError:
            break
    return depth, banks


def bank_slot(uc):
    return struct.unpack(">I", uc.mem_read(DISPATCH_BASE + BANK_CODE * 24, 4))[0]


def run_stress(label, path, rl_bank_yes=None):
    """Repeated real gestures. The user reports that after a few reload attempts
    stock [BANK] single-press stops working ENTIRELY -- which is what a corrupted
    or overridden dispatch table looks like. Single gestures all passed; this
    drives SEQUENCES, and compares against stock rather than judging in a vacuum."""
    print(f"\n##### STRESS: {label} #####")
    uc = mk(path)
    call(uc, PUSH_LAYER, [BASE_LAYER_SEL])
    d0, b0 = layer_depth(uc)
    print(f"   baseline: depth={d0} bank_layers={b0} BANK slot=0x{bank_slot(uc):08x}")

    def gesture(name, open_picker=False, trig=False):
        call(uc, BANK_PRESS, [BANK_CODE, 1])
        if trig:
            uc.mem_write(BANK_SEL, b"\x00\x00\x00\x01")
        if open_picker:
            uc.mem_write(G_MENU, b"\x01")
            uc.mem_write(BANK_COMMIT, b"\x00\x00\x00\x00")
        call(uc, BANK_REL, [BANK_CODE, 0])
        d, b = layer_depth(uc)
        print(f"   {name:<34} depth={d} bank_layers={b} "
              f"BANK=0x{bank_slot(uc):08x} YES=0x{yes_slot(uc):08x}")
        return d, b

    # Five plain taps in a row. On stock each tap shows the window whose onClose
    # pops the layer; nothing here lets that timeout fire, which is exactly the
    # real-world case of tapping faster than the toast expires.
    for i in range(5):
        gesture(f"plain tap #{i+1}")
    # Then reload-style gestures (picker open at release -> our swallow path).
    for i in range(3):
        gesture(f"reload gesture #{i+1}", open_picker=True)
        uc.mem_write(G_MENU, b"\x00")          # as rl_yes_exec would on execute
    d, b = gesture("tap after reload gestures")
    check(f"[{label}] BANK dispatch slot still the stock handler",
          bank_slot(uc) == BANK_PRESS, hex(bank_slot(uc)))
    check(f"[{label}] [BANK] overlay not stacked up (<=1 instance)", b <= 1, f"{b} copies")
    return d, b


def main():
    args = sys.argv[1:]
    stress = "--stress" in args
    do_stock = ("--stock" in args or not args) and not stress
    do_patched = ("--patched" in args or not args) and not stress
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
        run_patched(syms["rl_bank_yes"], syms)

    if stress:
        run_stress("STOCK", STOCK)
        import subprocess
        nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_reload2.elf")],
                            capture_output=True, text=True).stdout
        syms = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines())
                if len(q) == 3}
        run_stress("PATCHED", PATCHED, syms["rl_bank_yes"])

    print("\n" + ("ALL GOOD" if not FAILED else f"FAILED: {FAILED}"))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()

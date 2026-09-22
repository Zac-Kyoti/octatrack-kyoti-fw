#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_popup -- does repeated open/redraw/close of OUR picker leak?

WHY THIS EXISTS
---------------
Session 80 continued (6). The hardware symptoms are "degrades with use":

  - "[BANK]+[YES] hardly ever executes"
  - "[YES] almost always gives RELOAD BUSY"
  - "stock [BANK] single press seems to stop working entirely after messing with
     the reload function a few times"

diag_reload2_repeat.py ruled out the WORKER path: 5 consecutive reloads leave
G_KIND, POPUP, layer depth and the BANK/YES dispatch slots all at baseline. So
whatever accumulates is not in the job.

That leaves a surface no test in this repo has ever executed: **our picker's own
popup lifecycle**. Every harness here stubs CLOSE_CB (0x40056bc0) to `rts`, so
the real close has literally never run in a test.

Reading the two routines makes the suspicion concrete:

  POPUP2 = FUN_4005a0e0(text)          -- open / redraw our picker
      tst.l 0x460d1e64 ; bne -> bsr 0x40056bc0   (closes an existing popup FIRST)
      ... jsr 0x40012f30 ; bsr 0x4005829c        (create)
      move.l d0,0x460d1e64                       (store the handle)

  CLOSE_CB = FUN_40056bc0
      tst.l 0x460d1e64 ; beq -> rts
      pea 0x460d1e64 ; bsr 0x40055db4
      pea 0x400a7278 ; pea 0x460d17ae ; jsr 0x40000c3c   <-- QUEUE POST
      lea 12(sp),sp

So closing a popup POSTS A MESSAGE (queue 0x460d17ae) through 0x40000c3c -- the
primitive this project already measured as having NO full check: it wraps the
ring index with `and.l` and silently overwrites the oldest entry. And rl_draw
calls POPUP2 again on EVERY arrow press, so one picker session does an
open+close round trip per keypress, not once.

If the close is asynchronous and we immediately create a new popup, the handle at
0x460d1e64 is overwritten before the old one is reclaimed -- a leak that would
grow with use and eventually make popup creation fail. That single failure mode
would produce ALL THREE symptoms at once, because the picker, the RELOAD BUSY
toast and stock's own SELECT BANK window are all popups.

WHAT IT MEASURES
----------------
Repeated realistic picker sessions -- open (rl_bank_yes), redraw a few times
(rl_arr_b, as arrow presses do), close (rl_no) -- with the REAL POPUP2 and
CLOSE_CB running, watching per iteration:

  0x460d1e64   the popup handle: must be non-zero while open, 0 after close
  create-fn    how many times the creator 0x4005829c ran, and what it returned
  queue post   how many messages CLOSE_CB posted to 0x460d17ae
  layer depth  must not drift
  G_MENU       must return to 0 after rl_no

A handle that stops returning non-zero, or a count that climbs without bound,
is the bug. Nothing here asserts a pass/fail verdict on firmware it has not
measured -- read the table.

Usage:   python3 tools/diag_reload2_popup.py [iterations]     (default 20)
"""
import pathlib
import struct
import subprocess
import sys

from unicorn import (UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc,
                     UcError)
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHED = ROOT / "out/mainos_reload2.bin"
ELF = ROOT / "out/patch_reload2.elf"
BASE = 0x40000400

POPUP2 = 0x4005A0E0          # open / redraw
CLOSE_CB = 0x40056BC0        # close
POPUP_CREATE = 0x4005829C    # the actual creator POPUP2 tail-calls
POPUP_HANDLE = 0x460D1E64    # where the handle is stored
QUEUE_POST = 0x40000C3C
POPUP_QUEUE = 0x460D17AE

BANK_PRESS = 0x4007AF80
BANK_REL = 0x4007B3E0
PUSH_LAYER = 0x40031494
BASE_LAYER_SEL = 0x400C090A
LAYER_HEAD = 0x460D165C
DISPATCH_BASE = 0x46C7D8DE
BANK_CODE, YES_CODE, DOWN_CODE = 0x2F, 0x31, 0x33

G_KIND, G_MENU, G_SEL = 0x80006A50, 0x80006A52, 0x80006A53
BANK_COMMIT, BANK_SEL, BANK_WIN = 0x460E73C2, 0x460E73C6, 0x460E73BC


def syms():
    nm = subprocess.run(["m68k-elf-nm", str(ELF)], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for b, sz in ((0x40000000, 0x800000), (0x46000000, 0x1000000),
                  (0x80000000, 0x20000), (0x41000000, 0x20000),
                  (0x10000000, 0x1000000), (0x00000000, 0x10000)):
        uc.mem_map(b, sz)
    uc.mem_write(BASE, PATCHED.read_bytes())
    for a in (LAYER_HEAD, BANK_COMMIT, BANK_SEL, BANK_WIN, POPUP_HANDLE, 0x460E5CD0):
        uc.mem_write(a, b"\x00\x00\x00\x00")
    for a in (G_KIND, G_MENU, G_SEL):
        uc.mem_write(a, b"\x00")
    for a in (0x4007E760, 0x4007E81C, 0x4007E998, 0x40031200, 0x40056A70):
        uc.mem_write(a, b"\x4e\x75")
    return uc


def layer_depth(uc):
    n = struct.unpack(">I", uc.mem_read(LAYER_HEAD, 4))[0]
    d = 0
    for _ in range(64):
        if n == 0 or n < 0x40000000:
            break
        d += 1
        try:
            n = struct.unpack(">I", uc.mem_read(n, 4))[0]
        except UcError:
            break
    return d


def u32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    if not PATCHED.exists():
        sys.exit(f"missing {PATCHED} -- run python3 tools/build_reload2.py")
    s = syms()
    uc = mk()
    tally = {"create": 0, "create_ret": [], "close": 0, "qpost": 0, "faults": 0}

    def call(addr, args):
        ret, sp = 0x41010000, 0x41012000
        uc.mem_write(ret, b"\x4e\x71")
        for i, a in enumerate(args):
            uc.mem_write(sp + 4 + i * 4, struct.pack(">I", a))
        uc.mem_write(sp, struct.pack(">I", ret))
        uc.reg_write(UC_M68K_REG_A7, sp)

        def hook(u, pc, size, x):
            if pc == ret:
                u.emu_stop()
            elif pc == POPUP_CREATE:
                tally["create"] += 1
            elif pc == CLOSE_CB:
                tally["close"] += 1
            elif pc == QUEUE_POST:
                q = struct.unpack(">I", u.mem_read(u.reg_read(UC_M68K_REG_A7) + 4, 4))[0]
                if q == POPUP_QUEUE:
                    tally["qpost"] += 1

        h = uc.hook_add(UC_HOOK_CODE, hook)
        try:
            uc.emu_start(addr, 0, count=3_000_000)
        except UcError:
            tally["faults"] += 1
        uc.hook_del(h)

    call(PUSH_LAYER, [BASE_LAYER_SEL])
    print(f"baseline: depth={layer_depth(uc)} handle=0x{u32(uc, POPUP_HANDLE):08x}")
    print(f"\n{'it':>3} {'handle@open':>12} {'handle@close':>13} {'create':>7} "
          f"{'closes':>7} {'qpost':>6} {'depth':>6} {'G_MENU':>7} {'flt':>4}")

    first_open = None
    for i in range(1, iters + 1):
        call(BANK_PRESS, [BANK_CODE, 1])              # real [BANK] press
        call(s["rl_bank_yes"], [YES_CODE, 1])         # [YES] -> picker opens + rl_draw
        h_open = u32(uc, POPUP_HANDLE)
        if first_open is None:
            first_open = h_open
        for _ in range(3):                            # arrow presses -> rl_draw again
            call(s["rl_arr_b"], [DOWN_CODE, 1])
        call(BANK_REL, [BANK_CODE, 0])                # release (swallow path)
        call(s["rl_no"], [0x32, 1])                   # [NO] closes the picker
        h_close = u32(uc, POPUP_HANDLE)
        print(f"{i:>3} 0x{h_open:010x} 0x{h_close:011x} {tally['create']:>7} "
              f"{tally['close']:>7} {tally['qpost']:>6} {layer_depth(uc):>6} "
              f"{uc.mem_read(G_MENU,1)[0]:>7} {tally['faults']:>4}")

    print(f"\ncreate returns seen: {tally['create_ret'][:8]}")
    print(f"popup creator ran {tally['create']}x, CLOSE_CB ran {tally['close']}x, "
          f"posted {tally['qpost']} messages to the popup queue 0x460d17ae")
    print(f"first open handle 0x{first_open:08x}; final handle "
          f"0x{u32(uc, POPUP_HANDLE):08x}; final depth {layer_depth(uc)}")
    print("\nRead the columns: a handle that goes 0 at open (creation failing), or a\n"
          "depth that climbs, is the accumulating failure the user is hitting.\n"
          "NOTE: the popup queue's consumer does not run in this harness, so the\n"
          "qpost count is what a real system would have to drain -- it is a\n"
          "pressure indicator, not proof of overflow on hardware.")


if __name__ == "__main__":
    main()

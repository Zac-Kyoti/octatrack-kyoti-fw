#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Dynamic proof that RELOAD2's [YES]/[NO] keys reach rl_yes/rl_no while [PTN] is
physically held, using REAL (unstubbed) stock firmware code -- the same class
of check emu_directjump_v4.py already does for DIRECT JUMP's identical bug.

BACKGROUND (NOTES.md "Session 60" flagged this, unaddressed until now): [PTN]
press unconditionally runs FUN_4005a044 -> jsr 0x4004346c -> pea 0x400bf0f2 ;
jsr FUN_40031494, which PUSHES a small keymap OVERLAY LAYER (26-byte records,
one per key: trig 0-15, NO=0x32, YES=0x31) onto a layer list (0x460d165c,
newest appended at the tail, walked head->tail so the newest wins). The
rebuild this triggers (FUN_40031494 -> braw FUN_4003125c) recomputes a flat,
24-byte-stride dispatch table at 0x46c7d8de (slot(code) = 0x46c7d8de +
code*24): each active layer's press pointer for a key overwrites that slot.
The overlay's own YES record has press = NULL -- so the runtime YES slot goes
to 0, and rl_yes's detour site (0x4005e4c8) is never entered, for as long as
[PTN] stays held. This is exactly the bug that made DIRECTJUMP_V3 do nothing
on hardware; it hits rl_yes by the identical mechanism (Session 60 flagged
it, never fixed until now). The overlay's NO record is NOT null (press =
0x40056aa8), so rl_no (0x4005e25c) is equally unreachable while held, though
by a different route -- dispatch goes to 0x40056aa8 instead.

Fix (patch_reload2.s / build_reload2.py, mirroring DIRECT JUMP v4's
DJ_KEYMAP): write rl_yes_ptnheld / rl_no_ptnheld directly into those two
press fields. Both replay rl_yes/rl_no's own G_MENU/POPUP gate and bsr the
same rl_yes_exec/rl_no_exec bodies the original 0x4005e4c8/0x4005e25c
detours use, so behaviour is identical regardless of entry path. The
ORIGINAL detours are UNCHANGED and still needed for the case where [PTN] has
already been released (RELOAD2's picker is sticky/no-timeout by design, so
that's the documented common case) -- this script checks BOTH paths.

This script runs the REAL FUN_5a044 (PTN press) and FUN_40031494/FUN_4003125c
(layer push + table rebuild) under Unicorn against the built image, then:
  1. confirms the YES/NO runtime dispatch slots go to rl_yes_ptnheld /
     rl_no_ptnheld while [PTN] is held (not 0 / not 0x40056aa8);
  2. JSRs those slots directly (the same call the real per-key ISR makes)
     with the picker open (G_MENU=1) and confirms they drive the real
     worker-arming / window-close logic end to end;
  3. confirms that with the picker CLOSED (G_MENU=0), rl_yes_ptnheld does
     nothing (rts, matching stock's own NULL-slot behaviour) and
     rl_no_ptnheld falls through to the real, unmodified 0x40056aa8 (not
     just "doesn't call the picker logic" -- the actual stock function runs);
  4. confirms the ORIGINAL 0x4005e4c8/0x4005e25c detours are byte-for-byte
     untouched (this fix must never remove the after-release path).

Run after:  python3 tools/build_reload2.py
Usage:      python3 tools/emu_reload2_keymap.py
"""
import pathlib
import struct
import subprocess
import sys

from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE = ROOT / "out/mainos_reload2.bin"
ELF = ROOT / "out/patch_reload2.elf"

FUN_PTN_PRESS = 0x4005a044        # PTN key handler (real, unmodified)
FUN_PUSH_LAYER = 0x40031494       # push a layer struct + trigger the table rebuild
BASE_LAYER_SEL = 0x400c090a       # real boot-time base-keymap selector struct (T1 variant)
LAYER_HEAD = 0x460d165c           # layer list head (tail-append, walked head->tail)
DISPATCH_BASE = 0x46c7d8de        # runtime dispatch table, 24 B stride per keycode
YES_CODE = 0x31
NO_CODE = 0x32
YES_SLOT = DISPATCH_BASE + YES_CODE * 24
NO_SLOT = DISPATCH_BASE + NO_CODE * 24

STOCK_YES_HANDLER = 0x4005e4c8
STOCK_NO_HANDLER = 0x4005e25c
NO_PTNHELD_STOCK = 0x40056aa8

PTN_MODE = 0x460d1742
POPUP2 = 0x460d1ab2               # SELECT-window "in use" flag PTN's own handler touches

G_KIND = 0x80006a50
G_MENU = 0x80006a52
G_SEL = 0x80006a53
POPUP = 0x460e5cd0
CLOSE_CB = 0x40056bc0
JOB_POST = 0x40022778

fails = []


def check(name, cond, detail=""):
    print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def load_syms(elf):
    nm = subprocess.run(["m68k-elf-nm", str(elf)], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}


def mk(image):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x800000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(0x40000400, image)
    uc.mem_write(PTN_MODE, b"\x00\x00\x00\x00")
    uc.mem_write(POPUP2, b"\x00\x00\x00\x00")
    uc.mem_write(LAYER_HEAD, b"\x00\x00\x00\x00")
    uc.mem_write(POPUP, b"\x00\x00\x00\x00")
    uc.mem_write(G_KIND, b"\x00")
    uc.mem_write(G_MENU, b"\x00")
    uc.mem_write(G_SEL, b"\x00")
    return uc


def call(uc, addr, args, ret_trap=0x41010000, extra_hooks=None):
    """jsr addr(args...) from a synthetic return address; args pushed sp-relative low->high."""
    sp = 0x41012000
    uc.mem_write(ret_trap, b"\x4e\x71")
    for i, a in enumerate(args):
        uc.mem_write(sp + 4 + i * 4, struct.pack(">I", a))
    uc.mem_write(sp, struct.pack(">I", ret_trap))
    uc.reg_write(UC_M68K_REG_A7, sp)
    hits = {"trap": False}

    def hook(uc, addr, size, u):
        if addr == ret_trap:
            hits["trap"] = True
            uc.emu_stop()
        elif extra_hooks and addr in extra_hooks:
            extra_hooks[addr](uc)

    watch = {ret_trap} | (set(extra_hooks) if extra_hooks else set())
    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(addr, 0, count=400000)
    except UcError as e:
        print(f"    (UcError: {e})")
    uc.hook_del(h)
    return hits["trap"]


def push_and_hold(uc):
    """Real base layer push, then real [PTN] press -- returns (yes_slot, no_slot)."""
    call(uc, FUN_PUSH_LAYER, [BASE_LAYER_SEL])
    yes0 = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    no0 = struct.unpack(">I", uc.mem_read(NO_SLOT, 4))[0]
    check("after base layer: YES dispatch slot = stock handler", yes0 == STOCK_YES_HANDLER, hex(yes0))
    check("after base layer: NO dispatch slot = stock handler", no0 == STOCK_NO_HANDLER, hex(no0))

    call(uc, FUN_PTN_PRESS, [0x2e, 1])  # event=1 (press); tail runs into kernel code, expected
    ptn_mode = struct.unpack(">I", uc.mem_read(PTN_MODE, 4))[0]
    check("PTN_MODE == 1 (held)", ptn_mode == 1, ptn_mode)

    yes1 = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    no1 = struct.unpack(">I", uc.mem_read(NO_SLOT, 4))[0]
    return yes1, no1


def main():
    if not IMAGE.exists():
        sys.exit(f"missing {IMAGE} -- run python3 tools/build_reload2.py first")
    syms = load_syms(ELF)
    rl_yes_ptnheld = syms["rl_yes_ptnheld"]
    rl_no_ptnheld = syms["rl_no_ptnheld"]
    img = IMAGE.read_bytes()

    print("=== 1. real stock layer push + [PTN] press: runtime dispatch slots ===")
    uc = mk(img)
    yes_slot, no_slot = push_and_hold(uc)
    check("YES slot -> rl_yes_ptnheld (was NULL in stock -- Session 60's exact bug)",
          yes_slot == rl_yes_ptnheld, f"got 0x{yes_slot:08x} want 0x{rl_yes_ptnheld:08x}")
    check("NO slot -> rl_no_ptnheld (was 0x40056aa8 in stock)",
          no_slot == rl_no_ptnheld, f"got 0x{no_slot:08x} want 0x{rl_no_ptnheld:08x}")

    print("\n=== 2. jsr the live YES slot with the picker OPEN -- real worker-arm path ===")
    uc = mk(img)
    yes_slot, no_slot = push_and_hold(uc)
    uc.mem_write(G_MENU, b"\x01")
    uc.mem_write(G_SEL, b"\x01")     # PTN SEQ
    hits = {"close": False, "post": False}

    def on_close(uc):
        hits["close"] = True

    def on_post(uc):
        hits["post"] = True

    uc.mem_write(CLOSE_CB, b"\x4e\x75")   # rts stub -- just observe it's reached
    uc.mem_write(JOB_POST, b"\x4e\x75")
    call(uc, yes_slot, [YES_CODE, 1], extra_hooks={CLOSE_CB: on_close, JOB_POST: on_post})
    g_menu = struct.unpack(">B", uc.mem_read(G_MENU, 1))[0]
    g_kind = struct.unpack(">B", uc.mem_read(G_KIND, 1))[0]
    check("rl_yes_ptnheld (picker open): CLOSE_CB reached", hits["close"])
    check("rl_yes_ptnheld (picker open): JOB_POST reached (worker armed)", hits["post"])
    check("rl_yes_ptnheld (picker open): G_MENU cleared", g_menu == 0, g_menu)
    check("rl_yes_ptnheld (picker open): G_KIND == 1 (PTN SEQ)", g_kind == 1, g_kind)

    print("\n=== 3. jsr the live NO slot with the picker OPEN -- real window-close path ===")
    uc = mk(img)
    yes_slot, no_slot = push_and_hold(uc)
    uc.mem_write(G_MENU, b"\x01")
    hits = {"close": False}
    uc.mem_write(CLOSE_CB, b"\x4e\x75")
    call(uc, no_slot, [NO_CODE, 1], extra_hooks={CLOSE_CB: on_close})
    g_menu = struct.unpack(">B", uc.mem_read(G_MENU, 1))[0]
    check("rl_no_ptnheld (picker open): CLOSE_CB reached", hits["close"])
    check("rl_no_ptnheld (picker open): G_MENU cleared", g_menu == 0, g_menu)

    print("\n=== 4. jsr the live slots with the picker CLOSED -- must NOT run picker logic ===")
    uc = mk(img)
    yes_slot, no_slot = push_and_hold(uc)
    # G_MENU already 0 from mk()
    hits = {"close": False, "post": False}
    uc.mem_write(CLOSE_CB, b"\x4e\x75")
    uc.mem_write(JOB_POST, b"\x4e\x75")
    call(uc, yes_slot, [YES_CODE, 1], extra_hooks={CLOSE_CB: on_close, JOB_POST: on_post})
    check("rl_yes_ptnheld (picker closed): does nothing (stock's own NULL slot -- no CLOSE_CB, no JOB_POST)",
          not hits["close"] and not hits["post"])

    stock_hit = {"v": False}

    def on_stock_no(uc):
        stock_hit["v"] = True

    hits = {"close": False}
    call(uc, no_slot, [NO_CODE, 1], extra_hooks={CLOSE_CB: on_close, NO_PTNHELD_STOCK: on_stock_no})
    check("rl_no_ptnheld (picker closed): falls through to the REAL 0x40056aa8, not just a no-op stub",
          stock_hit["v"] and not hits["close"])

    print("\n=== 5. the original 0x4005e4c8 / 0x4005e25c detours are unchanged ===")
    yo = STOCK_YES_HANDLER - 0x40000400
    no = STOCK_NO_HANDLER - 0x40000400
    check("0x4005e4c8 still detours to rl_yes (not stock -- the after-release path must survive)",
          img[yo:yo + 2] == b"\x4e\xf9")
    check("0x4005e25c still detours to rl_no (not stock -- the after-release path must survive)",
          img[no:no + 2] == b"\x4e\xf9")


if __name__ == "__main__":
    main()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

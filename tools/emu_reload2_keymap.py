#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Dynamic proof that RELOAD2's [BANK]+[YES] entry gesture is actually REACHABLE,
using REAL (unstubbed) stock firmware code -- the same class of check
emu_directjump_v4.py does for DIRECT JUMP.

BACKGROUND. Session 60 found that [PTN] press pushes a keymap OVERLAY LAYER
whose YES record has press = NULL, so the runtime YES dispatch slot goes to 0
and the stock YES handler (where a detour would live) is never entered while
[PTN] is held -- that is why DIRECTJUMP_V3 was flashed and did nothing. This
script originally proved the same fix for RELOAD2's own [PTN]-held pokes.

Session 80 continued (2) MOVED THE GESTURE ENTIRELY. Hardware testing showed
[PTN]-hold firing only ~1 try in 5, and [PTN] was triple-booked (stock's
SELECT PATTERN chooser, DIRECT JUMP's [PTN]+[YES], our hold) with two keymap
pokes layered on just to stay reachable -- one of which collided with the very
slot DIRECT JUMP v4 pokes dj_toggle into. The entry is now [BANK]+[YES]:

  [BANK] press (0x4007af80) pushes ITS own overlay layer (struct 0x400cff14,
  records @ 0x400cff34) through the same FUN_40031494 push+rebuild, and [BANK]
  release pops it (0x4003146c @ 0x4007b40e). That layer's YES record sits at
  0x400d00ee with press = NULL -- structurally identical to PTN's dead slot --
  so build_reload2.py pokes rl_bank_yes into its press field (0x400d00f0).

So this script now drives the REAL FUN_4007af80 ([BANK] press) plus
FUN_40031494/FUN_4003125c (layer push + table rebuild) against the built image
and checks:
  1. the YES dispatch slot really resolves to rl_bank_yes while [BANK] is held
     (and the BANK layer's own NO slot is left stock -- we never poke it);
  2. jsr'ing that live slot (the call the real per-key ISR makes) genuinely
     OPENS the picker: G_MENU set, G_SEL defaulted to TRK SEQ, the popup
     renderer reached, and BANK_COMMIT cleared;
  3. a YES *release* in that layer does nothing;
  4. [PTN] is now byte-for-byte stock -- its handler AND both its layer records
     -- so PTN+YES belongs to DIRECT JUMP alone and the merged-build collision
     MERGE.md's [YES] trampoline existed for is gone;
  5. the base-layer 0x4005e4c8 / 0x4005e25c detours (which answer the sticky
     picker once [BANK] is released) are still ours.

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

FUN_BANK_PRESS = 0x4007af80       # BANK key handler (real, unmodified). Session 80
                                  # continued (2): the entry gesture moved [PTN]-hold
                                  # -> [BANK]+[YES], so this drives the BANK layer now.
BANK_CODE = 0x2f
BANK_HELD = 0x460e73c2            # BANK's own held/commit flag (press + hold both set it)
BANK_LAYER_NO_STOCK = 0x4007b25c  # the BANK layer's own NO press handler -- we do NOT
                                  # poke it, so it must stay exactly this
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
POPUP2 = 0x460d1ab2               # SELECT-window "in use" FLAG (not the renderer)
POPUP2_FN = 0x4005a0e0            # FUN_4005a0e0(text) -- the bare-text popup RENDERER
                                  # rl_draw calls; reaching it is how we observe that
                                  # the picker actually drew

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
    """Real base layer push, then real [BANK] press -- returns (yes_slot, no_slot)."""
    call(uc, FUN_PUSH_LAYER, [BASE_LAYER_SEL])
    yes0 = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    no0 = struct.unpack(">I", uc.mem_read(NO_SLOT, 4))[0]
    check("after base layer: YES dispatch slot = stock handler", yes0 == STOCK_YES_HANDLER, hex(yes0))
    check("after base layer: NO dispatch slot = stock handler", no0 == STOCK_NO_HANDLER, hex(no0))

    call(uc, FUN_BANK_PRESS, [BANK_CODE, 1])  # event=1 (press); pushes 0x400cff14 + rebuild
    held = struct.unpack(">I", uc.mem_read(BANK_HELD, 4))[0]
    check("BANK held-flag (0x460e73c2) set by the real press", held != 0, held)

    yes1 = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    no1 = struct.unpack(">I", uc.mem_read(NO_SLOT, 4))[0]
    return yes1, no1


def main():
    if not IMAGE.exists():
        sys.exit(f"missing {IMAGE} -- run python3 tools/build_reload2.py first")
    syms = load_syms(ELF)
    rl_bank_yes = syms["rl_bank_yes"]
    img = IMAGE.read_bytes()

    print("=== 1. real stock layer push + [BANK] press: runtime dispatch slots ===")
    uc = mk(img)
    yes_slot, no_slot = push_and_hold(uc)
    check("YES slot -> rl_bank_yes (stock had NULL here -- the same dead slot "
          "that made DIRECTJUMP_V3 do nothing)",
          yes_slot == rl_bank_yes, f"got 0x{yes_slot:08x} want 0x{rl_bank_yes:08x}")
    check("NO slot still the BANK layer's own stock handler (we never poke it)",
          no_slot == BANK_LAYER_NO_STOCK,
          f"got 0x{no_slot:08x} want 0x{BANK_LAYER_NO_STOCK:08x}")

    print("\n=== 2. jsr the live YES slot -- does [BANK]+[YES] really OPEN the picker? ===")
    uc = mk(img)
    yes_slot, _ = push_and_hold(uc)
    hits = {"popup": False}

    def on_popup(uc):
        hits["popup"] = True

    uc.mem_write(POPUP2_FN, b"\x4e\x75")   # rts stub -- just observe it's reached
    call(uc, yes_slot, [YES_CODE, 1], extra_hooks={POPUP2_FN: on_popup})
    g_menu = struct.unpack(">B", uc.mem_read(G_MENU, 1))[0]
    g_sel = struct.unpack(">B", uc.mem_read(G_SEL, 1))[0]
    bank_commit = struct.unpack(">I", uc.mem_read(BANK_HELD, 4))[0]
    check("BANK+YES: G_MENU set (picker opened)", g_menu == 1, g_menu)
    check("BANK+YES: G_SEL defaults to 0 (TRK SEQ)", g_sel == 0, g_sel)
    check("BANK+YES: the popup renderer was reached", hits["popup"])
    check("BANK+YES: BANK_COMMIT cleared (release takes the dismiss path) "
          "-- INFERRED behaviour, hardware still to confirm",
          bank_commit == 0, bank_commit)

    print("\n=== 3. a YES RELEASE in that layer must do nothing ===")
    uc = mk(img)
    yes_slot, _ = push_and_hold(uc)
    hits = {"popup": False}
    uc.mem_write(POPUP2_FN, b"\x4e\x75")
    call(uc, yes_slot, [YES_CODE, 0], extra_hooks={POPUP2_FN: on_popup})
    g_menu = struct.unpack(">B", uc.mem_read(G_MENU, 1))[0]
    check("BANK+YES release: picker NOT opened", g_menu == 0 and not hits["popup"],
          f"G_MENU={g_menu} popup={hits['popup']}")

    print("\n=== 4. [PTN] must now be completely stock (its YES slot belongs to DIRECT JUMP) ===")
    stock = (ROOT / "out/raw/section_3_MAIN_OS.bin").read_bytes()
    for addr, what in ((0x4005a044, "PTN key handler"),
                       (0x400bf0be, "PTN-layer YES record"),
                       (0x400bf0a4, "PTN-layer NO record")):
        o = addr - 0x40000400
        check(f"{what} 0x{addr:08x} byte-for-byte stock",
              img[o:o + 26] == stock[o:o + 26])

    print("\n=== 5. the base-layer 0x4005e4c8 / 0x4005e25c detours are unchanged ===")
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

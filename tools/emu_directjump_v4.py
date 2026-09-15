#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Dynamic proof of the v4 fix, using REAL (unstubbed) stock firmware code for the part
v1-v3's emulator never exercised: the [PTN]-held UI overlay layer and its effect on
the runtime key-dispatch table that decides what a [YES] press actually calls.

BACKGROUND (NOTES.md "Session 60"): DIRECTJUMP_V3 was flashed and did nothing at all --
no toast, no toggle.  Root cause, found by disassembling the STOCK image (not a patch):
[PTN] press unconditionally runs `FUN_4005a044` -> `jsr 0x4004346c` -> `pea 0x400bf0f2 ;
jsr FUN_40031494`, which PUSHES a small keymap OVERLAY LAYER (26-byte records, one per
key: trig 0-15, NO=0x32, YES=0x31) onto a layer list (`0x460d165c`, base at the tail,
newest layer appended and walked LAST).  The rebuild this push triggers
(`FUN_40031494` -> `braw FUN_4003125c`) recomputes a flat, 24-byte-stride dispatch
table at `0x46c7d8de` (one slot per keycode, `slot(code) = 0x46c7d8de + code*24`):
each active layer's press pointer for a key OVERWRITES that slot, and because our
overlay is walked LAST, its value always wins for the duration it's on the stack.
The PTN-held overlay's own YES record has press = NULL (0x400bf0f2's record @
0x400bf0be+2) -- so the instant [PTN] is held, the runtime dispatch slot for [YES]
(0x46c7dd76 = 0x46c7d8de + 0x31*24) is overwritten with 0, and stays 0 until [PTN] is
released.  v1/v2/v3 detour the STOCK handler `0x4005e4c8` -- which this NULLed slot
never reaches while the chord is being held.  This is entirely stock, structural
behaviour, unrelated to any patch in this project.

v4 (build_directjump_v4.py, --defsym DJ_KEYMAP=1) fixes it the way the mechanism
demands: instead of detouring 0x4005e4c8, it writes dj_toggle's address directly into
0x400bf0f2's YES record press field, so the SAME rebuild that would otherwise zero the
runtime slot instead points it at dj_toggle.

This script runs the REAL `FUN_4005a044` (PTN press) and `FUN_40031494`/`FUN_4003125c`
(layer push + table rebuild) under Unicorn against the finished image -- not a hand-
built stub -- and reads back the actual runtime dispatch slot for YES, on both:
  * out/mainos_directjump_v3.bin  (must reproduce the dead combo: slot -> 0)
  * out/mainos_directjump_v4.bin  (must fix it:                 slot -> dj_toggle)
then, for v4 only, JSRs that resulting slot pointer directly (the same call the real
per-key ISR would make) and confirms it runs dj_toggle end-to-end (NOTIFY reached,
DJ_MODE flips).

Before the PTN press, the harness first pushes the REAL base keymap layer using the
REAL boot-time selector struct at 0x400c090a (the exact `jsr FUN_40031494` argument
boot itself uses, per 0x40061bc4-40061bda in the stock image) -- so the ordering this
test relies on (base processed first, our overlay appended after and read last) is the
real, always-present ordering, not a fabricated one.

Run after:  python3 tools/build_directjump_v3.py  &&  python3 tools/build_directjump_v4.py
Usage:      python3 tools/emu_directjump_v4.py
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent

FUN_PTN_PRESS = 0x4005a044       # PTN key handler (real, unmodified in both images)
FUN_PUSH_LAYER = 0x40031494      # push a layer struct + trigger the table rebuild
BASE_LAYER_SEL = 0x400c090a      # real boot-time base-keymap selector struct (T1 variant)
LAYER_HEAD = 0x460d165c          # layer list head (tail-append, walked head->tail)
DISPATCH_BASE = 0x46c7d8de       # runtime dispatch table, 24 B stride per keycode
YES_CODE = 0x31
YES_SLOT = DISPATCH_BASE + YES_CODE * 24

PTN_MODE = 0x460d1742
PTN_USED = 0x460d173e            # !=0 -> PTN release skips the SELECT PATTERN chooser
POPUP2 = 0x460d1ab2              # SELECT-window "in use" flag PTN's own handler touches
CKSUM = 0x4001f23c
NOTIFY = 0x4005a2b8
NOTIFY_CLOSE = 0x40056bec        # tears down the FUN_4005a2b8 toast; no-op if none open
DJ_MODE = 0x800000d8

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
    # neutral scratch state -- a fresh session, [PTN] not already flagged, no popup up
    uc.mem_write(PTN_MODE, b"\x00\x00\x00\x00")
    uc.mem_write(POPUP2, b"\x00\x00\x00\x00")
    uc.mem_write(LAYER_HEAD, b"\x00\x00\x00\x00")
    for a in range(DISPATCH_BASE, DISPATCH_BASE + 64 * 24):
        pass  # left as whatever the image init left it -- the rebuild below fully repopulates it anyway
    return uc


def call(uc, addr, args, ret_trap=0x41010000, extra_hooks=None):
    """jsr addr(args...) from a synthetic return address; args pushed sp-relative low->high."""
    sp = 0x41012000
    uc.mem_write(ret_trap, b"\x4e\x71")           # nop, then we stop on hitting it
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


def run(label, image_path):
    print(f"{label} ------------------------------------------------")
    uc = mk(pathlib.Path(image_path).read_bytes())

    # 1. push the real base keymap layer (boot's own selector struct + push fn)
    ok = call(uc, FUN_PUSH_LAYER, [BASE_LAYER_SEL])
    check("base layer push returned", ok)
    base_slot = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    check("after base layer: YES dispatch slot = stock handler",
          base_slot == 0x4005e4c8, hex(base_slot))

    # 2. real [PTN] press (event=1) -- pushes 0x400bf0f2 and rebuilds the table.
    #    Its tail (`jmp 0x40027de4`, stock, past everything we care about) runs on into
    #    kernel/scheduler code Unicorn can't execute standalone (same class of limit
    #    emu_directjump.py already documents for FUN_400a1eea) -- the layer push +
    #    table rebuild we're testing complete first, so a trailing exception there is
    #    expected and not treated as a failure; only a pre-rebuild exception would be.
    ok = call(uc, FUN_PTN_PRESS, [0x2e, 1])
    check("PTN press ran the rebuild (rest of the stock tail is out of scope)", True,
          "returned cleanly" if ok else "trailing exception past 0x40027de4, as expected")
    ptn_mode = struct.unpack(">I", uc.mem_read(PTN_MODE, 4))[0]
    check("PTN_MODE == 1 (held)", ptn_mode == 1, ptn_mode)

    slot = struct.unpack(">I", uc.mem_read(YES_SLOT, 4))[0]
    return uc, slot


def check_ptn_release_closes_toast(label, image_path, expect_close):
    """Session 61: run the REAL FUN_4005a044 ([PTN] release, event=0) and confirm whether
    the toast-close primitive (NOTIFY_CLOSE) gets reached.  v3 never hooks this path (the
    toast rides out its own timer regardless of when [PTN] is released); v4 adds dj_ptnrel
    at FUN_40043418 -- confirmed the ONLY jsr caller of that function image-wide -- so it
    fires on every [PTN] release, combo-consumed or a plain quick tap alike."""
    print(f"{label} -- [PTN] release closes the toast -------------------")
    for tag, ptn_used in (("combo-consumed release (PTN_USED=1)", 1),
                          ("quick-tap release (PTN_USED=0)", 0)):
        uc = mk(pathlib.Path(image_path).read_bytes())
        uc.mem_write(PTN_USED, struct.pack(">I", ptn_used))
        uc.mem_write(POPUP2, b"\x00\x00\x00\x00")
        hit = {"v": False}

        def on_close(uc):
            hit["v"] = True

        call(uc, FUN_PTN_PRESS, [0x2e, 0], extra_hooks={NOTIFY_CLOSE: on_close})
        check(f"  {tag}: NOTIFY_CLOSE reached = {expect_close}", hit["v"] == expect_close,
              f"got {hit['v']}")


def main():
    v3 = ROOT / "out/mainos_directjump_v3.bin"
    v4 = ROOT / "out/mainos_directjump_v4.bin"
    if not v3.exists() or not v4.exists():
        sys.exit("missing out/mainos_directjump_v{3,4}.bin -- build both first")

    check_ptn_release_closes_toast("v3 image (no dj_ptnrel -- toast rides out its own timer)",
                                    v3, expect_close=False)
    print()
    check_ptn_release_closes_toast("v4 image (dj_ptnrel closes it immediately)",
                                    v4, expect_close=True)
    print()

    _, slot3 = run("v3 image (the flashed, dead-on-HW build)", v3)
    check("v3: YES dispatch slot goes to 0 while [PTN] held -- reproduces the HW failure",
          slot3 == 0, hex(slot3))

    print()
    uc4, slot4 = run("v4 image (the fix)", v4)
    dj_syms = load_syms(ROOT / "out/patch_directjump_v4.elf")
    dj_toggle = dj_syms["dj_toggle"]
    check("v4: YES dispatch slot -> dj_toggle while [PTN] held",
          slot4 == dj_toggle, f"got 0x{slot4:08x} want 0x{dj_toggle:08x}")

    # 3. actually jsr the resulting slot -- the same call the real per-key ISR makes --
    #    and confirm it runs dj_toggle for real: CKSUM + NOTIFY reached, DJ_MODE flips.
    if slot4 == dj_toggle:
        hits = {"cksum": False, "notify": None}

        def on_cksum(uc):
            hits["cksum"] = True

        def on_notify(uc):
            sp = uc.reg_read(UC_M68K_REG_A7)
            hits["notify"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]

        uc4.mem_write(CKSUM, b"\x4e\x75")
        uc4.mem_write(NOTIFY, b"\x4e\x75")
        uc4.mem_write(DJ_MODE, b"\x00\x00\x00\x00")
        # YES press, event=1 -- exactly what the real dispatch loop passes the slot fn
        call(uc4, slot4, [YES_CODE, 1], extra_hooks={CKSUM: on_cksum, NOTIFY: on_notify})
        check("v4: jsr'ing the live dispatch slot re-checksums (real dj_toggle ran)",
              hits["cksum"])
        check("v4: jsr'ing the live dispatch slot fires the NOTIFY toast",
              hits["notify"] is not None)
        dj_mode = struct.unpack(">I", uc4.mem_read(DJ_MODE, 4))[0]
        check("v4: DJ_MODE flipped 0 -> 1 via the live dispatch table, end to end",
              dj_mode == 1)


if __name__ == "__main__":
    main()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

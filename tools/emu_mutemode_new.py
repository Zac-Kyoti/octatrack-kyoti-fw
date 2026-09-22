#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Unit-level Unicorn validation of MUTEMODE_NEW (revision 3), run directly
against the actual assembled+spliced cave bytes in out/mainos_mutemode_new.bin
(build it first with tools/build_mutemode_new.py). Each hook/function is
called in isolation with synthetic register/memory state -- this is not a
full-firmware boot, it is a direct instruction-level check that the patched
bytes do what patch_mutemode_new.s says they do.

Revision 3 moved mode selection into a live PERSONALIZE menu entry backed by
RAM word 0x800000d0 -- these tests poke that word directly instead of reading
a build-time-baked byte.

    python3 tools/build_mutemode_new.py
    python3 tools/emu_mutemode_new.py out/mainos_mutemode_new.bin
"""
import struct, subprocess, sys, pathlib
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).parent.parent
BASE = 0x40000400

CONT_PERFRAME = 0x40004dcc
CONT_AMPGATE = 0x4000d374
CONT_ARM_YES, CONT_ARM_NO = 0x4000d356, 0x4000d35e
VOICE_MBOX = 0x40005178
MUTE_MODE_RAM = 0x800000d0
MUTE_MODE_SHADOW = 0x100fff60

MODE_OT, MODE_DTT, MODE_OTFX, MODE_OTFXT = 0, 1, 2, 3
MODE_NAMES = {0: "OT", 1: "DT-T", 2: "OTFX", 3: "OTFX-T"}

STACK = 0x41010000
SCRATCH = 0x41020000


def get_syms():
    r = subprocess.run(["m68k-elf-nm", "out/patch_mutemode_new.elf"],
                        cwd=ROOT, capture_output=True, text=True, check=True)
    syms = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def mk(img, mode):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_write(BASE, img[:0x400000 - 0x400])
    uc.mem_map(0x41000000, 0x40000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000)  # covers 0x100fff60 (shadow)

    def um(uc, access, addr, size, value, data):
        uc.mem_map(addr & ~0xFFF, 0x1000)
        return True
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, um)
    uc.reg_write(UC_M68K_REG_SR, 0x2000)
    uc.mem_write(MUTE_MODE_RAM, struct.pack(">I", mode))
    return uc


def test_perframe(uc, label, cave_perframe):
    uc.reg_write(UC_M68K_REG_A7, STACK)
    word = bytes([0x11, 0x22, 0xCC, 0x55])
    uc.mem_write(0x80000008, word)
    stock_word = struct.unpack(">I", word)[0]
    gated_word = stock_word & 0xffff00ff
    uc.reg_write(UC_M68K_REG_D5, 0xdeadbeef)
    uc.emu_start(cave_perframe, CONT_PERFRAME, count=200)
    d5 = uc.reg_read(UC_M68K_REG_D5)
    print(f"[{label}] hook1 perframe: d5 = 0x{d5:08x}", end="  ")
    print("(mute byte cleared)" if d5 == gated_word else "(stock word, untouched)")
    return d5, stock_word, gated_word


def test_armgate(uc, label, track, mute_mask_byte, cave_armgate):
    sp = STACK
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_D0, 0xd0)
    uc.reg_write(UC_M68K_REG_D1, 0xd0)
    uc.reg_write(UC_M68K_REG_D3, track)
    uc.mem_write(0x80000008, bytes([0x00, 0x00, mute_mask_byte, 0x00]))

    hit = {"target": None}

    def on_yes(uc, addr, size, ud):
        hit["target"] = "YES"; uc.emu_stop()

    def on_no(uc, addr, size, ud):
        hit["target"] = "NO"; uc.emu_stop()

    h1 = uc.hook_add(UC_HOOK_CODE, on_yes, begin=CONT_ARM_YES, end=CONT_ARM_YES)
    h2 = uc.hook_add(UC_HOOK_CODE, on_no, begin=CONT_ARM_NO, end=CONT_ARM_NO)
    try:
        uc.emu_start(cave_armgate, 0, count=200, timeout=0)
    except UcError:
        pass
    uc.hook_del(h1)
    uc.hook_del(h2)
    d1 = uc.reg_read(UC_M68K_REG_D1)
    print(f"[{label}] hook3 armgate track={track} mute_byte={mute_mask_byte:#04x}: reached {hit['target']} "
          f"(d1_preserved={'YES' if d1 == 0xd0 else 'NO -- BUG'})")
    return hit["target"], d1


def test_ampgate(uc, label, track, mute_mask_byte, cave_ampgate):
    scratch = SCRATCH
    uc.mem_write(scratch, struct.pack(">I", 0x12345678))
    uc.reg_write(UC_M68K_REG_A2, scratch)
    uc.reg_write(UC_M68K_REG_D0, 0x12345678)
    uc.reg_write(UC_M68K_REG_D3, track)
    uc.reg_write(UC_M68K_REG_D2, 0x99999999)
    sp = STACK
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.mem_write(sp + 0xa0, struct.pack(">I", scratch + 0x100))
    uc.mem_write(0x80000008, bytes([0x00, 0x00, mute_mask_byte, 0x00]))

    fired = {"n": 0, "args": None}

    def on_voicembox(uc, addr, size, ud):
        sp2 = uc.reg_read(UC_M68K_REG_A7)
        trk = struct.unpack(">I", uc.mem_read(sp2 + 4, 4))[0]
        flags = struct.unpack(">I", uc.mem_read(sp2 + 8, 4))[0]
        fired["n"] += 1
        fired["args"] = (trk, flags)
        retaddr = struct.unpack(">I", uc.mem_read(sp2, 4))[0]
        uc.reg_write(UC_M68K_REG_A7, sp2 + 4)
        uc.reg_write(UC_M68K_REG_PC, retaddr)

    h = uc.hook_add(UC_HOOK_CODE, on_voicembox, begin=VOICE_MBOX, end=VOICE_MBOX)
    uc.emu_start(cave_ampgate, CONT_AMPGATE, count=500)
    uc.hook_del(h)

    slot = struct.unpack(">I", uc.mem_read(scratch, 4))[0]
    d2 = uc.reg_read(UC_M68K_REG_D2)
    print(f"[{label}] hook2 ampgate track={track}: slot=0x{slot:08x} "
          f"d2_preserved={'YES' if d2==0x99999999 else 'NO -- BUG'} stop_fired={fired['n']} args={fired['args']}")
    return slot, d2, fired


def test_menu(uc, syms):
    getter, setter = syms["mute_menu_getter"], syms["mute_menu_setter"]
    labels = {0: b"OT", 1: b"DT-T", 2: b"OTFX", 3: b"OTFX-T"}

    for mode, want in labels.items():
        uc.mem_write(MUTE_MODE_RAM, struct.pack(">I", mode))
        uc.reg_write(UC_M68K_REG_A7, STACK)
        uc.emu_start(getter, 0, count=200, timeout=0)
        ptr = uc.reg_read(UC_M68K_REG_D0)
        got = uc.mem_read(ptr, len(want))
        print(f"  getter mode={mode}: -> {bytes(got)!r} (want {want!r})")
        assert bytes(got) == want, f"getter returned wrong string for mode {mode}"

    # setter: +1 wraps 0->1->2->3->0
    uc.mem_write(MUTE_MODE_RAM, struct.pack(">I", 0))
    for expect in (1, 2, 3, 0):
        sp = STACK
        uc.reg_write(UC_M68K_REG_A7, sp)
        uc.mem_write(sp, struct.pack(">I", 0x401f0000))   # fake return addr
        uc.mem_write(sp + 4, struct.pack(">I", 1))         # delta = +1
        uc.mem_write(sp + 8, struct.pack(">I", 1))         # direction (unused)
        uc.mem_write(0x401f0000, b"\x4e\x71")               # nop at return
        uc.emu_start(setter, 0x401f0000, count=200, timeout=0)
        val = struct.unpack(">I", uc.mem_read(MUTE_MODE_RAM, 4))[0]
        shadow = struct.unpack(">I", uc.mem_read(MUTE_MODE_SHADOW, 4))[0]
        print(f"  setter +1: -> {val} (want {expect}), shadow={shadow}")
        assert val == expect, f"setter wrap-forward wrong: got {val}, want {expect}"
        assert shadow == expect, "setter must write the battery shadow too"

    # setter: -1 wraps 0->3
    uc.mem_write(MUTE_MODE_RAM, struct.pack(">I", 0))
    sp = STACK
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.mem_write(sp, struct.pack(">I", 0x401f0000))
    uc.mem_write(sp + 4, struct.pack(">I", 0xffffffff))     # delta = -1
    uc.mem_write(sp + 8, struct.pack(">I", 0))
    uc.emu_start(setter, 0x401f0000, count=200, timeout=0)
    val = struct.unpack(">I", uc.mem_read(MUTE_MODE_RAM, 4))[0]
    print(f"  setter -1 from 0: -> {val} (want 3)")
    assert val == 3, f"setter wrap-backward wrong: got {val}"
    print("  menu getter/setter: ALL CHECKS PASSED")


def run_hook_tests(img, syms, mode):
    label = MODE_NAMES[mode]
    print(f"--- hooks under mode={label} ({mode}) ---")
    cave_perframe, cave_ampgate, cave_armgate = syms["cave_perframe"], syms["cave_ampgate"], syms["cave_armgate"]

    uc = mk(img, mode)
    d5, stock_word, gated_word = test_perframe(uc, label, cave_perframe)
    if mode == MODE_OTFXT:
        assert d5 == gated_word, "OTFX-T must clear only the mute byte"
    else:
        assert d5 == stock_word, "every other mode must leave the word untouched"

    uc = mk(img, mode)
    target, d1 = test_armgate(uc, label, track=3, mute_mask_byte=1 << 3, cave_armgate=cave_armgate)
    assert d1 == 0xd0, "the flags word (D1) must survive this hook untouched"
    if mode == MODE_DTT:
        assert target == "NO", "DT-T must drop the pending arm event for a muted track"
    else:
        assert target == "YES", "only DT-T suppresses the arm call"

    uc = mk(img, mode)
    slot, d2, fired = test_ampgate(uc, label, track=3, mute_mask_byte=1 << 3, cave_ampgate=cave_ampgate)
    assert slot == 0x12345678, "this hook must never alter the amp/gain value itself"
    assert d2 == 0x99999999, "D2 must survive the hook untouched"
    if mode == MODE_OTFXT:
        assert fired["n"] == 1 and fired["args"][1] == 0xf010, "OTFX-T must fire one real STOP on the mute edge"
    else:
        assert fired["n"] == 0, "only OTFX-T fires the STOP command"

    print(f"[{label}] ALL HOOK CHECKS PASSED\n")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_new.bin"
    img = (ROOT / path).read_bytes()
    syms = get_syms()
    for name in ("cave_perframe", "cave_ampgate", "cave_armgate",
                 "mute_menu_getter", "mute_menu_setter", "mute_menu_label"):
        assert name in syms, f"missing symbol {name!r}"

    for mode in (MODE_OT, MODE_DTT, MODE_OTFX, MODE_OTFXT):
        run_hook_tests(img, syms, mode)

    print("--- menu getter/setter ---")
    uc = mk(img, MODE_OT)
    test_menu(uc, syms)

    print("\nALL CHECKS PASSED (revision 3: live PERSONALIZE menu)")


if __name__ == "__main__":
    main()

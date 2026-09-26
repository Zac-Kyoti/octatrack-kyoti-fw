#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
PARKED 2026-09-25 -- NOT part of any test run.  Was tools/emu_firstflash.py.  This FAILS by
design against the shipping MUTEMODE_DT image, which no longer carries the patch: it only
passes against an image rebuilt with tools/parked/mutemode_firstflash_OT.s re-applied (see
tools/parked/README.md).  Kept because the 23 failures it reports against an unpatched image
are exactly the measurement that the shipping build restores a stale mode on a re-flash.

Verify patch_firstflash ("a FIRST flash of the MUTE MODE build comes up in OT") by running the
REAL patched boot code -- the detour at 0x4001fb1a, the cave, the stock ANDY checksum routine
0x4001f23c, and the stock restore memcpy 0x40020898 -- against seeded battery-SRAM blocks.

What this proves, and what it does not:
  * PROVES the logic: a stale-but-VALID block (an earlier build's GATE) is reset to OT and left
    with a valid checksum; an already-tagged block is left byte-identical; the choice the user
    makes afterwards persists across the next boots.
  * DOES NOT prove the hardware boot: this starts at 0x4001fb1a, the point in the real boot
    function just before the restore, with registers set up by hand.  tools/emu_firstflash.py
    is a unit test of the cave, not a power-up.  (`ot_emu` boots the whole image on a blank
    battery block; see NOTES.md for that run.)

    python3 tools/parked/mutemode_firstflash_OT_test.py [out/mainos_mutemode_dt.bin]
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

# Walk up to the repo root rather than assuming a depth: this file has lived in tools/ and in
# tools/parked/, and a hardcoded parent.parent silently became tools/ on the move (the failure
# arrives as a FileNotFoundError on out/..., not as anything that names the real cause).
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "CLAUDE.md").exists())
BASE = 0x40000400
IMG = (ROOT / (sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")).read_bytes()
STOCK = (ROOT / "out/raw/section_3_MAIN_OS.bin").read_bytes()

DETOUR, RESTORE_SETUP, AFTER_MEMCPY = 0x4001fb1a, 0x4001fb24, 0x4001fb3c
BOOT_FN, SEAL, VALIDATE = 0x4000fd34, 0x4001f23c, 0x4001f268
SRAM, BLOCK = 0x10000000, 0x100fff00
SH_GATE, SH_TAG, RT_GATE = 0x100fff6c, 0x100fff70, 0x800000dc
TAG_MAGIC = 0x4d4d4454
SENTINEL = 0xDEADBEEF
fail = 0


def check(cond, msg):
    global fail
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        fail += 1


def new_uc():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)            # mvzb etc. (ColdFire-only opcodes)
    uc.mem_map(0x40000000, 0x00200000)
    uc.mem_map(0x80000000, 0x00010000)
    uc.mem_map(SRAM, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)                  # stack
    uc.mem_write(BASE, IMG)
    return uc


def andy_sum(blk):
    """The stock checksum, over block bytes +4 .. +255 (252 B): sum(byte ^ i) + 514, i = 1..252."""
    return (sum(blk[3 + i] ^ i for i in range(1, 253)) + 514) & 0xffffffff


def make_block(gate, tag, personalize_seed=0x31):
    """A VALID ANDY block: magic, version 36, recognisable PERSONALIZE bytes, then GATE/tag."""
    b = bytearray(256)
    b[4:8] = b"ANDY"
    b[0x0e:0x10] = (36).to_bytes(2, "big")
    for i in range(0x14, 0x60):
        b[i] = (personalize_seed + 7 * i) & 0x7f
    b[0x64:0x68] = (0x11223344).to_bytes(4, "big")      # some other word in the restore window
    b[0x68:0x6c] = (0x55667788).to_bytes(4, "big")      # DJ_MODE's slot in a merged build
    b[0x6c:0x70] = gate.to_bytes(4, "big")
    b[0x70:0x74] = tag.to_bytes(4, "big")
    b[0:4] = andy_sum(b).to_bytes(4, "big")
    return bytes(b)


def rom_valid(blk):
    """Ask the ROM's own checksum-verify routine (0x4001f268) whether `blk` is valid: 1 = yes."""
    uc = new_uc()
    uc.mem_write(BLOCK, blk)
    uc.reg_write(UC_M68K_REG_A7, 0xF000 - 4)
    uc.mem_write(0xF000 - 4, struct.pack(">I", SENTINEL))
    uc.emu_start(VALIDATE, SENTINEL, count=5000)
    return uc.reg_read(UC_M68K_REG_D0) & 0xffffffff


def boot_tail(blk, d3=0xCAFE0001, a2=0x100fff04):
    """Run the real boot function's tail from the detour site through the restore memcpy."""
    uc = new_uc()
    uc.mem_write(BLOCK, blk)
    st = {"boot_fn": [], "seal": 0, "insns": 0}

    def on_code(u, addr, size, _):
        st["insns"] += 1
        if addr == BOOT_FN:                               # stub the displaced callee: rts
            sp = u.reg_read(UC_M68K_REG_A7)
            ret = struct.unpack(">I", u.mem_read(sp, 4))[0]
            arg = struct.unpack(">i", u.mem_read(sp + 4, 4))[0]
            st["boot_fn"].append(arg)
            u.reg_write(UC_M68K_REG_A7, sp + 4)
            u.reg_write(UC_M68K_REG_PC, ret)
        elif addr == SEAL:
            st["seal"] += 1
    uc.hook_add(UC_HOOK_CODE, on_code)
    sp = 0xF000
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_D3, d3)
    uc.reg_write(UC_M68K_REG_A2, a2)
    uc.emu_start(DETOUR, AFTER_MEMCPY, count=100000)
    out = bytes(uc.mem_read(BLOCK, 256))
    rt = bytes(uc.mem_read(0x80000070, 0x70))
    return out, rt, uc.reg_read(UC_M68K_REG_D3) & 0xffffffff, st


def gate_of(blk):
    return int.from_bytes(blk[0x6c:0x70], "big")


def tag_of(blk):
    return int.from_bytes(blk[0x70:0x74], "big")


print("image:", sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
print("\n=== static ===")
o = DETOUR - BASE
check(STOCK[o:o + 10].hex() == "487800014eb94000fd34", "stock bytes at 0x4001fb1a are `pea 1 / jsr 0x4000fd34`")
check(IMG[o:o + 2] == b"\x4e\xf9" and IMG[o + 6:o + 10] == b"\x4e\x71\x4e\x71", "detour is `jmp <cave>` + 2 nops")
cave = int.from_bytes(IMG[o + 2:o + 6], "big")
check(0x400d7a00 <= cave < 0x400d7b00, f"cave at 0x{cave:08x}")
check(IMG[RESTORE_SETUP - BASE:RESTORE_SETUP - BASE + 4] == b"\x48\x78\x00\x70",
      "restore length at 0x4001fb24 is still `pea 0x70` (the stock 0x64 patch is untouched)")
co = cave - BASE
check(IMG[co + 0x26:co + 0x30] == STOCK[o:o + 10], "cave replays the displaced 10 bytes byte-for-byte")
check(IMG[co + 0x30:co + 0x36] == b"\x4e\xf9" + RESTORE_SETUP.to_bytes(4, "big"),
      "cave returns with `jmp 0x4001fb24`")

print("\n=== ROM checksum oracle sanity ===")
good = make_block(2, 0)
check(rom_valid(good) == 1, "make_block() produces a block the ROM's own validator accepts")
bad = bytearray(good); bad[0x6c] ^= 1
check(rom_valid(bytes(bad)) == 0, "flipping one byte makes the ROM's validator reject it")

print("\n=== S1: a stale-but-VALID block from an earlier build (GATE=2 'DT-T', no tag) ===")
for stale in (1, 2, 3):
    blk = make_block(stale, 0)
    out, rt, d3, st = boot_tail(blk)
    check(gate_of(out) == 0, f"GATE {stale} -> shadow reset to 0 (OT)")
    check(int.from_bytes(rt[0x6c:0x70], "big") == 0, f"GATE {stale} -> RUNTIME 0x800000dc restored as 0")
    check(tag_of(out) == TAG_MAGIC, "tag set")
    check(rom_valid(out) == 1, "checksum is VALID afterwards (ROM validator)")
    check(int.from_bytes(out[0:4], "big") == andy_sum(out), "checksum equals the independent recompute")
    keep = [i for i in range(256) if not (i < 4 or 0x6c <= i < 0x74)]
    check(all(out[i] == blk[i] for i in keep), "every other block byte untouched (PERSONALIZE mirror, +0x64, +0x68 ...)")
    check(rt == out[:0x70], "runtime image = the (re-sealed) block bytes +0x00..+0x6f, i.e. the stock restore ran on the fixed block")
    check(d3 == 0xCAFE0001, "d3 (the 'defaults ran' flag) preserved across the cave")
    check(st["boot_fn"] == [1] and st["seal"] == 1, "replayed jsr 0x4000fd34 ran once with arg 1; checksum sealed once")

print("\n=== S2: already tagged -> a normal boot changes NOTHING ===")
for g in (0, 1, 2, 3):
    blk = make_block(g, TAG_MAGIC)
    out, rt, d3, st = boot_tail(blk)
    check(out == blk, f"GATE {g}: block byte-identical (incl. checksum)")
    check(int.from_bytes(rt[0x6c:0x70], "big") == g, f"GATE {g}: restored into RAM unchanged")
    check(st["seal"] == 0 and st["boot_fn"] == [1] and d3 == 0xCAFE0001, "no re-seal; replay + d3 intact")
    if g == 0:
        print(f"        (a tagged boot executes {st['insns']} instructions from the detour to the memcpy return, "
              f"of which the cave adds ~7)")

print("\n=== S3: any non-matching tag value resets (garbage, all-ones, one bit off) ===")
for t in (0xFFFFFFFF, 0xDEADBEEF, TAG_MAGIC ^ 1, TAG_MAGIC ^ 0x80000000, 1):
    out, rt, d3, st = boot_tail(make_block(2, t))
    check(gate_of(out) == 0 and tag_of(out) == TAG_MAGIC and rom_valid(out) == 1, f"tag 0x{t:08x} -> reset to OT, valid")

print("\n=== S4: the blank-battery case (the defaults path leaves an all-zero, valid block) ===")
out, rt, d3, st = boot_tail(make_block(0, 0))
check(gate_of(out) == 0 and tag_of(out) == TAG_MAGIC and rom_valid(out) == 1, "GATE stays 0, tag set, valid")

print("\n=== S5: first flash, then the user's own choice survives later boots ===")
blk = make_block(2, 0)                                    # earlier build left DT-T
blk, rt, _, _ = boot_tail(blk)
check(gate_of(blk) == 0, "boot 1 (first flash): OT")
# the user picks OTFX (GATE 3): the real setter writes the shadow, the key handler re-seals
b = bytearray(blk); b[0x6c:0x70] = (3).to_bytes(4, "big"); b[0:4] = andy_sum(b).to_bytes(4, "big")
blk = bytes(b)
for n in (2, 3, 4):
    blk, rt, _, st = boot_tail(blk)
    check(gate_of(blk) == 3 and int.from_bytes(rt[0x6c:0x70], "big") == 3 and st["seal"] == 0,
          f"boot {n}: still OTFX (GATE 3), block untouched")

print("\nALL CHECKS PASSED" if not fail else f"\n{fail} CHECK(S) FAILED")
sys.exit(1 if fail else 0)

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 14 -- the "new OT+FX" mute mode (instant dry cut + FX tail rings + unmute resumes
at the playhead, like stock OT).

This probe runs the ACTUAL FUN_40004db8 bytes (the per-frame mute/solo/cue gate) from the
stock image to nail down its per-track DSP-frame word layout and prove exactly which lever
mute pulls -- so we know what the new mode must and must not touch.

FUN_40004db8 writes 8 tracks x 4 u16 words (8 bytes/track) into the buffer pointed to by
0x80003c10, from three source arrays:
    A = 0x80000c60  stride 4  (two u16: word0, word1)
    B = 0x80000c80  stride 2  (one u16)
    C = 0x8000485a  stride 8  (first u16 used)
Non-solo branch (0x80000037 == 0), per track t, bit tests on 0x80000008:
    frame[8t+0] = cue(16+t)      ? A[t].word1 : 0            -- CUE-send level
    frame[8t+2] = solo(t)        ? A[t].word0
                : mute(8+t)       ? 0                          -- MAIN mix level  <-- the mute lever
                : (any-soloed)    ? 0 : A[t].word0
    frame[8t+4] = B[t]                                         -- UNGATED (pan)
    frame[8t+6] = C[t].word0                                   -- UNGATED (pan)

Usage:  python3 tools/emu_otfx.py [out/raw/section_3_MAIN_OS.bin]
"""
import pathlib, struct, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMGP = sys.argv[1] if len(sys.argv) > 1 else "out/raw/section_3_MAIN_OS.bin"
IMG = pathlib.Path(IMGP).read_bytes()

ENTRY, RET = 0x40004db8, 0x40004ee0       # lea -28,sp ... rts
MUTE_STATE = 0x80000008
SOLO_FLAG  = 0x80000037
CUEFOLD    = 0x8000009c
FRAME_PTR  = 0x80003c10
FRAME_DST  = 0x80050000
A_ARR, B_ARR, C_ARR = 0x80000c60, 0x80000c80, 0x8000485a
EB4, EB5   = 0x80000eb4, 0x80000eb5       # tail loop reads these; keep them != 3
E0         = 0x800000e0
fail = 0


def check(c, m):
    global fail
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fail += 1


def run(mute_state, solo_flag=0, cuefold=0, hook_clear_mutebits=False):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_map(0x80000000, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)
    uc.mem_write(0x40000400, IMG)
    uc.mem_write(FRAME_PTR, struct.pack(">I", FRAME_DST))
    uc.mem_write(MUTE_STATE, struct.pack(">I", mute_state))
    uc.mem_write(SOLO_FLAG, bytes([solo_flag]))
    uc.mem_write(CUEFOLD, struct.pack(">I", cuefold))
    uc.mem_write(E0, struct.pack(">I", 0))
    uc.mem_write(0x80000eb0, b"\x00" * 0x40)          # tail-loop machine-type bytes != 3
    # sentinels: A[t].word0 = 0xA000|t, A[t].word1 = 0xC000|t, B[t] = 0xB000|t, C[t] = 0x5000|t
    for t in range(8):
        uc.mem_write(A_ARR + t * 4, struct.pack(">HH", 0xA000 | t, 0xC000 | t))
        uc.mem_write(B_ARR + t * 2, struct.pack(">H", 0xB000 | t))
        uc.mem_write(C_ARR + t * 8, struct.pack(">HHHH", 0x5000 | t, 0, 0, 0))
    uc.mem_write(FRAME_DST, b"\xEE" * 0x80)

    # optional: emulate the V6/"pre" hook that clears the mute bits in the D5 copy.
    # FUN_40004db8 re-reads 0x80000008 only once (into d5 at 0x40004dc6); the patch hook
    # rewrites d5 right after.  Simulate by clearing the RAM word before entry AND trapping
    # the instruction: simplest is to just pass an already-cleared mute_state for the "kept"
    # case, which is exactly what the hook's `D5 &= ~(muted<<8)` achieves for the gate.
    sp = 0xF000
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.mem_write(sp, struct.pack(">I", RET))
    try:
        uc.emu_start(ENTRY, RET, count=100000)
    except UcError as e:
        print("   UcError", e)
    return [struct.unpack(">4H", uc.mem_read(FRAME_DST + 8 * t, 8)) for t in range(8)]


def show(tag, fr):
    print(f"  {tag}")
    for t, w in enumerate(fr):
        print(f"    trk{t}: +0={w[0]:#06x}  +2={w[1]:#06x}  +4={w[2]:#06x}  +6={w[3]:#06x}")


print("=== all tracks unmuted (mute_state = 0) ===")
fr0 = run(0)
show("baseline", fr0)
check(all(fr0[t][1] == (0xA000 | t) for t in range(8)), "frame +2 == A[t].word0 (MAIN level) for every track")
check(all(fr0[t][0] == 0 for t in range(8)), "frame +0 == 0 (no track cued)")
check(all(fr0[t][2] == (0xB000 | t) for t in range(8)), "frame +4 == B[t] (ungated)")
check(all(fr0[t][3] == (0x5000 | t) for t in range(8)), "frame +6 == C[t].word0 (ungated)")

print("\n=== track 3 muted (bit 8+3) -- STOCK behaviour ===")
fr = run(1 << (8 + 3))
show("stock mute t3", fr)
check(fr[3][1] == 0, "frame +2 for t3 == 0  -> MAIN mix cut (dry + FX-return both gone)")
check(fr[3][0] == fr0[3][0] and fr[3][2] == fr0[3][2] and fr[3][3] == fr0[3][3],
      "frame +0/+4/+6 for t3 UNCHANGED (mute only touches the MAIN word)")
check(all(fr[t] == fr0[t] for t in range(8) if t != 3), "other tracks untouched")

print("\n=== track 3: patch 'pre' hook clears the mute bit in D5 (V6 trick) ===")
fr = run(0)   # gate sees mute bit already cleared
check(fr[3][1] == (0xA000 | 3), "frame +2 for t3 PRESERVED -> post-FX bus stays open -> FX tail reaches MAIN")
print("  (the new mode keeps this word open exactly like OT+FX-TRIG/DT; the dry must then be")
print("   killed upstream at the voice amp, without disturbing the voice's cursor/envelope)")

print("\n=== track 3 cued (bit 16+3) ===")
fr = run(1 << (16 + 3))
check(fr[3][0] == (0xC000 | 3), "frame +0 for t3 == A[t].word1 (CUE-send level) when cued")

print("\n=== solo: track 5 soloed (bit 5), others not, solo flag set ===")
fr = run(1 << 5, solo_flag=1)
show("solo t5", fr)

print()
print("ALL GOOD" if not fail else f"{fail} FAILURE(S)")
sys.exit(1 if fail else 0)

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Emulate the V7 patch_softmute `pre` hook + the real FUN_40004db8 frame builder to prove the
SOLO soft-silence: with MUTE MODE == OT+FX, a track silenced because another track is soloed
keeps its DSP-frame level words (so its FX inserts still ring) and gets a one-shot note-off.

Runs the ACTUAL bytes from out/mainos_mutemode.bin.

Usage:  python3 tools/emu_solo.py [out/mainos_mutemode.bin]
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMGP = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode.bin"
IMG = pathlib.Path(IMGP).read_bytes()
# the DT build (build_mutemode_dt.py) links its stubs as out/patch_*_dt.elf
SOFTMUTE_ELF = "out/patch_softmute_dt.elf" if IMGP.endswith("_dt.bin") else "out/patch_softmute.elf"

MUTE_STATE = 0x80000008
SOLO_FLAG  = 0x80000037
REL_STATE  = 0x8000184a
SHADOW     = 0x80006c66
GATE       = 0x800000dc
FRAME_PTR  = 0x80003c10          # FUN_40004db8 loads this -> frame dest
FRAME_DST  = 0x80040000          # where we point it
PRE   = {p[2]: int(p[0], 16) for p in
         (l.split() for l in subprocess.run(["m68k-elf-nm", SOFTMUTE_ELF],
          capture_output=True, text=True).stdout.splitlines()) if len(p) == 3}["pre"]
NOTEOFF = 0x40008f84
fail = 0


def check(c, m):
    global fail
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fail += 1


BACK = 0x40004dcc              # `pre` returns here; FUN_40004db8 then branches on SOLO_FLAG


def run(mute_state, solo_flag, gate=1, shadow=0, trace=False):
    """run just `pre` (stop at BACK); return (uc, noteoffs, d5)."""
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_map(0x80000000, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)
    uc.mem_write(0x40000400, IMG)
    uc.mem_write(MUTE_STATE, struct.pack(">I", mute_state))
    uc.mem_write(SOLO_FLAG, bytes([solo_flag]))
    uc.mem_write(GATE, struct.pack(">I", gate))
    uc.mem_write(SHADOW, bytes([shadow]))
    uc.mem_write(REL_STATE, b"\x00")

    noteoffs = []

    def hook(u, addr, size, _):
        if addr == NOTEOFF:
            t = struct.unpack(">i", u.mem_read(u.reg_read(UC_M68K_REG_A7) + 4, 4))[0]
            noteoffs.append(t)
            ret = struct.unpack(">I", u.mem_read(u.reg_read(UC_M68K_REG_A7), 4))[0]
            u.reg_write(UC_M68K_REG_A7, u.reg_read(UC_M68K_REG_A7) + 4)
            u.reg_write(UC_M68K_REG_PC, ret)         # emulate FUN_40008f84 as rts
        if trace:
            print(f"    {addr:08x}")
    uc.hook_add(UC_HOOK_CODE, hook)

    sp = 0xF000
    uc.reg_write(UC_M68K_REG_A7, sp)
    d5 = None
    try:
        uc.emu_start(PRE, BACK, count=20000)
        d5 = uc.reg_read(UC_M68K_REG_D5)
    except UcError as e:
        if trace:
            print("   UcError", e)
    return uc, noteoffs, d5


# In FUN_40004db8, the NOT-solo branch keeps a track's mute-gated frame word iff D5 bit 8+t
# is clear; the SOLO branch keeps every track's words iff (bit t clear AND bit 8+t clear) and
# the "any track soloed?" mask D1 == -1, which holds iff D5 low byte == 0.  So the frame-keep
# claim reduces to: after `pre`, what is D5?

def mutebits(d5):   return (d5 >> 8) & 0xFF
def solobits(d5):   return d5 & 0xFF

print("=== not solo, track 3 muted (V6 mute path unchanged) ===")
uc, no, d5 = run(mute_state=(1 << (8 + 3)), solo_flag=0)
check(uc.mem_read(REL_STATE, 1)[0] == (1 << 3), "REL_STATE bit 3 set")
check(uc.mem_read(SHADOW, 1)[0] == (1 << 3), "SHADOW == 0x08")
check(no == [3], f"note-off once for track 3 (got {no})")
check(mutebits(d5) & (1 << 3) == 0, f"D5 mute bit 3 CLEARED -> FUN_40004db8 keeps track 3's word (D5={d5:#010x})")

print("\n=== solo active, track 0 soloed -> tracks 1..7 soft-silenced ===")
uc, no, d5 = run(mute_state=(1 << 0), solo_flag=1)
check(uc.mem_read(REL_STATE, 1)[0] == 0xFE, "REL_STATE == 0xFE (all non-soloed)")
check(uc.mem_read(SHADOW, 1)[0] == 0xFE, "SHADOW == 0xFE")
check(sorted(no) == [1, 2, 3, 4, 5, 6, 7], f"note-off once for tracks 1..7 (got {sorted(no)})")
check(solobits(d5) == 0 and mutebits(d5) == 0,
      f"D5 bits 0..15 CLEARED -> D1 becomes -1, FUN_40004db8 keeps every track's words (D5={d5:#010x})")

print("\n=== solo active, nothing soloed -> nothing silenced (stock) ===")
uc, no, d5 = run(mute_state=0, solo_flag=1)
check(uc.mem_read(REL_STATE, 1)[0] == 0 and uc.mem_read(SHADOW, 1)[0] == 0 and no == [],
      "no note-offs, REL/SHADOW clear")
check(d5 == (0 & 0xFFFFFFFF), f"D5 untouched (0) -> stock solo path (D5={d5:#010x})")

print("\n=== solo active + track 3 ALSO manually muted, track 0 soloed ===")
uc, no, d5 = run(mute_state=(1 << 0) | (1 << (8 + 3)), solo_flag=1)
check(sorted(no) == [1, 2, 3, 4, 5, 6, 7], f"note-off tracks 1..7 incl. the muted one (got {sorted(no)})")
check(solobits(d5) == 0 and mutebits(d5) == 0, f"D5 bits 0..15 cleared (D5={d5:#010x})")

print("\n=== solo edge: no double note-off when the silenced set is unchanged ===")
uc, no, d5 = run(mute_state=(1 << 1), solo_flag=1, shadow=0xFD)   # 0,2..7 already silenced
check(no == [], f"shadow already 0xFD -> no fresh note-offs (got {no})")
check(uc.mem_read(REL_STATE, 1)[0] == 0xFD, "REL_STATE still maintained at 0xFD")

print("\n=== MUTE MODE == OT: bail + clear shadow, stock cut downstream ===")
uc, no, d5 = run(mute_state=(1 << (8 + 3)), solo_flag=0, gate=0, shadow=0xAA)
check(uc.mem_read(SHADOW, 1)[0] == 0 and uc.mem_read(REL_STATE, 1)[0] == 0 and no == [],
      "OT mode: shadow cleared, no work")
check(mutebits(d5) & (1 << 3) != 0, f"D5 mute bit 3 LEFT SET -> stock FUN_40004db8 zeroes the word (D5={d5:#010x})")

print("\n=== OT -> OT+FX transition: stale shadow doesn't swallow the first note-off ===")
uc, no, d5 = run(mute_state=(1 << (8 + 5)), solo_flag=0, gate=0, shadow=0xFF)
check(uc.mem_read(SHADOW, 1)[0] == 0, "OT frame leaves shadow == 0")
uc, no, d5 = run(mute_state=(1 << (8 + 5)), solo_flag=0, gate=1, shadow=0x00)
check(no == [5], f"OT+FX frame then note-offs track 5 (got {no})")

print("\n=== mt_trig: drop the real per-trig voice-start for a silenced track ===")
# Session ??-bis: pre_v (detouring FUN_40005178/trig_to_voice) is GONE -- proven dead code
# for ordinary sequenced trigs by driving the real firmware in the full-firmware emulator
# (79 real trigs over 6s, FUN_40005178 entered ZERO times). The real per-trig dispatch,
# found by tracing the actual trig flag write back through live execution, is
# FUN_40006844 (reached via FUN_40006820's 8-track fan-out): it clears the voice's
# `active` byte, bumps a per-track trig counter, then calls FUN_4000672c to actually
# restart the sample -- nothing resembling FUN_40005178's (track,cmd,flag) stack contract.
# mt_trig detours FUN_40006844's own entry (`movew sr,d2`/`movew #0x2700,sr`, 6 B,
# replayed on the "pass" path); the track number is already in D1 at entry (FUN_40006820's
# fan-out guarantees 0..7), nothing is pushed to the stack by the caller, and no cmd value
# exists to filter on. "drop" = an immediate `rts` before any of the active-clear/counter/
# restart work; "pass" = replay the 2 displaced instructions and resume at FUN_40006844+6.
STOP_ADDR = 0xDEAD0000
RET_ADDR = 0x400003fc   # a mapped, harmless ROM address -- must be fetchable for the hook to fire
MT_TRIG = {p[2]: int(p[0], 16) for p in
           (l.split() for l in subprocess.run(["m68k-elf-nm", SOFTMUTE_ELF],
            capture_output=True, text=True).stdout.splitlines()) if len(p) == 3}["mt_trig"]
MT_BACK = 0x4000684a
SENTINEL_D2, SENTINEL_A2 = 0xCAFED00D, 0xCAFEA2A2


def run_mt(track, mute_state, solo_flag, gate=1):
    """call mt_trig with D1=track, simulating FUN_40006820's REAL stack frame at the
    `bccs 0x40006844` fallthrough: [sp+0]=its saved D2, [sp+4]=its saved A2, [sp+8]=the
    real return address -- NOT just a bare return address (Session ??-ter: an earlier,
    too-simple version of this harness entered mt_trig directly with nothing beneath a
    single synthetic return address, passed, and still crashed real hardware/emulated
    playback instantly, because the real caller always has 2 extra longs live on the
    stack at this point that any early return must also unwind). Returns
    ('drop'|'pass', final_sp, d2, a2) so the caller can verify the stack balanced AND
    that a 'drop' correctly restored the caller's D2/A2 before its `rts`."""
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_map(0x80000000, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)
    uc.mem_write(0x40000400, IMG)
    uc.mem_write(MUTE_STATE, struct.pack(">I", mute_state))
    uc.mem_write(SOLO_FLAG, bytes([solo_flag]))
    uc.mem_write(GATE, struct.pack(">I", gate))
    uc.reg_write(UC_M68K_REG_SR, 0x2700)   # supervisor mode -- the "pass" path replays the
                                            # displaced `movew sr,d2`, privileged on ColdFire
    sp0 = 0xF000
    sp = sp0 - 8
    ret = RET_ADDR
    uc.mem_write(sp, struct.pack(">I", SENTINEL_D2))
    uc.mem_write(sp + 4, struct.pack(">I", SENTINEL_A2))
    uc.mem_write(sp + 8, struct.pack(">I", ret))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_D1, track)
    out = {"where": None}

    def hook(u, addr, size, _):
        if addr == MT_BACK:
            out["where"] = "pass"
            u.reg_write(UC_M68K_REG_PC, STOP_ADDR)
        if addr == ret:
            out["where"] = "drop"
            u.reg_write(UC_M68K_REG_PC, STOP_ADDR)
    uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(MT_TRIG, STOP_ADDR, count=5000)
    except UcError:
        pass
    final_sp = uc.reg_read(UC_M68K_REG_A7)
    d2 = uc.reg_read(UC_M68K_REG_D2)
    a2 = uc.reg_read(UC_M68K_REG_A2)
    return out["where"], final_sp, d2, a2


SP0 = 0xF000


def check_drop(w, sp, d2, a2, label):
    check(w == "drop", f"{label} -> DROP (got {w})")
    check(sp == SP0 + 4, f"{label}: SP correctly unwound past D2/A2/ret (got {sp:#x}, want {SP0+4:#x})")
    check(d2 == SENTINEL_D2 and a2 == SENTINEL_A2,
          f"{label}: caller's D2/A2 correctly restored (got d2={d2:#x} a2={a2:#x})")


def check_pass(w, sp, label):
    check(w == "pass", f"{label} -> PASS (got {w})")
    check(sp == SP0 - 8, f"{label}: SP unchanged, ready for FUN_40006844's own epilogue "
          f"(got {sp:#x}, want {SP0-8:#x})")


w, sp, d2, a2 = run_mt(3, mute_state=(1 << (8 + 3)), solo_flag=0)
check_drop(w, sp, d2, a2, "muted track 3")
w, sp, d2, a2 = run_mt(3, mute_state=0, solo_flag=0)
check_pass(w, sp, "unmuted track 3, no solo")
w, sp, d2, a2 = run_mt(3, mute_state=(1 << 0), solo_flag=1)     # track 0 soloed, 3 not
check_drop(w, sp, d2, a2, "solo on t0, non-soloed t3")
w, sp, d2, a2 = run_mt(0, mute_state=(1 << 0), solo_flag=1)     # track 0 soloed
check_pass(w, sp, "solo on t0, soloed t0")
w, sp, d2, a2 = run_mt(3, mute_state=0, solo_flag=1)            # solo armed, nothing soloed
check_pass(w, sp, "solo armed but nothing soloed, t3")
w, sp, d2, a2 = run_mt(3, mute_state=(1 << 0), solo_flag=1, gate=0)  # OT mode
check_pass(w, sp, "MUTE MODE == OT")
for t in range(8):
    w, sp, d2, a2 = run_mt(t, mute_state=(1 << (8 + t)), solo_flag=0)
    check_drop(w, sp, d2, a2, f"every audio track (t={t})")

print("\n=== mt_rebind: gate the arena-pointer rebind write for a silenced track ===")
# Session ??-quater: mt_trig alone (isolation-tested AND dynamically proven against real
# playback) made zero difference on real hardware -- this ColdFire-only emulator cannot
# see the DSP at all, so mt_trig's proof, while real, doesn't cover whatever the DSP
# itself watches. Working hypothesis: the DSP treats THIS write (the arena-entry pointer
# rebind, `0x4000f4dc`/`e0`, one level up the call chain, unconditional in stock code) as
# its own independent restart signal. See patch_softmute.s for the full reasoning and the
# explicit caveat that -- unlike mt_trig -- this hook's real-world effect cannot be proven
# in this emulator; only that it correctly gates the one write it targets.
MT_REBIND = {p[2]: int(p[0], 16) for p in
             (l.split() for l in subprocess.run(["m68k-elf-nm", SOFTMUTE_ELF],
              capture_output=True, text=True).stdout.splitlines()) if len(p) == 3}["mt_rebind"]
MR_BACK = 0x4000f4e4
A2_TARGET = 0x80050000   # scratch dest for the a2@(4)/a2@(8) writes we're watching
SENT_A5, SENT_A4 = 0x46c92000, 0x100b1000   # arbitrary, distinguishable "new arena" addrs


def run_mr(track, mute_state, solo_flag, gate=1):
    """call mt_rebind with A2=A2_TARGET, A4/A5=sentinel 'new arena' addresses, and the
    track number at (0x40,sp) -- the same stack slot the real caller uses. Returns
    (a2_plus4, a2_plus8) read back after the call: SENT_A5/SENT_A4 if the write
    happened (pass), or whatever was there before (0) if it was skipped (silenced)."""
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_map(0x80000000, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)
    uc.mem_write(0x40000400, IMG)
    uc.mem_write(MUTE_STATE, struct.pack(">I", mute_state))
    uc.mem_write(SOLO_FLAG, bytes([solo_flag]))
    uc.mem_write(GATE, struct.pack(">I", gate))
    uc.mem_write(A2_TARGET, b"\x00" * 16)
    sp = 0xF000
    uc.mem_write(sp + 0x40, struct.pack(">I", track))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_A2, A2_TARGET)
    uc.reg_write(UC_M68K_REG_A4, SENT_A4)
    uc.reg_write(UC_M68K_REG_A5, SENT_A5)

    def hook(u, addr, size, _):
        if addr == MR_BACK:
            u.reg_write(UC_M68K_REG_PC, STOP_ADDR)
    uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(MT_REBIND, STOP_ADDR, count=2000)
    except UcError:
        pass
    a2p4 = struct.unpack(">I", uc.mem_read(A2_TARGET + 4, 4))[0]
    a2p8 = struct.unpack(">I", uc.mem_read(A2_TARGET + 8, 4))[0]
    return a2p4, a2p8


def check_mr_skipped(res, label):
    a2p4, a2p8 = res
    check(a2p4 == 0 and a2p8 == 0, f"{label}: BOTH arena-pointer writes skipped (got +4={a2p4:#x} +8={a2p8:#x})")


def check_mr_written(res, label):
    a2p4, a2p8 = res
    check(a2p4 == SENT_A5 and a2p8 == SENT_A4,
          f"{label}: BOTH arena-pointer writes happened (got +4={a2p4:#x} +8={a2p8:#x})")


check_mr_skipped(run_mr(3, mute_state=(1 << (8 + 3)), solo_flag=0), "muted track 3")
check_mr_written(run_mr(3, mute_state=0, solo_flag=0), "unmuted track 3, no solo")
check_mr_skipped(run_mr(3, mute_state=(1 << 0), solo_flag=1), "solo on t0, non-soloed t3")
check_mr_written(run_mr(0, mute_state=(1 << 0), solo_flag=1), "solo on t0, soloed t0")
check_mr_written(run_mr(3, mute_state=0, solo_flag=1), "solo armed but nothing soloed, t3")
check_mr_written(run_mr(3, mute_state=(1 << 0), solo_flag=1, gate=0), "MUTE MODE == OT")
for t in range(8):
    check_mr_skipped(run_mr(t, mute_state=(1 << (8 + t)), solo_flag=0), f"every audio track (t={t})")

print()
print("ALL GOOD" if not fail else f"{fail} FAILURE(S)")
sys.exit(1 if fail else 0)

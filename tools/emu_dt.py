#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Emulate the DT (MUTE MODE == 2) path in the DT build, against the real image bytes.

DT mute is a pure sequencer mute: the `pre` hook clears the same D5 mute/solo bits as OT+FX
(so FUN_40004db8 keeps every DSP-frame level word -> the sounding voice AND its FX still
reach the mix, untouched), but does NOT call the FUN_40008f84 note-off and does NOT maintain
DAT_8000184a.  `mt_trig` drops the real per-trig voice-start (FUN_40006844) for a silenced
track (no new trigs).  Net: whatever voice is playing rides its own amp envelope to its
natural end (fade / sustain / infinite loop); only re-triggering is suppressed.

  static : get/set_mutemode now cover 3 modes (OT / OT+FX / DT); val_tbl[2] -> "DT".
  emu    : `pre`     gate 2 -> D5 bits cleared, NO note-off, REL_STATE untouched, shadow cleared;
                     gate 1 -> unchanged (note-off + REL_STATE);  gate 0 -> stock bail.
           `mt_trig` gate 2 -> drops muted / solo-non-soloed trigs, passes soloed/unmuted.

Usage:  python3 tools/emu_dt.py [out/mainos_mutemode_dt.bin]
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

BASE = 0x40000400
IMGP = sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin"
IMG = pathlib.Path(IMGP).read_bytes()
STOCK = pathlib.Path("out/raw/section_3_MAIN_OS.bin").read_bytes()

MUTE_STATE = 0x80000008
SOLO_FLAG  = 0x80000037
REL_STATE  = 0x8000184a
SHADOW     = 0x80006c66
GATE       = 0x800000dc
NOTEOFF    = 0x40008f84
BACK       = 0x40004dcc
MT_BACK    = 0x4000684a
fail = 0


def check(c, m):
    global fail
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fail += 1


def cstr(a):
    o = a - BASE
    return IMG[o:IMG.index(b"\0", o)].decode("latin1")


SYM = {p[2]: int(p[0], 16) for p in
       (l.split() for l in subprocess.run(["m68k-elf-nm", "out/patch_softmute_dt.elf"],
        capture_output=True, text=True).stdout.splitlines()) if len(p) == 3}
MSYM = {p[2]: int(p[0], 16) for p in
        (l.split() for l in subprocess.run(["m68k-elf-nm", "out/patch_mutemode_dt.elf"],
         capture_output=True, text=True).stdout.splitlines()) if len(p) == 3}
PRE, MT_TRIG = SYM["pre"], SYM["mt_trig"]


# ------------------------------------------------------------------ static: menu
print("=== static: MUTE MODE now has 3 values ===")
vt = MSYM["val_tbl"]
vals = [cstr(struct.unpack(">I", IMG[vt - BASE + 4 * i:vt - BASE + 4 * i + 4])[0]) for i in range(3)]
check(vals == ["OT", "OT+FX", "DT"], f'val_tbl -> {vals}')


def new_uc():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_map(0x80000000, 0x00100000)
    uc.mem_map(0x00000000, 0x00010000)
    uc.mem_write(0x40000400, IMG)
    uc.reg_write(UC_M68K_REG_A7, 0x0000F000)
    return uc


print("\n=== emu: get_mutemode / set_mutemode over [0, 2] ===")
g = MSYM["get_mutemode"]
for mode, want in [(-1, "OT"), (0, "OT"), (1, "OT+FX"), (2, "DT"), (3, "DT"), (99, "DT")]:
    uc = new_uc()
    uc.mem_write(GATE, struct.pack(">i", mode))
    sp = 0xF000 - 4
    uc.mem_write(sp, struct.pack(">I", 0xDEADBEEF))
    uc.reg_write(UC_M68K_REG_A7, sp)
    try:
        uc.emu_start(g, 0xDEADBEEF, count=2000)
    except UcError:
        pass
    d0 = uc.reg_read(UC_M68K_REG_D0)
    try:
        s = cstr(d0)
    except Exception:
        s = f"<bad 0x{d0:08x}>"
    check(s == want, f"MUTE_MODE={mode:<3} -> \"{s}\" (want \"{want}\")")

s_ = MSYM["set_mutemode"]
# (start, delta, wrap) -> expected, N_MODES = 3
cases = [(1, 1, 0, 2), (2, 1, 0, 2),        # [RIGHT] clamps at 2
         (2, -1, 0, 1), (0, -1, 0, 0),      # [LEFT] clamps at 0
         (2, 1, 1, 0), (0, -1, 1, 2)]       # [YES] wraps 2->0 ; underflow 0->2
for start, delta, wrap, want in cases:
    uc = new_uc()
    uc.mem_write(GATE, struct.pack(">i", start))
    sp = 0xF000
    for v in (wrap, delta):
        sp -= 4
        uc.mem_write(sp, struct.pack(">i", v))
    sp -= 4
    uc.mem_write(sp, struct.pack(">I", 0xDEADBEEF))
    uc.reg_write(UC_M68K_REG_A7, sp)
    try:
        uc.emu_start(s_, 0xDEADBEEF, count=2000)
    except UcError:
        pass
    got = struct.unpack(">i", uc.mem_read(GATE, 4))[0]
    check(got == want, f"start={start} delta={delta:+d} wrap={wrap} -> {got} (want {want})")


# ------------------------------------------------------------------ emu: pre
def run_pre(mute_state, solo_flag, gate, shadow=0):
    uc = new_uc()
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
            u.reg_write(UC_M68K_REG_PC, ret)
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.reg_write(UC_M68K_REG_A7, 0xF000)
    d5 = None
    try:
        uc.emu_start(PRE, BACK, count=20000)
        d5 = uc.reg_read(UC_M68K_REG_D5)
    except UcError:
        pass
    return uc, noteoffs, d5


print("\n=== emu: DT `pre` (gate 2) -- keep frame words, NO note-off ===")
uc, no, d5 = run_pre(mute_state=(1 << (8 + 3)), solo_flag=0, gate=2)
check(no == [], f"no note-off (got {no})")
check(uc.mem_read(REL_STATE, 1)[0] == 0, "REL_STATE untouched (0)")
check(uc.mem_read(SHADOW, 1)[0] == 0, "SHADOW cleared")
check((d5 >> (8 + 3)) & 1 == 0, f"D5 mute bit 3 cleared -> FUN_40004db8 keeps track 3's word (D5={d5:#010x})")

print("\n=== emu: DT `pre` (gate 2) + solo, track 0 soloed ===")
uc, no, d5 = run_pre(mute_state=(1 << 0), solo_flag=1, gate=2)
check(no == [], f"no note-off for the non-soloed tracks (got {no})")
check(uc.mem_read(REL_STATE, 1)[0] == 0, "REL_STATE untouched")
check(d5 & 0xFFFF == 0, f"D5 bits 0..15 cleared -> every track's words kept (D5={d5:#010x})")

print("\n=== emu: DT `pre` (gate 2) + solo, nothing soloed -> stock (no-op) ===")
uc, no, d5 = run_pre(mute_state=0, solo_flag=1, gate=2)
check(no == [] and uc.mem_read(REL_STATE, 1)[0] == 0, "no note-off, REL_STATE clear")
check(d5 == 0, f"D5 untouched (D5={d5:#010x})")

print("\n=== regression: OT+FX `pre` (gate 1) still note-offs + maintains REL_STATE ===")
uc, no, d5 = run_pre(mute_state=(1 << (8 + 3)), solo_flag=0, gate=1)
check(no == [3], f"note-off track 3 (got {no})")
check(uc.mem_read(REL_STATE, 1)[0] == (1 << 3), "REL_STATE bit 3 set")

print("\n=== regression: OT `pre` (gate 0) bails, mute bit left set ===")
uc, no, d5 = run_pre(mute_state=(1 << (8 + 3)), solo_flag=0, gate=0, shadow=0xAA)
check(no == [] and uc.mem_read(SHADOW, 1)[0] == 0, "no work, shadow cleared")
check((d5 >> (8 + 3)) & 1 == 1, f"D5 mute bit 3 left SET -> stock cut (D5={d5:#010x})")


# ------------------------------------------------------------------ emu: mt_trig
# Session ??-bis: pre_v (detouring FUN_40005178/trig_to_voice) is GONE -- proven dead code
# for ordinary sequenced trigs by driving the real firmware in the full-firmware emulator
# (79 real trigs over 6s, FUN_40005178 entered ZERO times). The real per-trig dispatch is
# FUN_40006844 (via FUN_40006820's 8-track fan-out) -- found by tracing the actual trig-flag
# write back through live execution, not by re-reading a decompile. mt_trig detours its
# entry (`movew sr,d2`/`movew #0x2700,sr`, 6 B); the track number is already in D1 at entry
# (0..7, guaranteed by the fan-out), nothing is pushed to the stack, and there is no cmd
# value at all to filter on.
STOP_ADDR = 0xDEAD0000
RET_ADDR = 0x400003fc   # a mapped, harmless ROM address -- must be fetchable for the hook to fire
MT_BACK = 0x4000684a
SENTINEL_D2, SENTINEL_A2 = 0xCAFED00D, 0xCAFEA2A2
SP0 = 0xF000


def run_mt(track, mute_state, solo_flag, gate):
    """Simulates FUN_40006820's REAL stack frame at the `bccs 0x40006844` fallthrough:
    [sp+0]=its saved D2, [sp+4]=its saved A2, [sp+8]=the real return address (Session
    ??-ter: a bare single-return-address harness passed here but the same fix crashed
    real playback instantly, because an early return must also unwind those 2 extra
    longs). Returns ('drop'|'pass', final_sp, d2, a2)."""
    uc = new_uc()
    uc.mem_write(MUTE_STATE, struct.pack(">I", mute_state))
    uc.mem_write(SOLO_FLAG, bytes([solo_flag]))
    uc.mem_write(GATE, struct.pack(">I", gate))
    uc.reg_write(UC_M68K_REG_SR, 0x2700)   # supervisor mode -- the "pass" path replays the
                                            # displaced `movew sr,d2`, privileged on ColdFire
    sp = SP0 - 8
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
    return out["where"], uc.reg_read(UC_M68K_REG_A7), uc.reg_read(UC_M68K_REG_D2), uc.reg_read(UC_M68K_REG_A2)


def check_drop(res, label):
    w, sp, d2, a2 = res
    check(w == "drop", f"{label} -> DROP (got {w})")
    check(sp == SP0 + 4, f"{label}: SP correctly unwound past D2/A2/ret (got {sp:#x})")
    check(d2 == SENTINEL_D2 and a2 == SENTINEL_A2,
          f"{label}: caller's D2/A2 correctly restored (got d2={d2:#x} a2={a2:#x})")


def check_pass(res, label):
    w, sp, d2, a2 = res
    check(w == "pass", f"{label} -> PASS (got {w})")
    check(sp == SP0 - 8, f"{label}: SP unchanged, ready for FUN_40006844's own epilogue (got {sp:#x})")


print("\n=== emu: DT `mt_trig` (gate 2) -- suppress new trigs on silenced tracks ===")
check_drop(run_mt(3, 1 << (8 + 3), 0, 2), "muted t3")
check_pass(run_mt(3, 0, 0, 2), "unmuted t3, no solo")
check_drop(run_mt(3, 1 << 0, 1, 2), "solo t0, non-soloed t3")
check_pass(run_mt(0, 1 << 0, 1, 2), "solo t0, soloed t0")
check_drop(run_mt(3, 1 << (8 + 3), 0, 1), "regression: OT+FX still drops muted track")
check_pass(run_mt(3, 1 << (8 + 3), 0, 0), "regression: OT lets it through")
for t in range(8):
    check_drop(run_mt(t, 1 << (8 + t), 0, 2), f"every audio track (t={t})")

print("\n=== emu: DT `mt_rebind` (gate 2) -- gate the arena-pointer rebind write ===")
# Session ??-quater: see patch_softmute.s / emu_solo.py for the full reasoning -- mt_trig
# alone made no HW difference; this second hook gates the one remaining DSP-visible
# write mt_trig doesn't touch. Working hypothesis, not emulator-provable end to end.
MT_REBIND = SYM["mt_rebind"]
MR_BACK = 0x4000f4e4
A2_TARGET = 0x80050000
SENT_A5, SENT_A4 = 0x46c92000, 0x100b1000


def run_mr(track, mute_state, solo_flag, gate):
    uc = new_uc()
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
    check(a2p4 == 0 and a2p8 == 0, f"{label}: BOTH writes skipped (got +4={a2p4:#x} +8={a2p8:#x})")


def check_mr_written(res, label):
    a2p4, a2p8 = res
    check(a2p4 == SENT_A5 and a2p8 == SENT_A4,
          f"{label}: BOTH writes happened (got +4={a2p4:#x} +8={a2p8:#x})")


check_mr_skipped(run_mr(3, 1 << (8 + 3), 0, 2), "muted t3")
check_mr_written(run_mr(3, 0, 0, 2), "unmuted t3, no solo")
check_mr_skipped(run_mr(3, 1 << 0, 1, 2), "solo t0, non-soloed t3")
check_mr_written(run_mr(0, 1 << 0, 1, 2), "solo t0, soloed t0")
check_mr_skipped(run_mr(3, 1 << (8 + 3), 0, 1), "regression: OT+FX still gates muted track")
check_mr_written(run_mr(3, 1 << (8 + 3), 0, 0), "regression: OT lets it through")
for t in range(8):
    check_mr_skipped(run_mr(t, 1 << (8 + t), 0, 2), f"every audio track (t={t})")

print()
print("ALL GOOD" if not fail else f"{fail} FAILURE(S)")
sys.exit(1 if fail else 0)

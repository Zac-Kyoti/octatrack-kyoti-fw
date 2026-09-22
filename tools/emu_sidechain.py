#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Validate the side-chain page-2 formatters (patch_sidechain.s) under Unicorn.

  key_fmt   -- COMPRESSOR page-2 A-array callback  void fmt(char *buf, int value):
    value 0        -> "OFF"
    value 1..4     -> "T<n>",  n = coreBase + value - 1
                      coreBase = 1  when current track (0x100b14cc) is 0..3, else 5
  kfilt_fmt -- KEY FLT (step-3 scaffolding):
    value < 64 -> "LP"   value 64 -> "OFF"   value > 64 -> "HP"

Runs the real assembled caves. sprintf (0x40013a08) is stubbed: the call is
trapped, formatted in Python, written back to the buffer, and an rts is
simulated -- so nothing but the formatter's own instructions execute.
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
# sidechain3 carries both formatters; fall back to sidechain (step 1) for key_fmt only
_IMGP = ROOT / "out/mainos_sidechain3.bin"
if not _IMGP.exists():
    _IMGP = ROOT / "out/mainos_sidechain.bin"
IMG = _IMGP.read_bytes()
BASE = 0x40000400
_nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_sidechain.elf")],
                     capture_output=True, text=True).stdout
_SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
KEY_FMT = _SYM.get("key_fmt", 0x400d7000)
KFILT_FMT = _SYM.get("kfilt_fmt")
SPRINTF = 0x40013a08
CUR_TRACK = 0x100b14cc

STACK_TOP = 0x41030000
BUF = 0x41000200               # output buffer
RET_MAGIC = 0x41038000        # fake return address; emu stops when PC lands here

fails = []


def cstr(uc, addr):
    out = b""
    while True:
        c = uc.mem_read(addr + len(out), 1)
        if c == b"\x00":
            return out.decode("latin1")
        out += c
        if len(out) > 32:
            return out.decode("latin1")


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x10000000, 0x100000)      # 0x100b14cc lives here
    uc.mem_map(0x41000000, 0x40000)
    uc.mem_write(BASE, IMG)
    uc.mem_write(RET_MAGIC, b"\x4e\x75")   # rts, in case the fetch happens before the stop

    def on_code(uc, addr, size, u):
        if addr == SPRINTF:
            sp = uc.reg_read(UC_M68K_REG_A7)
            ret = struct.unpack(">I", uc.mem_read(sp, 4))[0]
            buf = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            fmt = cstr(uc, struct.unpack(">I", uc.mem_read(sp + 8, 4))[0])
            if "%d" in fmt:
                val = struct.unpack(">i", uc.mem_read(sp + 12, 4))[0]
                s = fmt.replace("%d", str(val))
            else:
                s = fmt
            uc.mem_write(buf, s.encode("latin1") + b"\x00")
            uc.reg_write(UC_M68K_REG_A7, sp + 4)      # pop return addr
            uc.reg_write(UC_M68K_REG_PC, ret)         # simulate rts
        elif addr == RET_MAGIC:
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    return uc


def run(cur_track, value):
    uc = mk()
    uc.mem_write(CUR_TRACK, bytes([cur_track]))
    uc.mem_write(BUF, b"\xcc" * 16)
    sp = STACK_TOP - 12
    uc.mem_write(sp, struct.pack(">III", RET_MAGIC, BUF, value & 0xffffffff))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_PC, KEY_FMT)
    uc.emu_start(KEY_FMT, 0, count=200)
    return cstr(uc, BUF)


def run_fmt(entry, value):
    uc = mk()
    uc.mem_write(BUF, b"\xcc" * 16)
    sp = STACK_TOP - 12
    uc.mem_write(sp, struct.pack(">III", RET_MAGIC, BUF, value & 0xffffffff))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.reg_write(UC_M68K_REG_PC, entry)
    uc.emu_start(entry, 0, count=200)
    return cstr(uc, BUF)


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def main():
    print("KEY formatter -- key_fmt @ 0x%08x\n" % KEY_FMT)
    # value 0 -> OFF, regardless of track
    for t in range(8):
        got = run(t, 0)
        check(f"track {t+1}, value 0", got == "OFF", f'got "{got}"')

    # value 1..4 -> T1..T4 on the low core, T5..T8 on the high core
    for t in range(8):
        base = 1 if t < 4 else 5
        for v in range(1, 5):
            got = run(t, v)
            exp = f"T{base + v - 1}"
            check(f"track {t+1}, value {v}", got == exp, f'got "{got}", exp "{exp}"')

    # a compressor on T3 can only ever show OFF / T1 / T2 / T3 / T4
    seen = {run(2, v) for v in range(5)}
    check("T3 chooser set == {OFF,T1,T2,T3,T4}", seen == {"OFF", "T1", "T2", "T3", "T4"}, str(sorted(seen)))
    # a compressor on T6 can only ever show OFF / T5 / T6 / T7 / T8
    seen = {run(5, v) for v in range(5)}
    check("T6 chooser set == {OFF,T5,T6,T7,T8}", seen == {"OFF", "T5", "T6", "T7", "T8"}, str(sorted(seen)))

    if KFILT_FMT:
        print(f"\nKEY FLT formatter -- kfilt_fmt @ 0x{KFILT_FMT:08x}")
        for v, exp in ((0, "LP"), (1, "LP"), (63, "LP"), (64, "OFF"), (65, "HP"), (100, "HP"), (127, "HP")):
            got = run_fmt(KFILT_FMT, v)
            check(f"value {v:3d}", got == exp, f'got "{got}", exp "{exp}"')

    print()
    if fails:
        print(f"FAIL -- {len(fails)} check(s): " + ", ".join(fails))
        sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

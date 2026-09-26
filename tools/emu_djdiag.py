#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 98: validate the DJ_DIAG toast end-to-end under raw Unicorn.

The diagnostic build's whole value is one flash that NAMES the failing condition, so the
reporting path itself must not be the thing that breaks. This drives the REAL dj_toggle
in the v5diag image with seeded counters, lets the firmware's own sprintf (0x40013a08)
run for real, and asserts:

  1. NOTIFY receives a pointer to dj_diag_buf;
  2. the buffer then reads exactly "A2 Z32 X32 Y1 P3 R7";
  3. every counter is reset after the read;
  4. DJ_MODE still toggles (the diag block must not have broken the feature).

Modelled on tools/emu_directjump_v4.py's synthetic-call harness (raw Unicorn, no RTOS
boot -- sprintf is self-contained code, measured here rather than assumed).

Run after:  DJ_DIAG=1 python3 tools/build_directjump_v5.py
Usage:      python3 tools/emu_djdiag.py
"""
import pathlib
import struct
import subprocess
import sys

from unicorn import *          # noqa: F401,F403
from unicorn.m68k_const import *  # noqa: F401,F403

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "out/mainos_directjump_v5diag.bin"
ELF = ROOT / "out/patch_directjump_v5diag.elf"

PTN_MODE = 0x460d1742
ARR_ACT = 0x460d1aec
POPUP = 0x460e5cd0
PTN_USED = 0x460d173e
CKSUM = 0x4001f23c
NOTIFY = 0x4005a2b8
DJ_MODE = 0x800000d8
YES_CODE = 0x31

SEED = dict(dj_cnt_arm=2, dj_cnt_z=32, dj_cnt_x=32, dj_cnt_y=1, dj_cnt_m=4)
SEED_B = dict(dj_cnt_pair=3, dj_cnt_rem=7)
WANT = "A2 Z32 X32 Y1 P3 R7 M4"

fails = []


def check(name, cond, detail=""):
    print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def load_syms():
    nm = subprocess.run(["m68k-elf-nm", str(ELF)], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}


def main():
    if not IMG.exists():
        sys.exit("missing out/mainos_directjump_v5diag.bin -- DJ_DIAG=1 build first")
    syms = load_syms()
    for need in ("dj_toggle", "dj_diag_buf", "dj_cnt_arm", "dj_cnt_pair", "dj_cnt_rem"):
        if need not in syms:
            sys.exit(f"symbol {need} missing from {ELF.name}")

    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x800000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(0x40000400, IMG.read_bytes())

    # gates dj_toggle checks before doing anything
    uc.mem_write(PTN_MODE, struct.pack(">I", 1))
    uc.mem_write(ARR_ACT, b"\x00" * 4)
    uc.mem_write(POPUP, b"\x00" * 4)
    uc.mem_write(DJ_MODE, b"\x00" * 4)

    for name, v in SEED.items():
        uc.mem_write(syms[name], struct.pack(">H", v))
    for name, v in SEED_B.items():
        uc.mem_write(syms[name], bytes([v]))

    # stub ONLY the toast sink; sprintf runs for real
    uc.mem_write(NOTIFY, b"\x4e\x75")
    uc.mem_write(CKSUM, b"\x4e\x75")

    hits = {"notify_text": None}

    def hook(u, addr, size, _):
        if addr == NOTIFY:
            sp = u.reg_read(UC_M68K_REG_A7)
            hits["notify_text"] = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
        elif addr == 0x41010000:
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)

    # press(keycode=YES, event=1), exactly what the dispatch loop passes the slot fn
    sp = 0x41012000
    uc.mem_write(0x41010000, b"\x4e\x71")
    uc.mem_write(sp, struct.pack(">I", 0x41010000))
    uc.mem_write(sp + 4, struct.pack(">I", YES_CODE))
    uc.mem_write(sp + 8, struct.pack(">I", 1))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.emu_start(syms["dj_toggle"], 0, timeout=5_000_000, count=2_000_000)

    check("NOTIFY reached", hits["notify_text"] is not None)
    check("NOTIFY text pointer == dj_diag_buf",
          hits["notify_text"] == syms["dj_diag_buf"],
          f"got {hits['notify_text'] and hex(hits['notify_text'])} want {hex(syms['dj_diag_buf'])}")
    raw = bytes(uc.mem_read(syms["dj_diag_buf"], 48))
    text = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
    check(f'buffer reads "{WANT}"', text == WANT, repr(text))
    for name in SEED:
        v = struct.unpack(">H", bytes(uc.mem_read(syms[name], 2)))[0]
        check(f"{name} reset after read", v == 0, str(v))
    for name in SEED_B:
        v = bytes(uc.mem_read(syms[name], 1))[0]
        check(f"{name} reset after read", v == 0, str(v))
    dj = struct.unpack(">I", bytes(uc.mem_read(DJ_MODE, 4)))[0]
    check("DJ_MODE still toggled 0 -> 1", dj == 1, str(dj))


if __name__ == "__main__":
    main()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

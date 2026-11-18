#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
KYOTI V1.8BC: ERASE_EMPTY_TRIGLESS_LOCKS skips BLKPYRAMD tracks (tools/patch_triglock_bp.s), run on the image's own
bytes in Unicorn. The detour at 0x40038a5c (FUN_40038874's erase store) is entered exactly as the store would be
(registers per patch_triglock.s: a0 = the step's row, d1 = 0xff, d2 = the param, d4 = step * 32, d7 = the track,
a3 = the step), with a Part and a pattern written into RAM; stock's NOTIFY (0x40027e00) is an rts here.

  case                                        want
  Flex track, its last lock erased            the trigless lock cleared (ERASE as always)
  BLKPYRAMD track, its last lock erased       the trigless lock kept (a tie)
  Static track with a stale 'OT',1 signature  cleared (not BLKPYRAMD: the machine byte is not Flex)
  BLKPYRAMD track, another lock still there   kept (ERASE would keep it too)
  Flex track, a never-locked param erased     kept (ERASE's own placeholder rule)
and every case: the displaced store done, d0 += d4, every other register as it was.

    <octabam venv python> tools/kyoti_bc_check_erase.py [IMAGE]
"""
import json, pathlib, sys
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.m68k_const import (UC_M68K_REG_PC, UC_M68K_REG_A7, UC_CPU_M68K_CFV4E,
                                UC_M68K_REG_D0, UC_M68K_REG_A0)

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out/KYOTI_WIP/KYOTI_V1.8BC/mainos_kyoti_v1.8bc.bin"
BASE, SITE, NOTIFY = 0x40000400, 0x40038a5c, 0x40027e00
BLOB = 0x40400000                     # a bank blob in RAM for the test (the image's own pages are left alone)
PART = BLOB + 0x8ed80
SENT = 0x47f00000                     # the return address: stop there
D = [UC_M68K_REG_D0 + i for i in range(8)]
A = [UC_M68K_REG_A0 + i for i in range(8)]


def run(case, machine, sig, row, param, track=1, step=3):
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, cpu=UC_CPU_M68K_CFV4E)
    img = IMG.read_bytes()
    uc.mem_map(0x40000000, 0x01000000)
    uc.mem_write(BASE, img[:0x200000])
    uc.mem_write(NOTIFY, b"\x4e\x75")                                 # rts
    uc.mem_map(0x10000000, 0x00200000)
    uc.mem_map(0x46000000, 0x01000000)
    uc.mem_map(0x47f00000, 0x00100000)
    uc.mem_write(0x46c82456, BLOB.to_bytes(4, "big"))                  # BANK -> the test blob
    uc.mem_write(0x100b14cf, b"\x00")                                  # Part 1
    uc.mem_write(0x100b14d0, b"\x00")                                  # pattern 0
    uc.mem_write(PART + 0x22 + track, bytes([machine]))
    uc.mem_write(PART + 60 + 30 * track, sig)
    trac = BLOB + track * 0x91a
    uc.mem_write(trac, bytes(0x59))                                    # every trig layer clear ...
    byte, bit = 7 - (step >> 3), 1 << (step & 7)
    uc.mem_write(trac + 0x10 + byte, bytes([bit]))                     # ... but the trigless-lock bit
    uc.mem_write(trac + 0x59 + 32 * step, bytes(row))
    jsr = img[SITE - BASE:SITE - BASE + 6]
    assert jsr[:2] == b"\x4e\xb9", f"0x{SITE:08x} is not a jsr: {jsr.hex()}"
    entry = int.from_bytes(jsr[2:], "big")
    regs = {D[0]: 0x1000, D[1]: 0xff, D[2]: param, D[3]: 0x33, D[4]: 32 * step, D[5]: 0x55, D[6]: 0x66, D[7]: track,
            A[0]: trac + 32 * step, A[1]: 0x11111111, A[2]: 0x22222222, A[3]: step, A[4]: 0x44444444, A[5]: 0x55555555,
            A[6]: 0x66666666}
    for r, val in regs.items():
        uc.reg_write(r, val)
    sp = 0x47f80000
    uc.mem_write(sp, SENT.to_bytes(4, "big"))
    uc.reg_write(UC_M68K_REG_A7, sp)
    uc.mem_write(SENT, b"\x4e\x71")
    uc.emu_start(entry, SENT, count=20000)
    stored = uc.mem_read(trac + 0x59 + 32 * step + param, 1)[0] == 0xff
    kept = bool(uc.mem_read(trac + 0x10 + byte, 1)[0] & bit)
    want_regs = dict(regs); want_regs[D[0]] = 0x1000 + 32 * step
    regs_ok = all(uc.reg_read(r) == v for r, v in want_regs.items()) and uc.reg_read(UC_M68K_REG_A7) == sp + 4
    return entry, kept, stored, regs_ok


def main():
    m = json.loads((IMG.parent / "kyoti_v1.8bc_map.json").read_text()) if (IMG.parent / "kyoti_v1.8bc_map.json").exists() else {}
    want_entry = int(m["pieces"]["patch_triglock_bp"]["at"], 16) if m else None
    last = [0xff] * 32
    last[1] = 0x40                                          # one CUT lock: the row's last
    two = list(last); two[2] = 0x30                         # and a RES lock as well
    cases = [("Flex track, its last lock erased", 1, b"\0\0\0", last, 1, False),
             ("BLKPYRAMD track, its last lock erased", 1, b"OT\x01", last, 1, True),
             ("Static track, stale 'OT',1 signature", 0, b"OT\x01", last, 1, False),
             ("BLKPYRAMD track, another lock still there", 1, b"OT\x01", two, 1, True),
             ("Flex track, a never-locked param erased", 1, b"\0\0\0", last, 5, True)]
    ok = True
    for name, machine, sig, row, param, want_kept in cases:
        entry, kept, stored, regs_ok = run(name, machine, sig, row, param)
        good = kept == want_kept and stored and regs_ok and (want_entry is None or entry == want_entry)
        ok &= good
        print(f"  {name:44s} trigless lock {'kept   ' if kept else 'cleared'} (want {'kept' if want_kept else 'cleared'}); "
              f"store done {stored}; registers {regs_ok}; entry 0x{entry:08x}: {'ok' if good else 'WRONG'}")
    print("ALL GOOD" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

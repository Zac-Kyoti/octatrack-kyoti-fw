#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Exercise the v3-only DIRECT JUMP overlay (built by build_directjump_v3.py, --defsym DJ_V3).

  dj_toggle @0x4005e4c8   [PTN]+[YES] combo.  Same toggle logic as v1/v2; the only
                          difference is the confirmation call:
                              FUN_4005a2b8(text, dur)   -- the OS self-timing toast
                          Checks: OFF<->ON flips DJ_MODE + shadow + re-checksum, calls
                          NOTIFY once with the right string pointer and dur, sets
                          PTN_USED, swallows YES; and that neither v1's SHOW_MSG
                          (0x40059f8c) nor v2's POPUP2 (0x4005a0e0) is ever reached.
                          Guards: PTN not held / release / arranger / popup -> stock.

  dj_a / dj_b / dj_c are byte-identical to v1 -- this script asserts that and defers
  to tools/emu_directjump.py (run after build_directjump.py) for their behaviour.

Run after:  python3 tools/build_directjump.py  &&  python3 tools/build_directjump_v3.py
Usage:      python3 tools/emu_directjump_v3.py
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
_bin = ROOT / "out/patch_directjump_v3.bin"
_elf = ROOT / "out/patch_directjump_v3.elf"
if not _bin.exists():
    sys.exit(f"missing {_bin.name} -- run: python3 tools/build_directjump_v3.py")
STUB = _bin.read_bytes()
LOAD = 0x400d7400
_nm = subprocess.run(["m68k-elf-nm", str(_elf)], capture_output=True, text=True).stdout
SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
DJ_TOGGLE = SYM["dj_toggle"]
DJ_MSG_ON, DJ_MSG_OFF = SYM["dj_msg_on"], SYM["dj_msg_off"]

CKSUM = 0x4001f23c
NOTIFY = 0x4005a2b8          # FUN_4005a2b8(text, dur) -- v3's overlay
SHOW_MSG = 0x40059f8c        # v1's -- must NOT be reached
POPUP2 = 0x4005a0e0          # v2's -- must NOT be reached
YES_RESUME = 0x4005e4d0
TOAST_DUR = 0x44             # build_directjump_v3.py default

DJ_MODE = 0x800000d8
SH_DJ = 0x100fff68
PTN_MODE = 0x460d1742
PTN_USED = 0x460d173e
POPUP = 0x460e5cd0
ARR_ACT = 0x460d1aec

fails = []


def check(name, cond, detail=""):
    print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(LOAD, STUB)
    for a in (CKSUM, NOTIFY, SHOW_MSG, POPUP2):
        uc.mem_write(a, b"\x4e\x75")           # rts -- record the call, return
    return uc


def run_toggle(event, ptn_mode, arr=0, popup=0, dj_mode=0, sh=0xdead):
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", dj_mode))
    uc.mem_write(SH_DJ, struct.pack(">I", sh))
    uc.mem_write(PTN_MODE, struct.pack(">I", ptn_mode))
    uc.mem_write(PTN_USED, struct.pack(">I", 0))
    uc.mem_write(ARR_ACT, struct.pack(">I", arr))
    uc.mem_write(POPUP, struct.pack(">I", popup))
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", 0xCAFE, 0x31, event))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = {"cksum": False, "notify": None, "notify_dur": None,
          "show_msg": False, "popup2": False, "yes_resume": False}

    def hook(uc, addr, size, u):
        if addr == CKSUM:
            st["cksum"] = True
        elif addr == NOTIFY:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["notify"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            st["notify_dur"] = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
        elif addr == SHOW_MSG:
            st["show_msg"] = True
        elif addr == POPUP2:
            st["popup2"] = True
        elif addr == YES_RESUME:
            st["yes_resume"] = True
            uc.emu_stop()
        elif addr == 0xCAFE:
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(DJ_TOGGLE, 0, count=20000)
    except UcError:
        pass
    uc.hook_del(h)
    st["dj_mode"] = struct.unpack(">I", uc.mem_read(DJ_MODE, 4))[0]
    st["sh"] = struct.unpack(">I", uc.mem_read(SH_DJ, 4))[0]
    st["ptn_used"] = struct.unpack(">I", uc.mem_read(PTN_USED, 4))[0]
    return st


def test_toggle_v3():
    print("dj_toggle  (v3 overlay = FUN_4005a2b8) ------------------------")

    r = run_toggle(event=1, ptn_mode=1, dj_mode=0)
    check("OFF->ON: DJ_MODE = 1", r["dj_mode"] == 1)
    check("OFF->ON: shadow = 1", r["sh"] == 1)
    check("OFF->ON: re-checksum called", r["cksum"])
    check("OFF->ON: NOTIFY( \"DIRECT JUMP ON\" )", r["notify"] == DJ_MSG_ON,
          f"got 0x{(r['notify'] or 0):08x} want 0x{DJ_MSG_ON:08x}")
    check("OFF->ON: NOTIFY dur = 0x44", r["notify_dur"] == TOAST_DUR, hex(r["notify_dur"] or 0))
    check("OFF->ON: PTN_USED set", r["ptn_used"] == 1)
    check("OFF->ON: v1 SHOW_MSG not reached", not r["show_msg"])
    check("OFF->ON: v2 POPUP2 not reached", not r["popup2"])
    check("OFF->ON: YES swallowed (no stock resume)", not r["yes_resume"])

    r = run_toggle(event=1, ptn_mode=1, dj_mode=1)
    check("ON->OFF: DJ_MODE = 0", r["dj_mode"] == 0)
    check("ON->OFF: shadow = 0", r["sh"] == 0)
    check("ON->OFF: NOTIFY( \"DIRECT JUMP OFF\" )", r["notify"] == DJ_MSG_OFF,
          f"got 0x{(r['notify'] or 0):08x} want 0x{DJ_MSG_OFF:08x}")

    r = run_toggle(event=1, ptn_mode=0)
    check("[PTN] not held -> stock resume, no toggle",
          r["yes_resume"] and r["dj_mode"] == 0 and r["notify"] is None)

    r = run_toggle(event=0, ptn_mode=1)
    check("release event -> stock resume", r["yes_resume"] and r["notify"] is None)

    r = run_toggle(event=1, ptn_mode=1, arr=1)
    check("arranger up -> stock resume", r["yes_resume"] and r["notify"] is None)

    r = run_toggle(event=1, ptn_mode=1, popup=1)
    check("modal popup up -> stock resume", r["yes_resume"] and r["notify"] is None)


def test_abc_identical_to_v1():
    print("dj_a / dj_b / dj_c  (must be byte-identical to v1) ------------")
    v1 = ROOT / "out/patch_directjump.bin"
    if not v1.exists():
        check("v1 stub present for comparison", False, "run build_directjump.py first")
        return
    v1nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_directjump.elf")],
                          capture_output=True, text=True).stdout
    v1s = {p[2]: int(p[0], 16) for p in (l.split() for l in v1nm.splitlines()) if len(p) == 3}
    v1b = v1.read_bytes()
    for sym, end in (("dj_a", "dj_b"), ("dj_b", "dj_c")):
        a1, b1 = v1s[sym] - LOAD, v1s[end] - LOAD
        a3, b3 = SYM[sym] - LOAD, SYM[end] - LOAD
        check(f"{sym} bytes == v1", v1b[a1:b1] == STUB[a3:b3],
              f"v3 len {b3-a3} / v1 len {b1-a1}")
    # dj_c runs to the end of .text in both
    check("dj_c bytes == v1",
          v1b[v1s["dj_c"] - LOAD:] == STUB[SYM["dj_c"] - LOAD:])


if __name__ == "__main__":
    test_toggle_v3()
    test_abc_identical_to_v1()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

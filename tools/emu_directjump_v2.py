#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Exercise the v2-only DIRECT JUMP stubs (built by build_directjump_v2.py, --defsym DJ_V2):

  dj_tick2 @0x400522ca   the toast frame countdown, spliced into the engine
                         per-control-frame handler.  Checks: G_TOAST==0 is inert;
                         G_TOAST>1 just decrements; G_TOAST==1 -> FUN_40056bc0 (close
                         the FUN_4005a0e0 popup); the displaced `lea 0x46c7dfba,%a2`
                         is replayed (a2 correct on return); d2-d7/a2..a6 preserved
                         across the close call.

  dj_toggle v2 path      [PTN]+[YES] press -> FUN_4005a0e0(text) (NOT FUN_40059f8c),
                         G_TOAST := TOAST_FRAMES, DJ_MODE flipped + shadow + re-checksum
                         + PTN chooser suppressed + YES swallowed.

The dj_a/b/c hooks are unchanged from v1 -- tools/emu_directjump.py covers them
(run it after build_directjump.py; run THIS after build_directjump_v2.py).
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
_bin = ROOT / "out/patch_directjump_v2.bin"       # written by build_directjump_v2.py
_elf = ROOT / "out/patch_directjump_v2.elf"
if not _bin.exists():
    sys.exit(f"missing {_bin.name} -- run: python3 tools/build_directjump_v2.py")
STUB = _bin.read_bytes()
LOAD = 0x400d7400
_nm = subprocess.run(["m68k-elf-nm", str(_elf)], capture_output=True, text=True).stdout
SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
if "dj_tick2" not in SYM:
    sys.exit("dj_tick2 not in the v2 stub -- rebuild with build_directjump_v2.py")
DJ_TICK2, DJ_TOGGLE = SYM["dj_tick2"], SYM["dj_toggle"]
DJ_MSG_ON, DJ_MSG_OFF = SYM["dj_msg_on"], SYM["dj_msg_off"]

POPUP2 = 0x4005a0e0
CLOSE_CB = 0x40056bc0
SHOW_MSG = 0x40059f8c        # v1's -- must NOT be reached by v2
CKSUM = 0x4001f23c
YES_RESUME = 0x4005e4d0
WATCHDOG = 0x46c7dfba        # dj_tick2's displaced `lea 0x46c7dfba,%a2`
G_TOAST = 0x80006a44
DJ_MODE = 0x800000d8
SH_DJ = 0x100fff68
PTN_MODE = 0x460d1742
PTN_USED = 0x460d173e
POPUP = 0x460e5cd0
ARR_ACT = 0x460d1aec
TOAST_FRAMES_DEFAULT = 0xC0

SEED = {UC_M68K_REG_D2: 0x0a0a0a0a, UC_M68K_REG_D3: 0x0b0b0b0b,
        UC_M68K_REG_D4: 0x0c0c0c0c, UC_M68K_REG_D5: 0x0d0d0d0d,
        UC_M68K_REG_D6: 0x0e0e0e0e, UC_M68K_REG_D7: 0x0f0f0f0f,
        UC_M68K_REG_A2: 0x46a2a2a2, UC_M68K_REG_A3: 0x46a3a3a3,
        UC_M68K_REG_A4: 0x46a4a4a4, UC_M68K_REG_A5: 0x46a5a5a5,
        UC_M68K_REG_A6: 0x46a6a6a6}

fails = []


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
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
    for a in (CKSUM, SHOW_MSG, POPUP2, CLOSE_CB):
        uc.mem_write(a, b"\x4e\x75")            # each OS routine -> bare rts
    return uc


# ---------------------------------------------------------------- dj_tick2
def run_tick(g_toast, close_clobbers=False):
    uc = mk()
    uc.mem_write(G_TOAST, struct.pack(">I", g_toast))
    ret = 0x41000200          # a mapped, code-less address -> the code hook stops us
    sp0 = 0x41018000
    uc.mem_write(sp0, struct.pack(">I", ret))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for r, v in SEED.items():
        uc.reg_write(r, v)
    st = {"close": 0, "at": None}

    def hook(uc, addr, size, u):
        if addr == CLOSE_CB:
            st["close"] += 1
            if close_clobbers:                 # kernel post clobbers d0-d1/a0-a1
                for r in (UC_M68K_REG_D0, UC_M68K_REG_D1,
                          UC_M68K_REG_A0, UC_M68K_REG_A1):
                    uc.reg_write(r, 0xdeadbeef)
        elif addr == ret:
            st["at"] = addr
            st["a2"] = uc.reg_read(UC_M68K_REG_A2)
            st["regs"] = {r: uc.reg_read(r) for r in SEED}
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(DJ_TICK2, 0, count=20000)
    except UcError as e:
        st["err"] = str(e)
    uc.hook_del(h)
    st["g_toast"] = struct.unpack(">I", uc.mem_read(G_TOAST, 4))[0]
    return st


# a2 is legitimately overwritten by the displaced `lea 0x46c7dfba,%a2` -- check the rest
KEEP = {r: v for r, v in SEED.items() if r != UC_M68K_REG_A2}


def test_tick():
    print("dj_tick2  (toast frame countdown) -----------------------------")

    t = run_tick(0)
    check("G_TOAST=0: returns to caller", t["at"] is not None)
    check("G_TOAST=0: stays 0", t["g_toast"] == 0)
    check("G_TOAST=0: no close", t["close"] == 0)
    check("G_TOAST=0: a2 = 0x46c7dfba (displaced lea)", t.get("a2") == WATCHDOG,
          hex(t.get("a2", 0)))
    check("G_TOAST=0: d2-d7/a3..a6 preserved",
          all(t["regs"][r] == v for r, v in KEEP.items()))

    t = run_tick(5)
    check("G_TOAST=5: -> 4", t["g_toast"] == 4)
    check("G_TOAST=5: no close", t["close"] == 0)
    check("G_TOAST=5: a2 correct", t.get("a2") == WATCHDOG)

    t = run_tick(1)
    check("G_TOAST=1: -> 0", t["g_toast"] == 0)
    check("G_TOAST=1: close called once", t["close"] == 1)
    check("G_TOAST=1: a2 correct after close", t.get("a2") == WATCHDOG)

    t = run_tick(1, close_clobbers=True)
    check("close clobbers d0-d1/a0-a1: d2-d7/a3..a6 still preserved",
          all(t["regs"][r] == v for r, v in KEEP.items()), str(t["regs"]))
    check("close clobbers: a2 restored to 0x46c7dfba", t.get("a2") == WATCHDOG)

    # stale/negative G_TOAST is treated as inert (ble guard)
    t = run_tick(0xFFFFFFFF)
    check("G_TOAST < 0: inert, no close", t["close"] == 0 and t.get("a2") == WATCHDOG)


# ---------------------------------------------------------------- dj_toggle v2
def run_toggle(event, ptn_mode, dj_mode=0, arr=0, popup=0):
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", dj_mode))
    uc.mem_write(SH_DJ, struct.pack(">I", 0xdead))
    uc.mem_write(PTN_MODE, struct.pack(">I", ptn_mode))
    uc.mem_write(PTN_USED, struct.pack(">I", 0))
    uc.mem_write(ARR_ACT, struct.pack(">I", arr))
    uc.mem_write(POPUP, struct.pack(">I", popup))
    uc.mem_write(G_TOAST, struct.pack(">I", 0))
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", 0xCAFE, 0x31, event))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = {"cksum": False, "popup2": None, "show_msg": False, "yes_resume": False}

    def hook(uc, addr, size, u):
        if addr == CKSUM:
            st["cksum"] = True
        elif addr == POPUP2:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["popup2"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
        elif addr == SHOW_MSG:
            st["show_msg"] = True
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
    return (struct.unpack(">I", uc.mem_read(DJ_MODE, 4))[0],
            struct.unpack(">I", uc.mem_read(SH_DJ, 4))[0],
            st["cksum"], st["popup2"], st["show_msg"],
            struct.unpack(">I", uc.mem_read(PTN_USED, 4))[0],
            struct.unpack(">I", uc.mem_read(G_TOAST, 4))[0],
            st["yes_resume"])


def test_toggle_v2():
    print("dj_toggle v2  ([PTN] + [YES], box-free toast) -----------------")

    dj, sh, ck, p2, sm, used, toast, resume = run_toggle(event=1, ptn_mode=1, dj_mode=0)
    check("OFF->ON: DJ_MODE = 1", dj == 1)
    check("OFF->ON: shadow = 1", sh == 1)
    check("OFF->ON: re-checksummed", ck)
    check("OFF->ON: FUN_4005a0e0('DIRECT JUMP ON')", p2 == DJ_MSG_ON, hex(p2 or 0))
    check("OFF->ON: FUN_40059f8c NOT called (no boxes)", not sm)
    check("OFF->ON: G_TOAST = TOAST_FRAMES", toast == TOAST_FRAMES_DEFAULT, hex(toast))
    check("OFF->ON: PTN chooser suppressed", used == 1)
    check("OFF->ON: YES swallowed", not resume)

    dj, sh, ck, p2, sm, used, toast, resume = run_toggle(event=1, ptn_mode=1, dj_mode=1)
    check("ON->OFF: DJ_MODE = 0", dj == 0)
    check("ON->OFF: FUN_4005a0e0('DIRECT JUMP OFF')", p2 == DJ_MSG_OFF, hex(p2 or 0))
    check("ON->OFF: G_TOAST re-armed", toast == TOAST_FRAMES_DEFAULT)

    dj, sh, ck, p2, sm, used, toast, resume = run_toggle(event=1, ptn_mode=0, dj_mode=0)
    check("no PTN: stock YES, no toggle, no popup", resume and dj == 0 and p2 is None)

    _, _, ck, p2, sm, _, toast, resume = run_toggle(event=0, ptn_mode=1, dj_mode=0)
    check("release: stock path, no popup, no toast", resume and p2 is None and toast == 0)

    dj, _, _, _, _, _, _, resume = run_toggle(event=1, ptn_mode=1, arr=1, dj_mode=0)
    check("arranger: stock path", dj == 0 and resume)

    dj, _, _, _, _, _, _, resume = run_toggle(event=1, ptn_mode=1, popup=1, dj_mode=0)
    check("modal popup: stock path", dj == 0 and resume)


test_tick()
test_toggle_v2()
print()
if fails:
    print(f"{len(fails)} FAIL: " + ", ".join(fails))
    sys.exit(1)
print("ALL GOOD")

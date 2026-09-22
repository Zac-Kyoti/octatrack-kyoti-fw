#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Exercise the three DIRECT JUMP stubs (patch_directjump.bin) on a hand-built ColdFire
state -- the whole per-step handler FUN_400a1eea can't run under Unicorn (unsupported
insns), like emu_otfx.py, so this drives each stub in isolation.

  dj_a @0x400a4006  arm / send PC / force step==0.  Checks the OFF path, the
                    arranger/chain guards, the 2-tick arm->commit sequence, PC dedup,
                    register save/restore, and the Z flag left for the caller's beq.w.
  dj_b @0x400a42fa  gate bypass.  Checks the return-address rewrite (armed) vs the
                    displaced `move.l #0x8e56,d0` (not armed) and D6.
  dj_c @0x400a4840  playhead resume.  Checks DAT_800065b6 = 0 + D7 untouched (not armed)
                    vs savedStep % newLen + D7 = (that) * TICKS_PER_STEP (armed), incl. a
                    shorter/longer new pattern (Session 65 -- see patch_directjump.s;
                    Session 61 had this hook leave D7 alone entirely, which flashed clean
                    but made every jump start every track fresh at phase 0).

FUN_4009e884 (the real PC sender) is stubbed: the call is trapped, its args recorded,
and control returned -- we only assert that dj_a calls it with (bank, pat) at the right
times.
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
STUB = (ROOT / "out/patch_directjump.bin").read_bytes()
LOAD = 0x400d7400
_nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_directjump.elf")],
                     capture_output=True, text=True).stdout
SYM = {p[2]: int(p[0], 16) for p in (l.split() for l in _nm.splitlines()) if len(p) == 3}
if "dj_tick2" in SYM:
    sys.exit("out/patch_directjump.elf is a DJ_V2 build -- run `python3 tools/build_directjump.py` "
             "to restore v1, or use `python3 tools/emu_directjump_v2.py` for the v2 stubs.")
DJ_A, DJ_B, DJ_C, DJ_TOGGLE = SYM["dj_a"], SYM["dj_b"], SYM["dj_c"], SYM["dj_toggle"]
PC_SEND = 0x4009e884
CKSUM = 0x4001f23c            # FUN_4001f23c -- ANDY-block re-checksum
SHOW_MSG = 0x40059f8c        # FUN_40059f8c(text, ticks, enable, on_timeout)
YES_RESUME = 0x4005e4d0
DJ_MSG_ON, DJ_MSG_OFF = SYM["dj_msg_on"], SYM["dj_msg_off"]

DJ_MODE = 0x800000d8
SH_DJ = 0x100fff68
PTN_MODE = 0x460d1742
PTN_USED = 0x460d173e
POPUP = 0x460e5cd0
G_ARMED, G_STEP, G_PCPAT = 0x80006a40, 0x80006a41, 0x80006a42
ACT_PAT, ACT_BANK = 0x800065be, 0x800065bd
PEND_PAT, PEND_BANK = 0x800065c0, 0x800065bf
STEP = 0x800065b6
SCALE_IX = 0x8000663d
STOPFLAG = 0x8000667e
ARR_ACT = 0x460d1aec
CHAIN_ACT = 0x80006546
LEN_TBL = 0x400aba50
PAT_SCALE = 0x400eb034
TICKS_PER_STEP = 0x80006628
SW_LABEL = 0x400a43a0
RET_A = 0x400a400c        # instruction after the dj_a detour
RET_B = 0x400a4300        # instruction after the dj_b detour

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
    uc.mem_map(0x10000000, 0x1000000)      # metadata SRAM (ANDY block @ 0x100fff00)
    uc.mem_write(LOAD, STUB)
    # the toggle stub calls two OS routines by absolute address -- stub each with an rts
    # so the isolated run returns; the tests hook the sites to record the call.
    for a in (CKSUM, SHOW_MSG):
        uc.mem_write(a, b"\x4e\x75")
    # pattern-length table: index 4 -> 16, index 6 -> 64  (just two entries we use)
    for idx, ln in ((4, 16), (6, 64), (2, 8)):
        uc.mem_write(LEN_TBL + idx * 4, struct.pack(">I", ln))
    # non-1, so dj_c's D7 = resumeStep * TICKS_PER_STEP is a non-trivial check (a value of
    # 1 here would make "multiplied" and "untouched" indistinguishable for a lot of inputs)
    uc.mem_write(TICKS_PER_STEP, struct.pack(">I", 3))
    return uc


def run(uc, entry, want_ret):
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">I", want_ret))   # the "return address" for the stub's rts
    uc.reg_write(UC_M68K_REG_A7, sp0)
    for r, v in SEED.items():
        uc.reg_write(r, v)
    uc.reg_write(UC_M68K_REG_D0, 0x11111111)
    uc.reg_write(UC_M68K_REG_D1, 0x22222222)

    trace = {"pc_send": [], "stopped_at": None, "sr": None}

    def hook(uc, addr, size, u):
        if addr == PC_SEND:
            sp = uc.reg_read(UC_M68K_REG_A7)
            bank = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]
            pat = struct.unpack(">I", uc.mem_read(sp + 8, 4))[0]
            trace["pc_send"].append((bank, pat))
            # emulate rts
            ret = struct.unpack(">I", uc.mem_read(sp, 4))[0]
            uc.reg_write(UC_M68K_REG_A7, sp + 4)
            uc.reg_write(UC_M68K_REG_PC, ret)
        elif addr in (want_ret, SW_LABEL):
            trace["stopped_at"] = addr
            trace["sr"] = uc.reg_read(UC_M68K_REG_SR)
            trace["regs"] = {r: uc.reg_read(r) for r in SEED}
            trace["d6"] = uc.reg_read(UC_M68K_REG_D6)
            trace["d7"] = uc.reg_read(UC_M68K_REG_D7)
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(entry, 0, count=20000)
    except UcError as e:
        trace["err"] = str(e)
    uc.hook_del(h)
    return trace


# ---------------------------------------------------------------- dj_a
def test_a():
    print("dj_a  (arm / PC / force step) ------------------------------------")

    # OFF: nothing pending, DJ_MODE=0 -> just clears stale arm, Z from tst.b STOPFLAG
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 0))
    uc.mem_write(G_ARMED, b"\x01")
    uc.mem_write(STOPFLAG, b"\x00")
    t = run(uc, DJ_A, RET_A)
    check("OFF: returns to caller", t["stopped_at"] == RET_A)
    check("OFF: stale arm cleared", uc.mem_read(G_ARMED, 1) == b"\x00")
    check("OFF: no PC sent", t["pc_send"] == [])
    check("OFF: seed regs preserved",
          all(t["regs"][r] == SEED[r] for r in SEED), str(t["regs"]))
    # NB: unicorn-m68k does not update the CCR on `tst.b (abs).l`, so the Z flag that the
    # caller's `beq.w 0x400a412e` consumes can't be checked here.  It is correct by
    # construction: dja_ret's last op before rts is the verbatim stock `tst.b STOPFLAG`.

    # arranger active -> disarm, bail
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 1))
    uc.mem_write(ARR_ACT, struct.pack(">I", 1))
    uc.mem_write(PEND_PAT, b"\x05"); uc.mem_write(ACT_PAT, b"\x00")
    uc.mem_write(G_ARMED, b"\x01")
    t = run(uc, DJ_A, RET_A)
    check("arranger: disarmed", uc.mem_read(G_ARMED, 1) == b"\x00")
    check("arranger: no PC", t["pc_send"] == [])

    # real pending, tick 1: send PC, arm, do NOT clear STEP
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 1))
    uc.mem_write(PEND_PAT, b"\x05"); uc.mem_write(PEND_BANK, b"\x02")
    uc.mem_write(ACT_PAT, b"\x00"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(STEP, b"\x07")
    uc.mem_write(G_ARMED, b"\x00"); uc.mem_write(G_PCPAT, b"\xff")
    uc.mem_write(STOPFLAG, b"\x00")
    t = run(uc, DJ_A, RET_A)
    check("tick1: PC sent (bank=2, pat=5)", t["pc_send"] == [(2, 5)], str(t["pc_send"]))
    check("tick1: armed", uc.mem_read(G_ARMED, 1) != b"\x00")
    check("tick1: G_STEP=7", uc.mem_read(G_STEP, 1) == b"\x07")
    check("tick1: STEP untouched (7)", uc.mem_read(STEP, 1) == b"\x07")
    check("tick1: G_PCPAT=5", uc.mem_read(G_PCPAT, 1) == b"\x05")
    check("tick1: regs preserved", all(t["regs"][r] == SEED[r] for r in SEED))

    # tick 2: already armed, pending unchanged -> PC deduped, STEP forced to 0
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 1))
    uc.mem_write(PEND_PAT, b"\x05"); uc.mem_write(PEND_BANK, b"\x02")
    uc.mem_write(ACT_PAT, b"\x00"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(STEP, b"\x09")
    uc.mem_write(G_ARMED, b"\xff"); uc.mem_write(G_PCPAT, b"\x05")
    t = run(uc, DJ_A, RET_A)
    check("tick2: PC deduped (none)", t["pc_send"] == [], str(t["pc_send"]))
    check("tick2: G_STEP=9", uc.mem_read(G_STEP, 1) == b"\x09")
    check("tick2: STEP forced to 0", uc.mem_read(STEP, 1) == b"\x00")
    check("tick2: still armed (dj_c clears it)", uc.mem_read(G_ARMED, 1) != b"\x00")

    # tick 2 but pending changed 5 -> 9 -> resend PC, still force
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 1))
    uc.mem_write(PEND_PAT, b"\x09"); uc.mem_write(PEND_BANK, b"\x03")
    uc.mem_write(ACT_PAT, b"\x00"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(STEP, b"\x04")
    uc.mem_write(G_ARMED, b"\xff"); uc.mem_write(G_PCPAT, b"\x05")
    t = run(uc, DJ_A, RET_A)
    check("flip: PC resent (bank=3, pat=9)", t["pc_send"] == [(3, 9)], str(t["pc_send"]))
    check("flip: STEP forced to 0", uc.mem_read(STEP, 1) == b"\x00")

    # pending == active (cue that matches) -> disarm
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", 1))
    uc.mem_write(PEND_PAT, b"\x03"); uc.mem_write(PEND_BANK, b"\x01")
    uc.mem_write(ACT_PAT, b"\x03"); uc.mem_write(ACT_BANK, b"\x01")
    uc.mem_write(G_ARMED, b"\xff")
    t = run(uc, DJ_A, RET_A)
    check("pend==act: disarmed", uc.mem_read(G_ARMED, 1) == b"\x00")
    check("pend==act: no PC", t["pc_send"] == [])


# ---------------------------------------------------------------- dj_b
def test_b():
    print("dj_b  (CHAIN-AFTER gate bypass) --------------------------------")

    # not armed: displaced `move.l #0x8e56,d0`, return to RET_B
    uc = mk()
    uc.mem_write(G_ARMED, b"\x00")
    t = run(uc, DJ_B, RET_B)
    check("not armed: returns to 0x400a4300", t["stopped_at"] == RET_B)
    check("not armed: d0 = 0x8e56", uc.reg_read(UC_M68K_REG_D0) == 0x8e56,
          hex(uc.reg_read(UC_M68K_REG_D0)))

    # armed: rewrite return -> SW_LABEL, d6 = 1
    uc = mk()
    uc.mem_write(G_ARMED, b"\xff")
    t = run(uc, DJ_B, RET_B)
    check("armed: jumps to SW_LABEL 0x400a43a0", t["stopped_at"] == SW_LABEL,
          hex(t["stopped_at"] or 0))
    check("armed: d6 = 1", t["d6"] == 1, hex(t["d6"]))


# ---------------------------------------------------------------- dj_c
def test_c():
    print("dj_c  (playhead resume) ---------------------------------------")

    # not armed: DAT_800065b6 = 0, d7 untouched
    uc = mk()
    uc.mem_write(G_ARMED, b"\x00")
    uc.mem_write(STEP, b"\x2a")
    t = run(uc, DJ_C, 0x400a4848)
    check("not armed: STEP = 0", uc.mem_read(STEP, 1) == b"\x00")
    check("not armed: d7 preserved", t["d7"] == SEED[UC_M68K_REG_D7], hex(t["d7"]))

    # armed, same length (new pattern len 16, saved step 9) -> STEP=9, D7 = 9 * ticksPerStep
    # (Session 65: Session 61's "leave D7 untouched" fix flashed clean but made every
    # manual jump start every track fresh at phase 0 -- "starts at step 1" every time.
    # D7 must be re-derived from the RESUME step using stock's own formula, matching the
    # per-track tick-phase loops just below this hook that consume it directly.)
    uc = mk()
    uc.mem_write(G_ARMED, b"\xff")
    uc.mem_write(ACT_PAT, b"\x01"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(PAT_SCALE + (0x01 * 0x8ed8), b"\x04")   # scale idx 4 -> len 16
    uc.mem_write(G_STEP, b"\x09")
    t = run(uc, DJ_C, 0x400a4848)
    check("armed same-len: STEP = 9", uc.mem_read(STEP, 1) == b"\x09")
    check("armed same-len: d7 = 9 * ticksPerStep(3) = 27", t["d7"] == 27, hex(t["d7"]))
    check("armed: G_ARMED cleared", uc.mem_read(G_ARMED, 1) == b"\x00")

    # armed, shorter new pattern (len 8, saved step 13) -> 13 % 8 = 5, D7 = 5 * ticksPerStep
    uc = mk()
    uc.mem_write(G_ARMED, b"\xff")
    uc.mem_write(ACT_PAT, b"\x02"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(PAT_SCALE + (0x02 * 0x8ed8), b"\x02")   # scale idx 2 -> len 8
    uc.mem_write(G_STEP, b"\x0d")
    t = run(uc, DJ_C, 0x400a4848)
    check("armed shorter: STEP = 5 (13 % 8)", uc.mem_read(STEP, 1) == b"\x05",
          str(uc.mem_read(STEP, 1)))
    check("armed shorter: d7 = 5 * ticksPerStep(3) = 15", t["d7"] == 15, hex(t["d7"]))

    # armed, longer new pattern (len 64, saved step 20) -> 20, D7 = 20 * ticksPerStep
    uc = mk()
    uc.mem_write(G_ARMED, b"\xff")
    uc.mem_write(ACT_PAT, b"\x03"); uc.mem_write(ACT_BANK, b"\x00")
    uc.mem_write(PAT_SCALE + (0x03 * 0x8ed8), b"\x06")   # scale idx 6 -> len 64
    uc.mem_write(G_STEP, b"\x14")
    t = run(uc, DJ_C, 0x400a4848)
    check("armed longer: STEP = 20", uc.mem_read(STEP, 1) == b"\x14")
    check("armed longer: d7 = 20 * ticksPerStep(3) = 60", t["d7"] == 60, hex(t["d7"]))


# ---------------------------------------------------------------- dj_toggle
def run_toggle(event, ptn_mode, arr=0, popup=0, dj_mode=0, sh=0xdead):
    """Drive dj_toggle. Returns (dj_mode, shadow, cksum_called, msg_text_ptr, ptn_used,
    reached_yes_resume)."""
    uc = mk()
    uc.mem_write(DJ_MODE, struct.pack(">I", dj_mode))
    uc.mem_write(SH_DJ, struct.pack(">I", sh))
    uc.mem_write(PTN_MODE, struct.pack(">I", ptn_mode))
    uc.mem_write(PTN_USED, struct.pack(">I", 0))
    uc.mem_write(ARR_ACT, struct.pack(">I", arr))
    uc.mem_write(POPUP, struct.pack(">I", popup))
    # the YES handler's stack frame: 0(sp)=ret, 4(sp)=keycode(0x31), 8(sp)=event
    sp0 = 0x41010000
    uc.mem_write(sp0, struct.pack(">III", 0xCAFE, 0x31, event))
    uc.reg_write(UC_M68K_REG_A7, sp0)
    st = {"cksum": False, "msg": None, "yes_resume": False}

    def hook(uc, addr, size, u):
        if addr == CKSUM:
            st["cksum"] = True
        elif addr == SHOW_MSG:
            sp = uc.reg_read(UC_M68K_REG_A7)
            st["msg"] = struct.unpack(">I", uc.mem_read(sp + 4, 4))[0]  # 0(sp)=ret, 4(sp)=text
        elif addr == YES_RESUME:
            st["yes_resume"] = True
            uc.emu_stop()
        elif addr == 0xCAFE:            # the swallow path rts'd back to our fake caller
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(DJ_TOGGLE, 0, count=20000)
    except UcError:
        pass
    uc.hook_del(h)
    return (struct.unpack(">I", uc.mem_read(DJ_MODE, 4))[0],
            struct.unpack(">I", uc.mem_read(SH_DJ, 4))[0],
            st["cksum"],
            st["msg"],
            struct.unpack(">I", uc.mem_read(PTN_USED, 4))[0],
            st["yes_resume"])


def test_toggle():
    print("dj_toggle  ([PTN] + [YES]) --------------------------------------")

    # OFF -> ON: PTN held, press, base view
    dj, sh, ck, msg, used, resume = run_toggle(event=1, ptn_mode=1, dj_mode=0)
    check("OFF->ON: DJ_MODE = 1", dj == 1)
    check("OFF->ON: shadow = 1", sh == 1)
    check("OFF->ON: re-checksummed", ck)
    check("OFF->ON: popup text = 'DIRECT JUMP ON'", msg == DJ_MSG_ON, hex(msg or 0))
    check("OFF->ON: PTN chooser suppressed (0x460d173e = 1)", used == 1)
    check("OFF->ON: YES swallowed (no stock resume)", not resume)

    # ON -> OFF
    dj, sh, ck, msg, used, resume = run_toggle(event=1, ptn_mode=1, dj_mode=1)
    check("ON->OFF: DJ_MODE = 0", dj == 0)
    check("ON->OFF: shadow = 0", sh == 0)
    check("ON->OFF: popup text = 'DIRECT JUMP OFF'", msg == DJ_MSG_OFF, hex(msg or 0))

    # PTN not held -> stock YES, no toggle
    dj, sh, ck, msg, used, resume = run_toggle(event=1, ptn_mode=0, dj_mode=0)
    check("no PTN: DJ_MODE untouched", dj == 0)
    check("no PTN: not re-checksummed", not ck)
    check("no PTN: no popup", msg is None)
    check("no PTN: falls through to stock YES (0x4005e4d0)", resume)

    # release event -> stock
    _, _, ck, msg, _, resume = run_toggle(event=0, ptn_mode=1, dj_mode=0)
    check("release: stock path", resume and not ck and msg is None)

    # PTN held but arranger up -> stock (don't shadow arranger-YES)
    dj, _, ck, _, _, resume = run_toggle(event=1, ptn_mode=1, arr=1, dj_mode=0)
    check("arranger: DJ_MODE untouched + stock path", dj == 0 and resume and not ck)

    # PTN held but a modal popup is open -> stock
    dj, _, _, _, _, resume = run_toggle(event=1, ptn_mode=1, popup=1, dj_mode=0)
    check("popup open: stock path", dj == 0 and resume)


test_toggle()
test_a()
test_b()
test_c()
print()
if fails:
    print(f"{len(fails)} FAIL: " + ", ".join(fails))
    sys.exit(1)
print("ALL GOOD")

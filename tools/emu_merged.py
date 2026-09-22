#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
emu_merged.py -- verify the combined image build_merged.py produces.

Two parts:

  STATIC  -- every feature's detour landed as the right branch into the relocated
             merged cave; the [YES] handler @ 0x4005e4c8 goes to RELOAD2's rl_yes
             (not DIRECT JUMP), and rl_yes's "not the picker" path is `jmp dj_toggle`
             (the MERGE=1 chaining), not the stock prologue replay.

  DYNAMIC -- drive the [YES] key at 0x4005e4c8 on the real merged bytes for the four
             cases that matter and confirm which owner handles it, by which OS
             routine the trampoline reaches first:
                CLOSE_CB  0x40056bc0  -> RELOAD2 picker  (rl_yes closes the window)
                CKSUM     0x4001f23c  -> DIRECT JUMP     (dj_toggle commits + re-checksums)
                YES_RESUME 0x4005e4d0 -> stock YES

               1. picker open            -> RELOAD2
               2. closed, [PTN] held     -> DIRECT JUMP
               3. closed, [PTN] not held -> stock
               4. key release (not press)-> stock

The rest of each feature keeps its own emu_*.py (run against its standalone image);
this only proves the *merge* -- relocation + the one shared handler.

Usage:  python3 tools/emu_merged.py
"""
import pathlib, struct, subprocess, sys
from unicorn import *
from unicorn.m68k_const import *

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = 0x40000400
IMGP = ROOT / "out/mainos_merged.bin"
if not IMGP.exists():
    sys.exit("run tools/build_merged.py first (out/mainos_merged.bin missing)")
IMG = IMGP.read_bytes()
STOCK = (ROOT / "out/raw/section_3_MAIN_OS.bin").read_bytes()


def nm(elf):
    r = subprocess.run(["m68k-elf-nm", str(ROOT / "out" / elf)], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in r.splitlines()) if len(p) == 3}


RLD = nm("merged_patch_reload2.elf")
DJ = nm("merged_patch_directjump.elf")
SM = nm("merged_patch_softmute.elf")
MM = nm("merged_patch_mutemode.elf")
TS = nm("merged_patch_trigscale.elf")
PL = nm("merged_patch_pattern_led.elf")
QL = nm("merged_patch_qlrec.elf")

CLOSE_CB = 0x40056bc0
CKSUM = 0x4001f23c
YES_RESUME = 0x4005e4d0
G_MENU = 0x80006a52
PTN_MODE_DJ = 0x460d1742
POPUP = 0x460e5cd0
ARR_ACT = 0x460d1aec

fails = []


def ck(name, cond, detail=""):
    print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------------------------ STATIC
def u32(a):
    return struct.unpack(">I", IMG[a - BASE:a - BASE + 4])[0]


def static_checks():
    print("STATIC -- detours + [YES] chaining")

    # trigscale (pinned, shared base)
    ck("0x4009b6f2 -> jmp patch_trigscale:cave",
       IMG[0x4009b6f2 - BASE:0x4009b6f2 - BASE + 2] == b"\x4e\xf9" and u32(0x4009b6f2 + 2) == TS["cave"],
       f"cave 0x{TS['cave']:08x}")

    # MUTE MODE
    for site, sym, tbl, nmn in ((0x40004dc6, "pre", SM, "softmute"),
                                (0x40005178, "pre_v", SM, "softmute")):
        ck(f"0x{site:08x} -> jmp {nmn}:{sym}",
           IMG[site - BASE:site - BASE + 2] == b"\x4e\xf9" and u32(site + 2) == tbl[sym],
           f"0x{tbl[sym]:08x}")

    # DIRECT JUMP -- three jsr sequencer hooks; dj_toggle NOT a detour
    for site, sym in ((0x400a4006, "dj_a"), (0x400a42fa, "dj_b"), (0x400a4840, "dj_c")):
        ck(f"0x{site:08x} -> jsr directjump:{sym}",
           IMG[site - BASE:site - BASE + 2] == b"\x4e\xb9" and u32(site + 2) == DJ[sym],
           f"0x{DJ[sym]:08x}")
    ck("dj_toggle is present but not wired to a detour",
       DJ["dj_toggle"] not in (u32(0x4005e4c8 + 2),))

    # RELOAD2 -- six jmp hooks incl. the single [YES]
    for site, sym in ((0x4005a044, "rl_ptn"), (0x4005e25c, "rl_no"), (0x4005e4c8, "rl_yes"),
                      (0x4004b970, "rl_arr_a"), (0x400491a0, "rl_arr_b"), (0x40085864, "rl_job")):
        ck(f"0x{site:08x} -> jmp reload2:{sym}",
           IMG[site - BASE:site - BASE + 2] == b"\x4e\xf9" and u32(site + 2) == RLD[sym],
           f"0x{RLD[sym]:08x}")

    ck("[YES] @ 0x4005e4c8 owned by RELOAD2 (rl_yes), not DIRECT JUMP",
       u32(0x4005e4c8 + 2) == RLD["rl_yes"])

    # pattern-LED fix -- one jmp detour at FUN_4009a464's prologue
    ck("0x4009a464 -> jmp pattern_led:cave",
       IMG[0x4009a464 - BASE:0x4009a464 - BASE + 2] == b"\x4e\xf9" and u32(0x4009a464 + 2) == PL["cave"],
       f"cave 0x{PL['cave']:08x}")
    ck("pattern_led cave ends `jmp 0x4009a46a` (falls into the stock trig scan)",
       (b"\x4e\xf9" + struct.pack(">I", 0x4009a46a)) in
       IMG[PL["cave"] - BASE:PL["cave"] - BASE + _elf_size("merged_patch_pattern_led.elf")])

    # QUANTIZE LIVE REC -- two jmp detours ([PLAY] press, [REC] release)
    for site, sym in ((0x40061778, "qlr_play"), (0x4004883a, "qlr_recrel")):
        ck(f"0x{site:08x} -> jmp qlrec:{sym}",
           IMG[site - BASE:site - BASE + 2] == b"\x4e\xf9" and u32(site + 2) == QL[sym],
           f"0x{QL[sym]:08x}")

    # rl_yes's not-the-picker exit is `jmp dj_toggle`  (MERGE chaining)
    # find the `jmp` (0x4ef9 <abs>) inside the rl_yes .. rl_arr_a span that targets dj_toggle
    lo, hi = RLD["rl_yes"] - BASE, RLD["rl_arr_a"] - BASE
    blob = IMG[lo:hi]
    tgt = struct.pack(">I", DJ["dj_toggle"])
    ck("rl_yes contains `jmp dj_toggle` (MERGE=1 chaining)",
       (b"\x4e\xf9" + tgt) in blob, f"dj_toggle 0x{DJ['dj_toggle']:08x}")
    ck("rl_yes does NOT jmp the stock YES_RESUME directly",
       (b"\x4e\xf9" + struct.pack(">I", YES_RESUME)) not in blob)

    # persistence pea 0x64 -> 0x70 (MUTE MODE + DIRECT JUMP, shared)
    for s in (0x4001f322, 0x4001f3be, 0x4001fb24):
        ck(f"restore 0x{s:08x}: pea 0x70",
           IMG[s - BASE:s - BASE + 4] == b"\x48\x78\x00\x70" and
           STOCK[s - BASE:s - BASE + 4] == b"\x48\x78\x00\x64")

    # menu count
    ck("PERSONALIZE count moveq #15 -> #16",
       IMG[0x40068fb2 - BASE:0x40068fb2 - BASE + 2] == b"\x72\x10")

    # SIDE-CHAIN COMPRESSOR descriptor: KEY name landed at slot 8
    E = 0x400d5a4a
    ck('COMPRESSOR slot 8 name == "KEY"',
       IMG[E + 0x4e + 6 * 8 - BASE:E + 0x4e + 6 * 8 - BASE + 3] == b"KEY")

    # caves disjoint + inside the free zone (independent of build_merged's own check)
    spans = sorted([(v, v + _elf_size(e)) for e, syms in
                    (("merged_patch_sidechain.elf", None),) for v in [_text_addr("merged_patch_sidechain.elf")]]
                   + [(_text_addr(e), _text_addr(e) + _elf_size(e)) for e in
                      ("merged_patch_softmute.elf", "merged_patch_mutemode.elf",
                       "merged_patch_directjump.elf", "merged_patch_reload2.elf",
                       "merged_patch_pattern_led.elf", "merged_patch_qlrec.elf",
                       "merged_patch_trigscale.elf")])
    overlap = any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1))
    ck("relocated caves are disjoint",
       not overlap, " ".join(f"0x{a:x}-0x{b:x}" for a, b in spans))
    ck("caves within 0x400d6500..0x400d7c3c",
       spans[0][0] >= 0x400d6500 and spans[-1][1] <= 0x400d7c3c)


def _text_addr(elf):
    r = subprocess.run(["m68k-elf-objdump", "-h", str(ROOT / "out" / elf)],
                       capture_output=True, text=True).stdout
    for l in r.splitlines():
        if " .text " in l:
            return int(l.split()[3], 16)
    sys.exit(f"no .text in {elf}")


def _elf_size(elf):
    p = ROOT / "out" / elf.replace(".elf", ".bin")
    return len(p.read_bytes())


# ------------------------------------------------------------------ DYNAMIC
def mk():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x40000000, 0x400000)
    uc.mem_map(0x46000000, 0x1000000)
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_map(0x41000000, 0x20000)
    uc.mem_map(0x10000000, 0x1000000)
    uc.mem_write(BASE, IMG)
    return uc


def yes_key(menu, ptn_held, event, popup=0, arr=0):
    """enter the [YES] handler at 0x4005e4c8; return which owner reached first."""
    uc = mk()
    uc.mem_write(G_MENU, bytes([menu]))
    uc.mem_write(PTN_MODE_DJ, struct.pack(">I", 1 if ptn_held else 0))
    uc.mem_write(POPUP, struct.pack(">I", popup))
    uc.mem_write(ARR_ACT, struct.pack(">I", arr))

    sp = 0x41010000
    uc.mem_write(sp, struct.pack(">III", 0x00c0ffee, 0x31, event))   # ret, keycode, event
    uc.reg_write(UC_M68K_REG_A7, sp)

    verdict = {"who": None}

    def hook(uc, addr, size, u):
        if addr == CLOSE_CB:
            verdict["who"] = "RELOAD"; uc.emu_stop()
        elif addr == CKSUM:
            verdict["who"] = "DIRECTJUMP"; uc.emu_stop()
        elif addr == YES_RESUME:
            verdict["who"] = "STOCK"; uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(0x4005e4c8, 0, count=4000)
    except UcError as e:
        verdict["err"] = str(e)
    uc.hook_del(h)
    return verdict.get("who") or verdict.get("err", "no-verdict")


def dynamic_checks():
    print("\nDYNAMIC -- [YES] @ 0x4005e4c8 trampoline dispatch")
    ck("picker open            -> RELOAD2 picker", yes_key(1, 0, 1) == "RELOAD")
    ck("closed, [PTN] held     -> DIRECT JUMP toggle", yes_key(0, 1, 1) == "DIRECTJUMP")
    ck("closed, [PTN] not held -> stock YES", yes_key(0, 0, 1) == "STOCK")
    ck("key release (event 0)  -> stock YES", yes_key(0, 1, 0) == "STOCK")
    ck("picker open + [PTN] held -> still RELOAD2 (picker wins)", yes_key(1, 1, 1) == "RELOAD")
    ck("closed, [PTN] held, popup up -> stock (DJ guard)", yes_key(0, 1, 1, popup=1) == "STOCK")


if __name__ == "__main__":
    static_checks()
    dynamic_checks()
    print()
    if fails:
        print(f"FAILED: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GOOD")

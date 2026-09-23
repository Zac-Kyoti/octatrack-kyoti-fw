#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 49 -- "Part params carry over after a pattern->Part change".

Three Elektronauts reports, one family: a pattern change that LINKS A DIFFERENT
PART does not fully re-apply that Part's per-track state (a PICKUP->FLEX track
keeps playing the old Part's pickup loop; the recorder SRC/RLEN and the last
tweaked REC SETUP value persist).

This drives octabam's full-firmware emulator (via `tools/emu_rtos.py`) against the
factory OT DEMO -- whose banks link P1-4->Part0, P5-8->Part1, P9-12->Part2,
P13-16->Part3 (confirmed statically) -- so a P4<->P5 pattern change IS a real
Part 0<->1 change.

  --probe   read-only reconnaissance in ONE boot:
              * dump the machine-type byte per Part/track  (blob + 0x8ed80 +
                part*0x18b2 + 0x22 + track)  -- 0 STATIC / 1 FLEX / 4 PICKUP
              * dump each pattern's RAM Part-link byte      (slab + 0x8e57)
              * play P1 (Part 0); record the witnesses:
                  0x80001828 applied-bank,  0x80001829 applied-part
                  (set at the TOP of FUN_40009094 every time a Part is applied)
                  the live recorder record for T0
                  the T0 voice struct  0x800049d8 + 0*0xA8  (+8 SETTINGS ptr)
              * switch to P5 (Part 1) through the sequencer's own select, run
                frames, re-read the witnesses
              * watch_calls FUN_40009094 / FUN_4002b654 (kind-4 Part apply) /
                FUN_400972fc (PICKUP rebind) across the switch
              * watch_mem 0x460c80f0 (the deferred change-queue KIND word) and
                0x80001829 (applied-part)
            Decisive first cut: if applied-part stays 0 across P1->P5 and no
            Part-apply call fires, the pattern change simply never re-applies
            the Part = root cause (a).

Needs `python3 tools/refs/sync.py` + the EMAC-patched Unicorn
(`refs/octabam/scripts/build_unicorn.sh`).  ~3 min wall per boot.
"""
import argparse
import os
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
PATCHED_IMAGE = ROOT / "out" / "mainos_partreapply.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

BANK_BLOB = er.BANK_BLOB               # 0x400e21e0
BANK_STRIDE = er.BANK_STRIDE           # 0x9b340
PAT_STRIDE = er.PATTERN_STRIDE         # 0x8ed8
TRAC_STRIDE = er.TRAC_STRIDE           # 0x91a

PARTS_OFF = 0x8ed80                    # 16 pattern slabs, then the 4 Part payloads
PART_STRIDE = 0x18b2                   # 6322
MACHINE_OFF = 0x22                     # 8 machine-type bytes per Part payload
PART_LINK_IN_SLAB = 0x8e57            # RAM pattern -> Part index (disk is +0x8ee7)

APPLIED_BANK = 0x80001828             # FUN_40009094 stores its bank arg here (top of fn)
APPLIED_PART = 0x80001829             # ...and its part arg
VOICE_BASE = 0x800049d8              # per-track voice struct, stride 0xA8
VOICE_STRIDE = 0xA8
CHANGE_Q_KIND = 0x460c80f0           # deferred change queue: KIND longword

FUN_40009094 = 0x40009094            # per-track Part -> engine apply
FUN_4002b654 = 0x4002b654            # kind-4 deferred Part-apply handler
FUN_400972fc = 0x400972fc            # PICKUP-only voice rebind
FUN_400a0570 = 0x400a0570            # the cue-pattern choke point (every pattern change)
# The real per-trig sample resolver (Session 81; open since Session 49, which ruled
# out FUN_40005030 and wrongly guessed FUN_4009d1e8). Picks STATIC_ARENA (0x4000f4b4)
# vs FLEX_ARENA (0x4000f4d8), stride 0x448, and carries the PICKUP ownership claim
# at 0x4000f7d0.
#   Reached by INDIRECT dispatch through the per-machine-type function-pointer table
#   at 0x400d6454 -- `a0 = *(0x400d6454 + type*4)` then `jsr (a0)` at 0x4000d49c.
#   Table: [0]STATIC and [1]FLEX and [4]PICKUP all -> 0x4000f450; [2]THRU -> 0x400043f4;
#   [3]NEIGHBOR -> 0x4000463c. (There is also a direct `jsr 0x4000f450.l` at 0x4000421c,
#   but that is NOT the path any observed run took -- a literal-address grep finds only
#   that one and misses the real dispatch.)
#   Convention, measured off a live run: FUN_4000f450(track, slot, flags=0xc0), stack
#   at entry [ret][arg1=track][arg2=slot][arg3=0xc0].
FUN_4000f450 = 0x4000f450

MT = {0: "STATIC", 1: "FLEX", 2: "THRU", 3: "NEIGH", 4: "PICKUP"}


def u8(rt, a):
    return rt.uc.mem_read(a, 1)[0]


def u32(rt, a):
    return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]


def rd(rt, a, n):
    return bytes(rt.uc.mem_read(a, n))


def part_ptr(rt):
    return u32(rt, ec.PART_PTR)


def machine_row(rt, blob, part):
    base = blob + PARTS_OFF + part * PART_STRIDE + MACHINE_OFF
    return [u8(rt, base + t) for t in range(8)]


def dump_machines(rt, blob):
    print(f"\n  machine types  (blob {blob:#x} + 0x8ed80 + part*0x18b2 + 0x22 + track)")
    print(f"    {'':6}" + "".join(f" T{t+1:<7}" for t in range(8)))
    for part in range(4):
        row = machine_row(rt, blob, part)
        print(f"    part{part}: " + "".join(f" {MT.get(v, hex(v)):<7}" for v in row))


def dump_links(rt, blob):
    print(f"\n  pattern -> Part link  (slab + 0x8e57)")
    for pat in range(16):
        v = u8(rt, blob + pat * PAT_STRIDE + PART_LINK_IN_SLAB)
        print(f"    P{pat+1:2d}: part {v}")


def witnesses(rt, blob, track=0):
    vb = VOICE_BASE + track * VOICE_STRIDE
    return {
        "applied_bank": u8(rt, APPLIED_BANK),
        "applied_part": u8(rt, APPLIED_PART),
        "voice+0 (active)": u8(rt, vb + 0),
        "voice+8 (SETTINGS ptr)": u32(rt, vb + 8),
        "voice+23 (loop mode)": u8(rt, vb + 23),
        "voice+32 (slice idx)": u8(rt, vb + 32),
        "machine[T] published": None,   # filled by caller from the pre-image if wanted
    }


def show(tag, w):
    print(f"  {tag}")
    for k, v in w.items():
        if v is None:
            continue
        print(f"    {k:24} = {v if not isinstance(v, int) else hex(v) if v > 9 else v}")


# --- PICKUP ownership singleton (Session 51) ------------------------------
# PICKUP is NOT a per-track arena slot like FLEX/STATIC: it is one global
# capture buffer with a single owner track at a time.
#   PICKUP_OWNER   -1 == unclaimed.  Claimed at 0x4000f7d0, but ONLY on the
#                  `owner < 0` branch -- once non-negative the claim path is
#                  never taken again (0x4000f7ca bge -> "already owned").
#                  Released to -1 only at 0x400a112c / 0x400a148a.
#   PICKUP_SKIP    FUN_40097204 sets bit<<track when the track's machine byte
#                  == 4, and on the else branch clears ONLY this bit -- it
#                  performs no ownership release.
PICKUP_OWNER = 0x400d7c4c
PICKUP_ENABLE = 0x461054ec        # per-track PICKUP enable bitmask
PICKUP_CFG = 0x461054f0           # written beside the claim/release
PICKUP_SKIP = 0x46c7ff3e          # per-track "machine is PICKUP" flag byte

# Per-Part "edited / unsaved" flag: a BITMASK, one bit per part, kept in two
# places -- blob+0x95048 (persisted) and 0x100b145e (RAM mirror). SAVE PART
# (FUN_4004a908) clears this part's bit in both at 0x4004a968/0x4004a974.
# FUN_400972fc SETS it at 0x4009737c/0x40097388, before its own machine-type
# check -- so stock touches it on the Part-change path too.
PART_DIRTY = 0x100b145e

SLOT_MIRROR = 0x100a519c          # FUN_400972fc writes the forced PICKUP slot here [+d3]
FUN_400972fc_ENTRY = FUN_400972fc
PREIMG_A = 0x8000082f            # FUN_40009094 per-track pre-image regions
PREIMG_B = 0x80000810
PREIMG_C = 0x80000a50
KILL_BIT = 0x8000184c           # voice AMP-kill / release trigger bitmap (Session 9)

# --- recorder-page config, reports #2/#3 (memory-map "Entry 8" 3-tier storage) ---
REC_CACHE = 0x80000c94          # recorder-page UI cache, 8*12 B; knob editor + FUN_40009094 write it
REC_PUB = 0x80000cf4           # per-frame published copy = 0x80000cf4 + track*12 + [0x800000e0]*96
REC_SRAM = 0x100a54d0          # SRAM mirror
REC_BLOB_OFF = 0x8f382         # blob + part*6322 + track*12 + 0x8f382 = the persisted Part copy
FRAME_SEL = 0x800000e0

# --- scene subsystem (Open_Mike's scene aside; the "data must match audio" thread) ---
FUN_4003f1b4 = 0x4003f1b4     # crossfader / scene morph -> DSP (kind-0x0e posts)
FUN_40002df4 = 0x40002df4     # scene-param stager: blob +0x8f3e2 -> 0x80000ed4 + per-voice, GATED
MORPH_GUARD = 0x400c0c44      # FUN_4003f1b4 early-returns if fader pos 0x460d16c8 == this
FADER_POS = 0x460d16c8
SCENE_SEL = 0x8ed90          # blob + part*0x18b2 + 0x8ed90/91 = scene A/B selection
SCENE_DATA_OFF = 0x8f3e2     # blob + part*0x18b2 + scene*0x100 + 0x8f3e2 = scene param data
TRK_PART = 0x80001832        # per-track "the Part this track's staged scene data is for" (8 B)
TRK_BANK = 0x8000182a        # per-track bank (8 B); FUN_40002df4's gate = [==active]
SCENE_LIVE = 0x80000ed4     # live scene param buffer, track*0x40, A/B interleaved (stride 2)
ACTIVE_PART = 0x80000003


def tp_word(rt):
    return u32(rt, 0x800065b8)


def cmd_probe(rt, poke_pickup):
    blob = part_ptr(rt)
    curbank = u8(rt, er.CUR_BANK)
    print(f"\n===== emu_partswitch : PICKUP->FLEX voice carryover on a Part change =====")
    print(f"curbank={curbank}  PART_PTR={blob:#x}")
    if not blob:
        sys.exit("PART_PTR null -- load failed")

    dump_machines(rt, blob)
    dump_links(rt, blob)

    T = 0  # track under test
    m0 = blob + PARTS_OFF + 0 * PART_STRIDE + MACHINE_OFF + T   # Part 0, track T machine byte
    m1 = blob + PARTS_OFF + 1 * PART_STRIDE + MACHINE_OFF + T   # Part 1, track T machine byte
    # per-track 5-byte slot record inside a Part payload: +0 STATIC / +1 FLEX / +4 PICKUP
    # (FUN_400972fc reads the PICKUP slot at blob + part*0x18b2 + track*5 + 0x8f04e;
    #  0x8f04e = PARTS_OFF + 0x2ce, so the record base is PARTS_OFF + 0x2ca + track*5)
    def slot_addr(part, track, typ):
        return blob + PARTS_OFF + part * PART_STRIDE + 0x2ca + track * 5 + typ

    # blob recorder record addresses for Part 0 / Part 1, track T
    rb0 = blob + 0 * PART_STRIDE + REC_BLOB_OFF + T * 12
    rb1 = blob + 1 * PART_STRIDE + REC_BLOB_OFF + T * 12

    if poke_pickup:
        print(f"\npoke       : Part0 T{T+1} machine {u8(rt, m0)} -> 4 (PICKUP);  "
              f"Part1 T{T+1} machine stays {u8(rt, m1)} (FLEX)")
        rt.uc.mem_write(m0, b"\x04")
        rt.uc.mem_write(slot_addr(0, T, 4), bytes([128 + T]))   # Part0 PICKUP buffer slot
        rt.uc.mem_write(slot_addr(1, T, 1), b"\x00")            # Part1 FLEX slot -> slot 1
        print(f"           : Part0 PICKUP slot @ {slot_addr(0,T,4):#x} = {u8(rt, slot_addr(0,T,4))};  "
              f"Part1 FLEX slot @ {slot_addr(1,T,1):#x} = {u8(rt, slot_addr(1,T,1))}")
        # reports #2/#3: make the two Parts' stored recorder records distinct, and stamp a
        # "just tweaked" marker into the live UI cache (0x80000c94) for T -- if a Part change
        # never refreshes the cache from the new Part's blob record, the marker survives.
        rt.uc.mem_write(rb0, bytes(range(0x40, 0x4c)))          # Part0 rec record = 0x40..0x4b
        rt.uc.mem_write(rb1, bytes(range(0x60, 0x6c)))          # Part1 rec record = 0x60..0x6b
        rt.uc.mem_write(REC_CACHE + T * 12, b"\xAA" * 12)       # "last tweak" marker
        print(f"           : Part0 rec blob @ {rb0:#x} = {rd(rt, rb0, 12).hex(' ')}")
        print(f"           : Part1 rec blob @ {rb1:#x} = {rd(rt, rb1, 12).hex(' ')}")
        print(f"           : REC_CACHE[T] @ {REC_CACHE + T*12:#x} = {rd(rt, REC_CACHE + T*12, 12).hex(' ')} (0xAA marker)")
        # --- scene thread: distinct scene selection + scene data per Part, and a
        #     stale marker in the live scene buffer 0x80000ed4 for T ---
        rt.uc.mem_write(blob + 0 * PART_STRIDE + SCENE_SEL, b"\x00\x01")   # Part0: A=0 B=1
        rt.uc.mem_write(blob + 1 * PART_STRIDE + SCENE_SEL, b"\x04\x05")   # Part1: A=4 B=5
        # Part0 scene 0/1 data for T = 0x30.. / 0x38.. ; Part1 scene 4/5 for T = 0x50.. / 0x58..
        for pt, sc, fill in ((0, 0, 0x30), (0, 1, 0x38), (1, 4, 0x50), (1, 5, 0x58)):
            rt.uc.mem_write(blob + pt * PART_STRIDE + sc * 0x100 + SCENE_DATA_OFF + T * 32,
                            bytes([fill]) * 32)
        rt.uc.mem_write(SCENE_LIVE + T * 0x40, b"\xEE" * 16)              # stale marker
        print(f"           : scene sel P0={rd(rt, blob+0*PART_STRIDE+SCENE_SEL,2).hex()} "
              f"P1={rd(rt, blob+1*PART_STRIDE+SCENE_SEL,2).hex()}")
        print(f"           : TRK_PART[0..7]={rd(rt, TRK_PART, 8).hex(' ')}  "
              f"TRK_BANK[0..7]={rd(rt, TRK_BANK, 8).hex(' ')}")
        print(f"           : SCENE_LIVE[T] @ {SCENE_LIVE+T*0x40:#x} = {rd(rt, SCENE_LIVE+T*0x40, 16).hex(' ')} (0xEE marker)")

    vb = VOICE_BASE + T * VOICE_STRIDE

    # instruments: watch the rebind fn's args, the Part-apply fns, and the T voice +
    # the per-track slot mirror / pre-image / kill bitmap.
    rt.watch_pc([FUN_400972fc_ENTRY, FUN_40009094, FUN_4002b654, FUN_40002df4, FUN_4003f1b4])
    rt.watch_mem(vb, 0x50)
    mw_slot = []
    sm0 = SLOT_MIRROR + 0 * 6322 + T * 5   # slot mirror, Part 0 track T
    sm1 = SLOT_MIRROR + 1 * 6322 + T * 5   # slot mirror, Part 1 track T
    for base, ln in ((sm0, 5), (sm1, 5), (PREIMG_A + T * 12, 12),
                     (PREIMG_C + T * 64, 24), (KILL_BIT, 1), (APPLIED_PART, 1),
                     (REC_CACHE + T * 12, 12), (REC_SRAM + T * 12, 12),
                     (rb0, 12), (rb1, 12),
                     (TRK_PART, 8), (TRK_BANK, 8), (SCENE_LIVE + T * 0x40, 0x20),
                     (MORPH_GUARD, 4), (ACTIVE_PART, 1)):
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE,
                       (lambda tag: (lambda u, acc, a, sz, v, x:
                        mw_slot.append((tag, u.reg_read(er.eb.UC_M68K_REG_PC), a, sz, v))))(hex(base)),
                       begin=base, end=base + ln - 1)
    rt.uc.ctl_flush_tb()

    def snap(tag):
        print(f"  {tag}:")
        print(f"    applied bank/part          = {u8(rt, APPLIED_BANK)}/{u8(rt, APPLIED_PART)}")
        print(f"    transport word 0x800065b8  = {tp_word(rt):#010x}")
        print(f"    T{T+1} voice +0 active      = {u8(rt, vb):#x}")
        print(f"    T{T+1} voice +8 SETTINGS    = {u32(rt, vb + 8):#010x}")
        print(f"    T{T+1} voice +20..+2c       = {rd(rt, vb + 0x20, 12).hex(' ')}")
        print(f"    T{T+1} voice +32 slice      = {u8(rt, vb + 32):#x}")
        print(f"    slot mirror P0/P1 [T]       = {rd(rt, sm0, 5).hex(' ')}  /  {rd(rt, sm1, 5).hex(' ')}")
        print(f"    pre-image 0x80000a50[T]     = {rd(rt, PREIMG_C + T * 64, 16).hex(' ')}")
        print(f"    kill bitmap 0x8000184c      = {u8(rt, KILL_BIT):#04x}")
        fs = u8(rt, FRAME_SEL)
        print(f"    REC cache 0x80000c94[T]     = {rd(rt, REC_CACHE + T * 12, 12).hex(' ')}")
        print(f"    REC pub 0x80000cf4 f{fs} [T]  = {rd(rt, REC_PUB + fs * 96 + T * 12, 12).hex(' ')}")
        print(f"    REC SRAM 0x100a54d0[T]      = {rd(rt, REC_SRAM + T * 12, 12).hex(' ')}")
        print(f"    REC blob P0/P1 [T]         = {rd(rt, rb0, 12).hex(' ')}  /  {rd(rt, rb1, 12).hex(' ')}")
        print(f"    active part 0x80000003     = {u8(rt, ACTIVE_PART)}")
        print(f"    TRK_PART[0..7] 0x80001832  = {rd(rt, TRK_PART, 8).hex(' ')}")
        print(f"    TRK_BANK[0..7] 0x8000182a  = {rd(rt, TRK_BANK, 8).hex(' ')}")
        print(f"    scene sel P0/P1 (blob)     = {rd(rt, blob+0*PART_STRIDE+SCENE_SEL,2).hex()}  /  "
              f"{rd(rt, blob+1*PART_STRIDE+SCENE_SEL,2).hex()}")
        print(f"    SCENE_LIVE 0x80000ed4[T]   = {rd(rt, SCENE_LIVE + T*0x40, 16).hex(' ')}")
        print(f"    morph guard 0x400c0c44     = {u32(rt, MORPH_GUARD):#010x}   fader 0x460d16c8 = {u32(rt, FADER_POS):#010x}")

    # --- P1 (Part 0), transport running --------------------------------
    # Simulate "this Part was saved": clear the per-Part edited bitmask in BOTH
    # places before the round trip. Without this the harness's own blob pokes
    # leave Part 0 already reading dirty (0x01) at every snapshot, which makes
    # the measurement useless for the user's report -- their Part IS saved and
    # goes dirty during the round trip.
    rt.uc.mem_write(PART_DIRTY, b"\x00")
    rt.uc.mem_write(blob + 0x95048, b"\x00")
    print(f"\nclear-dirty : PART_DIRTY(0x100b145e)=0, blob+0x95048(={blob + 0x95048:#x})=0 "
          f"-- simulating a saved Part before the round trip")

    rt.seq_select_live(curbank, 0)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    tgt = rt.frame_count + 60
    try:
        rt.start_transport_live()
        rt.run(ms=8000, until=lambda r: r.frame_count >= tgt)
    except Exception as e:
        print(f"  transport start raised {type(e).__name__}: {e}")
    print(f"\n  transport after start: 0x800065b8 = {tp_word(rt):#010x}  frame_count = {rt.frame_count}")
    snap("after P1 / Part 0 (T under test = PICKUP)" if poke_pickup else "after P1 / Part 0")

    # --- THE SWITCH: P1 -> P5 (Part 0 -> Part 1, T -> FLEX) ------------
    print(f"\n----- switching P1 -> P5 (Part 0 -> Part 1); T{T+1}: PICKUP -> FLEX -----")
    # stop first so the Part change commits synchronously (a running switch defers to the
    # step engine's pattern boundary -- thousands of frames away; the reports cover the
    # stopped case too). press_key_live(KEY_STOP) does NOT actually stop the transport here
    # (0x800065b8 stays 1, confirmed Session 49 -- the switch below then silently stays
    # queued and never commits, `seq_select_live`'s own readback still showing pattern 0,
    # which made an earlier fix-validation pass look like a no-op on BOTH stock and patched
    # images). Poke the transport-running flag directly instead -- reliable throughout this
    # session's other probes.
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    print(f"  transport after STOP: {tp_word(rt):#010x}")
    n_pc = len(rt.pc_hits)
    n_v = len(rt.mem_writes)
    n_s = len(mw_slot)
    sb, sp2 = rt.seq_select_live(curbank, 4)
    rt.run(ms=1500)
    print(f"\n  seq now: bank {sb} pattern {sp2} (0x800065be={u8(rt, 0x800065be)})  "
          f"frame_count = {rt.frame_count}")
    for s, line in rt.pc_hits[n_pc:]:
        print(f"    PC-HIT {line}")
    print(f"\n  writes to the T{T+1} voice struct during the switch (excl. the idle-zero loop):")
    vseen = set()
    for _, task, pc, ad, sz, val in rt.mem_writes[n_v:]:
        if pc in (0x40006b80, 0x40006b8e):   # inactive-voice idle zeroing -- noise
            continue
        key = (pc, ad, val)
        if key in vseen:
            continue
        vseen.add(key)
        print(f"    [{ad:#x}] (+{ad - vb:#x}) <- {val:#x} ({sz}) at {pc:#x}")
    if not vseen:
        print("    (none of substance -- only the idle-zero loop touched it)")
    print(f"\n  writes to slot mirror / pre-image / kill / applied-part / TRK_PART / "
          f"SCENE_LIVE / morph-guard during the switch:")
    for tag, pc, ad, sz, val in mw_slot[n_s:]:
        print(f"    {tag} [{ad:#x}] <- {val:#x} ({sz}) at {pc:#x}")
    if len(mw_slot) == n_s:
        print("    (none)")
    print()
    snap("after P5 / Part 1 (T under test now FLEX)" if poke_pickup else "after P5 / Part 1")

    print(f"\n===== READ-OFF =====")
    print("  #1  voice/slot: did anything rebind T away from 128+T toward Part 1's FLEX slot?")
    print("  #2/3 recorder: did REC_CACHE[T] refresh from Part 1's blob rec (0x60..0x6b)?")
    print("  scene: did TRK_PART[T] move to Part 1?  did SCENE_LIVE[T] refresh from Part 1's")
    print("         scene data (0x50../0x58..)?  did FUN_40002df4 / FUN_4003f1b4 run?  did the")
    print("         morph guard 0x400c0c44 change?  (0xEE / 0xAA markers surviving = the bug)")
    return True


FLEX_ARENA = 0x100b14f0
STATIC_ARENA = 0x100d5b30
ARENA_STRIDE = 1096


def cmd_repeat(rt, own_poke=False, resolver=False, drive=False):
    """HW finding (2026-09-13, real MKI, PARTREAPPLY flashed): P1(Part0 T1=PICKUP,
    silent) -> P5(Part1 T1=FLEX, sample B) sounds correct the FIRST time; jump back
    to P1 then forward to P5 AGAIN and T1 now plays Part0's PICKUP content (sample A)
    under the FLEX machine. The fix's #1 mechanism (SLOT_MIRROR write + KILL_BIT) was
    always flagged unverified/suspect (HANDOFF) -- this does a real P1->P5->P1->P5
    round trip and snapshots the voice struct + SLOT_MIRROR + KILL_BIT at BOTH
    arrivals at P5 to see exactly what differs the second time."""
    blob = part_ptr(rt)
    curbank = u8(rt, er.CUR_BANK)
    T = 0
    m0 = blob + PARTS_OFF + 0 * PART_STRIDE + MACHINE_OFF + T
    m1 = blob + PARTS_OFF + 1 * PART_STRIDE + MACHINE_OFF + T
    print(f"\n===== emu_partswitch --repeat : P1<->P5 round trip, T{T+1} PICKUP<->FLEX =====")
    print(f"curbank={curbank}  PART_PTR={blob:#x}")

    def slot_addr(part, track, typ):
        return blob + PARTS_OFF + part * PART_STRIDE + 0x2ca + track * 5 + typ

    print(f"poke       : Part0 T{T+1} machine {u8(rt, m0)} -> 4 (PICKUP);  "
          f"Part1 T{T+1} machine stays {u8(rt, m1)} (FLEX)")
    rt.uc.mem_write(m0, b"\x04")
    rt.uc.mem_write(slot_addr(0, T, 4), bytes([128 + T]))   # Part0 PICKUP buffer slot
    rt.uc.mem_write(slot_addr(1, T, 1), b"\x02")            # Part1 FLEX slot -> slot 2 (distinct from 128+T and from slot 1)
    print(f"           : Part0 PICKUP slot @ {slot_addr(0,T,4):#x} = {u8(rt, slot_addr(0,T,4))};  "
          f"Part1 FLEX slot @ {slot_addr(1,T,1):#x} = {u8(rt, slot_addr(1,T,1))}")

    vb = VOICE_BASE + T * VOICE_STRIDE
    sm1 = SLOT_MIRROR + 1 * 6322 + T * 5

    def own(tag=None):
        """The PICKUP ownership singleton + its companions. The 2026-09-13
        --repeat run snapshotted only the voice struct / SLOT_MIRROR /
        KILL_BIT and reported 'byte-identical' -- it never read THESE, so
        that null result says nothing about ownership going stale."""
        o = u32(rt, PICKUP_OWNER)
        return {
            "PICKUP_OWNER 0x400d7c4c": f"{o:#010x} ({'unclaimed' if o == 0xffffffff else f'track {o}'})",
            "PICKUP_ENABLE 0x461054ec": f"{u32(rt, PICKUP_ENABLE):#010x}",
            "PICKUP_CFG 0x461054f0": f"{u32(rt, PICKUP_CFG):#010x}",
            "PICKUP_SKIP 0x46c7ff3e": f"{u8(rt, PICKUP_SKIP):#04x}",
            "PART_DIRTY 0x100b145e": f"{u8(rt, PART_DIRTY):#04x}",
            f"voice[T{T+1}]+0x14 (mach)": f"{u8(rt, vb + 0x14):#04x}",
        }

    def snap(tag):
        v = rd(rt, vb, 0x50)
        print(f"\n  {tag}")
        print(f"    voice[T{T+1}] +0..+0x50 = {v.hex(' ')}")
        print(f"    SLOT_MIRROR Part1[T]     = {rd(rt, sm1, 5).hex(' ')}")
        print(f"    KILL_BIT 0x8000184c      = {u8(rt, KILL_BIT):#04x}")
        print(f"    applied bank/part        = {u8(rt, APPLIED_BANK)}/{u8(rt, APPLIED_PART)}")
        o = own()
        for k, val in o.items():
            print(f"    {k:<26} = {val}")
        # The resolver's `slot` argument is read from here: measured
        # a1 == PREIMG_A + track*0x48 at the resolver entry for tracks
        # 1/3/4/5 (slots 2/0xa/9/0x15), all four exact. PREIMG_A is one of
        # FUN_40009094's per-track pre-image regions -- and FUN_40009094 is
        # exactly what a pattern->Part change never calls.
        print(f"    PREIMG_A per-track (slot source, {PREIMG_A:#x} + track*0x48):")
        for t in range(8):
            row = rd(rt, PREIMG_A + t * 0x48, 12)
            print(f"      T{t+1} {PREIMG_A + t*0x48:#010x}: {row.hex(' ')}")
        return v, o

    watch = [FUN_400972fc_ENTRY, FUN_40009094, FUN_4002b654]
    if resolver:
        # watch_pc dumps [sp: ret arg1 arg2 arg3 ...] at the entry, before the
        # callee's own `lea -0x3c(a7)` -- so this reads the resolver's calling
        # convention off a live run instead of off a desynced linear disassembly,
        # and says which tracks actually reach it.
        watch.append(FUN_4000f450)
    rt.watch_pc(watch)
    rt.watch_mem(PICKUP_OWNER, 4)
    rt.watch_mem(PICKUP_ENABLE, 8)        # 0x461054ec + 0x461054f0, adjacent
    rt.watch_mem(PICKUP_SKIP, 1)
    rt.watch_mem(PREIMG_A + T * 0x48, 1)   # the resolver's slot source, T1
    rt.watch_mem(PART_DIRTY, 1)            # per-Part edited/unsaved bitmask
    n_pc = 0
    n_mw = 0

    if own_poke:
        # The plain --repeat run (2026-09-22) showed PICKUP_OWNER never leaves
        # -1 and voice+0x14 never becomes 4: a machine-byte poke alone never
        # engages the ownership machinery, so that run could not exercise the
        # claim/release asymmetry at all (same blind spot as Session 49's
        # diff_flex_static.py). On hardware the report's precondition -- a
        # PICKUP track "already linked to a sample" -- means the buffer IS
        # owned. Fabricate that minimal state, then ask the ONE question this
        # settles: does anything on the pattern-change path ever release it?
        rt.uc.mem_write(PICKUP_OWNER, struct.pack(">I", T))
        rt.uc.mem_write(vb + 0x14, bytes([4]))
        rt.uc.mem_write(PICKUP_ENABLE, struct.pack(">I", 1 << T))
        print(f"\nown-poke   : PICKUP_OWNER={T} (T{T+1} owns the buffer), "
              f"voice[T{T+1}]+0x14=4, PICKUP_ENABLE={1 << T:#x}")
        print("             FABRICATED state -- what a used PICKUP track looks like.")
        print("             Question under test: does a Part change ever release it?")

    names = {PICKUP_OWNER: "PICKUP_OWNER", PICKUP_ENABLE: "PICKUP_ENABLE",
             PICKUP_CFG: "PICKUP_CFG", PICKUP_SKIP: "PICKUP_SKIP",
             PREIMG_A + T * 0x48: "PREIMG_SLOT[T1]", PART_DIRTY: "PART_DIRTY"}

    # --- drive the resolver directly (Session 81) -------------------------
    # T1 never sounds in the emulator, so it never reaches FUN_4000f450 on its
    # own and no arrival#1-vs-#2 diff of passive state can ever show the latch.
    # Now that the resolver is named AND its convention is measured off a live
    # run -- FUN_4000f450(track, slot, flags=0xc0) -- drive it directly instead
    # of waiting for a trig. call_as_main is the faithful context here: the real
    # dispatch was observed running in task `main` (cur=0x46c7ae84).
    arena_reads = {}
    voice_writes = []

    def _install_drive_hooks(slot):
        ent = {
            "PICKUP_entry": FLEX_ARENA + (128 + T) * ARENA_STRIDE,
            "FLEX_entry": FLEX_ARENA + slot * ARENA_STRIDE,
            "STATIC_entry": STATIC_ARENA + slot * ARENA_STRIDE,
        }

        def mk(name):
            def h(u, acc, addr, size, val, user):
                arena_reads.setdefault(name, []).append(
                    (u.reg_read(er.eb.UC_M68K_REG_PC), addr))
            return h

        for nm, base in ent.items():
            rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk(nm),
                           begin=base, end=base + ARENA_STRIDE - 1)

        def vw(u, acc, addr, size, val, user):
            voice_writes.append((u.reg_read(er.eb.UC_M68K_REG_PC), addr, size, val))

        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, vw,
                       begin=vb, end=vb + VOICE_STRIDE - 1)
        rt.uc.ctl_flush_tb()
        print(f"drive      : arena entries  PICKUP={ent['PICKUP_entry']:#x}  "
              f"FLEX(slot {slot})={ent['FLEX_entry']:#x}  STATIC={ent['STATIC_entry']:#x}")
        return ent

    def drive(tag, slot):
        arena_reads.clear()
        voice_writes.clear()
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        pre = rd(rt, vb, VOICE_STRIDE)
        try:
            d0 = rt.call_as_main(FUN_4000f450, (T, slot, 0xc0))
        except Exception as e:                         # noqa: BLE001 - diagnostic
            print(f"\n  DRIVE {tag}: call FAILED -- {type(e).__name__}: {e}")
            return None
        post = rd(rt, vb, VOICE_STRIDE)
        hit = {k: len(v) for k, v in sorted(arena_reads.items())}
        vd = [(i, pre[i], post[i]) for i in range(VOICE_STRIDE) if pre[i] != post[i]]
        print(f"\n  DRIVE {tag}: FUN_4000f450(track={T}, slot={slot}, 0xc0) -> d0={d0:#x}")
        print(f"    arena entry reads  : {hit if hit else 'NONE'}")
        print(f"    voice[T] writes    : {len(voice_writes)}")
        if vd:
            print("    voice bytes changed: " +
                  " ".join(f"+{i:#04x}:{a:#04x}->{b:#04x}" for i, a, b in vd[:16]))
        return {"d0": d0, "reads": hit,
                "voice_delta": tuple(vd), "nwrites": len(voice_writes)}

    def switch(bank, pat, tag):
        nonlocal n_pc, n_mw
        rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        sb, sp = rt.seq_select_live(bank, pat)
        rt.run(ms=1500)
        print(f"\n----- switch: bank {sb} pattern {sp}  ({tag}) -----")
        for s, line in rt.pc_hits[n_pc:]:
            print(f"    PC-HIT {line}")
        n_pc = len(rt.pc_hits)
        for s, task, pc, addr, size, val in rt.mem_writes[n_mw:]:
            print(f"    MEM-W  {names.get(addr, hex(addr))} [{addr:#x}] <- {val:#x} "
                  f"({size}B) at pc {pc:#x}")
        n_mw = len(rt.mem_writes)

    # Simulate "this Part was saved": clear the per-Part edited bitmask in BOTH
    # places before the round trip. Without this the harness's own blob pokes
    # leave Part 0 already reading dirty (0x01) at every snapshot, which makes
    # the measurement useless for the user's report -- their Part IS saved and
    # goes dirty during the round trip.
    rt.uc.mem_write(PART_DIRTY, b"\x00")
    rt.uc.mem_write(blob + 0x95048, b"\x00")
    print(f"\nclear-dirty : PART_DIRTY(0x100b145e)=0, blob+0x95048(={blob + 0x95048:#x})=0 "
          f"-- simulating a saved Part before the round trip")

    rt.seq_select_live(curbank, 0)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    tgt = rt.frame_count + 60
    rt.start_transport_live()
    rt.run(ms=8000, until=lambda r: r.frame_count >= tgt)
    snap("after initial P1 (Part0, T1=PICKUP)")

    dslot = u8(rt, slot_addr(1, T, 1))
    if drive:
        _install_drive_hooks(dslot)
    d1r = d2r = None

    switch(curbank, 4, "P1->P5 #1 (Part0->Part1, T1 PICKUP->FLEX)")
    v1, o1 = snap("ARRIVAL #1 at P5 (Part1, T1=FLEX)")
    if drive:
        d1r = drive("ARRIVAL #1", dslot)

    switch(curbank, 0, "P5->P1 (Part1->Part0, T1 FLEX->PICKUP)")
    snap("back at P1 (Part0, T1=PICKUP)")
    if drive:
        # Resolve T1 as PICKUP here, the way a real trig at P1 would. Without
        # this the voice keeps arrival #1's FLEX binding, so the run can only
        # show the re-bind SKIP and never the wrong CONTENT the skip lets
        # through. Expected stale binding if the skip bites at arrival #2:
        # +0x04=0x46c938c4, +0x08=0x100d38f0 (FLEX_ARENA + (128+T)*1096).
        drive("BACK AT P1 (as PICKUP, slot 128+T)", 128 + T)

    switch(curbank, 4, "P1->P5 #2 (Part0->Part1, T1 PICKUP->FLEX AGAIN)")
    v2, o2 = snap("ARRIVAL #2 at P5 (Part1, T1=FLEX)")
    if drive:
        d2r = drive("ARRIVAL #2", dslot)

    print(f"\n===== DIFF: arrival #1 vs arrival #2 at P5, voice[T{T+1}] +0..+0x50 =====")
    diffs = [(i, v1[i], v2[i]) for i in range(len(v1)) if v1[i] != v2[i]]
    if not diffs:
        print("  (byte-identical -- whatever differs audibly is NOT in this 0x50-byte window)")
    else:
        for i, a, b in diffs:
            print(f"    +{i:#04x}: arrival#1={a:#04x}  arrival#2={b:#04x}")

    if drive and d1r and d2r:
        print("\n===== DIFF: arrival #1 vs arrival #2, RESOLVER driven directly =====")
        if d1r == d2r:
            print("  (identical -- the resolver resolves T1 the SAME way on both passes)")
        else:
            for k in d1r:
                if d1r[k] != d2r[k]:
                    print(f"    {k:<12} arrival#1={d1r[k]}\n    {'':<12} arrival#2={d2r[k]}")

    print(f"\n===== DIFF: arrival #1 vs arrival #2, PICKUP ownership singleton =====")
    odiff = [(k, o1[k], o2[k]) for k in o1 if o1[k] != o2[k]]
    if not odiff:
        print("  (identical -- ownership state is NOT what differs on the second pass)")
    else:
        for k, a, b in odiff:
            print(f"    {k:<26} arrival#1={a}   arrival#2={b}")
    return True


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="DEMO as-is (all FLEX)")
    ap.add_argument("--repro", action="store_true",
                    help="poke Part0 T1 -> PICKUP first, then switch to Part1 (FLEX)")
    ap.add_argument("--repeat", action="store_true",
                    help="HW finding follow-up: P1->P5->P1->P5 round trip, diff the voice "
                         "struct between the first and second arrival at P5")
    ap.add_argument("--drive", action="store_true",
                    help="with --repeat: call FUN_4000f450 directly at each arrival and "
                         "diff which arena entry it resolves T1 to")
    ap.add_argument("--resolver", action="store_true",
                    help="with --repeat: also trace FUN_4000f450 (the per-trig sample "
                         "resolver) -- args + which tracks reach it")
    ap.add_argument("--own-poke", action="store_true",
                    help="with --repeat: fabricate a CLAIMED PICKUP buffer (owner=T1) first, "
                         "then test whether the pattern->Part change ever releases it")
    ap.add_argument("--patched", action="store_true",
                    help="boot out/mainos_partreapply.bin (tools/build_partreapply.py) instead of stock")
    ap.add_argument("--image", help="explicit MAIN OS section to boot (e.g. out/mainos_merged.bin)")
    a = ap.parse_args(argv)

    if a.image:
        image = pathlib.Path(a.image)
        if not image.is_absolute():
            image = ROOT / image        # args are relative to the repo, not octabam (we chdir'd)
    else:
        image = PATCHED_IMAGE if a.patched else STOCK_IMAGE
    if not image.exists():
        sys.exit(f"missing {image} -- run tools/build_partreapply.py first" if image == PATCHED_IMAGE else
                  f"missing {image}")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    print(f"image      : {image.name}")
    print(f"boot       : {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load       : mounted={mounted} posted={posted} saved_bank={saved_bank} "
          f"final_bank={final_bank} ({elapsed:.0f} ms)")

    if a.repeat:
        cmd_repeat(rt, own_poke=a.own_poke, resolver=a.resolver, drive=a.drive)
    else:
        cmd_probe(rt, poke_pickup=a.repro)


if __name__ == "__main__":
    main(sys.argv[1:])

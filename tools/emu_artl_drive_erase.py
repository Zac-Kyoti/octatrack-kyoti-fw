#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 78: drive the REAL LIVE `[NO]`+knob erase against the user's REAL ARTLTEST1
export and watch what it writes -- instead of inferring the handler from labels.

Two things make this tractable now that Session 34's attempt was not:

 1. The dispatcher case is pinned. The sys task's 78-way message table (0x40061cfa,
    index = msg[0]-1) routes **opcode 70** to 0x400629ee, and that case -- given
    msg[1] == 8 -- is the ONLY caller of both erase functions:
        0x460d172e != 0            -> FUN_4004f124(track, msg[2], msg[3])       (armed)
        else 0x460d172a != 0       -> 0x46c7e956 = msg[4..7]
                                      FUN_40041bc4(track, msg[2], msg[3], msg[4..7])  (LIVE)
    `track` is the byte at 0x80000000. Note the case itself does NOT test 0x460d1a90;
    only the callee does.

 2. Session 34 drove FUN_40041bc4 over a bare bank load, so every per-track table the
    decode reads (0x46c775bc, 0x46c7759c, the param cursor) was 0 and the working index
    collapsed to 0. Here the project is brought up through `load_project_live`, the same
    path emu_artl_fields.py used to read the real lock state, so those tables are real.

Ground truth this must reproduce, from the user's own exports (all bank 1 / pattern 1 /
track 1, 0-indexed 0, step 6):
    ARTLTEST1 .strd/.work  #1[6] = {0x00: 0x30 (PTCH), 0x02: 0x4e (LEN)}
    ARTLTEST2 .strd        #1[6] = {0x02: 0x4e}                  <- PTCH erased
    ARTLTEST2 .work        #1[6] = none (all 0xFF)               <- LEN erased too
    TRAC+0x19 (disk) / +0x10 (RAM) bit 6 stays SET through all of it -- the bug.

So a correct drive of the PTCH erase must turn `#1[6][0x00]` from 0x30 into 0xFF.

    python3 tools/emu_artl_drive_erase.py [project-dir]
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
DEFAULT_PROJECT = pathlib.Path.home() / "Desktop" / "ARTLTEST1"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath          # noqa: E402
import emu_rtos as er    # noqa: E402
import emu_card as ec    # noqa: E402
import unicorn               # noqa: E402
import unicorn.m68k_const as eb  # noqa: E402

PAT_STRIDE = er.PATTERN_STRIDE    # 0x8ed8
TRAC_STRIDE = er.TRAC_STRIDE      # 0x91a
PLOCK_IN_TRAC = 0x59
PAT, TRK, STEP = 0, 0, 6

LIVE_ERASE_FN = 0x40041bc4
CUR_TRACK = 0x80000000
GATE_LIVE = 0x460d172a            # LIVE-REC edit active
GATE_ARMED = 0x460d172e           # grid-rec armed (routes to the sibling instead)
GATE_BLOCK = 0x460d1a90           # must be 0 or FUN_40041bc4 bails at once
ARG3_GLOBAL = 0x46c7e956          # the case stores msg[4..7] here before the call
TRACK_GATE_FN = 0x4009b290        # per-track gate: must return 1 for track+8
TRACK_GATE_TBL = 0x80006508       # the byte array that gate reads (Session 34)


def main():
    project = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    if not project.exists():
        sys.exit(f"missing {project}")

    card, name = er.stage_project(str(project), "OCTABAM", None)
    r, rt = er.attach(str(STOCK), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)  [{project.name}]")

    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    trac = blob + PAT * PAT_STRIDE + TRK * TRAC_STRIDE
    row = trac + PLOCK_IN_TRAC + STEP * 32

    def one():
        v = bytes(rt.uc.mem_read(row, 32))
        return {i: v[i] for i in range(32) if v[i] != 0xFF}

    def trigless():
        v = bytes(rt.uc.mem_read(trac + 0x10, 8))
        return [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]

    print(f"blob {blob:#x}  TRAC {trac:#x}  #1[{STEP}] row {row:#x}")
    print(f"pre : #1[{STEP}] = {{{', '.join(f'{hex(k)}:{hex(v)}' for k, v in one().items()) or 'none'}}}"
          f"   TRAC+0x10 steps={trigless()}")
    if not one():
        sys.exit("!! no locks in RAM after load -- nothing to erase; stop here.")

    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)

    def rl(a):
        return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]
    print(f"\ngates as loaded: LIVE(0x460d172a)={rl(GATE_LIVE):#x} "
          f"ARMED(0x460d172e)={rl(GATE_ARMED):#x} BLOCK(0x460d1a90)={rl(GATE_BLOCK):#x} "
          f"track(0x80000000)={rt.uc.mem_read(CUR_TRACK, 1)[0]}")

    # Put the unit in the state the gesture needs: LIVE-REC edit active, not armed,
    # not blocked, and the current track the one holding the lock.
    rt.uc.mem_write(GATE_LIVE, struct.pack(">I", 1))
    rt.uc.mem_write(GATE_ARMED, struct.pack(">I", 0))
    rt.uc.mem_write(GATE_BLOCK, struct.pack(">I", 0))
    rt.uc.mem_write(CUR_TRACK, bytes([TRK]))
    gate = rt.call_as_main(TRACK_GATE_FN, args=(TRK + 8,), budget=200_000)
    if not gate:
        # Session 34's lever: FUN_4009b290(track+8) reads [0x80006508 + track].
        rt.uc.mem_write(TRACK_GATE_TBL + TRK, bytes([1]))
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        gate = rt.call_as_main(TRACK_GATE_FN, args=(TRK + 8,), budget=200_000)
        print(f"per-track gate was shut; poked [{TRACK_GATE_TBL + TRK:#x}]=1 -> {gate:#x}")
    print(f"per-track gate FUN_4009b290({TRK + 8}) -> {gate:#x}"
          f"   {'(open)' if gate else '(SHUT -- FUN_40041bc4 will bail)'}")

    # Watch the whole TRAC block, so a write anywhere in the stored pattern data for
    # this track is caught, not just the one row we expect.
    hits = []
    armed = [False]

    def on_write(u, acc, a, size, val, user):
        if not armed[0]:
            return
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        if sp - 0x400 <= a <= sp + 0x400:      # its own frame -- noise
            return
        hits.append((u.reg_read(eb.UC_M68K_REG_PC), a, size, val))
    rt.uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, on_write)
    rt.uc.ctl_flush_tb()

    print("\nsweeping FUN_40041bc4(track, arg1, arg2, arg3) -- arg1 is msg[2] (the encoder/param\n"
          "selector), arg2 is msg[3], arg3 is the longword the case caches at 0x46c7e956.")
    hdr = f"{'arg1':>5} {'arg2':>5} {'arg3':>10}  {'d0':>8}  writes-into-TRAC  #1[6] after"
    print(hdr)
    print("-" * len(hdr))
    for arg1 in (0, 1, 2, 3):
        for arg2, arg3 in ((0, 0), (0, 0xFFFFFFFF), (1, 0), (0xFF, 0)):
            before = one()
            hits.clear()
            rt.uc.mem_write(ARG3_GLOBAL, struct.pack(">I", arg3))
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            armed[0] = True
            try:
                d0 = rt.call_as_main(LIVE_ERASE_FN, args=(TRK, arg1, arg2, arg3),
                                     budget=1_500_000)
            except Exception as e:
                armed[0] = False
                print(f"{arg1:5} {arg2:5} {arg3:#10x}  fault: {e}")
                continue
            armed[0] = False
            after = one()
            print(f"{arg1:5} {arg2:5} {arg3:#10x}  {d0:#8x}  {len(hits):4d} writes"
                  f"  #1[6]={{{', '.join(f'{hex(k)}:{hex(v)}' for k, v in after.items()) or 'none'}}}")
            seen = {}
            for pc, a, size, v in hits:
                seen.setdefault((pc, a), (size, v))
            for (pc, a), (size, v) in list(seen.items())[:14]:
                where = f"TRAC+{a - trac:#x}" if trac <= a < trac + TRAC_STRIDE else (
                    f"blob+{a - blob:#x}" if blob <= a < blob + 0x100000 else f"{a:#x}")
                print(f"        {pc:#010x}  {where:>18} <- {v:#x} ({size})")

    print(f"\npost: #1[{STEP}] = {{{', '.join(f'{hex(k)}:{hex(v)}' for k, v in one().items()) or 'none'}}}"
          f"   TRAC+0x10 steps={trigless()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

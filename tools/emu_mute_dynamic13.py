#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
HANDOFF (2026-09-14): reconciling octabam's independent RTOS_FORK.md §10.13/§10.25
finding against this project's own mt_trig/mt_rebind fixes, both of which stopped
CPU-side work for a muted track's trig but had ZERO hardware effect. octabam's own
"real arm caller" is 0x40006238 (RECORDER ARM specific, per their own measurement),
NOT 0x4000672c (this project's mt_trig target). Static disassembly of the stock
1.40C image (m68k-elf-objdump -m 5307, base 0x40000400 -- confirmed against
build_mutemode.py's own BASE constant, NOT the naive 0x40000000 guess) already shows
the structure:

    40006238: btst #4,%d7        ; bit 4 of the trig word = RECORDER-TRIG flag
    4000623c: beq   0x400066bc   ; clear (ordinary FLEX/STATIC trig) -> bail immediately
    40006240: tstl  %d4          ; set (recorder trig) -> machine-type check (PICKUP?)
    40006242: beq   0x40006714   ; ... continues into the recorder-arm body

The caller (0x4000607c: tstb %d7 / bgew 0x40006238) branches here whenever the trig
word's SIGN bit (bit 7, a timing byte per §10.13 point 5) is clear -- unconditional on
recorder-vs-ordinary. So 0x40006238 as an ADDRESS is entered for both kinds of trig.
But everything of substance -- the FUN_40097168 call, the 0x00000101 record-header
write, the arena bookkeeping -- sits behind the SECOND gate (btst #4), 2 instructions
in, and an ordinary trig takes the beq and does nothing.

This is the dynamic half of that claim: watch 0x40006238 across a real sequencer run
on the OT DEMO project used by dynamic5/9/11/12 (ordinary FLEX/STATIC trigs, no
recorder armed) and record, for every hit, D7's bit 4 and which of the two exits
(0x400066bc "bail" vs the recorder-arm body past 0x40006246) got taken.

    python3 tools/emu_mute_dynamic13.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import struct
import subprocess
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

MUTE_STATE = 0x80000008
GATE = 0x800000dc
T_MUTED = 0

ARM_CALLER = 0x40006238    # octabam's RTOS_FORK.md §10.13/§10.25 "real arm caller"
BIT4_BAIL = 0x400066bc     # taken when btst #4,%d7 is clear -- ordinary (non-recorder) trig
RECORDER_BODY = 0x40006246 # first instruction past both gates -- true recorder-arm work


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    rt.uc.mem_write(GATE, struct.pack(">I", 1))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + T_MUTED)))

    entries = []

    def on_entry(u, addr, size, ctx):
        d7 = u.reg_read(er.eb.UC_M68K_REG_D7)
        d3 = u.reg_read(er.eb.UC_M68K_REG_D3)  # track index, by this function's own convention
        bit4 = (d7 >> 4) & 1
        entries.append((rt.frame_count, d3 & 0xff, d7 & 0xffffffff, bit4))
    h1 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_entry, begin=ARM_CALLER, end=ARM_CALLER + 1)

    exits = []

    def on_exit(u, addr, size, ctx):
        exits.append((rt.frame_count, "bail(ordinary)" if addr == BIT4_BAIL else "recorder-body"))
    h2 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_exit, begin=BIT4_BAIL, end=BIT4_BAIL + 1)
    h3 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_exit, begin=RECORDER_BODY, end=RECORDER_BODY + 1)

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing 6000ms, instrumenting every 0x40006238 (octabam arm-caller) entry...")
    rt.run(ms=6000)
    rt.uc.hook_del(h1)
    rt.uc.hook_del(h2)
    rt.uc.hook_del(h3)

    print(f"\n{len(entries)} entries at {ARM_CALLER:#x}:")
    for (frame, trk, d7, bit4), (eframe, etag) in zip(entries, exits):
        print(f"    frame={frame:<6d} D3(track)={trk} D7={d7:#010x} bit4(rec-flag)={bit4} -> {etag}")
    if len(entries) != len(exits):
        print(f"  !! entries ({len(entries)}) != exits ({len(exits)}) -- something reached one of "
              f"the exit sites without going through {ARM_CALLER:#x}'s own entry, or vice versa "
              f"(e.g. a nested/recursive hit, or PC landing inside the watched byte from elsewhere)")

    n_bail = sum(1 for _, t in exits if t == "bail(ordinary)")
    n_body = sum(1 for _, t in exits if t == "recorder-body")
    print(f"\nsummary: {len(entries)} total hits, {n_bail} bailed at bit4==0 (ordinary trig), "
          f"{n_body} entered the recorder-arm body (bit4==1)")
    if n_body == 0 and len(entries) > 0:
        print("-> CONFIRMED: 0x40006238 is reached on ordinary trigs but ALWAYS bails out in 2 "
              "instructions (btst #4,%d7 / beq) without doing any real work -- dead end for the "
              "mute-mode bug, matches the static read. Real gap is elsewhere (DSP side, most likely).")
    elif len(entries) == 0:
        print("-> 0x40006238 was NEVER reached in this run at all -- inconsistent with the caller "
              "at 0x4000607c being unconditional on trig type; re-check the bgew's own condition "
              "(d7 sign bit) against what real trigs actually carry.")
    else:
        print("-> unexpected: the recorder-arm body executed during an ordinary-trig run -- "
              "this project's demo project may have a recorder-armed track after all, or bit 4 "
              "is not what it's assumed to be. Needs a look before concluding anything.")


if __name__ == "__main__":
    main()

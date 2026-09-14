#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 49 -- differential test for report #1 (Elektronauts, Open_Mike + a second
reporter): switching from a pattern/Part with a PICKUP machine on a track to a
pattern/Part with a FLEX machine on the same track plays the old PICKUP loop instead
of the new FLEX sample -- but the SAME switch to a STATIC machine works correctly.

Diffs two scenarios in one boot (same track, same everything else) instead of guessing
which function matters from static disassembly first: PICKUP(idle)->FLEX vs
PICKUP(idle)->STATIC. Watches which of the 3 candidate sample-arena entries actually
gets READ, and where the voice struct's SETTINGS pointer (0x800049d8+track*0xA8+8)
ends up, after the switch commits and the first new trig lands.

STATUS (end of Session 49, handed off -- see NOTES.md "Session 49" HANDOFF section):
Two runs so far both showed **correct** resolution in BOTH the FLEX and the STATIC
case (SETTINGS pointer landed on the right arena entry, right slot, no bug reproduced)
-- but BOTH runs failed to establish the bug's actual precondition first: a real prior
trig has to land on the PICKUP machine (genuinely binding the voice to the PICKUP
arena entry, matching "the pickup machine ran at some point") before the track goes
idle and the switch happens. P1/T1 in the factory OT DEMO trigs on nearly every step,
but the FIRST real trig from a cold pattern start doesn't land until roughly frame
1300-1600 (empirically, base = ``FRAME_PERIOD=16`` samples/frame, ~44.1kHz) -- the
original 200-frame bind budget never reached it. Fixed here: the bind phase now runs
until a trig genuinely lands (or a generous frame ceiling, whichever first) and
ASSERTS the voice's SETTINGS pointer actually equals the PICKUP entry before
proceeding -- if that assertion fails, nothing after it should be trusted, and the
script says so instead of silently continuing on an unmet precondition (a mistake
this script itself made twice before this fix).

NOT YET TESTED (the real open question): whether reproduction additionally needs a
Part change committed WHILE THE TRANSPORT IS RUNNING (a live pattern-boundary
commit), vs. the stop-switch-restart sequence this script uses (the only reliably
*committing* method found so far -- `seq_select_live` while playing just queues the
change for the next pattern boundary, which is 1000s of frames out and wasn't
reached in any run this session). If the fixed bind-phase still shows correct
resolution on a stopped-then-restarted switch, the bug may be specific to the live
commit path, which needs its own harness (drive playback until the *current*
pattern's step count is reached, not a fixed frame budget).

    python3 tools/diff_flex_static.py

~8-12 min wall (two full transitions, each waiting for a real trig from a cold
pattern start). Needs `python3 tools/refs/sync.py` + the EMAC-patched Unicorn
(`refs/octabam/scripts/build_unicorn.sh`), same as the other `emu_*` tools.
"""
import os
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
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

PART_STRIDE = 0x18b2
MACHINE_OFF = 0x22
PARTS_OFF = 0x8ed80
SLOT_BASE = 0x8f04a        # blob + part*0x18b2 + 0x8f04a + track*5 + type = slot byte
FLEX_ARENA = 0x100b14f0
STATIC_ARENA = 0x100d5b30
ARENA_STRIDE = 1096
VOICE_BASE = 0x800049d8
VOICE_STRIDE = 0xA8
T = 0  # track 1

WATCH_LOW, WATCH_HIGH = 0x80000800, 0x80001900   # pre-image/cache/scene-buf/markers band
BAIL_WORD = 0x46c80354
BIND_FRAME_CEILING = 3000    # generous; real first trig observed ~1300-1600 from cold


def machine_addr(blob, part):
    return blob + PARTS_OFF + part * PART_STRIDE + MACHINE_OFF + T


def slot_addr(blob, part, typ):
    return blob + part * PART_STRIDE + SLOT_BASE + T * 5 + typ


def main():
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(STOCK_IMAGE), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank}")

    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    curbank = rt.uc.mem_read(0x80000002, 1)[0]

    flex_slot = rt.uc.mem_read(slot_addr(blob, 1, 1), 1)[0]         # Part1/T1's real FLEX slot
    static_slot = rt.uc.mem_read(blob + 3 * PART_STRIDE + SLOT_BASE + 7 * 5 + 0, 1)[0]  # Part3/T8's real STATIC slot
    print(f"Part1/T1 real FLEX slot = {flex_slot}   Part3/T8 real STATIC slot = {static_slot}")

    rt.uc.mem_write(machine_addr(blob, 0), b"\x04")                 # Part0/T1 -> PICKUP
    rt.uc.mem_write(slot_addr(blob, 0, 4), bytes([128 + T]))
    rt.uc.mem_write(machine_addr(blob, 2), b"\x00")                 # Part2/T1 -> STATIC (real, loaded slot)
    rt.uc.mem_write(slot_addr(blob, 2, 0), bytes([static_slot]))
    print(f"poked: Part0/T1=PICKUP(slot {128+T})  Part2/T1=STATIC(slot {static_slot})  "
          f"Part1/T1=FLEX(slot {flex_slot}, untouched)")

    pickup_entry = FLEX_ARENA + (128 + T) * ARENA_STRIDE
    flex_entry = FLEX_ARENA + flex_slot * ARENA_STRIDE
    static_entry = STATIC_ARENA + static_slot * ARENA_STRIDE
    print(f"arena entries: pickup={pickup_entry:#010x}  flex={flex_entry:#010x}  static={static_entry:#010x}")

    # The report's precondition is a PICKUP machine that is "already linked to a sample"
    # (a real prior capture), just idle before the switch -- a bare machine-type poke
    # leaves the PICKUP arena entry (slot 128+T) empty (measured: 12 nonzero bytes out of
    # 1096, no path string), and an empty PICKUP entry never gets a trig scheduled at all
    # (measured: T1 goes fully silent, voice struct never leaves active=0/SETTINGS=0).
    # Seed it with a clone of the real, loaded FLEX entry's bytes so it reads as populated
    # -- the test only distinguishes ENTRIES by address (which band gets read, where the
    # voice SETTINGS pointer lands), not by content, so identical file content in two
    # slots does not confound it.
    pickup_seed = rt.uc.mem_read(flex_entry, ARENA_STRIDE)
    rt.uc.mem_write(pickup_entry, bytes(pickup_seed))
    print(f"seeded pickup_entry with a clone of flex_entry's loaded-sample bytes "
          f"({sum(1 for b in pickup_seed if b)} nonzero of {ARENA_STRIDE}) so PICKUP is "
          f"'already linked to a sample', per the report's stated precondition")

    reads = {"pickup_entry": [], "flex_entry": [], "static_entry": []}

    def mk_read_hook(tag):
        def h(u, acc, a, sz, val, d):
            reads[tag].append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_PC), a, sz))
        return h
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk_read_hook("pickup_entry"), begin=pickup_entry, end=pickup_entry + ARENA_STRIDE - 1)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk_read_hook("flex_entry"), begin=flex_entry, end=flex_entry + ARENA_STRIDE - 1)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk_read_hook("static_entry"), begin=static_entry, end=static_entry + ARENA_STRIDE - 1)

    writes = []

    def on_write(u, acc, a, sz, val, d):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc in (0x40006b80, 0x40006b8e):   # inactive-voice idle-zero loop -- noise
            return
        writes.append((rt.frame_count, pc, a, sz, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=WATCH_LOW, end=WATCH_HIGH - 1)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=BAIL_WORD, end=BAIL_WORD + 3)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=VOICE_BASE, end=VOICE_BASE + VOICE_STRIDE - 1)
    rt.uc.ctl_flush_tb()

    def voice_settings():
        vb = rt.uc.mem_read(VOICE_BASE, VOICE_STRIDE)
        return vb[0], int.from_bytes(vb[8:12], 'big'), vb[32]

    def snapshot(label):
        active, settings, slice_idx = voice_settings()
        print(f"  [{label}] voice T1: active(+0)={active:#x}  SETTINGS(+8)={settings:#010x}  slice(+32)={slice_idx}")
        print(f"  [{label}] reads: pickup_entry={len(reads['pickup_entry'])}  flex_entry={len(reads['flex_entry'])}  "
              f"static_entry={len(reads['static_entry'])}")
        print(f"  [{label}] writes in watched band: {len(writes)}")

    def bind_pickup_then_idle():
        """P1/Part0/T1 = PICKUP, trigs on nearly every step. Run for real (not just
        poked bytes) until the voice genuinely binds to the PICKUP arena entry, or
        bail loudly if it never does -- don't let a later phase run on an unmet
        precondition, which is exactly what happened twice before this fix."""
        rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        rt.seq_select_live(curbank, 0)
        rt.run(ms=500)
        rt.internal_clock()
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.install_trig_log()
        rt.start_transport_live()
        tgt = rt.frame_count + BIND_FRAME_CEILING
        rt.run(ms=90000, until=lambda r: r.frame_count >= tgt or voice_settings()[1] == pickup_entry)
        active, settings, _ = voice_settings()
        trigs_t1 = [t for t in rt.live_nibble_log if t[1] == T]
        print(f"  bind phase: frame={rt.frame_count}  trigs on T1={trigs_t1}  SETTINGS={settings:#010x} "
              f"(want {pickup_entry:#010x})")
        if settings != pickup_entry:
            sys.exit("BIND FAILED -- voice never bound to the PICKUP arena entry within "
                     f"{BIND_FRAME_CEILING} frames. Precondition not met; raise BIND_FRAME_CEILING "
                     "or re-check the trig data / step timing before trusting anything past this point.")
        rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")   # now go idle: stop ("not running before switching")
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        active, settings, _ = voice_settings()
        print(f"  after stop: active(+0)={active:#x}  SETTINGS(+8)={settings:#010x} (bound, now idle -- matches the report)")

    def run_transition(pat_index, label):
        bind_pickup_then_idle()
        for k in reads:
            reads[k].clear()
        writes.clear()
        rt.seq_select_live(curbank, pat_index)
        rt.run(ms=500)
        rt.internal_clock()
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.install_trig_log()
        tgt = rt.frame_count + 300
        rt.start_transport_live()
        rt.run(ms=15000, until=lambda r: r.frame_count >= tgt)
        print(f"\n===== {label}: switched to pattern index {pat_index}, ran to frame {rt.frame_count} =====")
        print(f"  trigs on T1: {[t for t in rt.live_nibble_log if t[1] == T]}")
        snapshot(label)

    run_transition(4, "PICKUP(bound,idle)->FLEX (P1->P5)")
    print(f"\nre-check pokes before 2nd transition: Part0/T1 machine={rt.uc.mem_read(machine_addr(blob,0),1)[0]}  "
          f"Part2/T1 machine={rt.uc.mem_read(machine_addr(blob,2),1)[0]}")
    run_transition(8, "PICKUP(bound,idle)->STATIC (P1->P9)")


if __name__ == "__main__":
    main()

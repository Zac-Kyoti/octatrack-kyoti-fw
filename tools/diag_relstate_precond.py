#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Throwaway diagnostic (Session 58 continued yet again, part 8): emu_relstate_shadow.py's
first two runs showed IDENTICAL write counts whether or not `poke_trig` forced 16 extra
T1 trigs -- meaning either poke_trig had no effect, or the metric can't tell "more trigs"
from ordinary per-frame level-chain writes anyway (a continuously-sounding voice writes
a gain value every frame with or without a NEW trig). Before iterating on the test
scenario further, check the PRECONDITION directly: does 0x4000bf22 (the stock function
that transiently clears a muted track's REL_STATE bit) even fire for T1 during the muted
window in this project, with or without the forced pokes?

    python3 tools/diag_relstate_precond.py [--poke]
"""
import argparse
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
BOTLI = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "BOTLI"

import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402

MUTE_STATE = 0x80000008
GATE = 0x800000dc
REL_STATE = 0x8000184a
BF22 = 0x4000bf22
MT_TRIG = 0x40006844
FRESH_BIND = 0x40006820


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poke", action="store_true")
    ap.add_argument("--ms", type=int, default=3000)
    args = ap.parse_args()

    card, name = er.stage_project(str(BOTLI), "OCTABAM", None)
    r, rt = er.attach(str(ROOT / "out/mainos_mutemode_dt.bin"), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    if args.poke:
        # BUG found this session: `poke_trig` is hardcoded to TRAC record offset 0 (its own
        # docstring's "track 1" = zero-based slot 0), but the track this script mutes via
        # MUTE_STATE bit 8+1 is zero-based slot 1 -- a DIFFERENT physical track. Verified
        # directly: before/after mask bytes were byte-identical, i.e. poke_trig touched a
        # track nothing here mutes or watches. Use `poke_mask(0x00, step, track=1)` instead,
        # which takes an explicit zero-based `track` and multiplies by TRAC_STRIDE -- the
        # same index MUTE_STATE bit 8+1 and REL_STATE bit 1 already use.
        before = [rt.uc.mem_read(rt.pattern_base() + 1 * 0x91a + 7 - (s - 1) // 8, 1)[0]
                  for s in range(1, 9)]
        for step in range(1, 65, 4):
            rt.poke_mask(0x00, step, track=1)
        after = [rt.uc.mem_read(rt.pattern_base() + 1 * 0x91a + 7 - (s - 1) // 8, 1)[0]
                 for s in range(1, 9)]
        print(f"poke_mask(track=1): T1 mask bytes[0:8] before={[hex(b) for b in before]} "
              f"after={[hex(b) for b in after]}")

    rt.uc.mem_write(GATE, struct.pack(">I", 1))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + 1)))
    mute_frame = rt.frame_count
    print(f"muted T1 at frame {mute_frame}")

    bf22_hits = []
    mt_trig_hits = []
    fresh_bind_hits = []

    def on_bf22(u, addr, size, ctx):
        # per earlier RE (NOTES.md "Session 58 continued again"): `moveb REL_STATE,%d0 /
        # andl %d4,%d0 / moveb %d0,REL_STATE` -- %d4 is the AND-mask, ~(1<<track) for
        # whichever track this call clears. Recover track = the zero bit's position.
        d4 = u.reg_read(er.eb.UC_M68K_REG_D4) & 0xff
        cleared_track = (~d4 & 0xff).bit_length() - 1 if (~d4 & 0xff) else None
        rel = u.mem_read(REL_STATE, 1)[0]
        bf22_hits.append((rt.frame_count, rel, d4, cleared_track))

    def on_mt_trig(u, addr, size, ctx):
        mt_trig_hits.append(rt.frame_count)

    def on_fresh_bind(u, addr, size, ctx):
        fresh_bind_hits.append(rt.frame_count)

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_bf22, begin=BF22, end=BF22 + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_mt_trig, begin=MT_TRIG, end=MT_TRIG + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fresh_bind, begin=FRESH_BIND, end=FRESH_BIND + 1)
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=args.ms)

    print(f"ran to frame {rt.frame_count} ({rt.frame_count - mute_frame} frames muted)")
    print(f"0x4000bf22 fired {len(bf22_hits)} times total during the run")
    print(f"mt_trig (0x40006844) fired {len(mt_trig_hits)} times -- these are the actual "
          f"per-trig voice-start dispatches, muted or not, ANY track")
    print(f"fresh_bind (0x40006820) fired {len(fresh_bind_hits)} times -- fresh-voice-bind "
          f"entries, ANY track")
    if bf22_hits:
        print("first 30 bf22 hits (frame, REL_STATE just before the clear, D4 mask, "
              "inferred cleared track):")
        for f, rel, d4, ct in bf22_hits[:30]:
            print(f"    frame={f:<6d} REL_STATE={rel:#04x} D4={d4:#04x} "
                  f"cleared_track={ct}  (T1-bit-set-at-hit={'YES' if rel & 2 else 'no'})")


if __name__ == "__main__":
    main()

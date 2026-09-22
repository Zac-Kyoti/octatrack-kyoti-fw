#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 58 continued yet again, part 8: validates hook 13 (`relstate_shadow`,
tools/patch_softmute.s / tools/build_relstate_shadow.py) against the REL_STATE race it
was built to close -- the "first pattern pass after mute" blip (Bug A), NOT the hook-12
silence regression (Bug B, already reverted and out of scope here; see NOTES.md "part 3"
onward). This fix lives entirely in the cold, ~8-iterations/frame release loop `relcut`
(hook 8) already runs in safely -- nowhere near the 100+/frame EMAC level-chain loops
hook 12 broke -- so this script only needs route A (`emu_rtos.py`, no DSP/audio), exactly
like the ColdFire-only mechanism itself.

Mutes track 1 (T1, the same track every prior session in this thread used), runs the real
sequencer over a real project for long enough to cover many pattern passes, and watches
BOTH ping buffers' T1 level words (`+2`/`+4` off `0x80000110/0x80000310 + track*0x40`,
per `kb/memory-map.md`) for ANY nonzero write after the initial mute-engage settle window
(a handful of frames, matching `pre`'s own known SHADOW-catch-up delay -- established
harmless in "part 2, CORRECTED"). Runs the IDENTICAL scenario against TWO images:

  - the CURRENT hardware-good baseline (`out/mainos_mutemode_dt.bin`, relcut alone) --
    expected to REPRODUCE the known leak (a sanity check on this harness itself: if the
    baseline shows NO leak either, the scenario doesn't exercise the race and a clean
    result from the candidate build would be meaningless)
  - the candidate (`out/mainos_relstate_shadow.bin`, hook 13) -- expected to show NONE

    python3 tools/emu_relstate_shadow.py [--ms 3000] [--track 1]
"""
import argparse
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
BOTLI = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "BOTLI"
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

MUTE_STATE = 0x80000008
GATE = 0x800000dc
SETTLE_FRAMES = 30   # generous vs the ~few-frame SHADOW-catch-up settle "part 2, CORRECTED" found


def run_scenario(img_path, track, ms, project_dir, gate=1):
    card, name = er.stage_project(str(project_dir), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"  boot: {r.stopped}")

    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"  load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    # Force DENSE retriggering on `track`, rather than hoping the raw export's own pattern
    # happens to retrig it often enough within the run -- a first attempt at this exact
    # scenario (this session) muted track 1 in BOTLI's own unmodified pattern and saw ZERO
    # retrigs coincide with the race in 8269 frames. `poke_trig` (tried first) turned out to
    # be hardcoded to TRAC record offset 0 regardless of which track is actually muted -- a
    # real bug caught via `tools/diag_relstate_precond.py` (before/after mask bytes were
    # byte-identical, proving it silently touched the wrong track). `poke_mask(0x00, step,
    # track=track)` takes an explicit zero-based track and writes the SAME index MUTE_STATE/
    # REL_STATE already use -- verified via the same diagnostic (mask bytes actually
    # changed, AND 0x4000bf22 was then observed clearing exactly this track's REL_STATE bit
    # 4 times in an 8269-frame run). Writes a real trig bit into the CURRENT pattern's live,
    # in-RAM step mask (the same path a key-press would produce, not a fabricated file) --
    # legitimate under this project's "no hand-edited project files" rule since nothing on
    # the CARD is touched. Every 4th step, 16 trigs over a 64-step pattern.
    for step in range(1, 65, 4):
        rt.poke_mask(0x00, step, track=track)

    # engage mute on `track` (gate=1 OT+FX, gate=2 DT)
    rt.uc.mem_write(GATE, struct.pack(">I", gate))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + track)))
    mute_frame = rt.frame_count

    # Watch each level word (+2, +4) SEPARATELY and narrowly (2 B each) -- both `relcut`'s
    # clear and the level-chain's own write are plain `clrw`/`movew` (2-byte WORD stores,
    # confirmed directly off the stock disassembly this session); a size!=2 hit here is a
    # DIFFERENT, unrelated field's wider store merely overlapping this narrow window, not
    # this mechanism, and is filtered out below. Per-FRAME LAST-WRITE-WINS is what matters:
    # the level-chain writes a fresh (nonzero) value EVERY frame regardless of mute (that's
    # stock, unavoidable, and NOT what this fix touches) -- what this fix guarantees is that
    # relcut's own zero, when the track is muted, is the LAST write of the frame, so the
    # value actually held by the time the DSP reads it is 0. Counting "any nonzero write"
    # would flag every frame on EVERY build, working or not.
    def make_watch(addr):
        last = {}

        def on_write(u, acc, a, size, val, user):
            if size == 2 and a == addr:
                last[rt.frame_count] = val
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=addr, end=addr + 1)
        return last

    ping0_dry = make_watch(0x80000110 + track * 0x40 + 2)
    ping0_route = make_watch(0x80000110 + track * 0x40 + 4)
    ping1_dry = make_watch(0x80000310 + track * 0x40 + 2)
    ping1_route = make_watch(0x80000310 + track * 0x40 + 4)
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=ms)

    # A frame LEAKS iff the RESTING (last-written) value of either level word, for a frame
    # that actually saw a write, is nonzero after the settle window -- i.e. relcut's zero
    # was not the last thing written that frame.
    leaks = []
    n_writes = 0
    for label, d in (("ping0-dry(+2)", ping0_dry), ("ping0-route(+4)", ping0_route),
                     ("ping1-dry(+2)", ping1_dry), ("ping1-route(+4)", ping1_route)):
        n_writes += len(d)
        for frame, val in sorted(d.items()):
            if frame - mute_frame < SETTLE_FRAMES:
                continue
            if val != 0:
                leaks.append((label, frame, val))
    return mute_frame, rt.frame_count, n_writes, leaks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ms", type=int, default=3000)
    ap.add_argument("--track", type=int, default=1)
    ap.add_argument("--project", default=str(BOTLI))
    ap.add_argument("--gate", type=int, default=1, help="1=OT+FX, 2=DT")
    ap.add_argument("--baseline", default="out/mainos_mutemode_dt.bin")
    args = ap.parse_args()
    project_dir = pathlib.Path(args.project)
    if not project_dir.is_dir():
        sys.exit(f"missing project dir {project_dir} -- falling back needs --project")

    images = [
        ("BASELINE (relcut alone, hardware-good, EXPECTED to leak)",
         ROOT / args.baseline),
        ("CANDIDATE (hook 13 relstate_shadow, EXPECTED clean)",
         ROOT / "out/mainos_relstate_shadow.bin"),
    ]

    results = {}
    for label, path in images:
        if not path.exists():
            sys.exit(f"missing {path}")
        print(f"\n=== {label}: {path.name} ===")
        mute_frame, end_frame, n_writes, leaks = run_scenario(
            path, args.track, args.ms, project_dir, gate=args.gate)
        print(f"  muted T{args.track} at frame {mute_frame}, ran to frame {end_frame} "
              f"({end_frame - mute_frame} frames muted)")
        print(f"  {n_writes} total word-writes to the four level-word slots, "
              f"{len(leaks)} frames with a nonzero RESTING value after the "
              f"{SETTLE_FRAMES}-frame settle window")
        for label2, frame, val in leaks[:30]:
            print(f"    LEAK  frame={frame:<6d} (+{frame - mute_frame:<5d} since mute)  "
                  f"{label2}  resting val={val:#x}")
        if len(leaks) > 30:
            print(f"    ... and {len(leaks) - 30} more")
        results[path.name] = leaks

    print("\n=== verdict ===")
    baseline_leaks = results[images[0][1].name]
    candidate_leaks = results[images[1][1].name]
    if not baseline_leaks:
        print("!! baseline shows NO leak either -- this scenario does not exercise the race "
              "(wrong project/track/timing, or the race needs a richer trigger than this run "
              "provides). A clean candidate result is NOT meaningful until the baseline is "
              "made to reproduce the known leak first.")
    elif not candidate_leaks:
        print(f"baseline leaked {len(baseline_leaks)} time(s) (as expected -- harness is sound); "
              f"candidate leaked ZERO times over the same scenario. Consistent with the fix "
              f"working, on this one scenario/project/track.")
    else:
        print(f"baseline leaked {len(baseline_leaks)} time(s); candidate ALSO leaked "
              f"{len(candidate_leaks)} time(s) -- the fix did NOT close the race in this "
              f"scenario. Needs investigation before trusting hook 13.")


if __name__ == "__main__":
    main()

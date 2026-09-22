#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
MUTE MODE / hook-12 aftermath (NOTES.md "Session 58 continued yet again, part 4/5"):
tests the MACSR-corruption hypothesis for why `levelchain_mute` (hook 12) passed
emulator validation but made ALL audio in OT+FX/DT go silent on real hardware.

The hypothesis: the per-frame copier function (`0x4000cae8`) runs the EMAC at
MACSR=0x60 (fractional, S/U=1) across four back-to-back level-chain loops
(`0x4000ccae`/`cd22`/`cd64`/`ce40` -- hook 12's own site, `0x4000ced0/ced4`, is the
last of these four), then later -- still the SAME function, no `rts` in between --
sets MACSR to other values (`0x4000cf60`, `0x4000d3ae`). The RTOS's own task-switch
code (`0x40000550`) never saves/restores MACSR (only d0-d7/a0-a7). So IF this
function's MACSR=0x60 window (`0x4000cc68..0x4000cf60`) is ever preempted by a PIT0
tick (5.0 ms / 220.5 samples) and some UNRELATED task also touches the EMAC while
it's paused, the resumed function would read back corrupted values for the rest of
its own pass -- consistent with "every track silent," not just muted ones. Full
writeup + citations: `NOTES.md` "part 4" and "part 5", `reference/kb/memory-map.md`
"Kernel / RTOS scheduler".

This does NOT rebuild or touch hook 12 (its source isn't in the working tree --
see "part 3"). It only asks the FIRST, cheapest question "part 5" posed: **on the
current, hardware-confirmed-good baseline (no hook 12), does a scheduler dispatch
EVER resume execution inside that MACSR=0x60 window at all, across a real project
load and a real sequencer run?** octabam's own `emu_rtos.py` already logs exactly
this (`Rtos.dispatches`, `(sample, tcb, pc)` at every scheduler `rte` -- see
`_pop()`/`SCHED_RTE` in `refs/octabam/tools/emu/emu_rtos.py`), so no new Unicorn
hooks are needed -- this script just runs a normal route-A session and filters the
log. If NO dispatch ever lands in the window, hook 12's own instinct ("this PC is
too hot to touch") likely needs a different, non-MACSR explanation, per "part 5"'s
own "if it NEVER does even once ... this whole theory is likely dead." If some DO,
the follow-up (not built here) is a second run with hook 12 rebuilt, to see whether
its added cycles change the hit rate.

    python3 tools/emu_macsr_race.py [out/mainos_mutemode_dt.bin] [--ms 6000]
"""
import argparse
import pathlib
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
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

# The copier's MACSR=0x60 window: right after `movel #96,%macsr` (0x4000cc62,
# 6 bytes) up to (not including) the first instruction of the NEXT macsr write
# (`0x4000cf60`, register-sourced -- confirmed via `m68k-elf-objdump -m m68k:cfv4e`,
# NOTES.md "part 5"). Covers all four level-chain siblings (ccae/cd22/cd64/ce40),
# including hook 12's own site at ced0/ced4.
WINDOW_LO = 0x4000cc68
WINDOW_HI = 0x4000cf60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default="out/mainos_mutemode_dt.bin")
    ap.add_argument("--ms", type=int, default=6000, help="emulated playback time, ms")
    args = ap.parse_args()

    img_path = ROOT / args.image
    if not img_path.exists():
        sys.exit(f"missing {img_path}")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"[emu_macsr_race] image={img_path.name}  boot: {r.stopped}")

    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    n_dispatches_before = len(rt.dispatches)
    switches_before, forces_before = rt.switches, rt.forces
    frames_before, ticks_before = rt.frame_count, rt.tick_count

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print(f"playing {args.ms} ms, watching every scheduler dispatch's resume PC "
          f"against the MACSR=0x60 window [{WINDOW_LO:#x}, {WINDOW_HI:#x})...")
    rt.run(ms=args.ms)

    new_dispatches = rt.dispatches[n_dispatches_before:]
    in_window = [(s, tcb, pc) for (s, tcb, pc) in new_dispatches if WINDOW_LO <= pc < WINDOW_HI]

    print(f"\n{len(new_dispatches)} scheduler dispatches during the {args.ms} ms run "
          f"({rt.switches - switches_before} task switches, "
          f"{rt.forces - forces_before} PIT0/INTFRC forces, "
          f"{rt.frame_count - frames_before} DSP frames, "
          f"{rt.tick_count - ticks_before} sequencer ticks)")
    print(f"{len(in_window)} of those dispatches resumed with PC inside the MACSR=0x60 "
          f"window:")
    for s, tcb, pc in in_window[:50]:
        print(f"    sample={s:<10.0f}  tcb={rt._name(tcb):<20}  pc={pc:#x}")
    if len(in_window) > 50:
        print(f"    ... and {len(in_window) - 50} more")

    if not in_window:
        print("\n-> NEVER observed on this baseline/scenario: no scheduler dispatch "
              "resumed inside the MACSR=0x60 window in this run. Consistent with "
              "'part 5's own falsification criterion -- does NOT prove the window is "
              "unreachable (longer run / different project / hook-12's added cycles "
              "could still tip it), but this specific run gives zero support to the "
              "MACSR-corruption hypothesis as the hardware root cause.")
    else:
        distinct_tcbs = {tcb for _, tcb, _ in in_window}
        print(f"\n-> CONFIRMED: this code IS preemptible in practice -- {len(in_window)} "
              f"dispatch(es) resumed mid-window, from {len(distinct_tcbs)} distinct task(s) "
              f"({', '.join(rt._name(t) for t in distinct_tcbs)}). This answers 'part 5's "
              f"open unknown (a) for this baseline: YES, a PIT0/scheduler event can land "
              f"inside the copier's own MACSR=0x60 span even on the CURRENT, hardware-good "
              f"build. Does not yet prove hook 12's added cycles made this WORSE (needs a "
              f"second run with hook 12 rebuilt) or that a same-task resume actually left "
              f"MACSR corrupted (needs checking whether any code ran the EMAC in between at "
              f"a different MACSR) -- but this is no longer purely theoretical.")


if __name__ == "__main__":
    main()

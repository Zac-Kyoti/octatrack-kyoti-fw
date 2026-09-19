#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Hardware report (Session 58 continued yet again, part 10): flashing the hook-13
candidate, WITHOUT MUTING ANYTHING, changed ordinary OT+FX/DT playback -- every note's
envelope/release sounds shortened, "amp hold reduced to trig length". Never tested before:
`relcut` only checks GATE (is MUTE MODE on at all), NOT whether the SPECIFIC track is
actually muted, before zeroing the second level word (+4, previously clamped to 6144 by
stock). REL_STATE ("voice t in RELEASE") is described everywhere in this file as a STOCK,
per-voice byte, not something exclusive to the mute feature -- so if stock ALSO sets a
track's REL_STATE bit during its own ordinary, natural AMP release (nothing muted at
all), relcut would zero +4 for that voice too, changing the natural release tail's second-
channel behaviour EVEN WITH NOTHING MUTED. If true, this predates hook 13 entirely --
Session 58's own relcut, unmodified.

Checks directly: for a track with NOTHING muted (GATE toggled 0 vs 1, MUTE_STATE left at
0 throughout), does REL_STATE's bit ever go high (implying relcut runs at all for it),
and if so, does +4 actually get zeroed (GATE=1) vs left alone/clamped (GATE=0) for that
same natural-release episode? Runs on `out/mainos_mutemode_dt_BASELINE.bin` (relcut
alone, no hook 13) -- if the effect shows up there too, it is NOT a hook-13 regression.

    python3 tools/diag_relcut_unmuted.py [image] [--track 1] [--ms 4000]
"""
import argparse
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
BOTLI = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "BOTLI"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402

GATE = 0x800000dc
REL_STATE = 0x8000184a
MUTE_STATE = 0x80000008


def run(img_path, track, ms, gate):
    card, name = er.stage_project(str(BOTLI), "OCTABAM", None)
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

    rt.poke_mask(0x00, 1, track=track)  # single sparse trig -- let it fully decay

    # BUG caught this session: this project's own SAVED state loads with MUTE_STATE's
    # mute byte already 0x3d (tracks 0,2,3,4,5 pre-muted) -- confirmed via
    # /tmp/check_solo.py. Earlier runs of this script never explicitly cleared
    # MUTE_STATE, so "nothing muted" was actually testing an ALREADY-muted track
    # whenever `track` was one of those five. Explicitly zero it now for a genuinely
    # clean unmuted control, regardless of the project's own saved state.
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 0))
    rt.uc.mem_write(GATE, struct.pack(">I", gate))

    rel_state_log = []
    route_log = {}   # frame -> last-written value of +4 (word write only)
    dry_log = {}

    def on_rel(u, acc, a, size, val, user):
        rel_state_log.append((rt.frame_count, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_rel, begin=REL_STATE, end=REL_STATE)

    def on_route(u, acc, a, size, val, user):
        if size == 2:
            route_log[rt.frame_count] = val
    def on_dry(u, acc, a, size, val, user):
        if size == 2:
            dry_log[rt.frame_count] = val

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_route,
                    begin=0x80000110 + track * 0x40 + 4, end=0x80000110 + track * 0x40 + 5)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_dry,
                    begin=0x80000110 + track * 0x40 + 2, end=0x80000110 + track * 0x40 + 3)
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=ms)

    rel_high = [f for f, v in rel_state_log if v & (1 << track)]
    zero_route_frames = [f for f, v in sorted(route_log.items()) if v == 0]
    return rt.frame_count, len(rel_state_log), rel_high[:10], len(route_log), \
        len(zero_route_frames), zero_route_frames[:15]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default="out/mainos_mutemode_dt_BASELINE.bin")
    ap.add_argument("--track", type=int, default=1)
    ap.add_argument("--ms", type=int, default=4000)
    args = ap.parse_args()
    img_path = ROOT / args.image
    if not img_path.exists():
        sys.exit(f"missing {img_path}")

    for gate in (0, 1):
        print(f"\n=== {img_path.name}  GATE={gate}  (nothing muted, MUTE_STATE stays 0) ===")
        end_frame, n_rel_writes, rel_high, n_route_writes, n_zero, zero_frames = run(
            img_path, args.track, args.ms, gate)
        print(f"  ran to frame {end_frame}")
        print(f"  REL_STATE written {n_rel_writes} times; track {args.track}'s bit was SET "
              f"at {len(rel_high)}+ of those writes (first few frames: {rel_high})")
        print(f"  +4 (route) word-written {n_route_writes} times; {n_zero} of those writes "
              f"were VALUE 0 (frames: {zero_frames})")
        if gate == 1 and n_zero > 0:
            print("  -> +4 DOES get zeroed under GATE=1 even with NOTHING muted here.")
        elif gate == 1:
            print("  -> +4 never reads 0 under GATE=1 with nothing muted in this run.")


if __name__ == "__main__":
    main()

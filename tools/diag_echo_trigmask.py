#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 58 continued yet again, part 10 continued: hardware report describes a tempo-
locked "echo" after muting -- the trig pattern audibly repeats for a fixed WALL-CLOCK
duration (not a fixed number of pattern cycles), fading out by the second pattern cycle
at 120 BPM. Per the user's own two-part framework (trig masking vs audio path), this
smells like a TRIG-MASKING gap: new trigs still reaching a voice-start dispatch for a
bounded window after the mute engages, not anything about how a note's audio decays.

hooks 9 (`dt_trig`, 0x4000d498) and 10 (`fresh_bind`, 0x40006820) both gate on a plain
`btst MUTE_STATE-bit` with NO timing/counter logic at all -- so if they're working, there
is no mechanism by which trigs could "echo for a bounded duration" at all; muted should
mean muted, instantly, forever, no decay. This script watches whether either hook's
PASS-THROUGH branch (`dt_pass`/`fb_pass` -- the trig reaches the real handler) is EVER
taken for a track AFTER MUTE_STATE's bit for it is set, across several natural pattern
loops with a REAL repeating trig (poked once via `poke_mask`, a legitimate live-RAM edit,
not a fabricated file -- same convention as the race-fix testing this session).

    python3 tools/diag_echo_trigmask.py [image] [--track 4] [--ms 6000]
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
MUTE_STATE = 0x80000008

# hook 9 (dt_trig) / hook 10 (fresh_bind) detour entries -- every dispatch attempt, any track
DT_SILENCE_ENTRY = 0x4000d498
FB_ENTRY = 0x40006820
# exact internal branch targets, read from `m68k-elf-nm out/patch_softmute_rs.elf` --
# these are the ACTUAL decision points: which one runs says definitively whether a given
# dispatch attempt was silenced or let through, unlike a PC hook at the shared entry above
DT_PASS = 0x400d7676     # dt_trig: trig reaches the real per-machine-type handler
DT_SILENCE = 0x400d766e  # dt_trig: trig dropped, handler never runs
FB_PASS = 0x400d76d2     # fresh_bind: falls through to stock's own per-track work
FB_SILENCE = 0x400d76cc  # fresh_bind: skips straight to the shared epilogue, no bind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default="out/mainos_relstate_shadow.bin")
    ap.add_argument("--track", type=int, default=4)
    ap.add_argument("--gate", type=int, default=1, help="1=OT+FX, 2=DT")
    ap.add_argument("--ms", type=int, default=8000)
    ap.add_argument("--project", default=str(BOTLI))
    ap.add_argument("--steps", default="1,5,9,13",
                     help="comma-separated 1-based steps to poke a trig at")
    ap.add_argument("--pre-ms", type=int, default=None,
                     help="unmuted warm-up duration; default is half of --ms")
    args = ap.parse_args()
    img_path = ROOT / args.image
    if not img_path.exists():
        sys.exit(f"missing {img_path}")
    project_dir = pathlib.Path(args.project)
    steps = [int(s) for s in args.steps.split(",")]

    card, name = er.stage_project(str(project_dir), "SCTEST", None)
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

    # a real, repeating trig, SPARSELY spaced (every 32 steps -> 2 hits per 64-step
    # pattern) on `track`, via poke_mask -- a live in-RAM edit of the pattern's own step
    # mask, not a fabricated file (same convention already used to validate the
    # REL_STATE-race fix this session). Spacing matters: a first pass with 8-step spacing
    # came back clean but NEVER exercised fresh_bind (0 hits) -- the voice never actually
    # went cold between retrigs at that density, so the exact path hook 10 was built to
    # guard (a trig landing on a voice already recycled by relcut's note-off) was never
    # tested. Wider spacing gives the note-off + ~45-control-frame watchdog
    # (relparam_46c7dfba, hook 10's own header) comfortable room to actually free the
    # voice before the next trig arrives.
    track = args.track
    for step in steps:
        rt.poke_mask(0x00, step, track=track)

    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 0))
    rt.uc.mem_write(GATE, struct.pack(">I", args.gate))

    dt_hits = []          # (frame, d3=track) -- every trig-dispatch attempt, any track
    fb_hits = []          # (frame, d1=track) -- every fresh-bind attempt, any track
    dt_decisions = []     # (frame, track, "pass"|"silence") -- the ACTUAL branch taken
    fb_decisions = []

    def on_dt(u, addr, size, ctx):
        d3 = u.reg_read(er.eb.UC_M68K_REG_D3) & 0xff
        dt_hits.append((rt.frame_count, d3))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_dt, begin=DT_SILENCE_ENTRY, end=DT_SILENCE_ENTRY + 1)

    def on_fb(u, addr, size, ctx):
        d1 = u.reg_read(er.eb.UC_M68K_REG_D1) & 0xff
        fb_hits.append((rt.frame_count, d1))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fb, begin=FB_ENTRY, end=FB_ENTRY + 1)

    def make_decision_hook(store, label, reg):
        def on_hit(u, addr, size, ctx):
            v = u.reg_read(reg) & 0xff
            store.append((rt.frame_count, v, label))
        return on_hit
    D3, D1 = er.eb.UC_M68K_REG_D3, er.eb.UC_M68K_REG_D1
    # dt_trig keeps the track number in %d3 throughout (its own header: "%d3 (track) is
    # live afterwards and is never touched"); fresh_bind keeps it in %d1 instead
    # ("move.l (12,%sp),%d1" -- its own %d3 is unrelated scratch).
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_decision_hook(dt_decisions, "pass", D3), begin=DT_PASS, end=DT_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_decision_hook(dt_decisions, "silence", D3), begin=DT_SILENCE, end=DT_SILENCE + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_decision_hook(fb_decisions, "pass", D1), begin=FB_PASS, end=FB_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_decision_hook(fb_decisions, "silence", D1), begin=FB_SILENCE, end=FB_SILENCE + 1)
    rt.uc.ctl_flush_tb()

    # run UNMUTED first, long enough to pass several natural loops, to see the BASELINE
    # dispatch rate for this track before muting at all
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    pre_ms = args.pre_ms if args.pre_ms is not None else args.ms // 2
    rt.run(ms=pre_ms)
    pre_mute_dt = [h for h in dt_hits if h[1] == track]
    pre_mute_fb = [h for h in fb_hits if h[1] == track]
    print(f"\nUNMUTED for {pre_ms} ms: {len(pre_mute_dt)} dt_trig hits for track {track}, "
          f"{len(pre_mute_fb)} fresh_bind hits for track {track}")

    # now mute and keep running for the same duration again
    mute_frame = rt.frame_count
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + track)))
    print(f"MUTED track {track} at frame {mute_frame}, GATE={args.gate}")
    rt.run(ms=args.ms - pre_ms)

    post_mute_dt = [h for h in dt_hits if h[1] == track and h[0] >= mute_frame]
    post_mute_fb = [h for h in fb_hits if h[1] == track and h[0] >= mute_frame]
    print(f"AFTER muting: {len(post_mute_dt)} dt_trig dispatch ATTEMPTS, {len(post_mute_fb)} "
          f"fresh_bind dispatch ATTEMPTS reached the detour entry for track {track}")

    # The decisive check: which branch did each attempt actually take?
    dt_post = [(f, tr, lab) for f, tr, lab in dt_decisions if tr == track and f >= mute_frame]
    fb_post = [(f, tr, lab) for f, tr, lab in fb_decisions if tr == track and f >= mute_frame]
    dt_pre = [(f, tr, lab) for f, tr, lab in dt_decisions if tr == track and f < mute_frame]
    fb_pre = [(f, tr, lab) for f, tr, lab in fb_decisions if tr == track and f < mute_frame]

    print(f"\ndt_trig decisions for track {track}: "
          f"pre-mute {sum(1 for *_, lab in dt_pre if lab=='pass')} pass / "
          f"{sum(1 for *_, lab in dt_pre if lab=='silence')} silence  |  "
          f"post-mute {sum(1 for *_, lab in dt_post if lab=='pass')} pass / "
          f"{sum(1 for *_, lab in dt_post if lab=='silence')} silence")
    print(f"fresh_bind decisions for track {track}: "
          f"pre-mute {sum(1 for *_, lab in fb_pre if lab=='pass')} pass / "
          f"{sum(1 for *_, lab in fb_pre if lab=='silence')} silence  |  "
          f"post-mute {sum(1 for *_, lab in fb_post if lab=='pass')} pass / "
          f"{sum(1 for *_, lab in fb_post if lab=='silence')} silence")

    leaks = [x for x in dt_post + fb_post if x[2] == "pass"]
    if leaks:
        print(f"\n-> LEAK CONFIRMED: {len(leaks)} dispatch(es) for the MUTED track took the "
              f"PASS branch (frames: {[f for f,_,_ in leaks][:20]})")
    else:
        print(f"\n-> CLEAN: every dispatch attempt for track {track} after muting took the "
              f"SILENCE branch. No trig-masking leak found in this run.")


if __name__ == "__main__":
    main()

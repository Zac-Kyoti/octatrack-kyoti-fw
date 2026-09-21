#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Continuing the "echo" investigation (NOTES.md "Session 58 continued yet again,
part 16" HANDOFF): hook 10 (fresh_bind) gates FUN_40006820's entry, converging
on all 7 known callers -- but part 16 found FUN_40006820 is a FREE/INVALIDATE
call, not "bind + play" (that mislabels hook 10's own header comment), so
gating it stops legitimate per-frame cleanup (a real, confirmed bug) without
being the actual "start a new voice" lever.

This session (a from-scratch MUTEMODE_NEW detour, since abandoned per the
user's direction to return to this MUTEMODE_DT thread) re-decompiled
FUN_40006820's 6 independent, hook-9/10-UNCOVERED callers
(tools/ghidra/attic/GhidraEchoCallers.java). Three are OS-upgrade / task-
switch paths calling FUN_40006820(-1) (all tracks) -- clearly unrelated.
But TWO (fb_caller_93ec0 @ 0x40093e9c, fb_caller_96ad4 @ 0x40096ab0) are near-
identical per-track "apply a pending part/lock parameter change" routines:
gated on `if (-1 < DAT_400d7c44 [or _48])` (a per-track pending-apply index),
they set `&DAT_46c80354[track] = 0x40` (looks like a level-ramp reset), call
FUN_40006820(track) to invalidate the OLD voice, copy in a NEW machine-type/
sample-slot byte and a block of per-track state, then reset the pending index
to -1. This is NOT on the trig-dispatch chain hooks 9/10 gate at all -- it is
plausibly how a P-LOCKED parameter change (e.g. a different sample slot on a
later step, exactly what the user's own "3-case step data" used) gets applied
mid-playback, entirely independent of MUTE_STATE.

This script re-runs diag_echo_realkey.py's exact real-key-path mute scenario
(FUN_40083ab4 through the real per-key dispatcher, not a raw MUTE_STATE poke)
and additionally watches these two candidate entries (plus fb_caller_40043c50
@ 0x40043ba0, the third per-track one, gated on param_1==0x2a) across the
whole post-mute window, to see whether ANY of them fire for a muted track's
subsequent would-be trig steps -- which would make them a genuinely NEW,
previously-untested candidate for the echo mechanism.

    python3 tools/diag_echo_newcallers.py [image] [--track 1] [--post-ms 16000]
"""
import argparse
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SCTEST = ROOT / "out/hw-projects/SIDECHAIN_TEST/test"
MMTESTDT = ROOT / "out/hw-projects/MMTESTDT/test"
MMTESTDT_AUDIO = ROOT / "out/hw-projects/MMTESTDT/AUDIO/ELEKTRON"

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
MUTE_KEY_FN = 0x40083ab4

DT_SILENCE_ENTRY = 0x4000d498
FB_ENTRY = 0x40006820
DT_PASS = 0x400d7676
DT_SILENCE = 0x400d766e
FB_PASS = 0x400d76d2
FB_SILENCE = 0x400d76cc

# newly-decompiled candidates, this session (GhidraEchoCallers.java) -- NOT
# gated by hooks 9/10 at all
CAND_43C50 = 0x40043ba0   # fb_caller_40043c50's real entry (Ghidra snapped the
                          # requested 0x40043c50 -- a mid-function call site,
                          # not an instruction boundary safe to hook -- back
                          # to this address); gated on an event code == 0x2a
CAND_93EC0 = 0x40093e9c   # fb_caller_93ec0: per-track pending-apply, bank A
CAND_96AD4 = 0x40096ab0   # fb_caller_96ad4: per-track pending-apply, bank B


def run_once(img_path, project_dir, track, gate, pre_ms, post_ms, steps, audio, poke_steps):
    card, name = er.stage_project(str(project_dir), "SCTEST", None, audio=audio)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"  boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "SCTEST", name, run_ms=6000, mount_ms=3000)
    print(f"  load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    curpat = rt.uc.mem_read(0x80000004, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    # NOTE: earlier revision hardcoded pattern=1 here (copied from
    # diag_echo_realkey.py, whose SIDECHAIN_TEST scenario always poked its
    # own trig masks regardless of what pattern was live, so it never
    # mattered there). Reading the REAL live pattern index instead --
    # verified against MMTESTDT via /tmp/probe_mmtestdt_pattern.py: curpat=0
    # (0-indexed) is the one with real content (track 1 trig-mask
    # 0000000000004201 = steps 1/10/15); a hardcoded "1" silently selected
    # an EMPTY pattern for the entire 40s run and produced an all-zero,
    # falsely-clean result.
    seq_bank, seq_pattern = rt.seq_select_live(curbank, curpat)
    print(f"  seq_select_live: bank={seq_bank} pattern={seq_pattern} (live curbank={curbank} curpat={curpat})")
    rt.run(ms=500)

    base = rt.pattern_base()
    trig_raw = rt.uc.mem_read(base + track * 0x91a, 8)
    print(f"  sanity check -- track {track+1}'s live trig-mask bytes: {trig_raw.hex()} "
          f"(all-zero here means an empty pattern got selected; stop and fix that before "
          f"trusting any hit-count below)")

    if poke_steps:
        for step in steps:
            rt.poke_mask(0x00, step, track=track)
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 0))
    rt.uc.mem_write(GATE, struct.pack(">I", gate))

    dt_decisions, fb_decisions, cand_hits = [], [], []

    def make_hook(store, label, reg):
        def on_hit(u, addr, size, ctx):
            store.append((rt.frame_count, u.reg_read(reg) & 0xff, label))
        return on_hit
    D3, D1, A7 = er.eb.UC_M68K_REG_D3, er.eb.UC_M68K_REG_D1, er.eb.UC_M68K_REG_A7

    def make_fb_hook(store, label):
        def on_hit(u, addr, size, ctx):
            sp = u.reg_read(A7)
            ret = struct.unpack(">I", u.mem_read(sp + 8, 4))[0]
            trk = u.reg_read(D1) & 0xff
            store.append((rt.frame_count, trk, label, ret))
        return on_hit

    def make_cand_hook(name, arg_reg):
        def on_hit(u, addr, size, ctx):
            arg = u.reg_read(arg_reg) & 0xff if arg_reg is not None else -1
            cand_hits.append((rt.frame_count, name, arg))
        return on_hit

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_hook(dt_decisions, "pass", D3), begin=DT_PASS, end=DT_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_hook(dt_decisions, "silence", D3), begin=DT_SILENCE, end=DT_SILENCE + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_fb_hook(fb_decisions, "pass"), begin=FB_PASS, end=FB_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_fb_hook(fb_decisions, "silence"), begin=FB_SILENCE, end=FB_SILENCE + 1)
    # candidates: param_1 is on the stack for all three (standard C calling
    # convention here, per the decompile's `int param_1` with no register
    # hint) -- read (4,%sp) directly rather than guessing a register.
    def make_cand_hook_stack(name):
        def on_hit(u, addr, size, ctx):
            sp = u.reg_read(A7)
            arg = struct.unpack(">i", u.mem_read(sp + 4, 4))[0]
            cand_hits.append((rt.frame_count, name, arg))
        return on_hit
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_cand_hook_stack("40043c50"), begin=CAND_43C50, end=CAND_43C50 + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_cand_hook_stack("93ec0"), begin=CAND_93EC0, end=CAND_93EC0 + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_cand_hook_stack("96ad4"), begin=CAND_96AD4, end=CAND_96AD4 + 1)
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=pre_ms)

    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    mute_before = rt.uc.mem_read(MUTE_STATE, 4)
    d0 = rt.call_as_main(MUTE_KEY_FN, args=(track + 0x10, 1))
    mute_after = rt.uc.mem_read(MUTE_STATE, 4)
    mute_frame = rt.frame_count
    print(f"  called FUN_40083ab4({track + 0x10:#x}, 1) [track {track}] at frame {mute_frame}: D0={d0:#x}, "
          f"MUTE_STATE {mute_before.hex()} -> {mute_after.hex()}")
    mute_toggled = struct.unpack(">I", mute_after)[0] ^ (0x100 << track)
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", mute_toggled))
    print(f"  manually toggled MUTE_STATE bit (8+{track}): -> {mute_toggled:#010x}")

    rt.run(ms=post_ms)
    mute_end = rt.uc.mem_read(MUTE_STATE, 4)
    print(f"  end of window: MUTE_STATE (final) = {mute_end.hex()}")

    dt_post = [(f, tr, lab) for f, tr, lab in dt_decisions if tr == track and f >= mute_frame]
    fb_post = [(f, tr, lab, ret) for f, tr, lab, ret in fb_decisions if tr == track and f >= mute_frame]
    cand_pre = [(f, name, arg) for f, name, arg in cand_hits if f < mute_frame]
    cand_post = [(f, name, arg) for f, name, arg in cand_hits if f >= mute_frame]
    print(f"  post-mute: dt_trig {sum(1 for *_,l in dt_post if l=='pass')} pass / "
          f"{sum(1 for *_,l in dt_post if l=='silence')} silence  |  "
          f"fresh_bind {sum(1 for x in fb_post if x[2]=='pass')} pass / "
          f"{sum(1 for x in fb_post if x[2]=='silence')} silence")
    print(f"  PRE-mute candidate hits: {len(cand_pre)} total (sanity check -- confirms the "
          f"candidates fire normally, unmuted, before we ask whether muting stops them)")
    for f, name, arg in cand_pre[:40]:
        print(f"    frame {f}: {name}(track_arg={arg})")
    print(f"  post-mute NEW-CANDIDATE hits: {len(cand_post)} total")
    if cand_post:
        print("  !! at least one of the newly-decompiled, hook-9/10-UNCOVERED candidates "
              "fired during the muted window -- this is a genuinely new lead:")
        for f, name, arg in cand_post[:40]:
            rel = f - mute_frame
            print(f"    frame {f} (+{rel} since mute): {name}(track_arg={arg})")
    else:
        print("  none of the 3 newly-decompiled candidates (40043c50/93ec0/96ad4) fired at "
              "all during the post-mute window.")
    return mute_frame, cand_pre, cand_post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default="out/mainos_mutemode_dt.bin")
    ap.add_argument("--project", default=str(MMTESTDT))
    ap.add_argument("--track", type=int, default=1)
    ap.add_argument("--gate", type=int, default=2, help="2 = DT_MODE")
    ap.add_argument("--pre-ms", type=int, default=500)
    ap.add_argument("--post-ms", type=int, default=40000)
    ap.add_argument("--steps", default="1,5,9,13",
                     help="only used with --poke (forced trig steps); MMTESTDT already has "
                          "real trigs at 1/10/15 with a sample-slot lock on 10/15")
    ap.add_argument("--poke", action="store_true",
                     help="force trig masks onto --steps instead of using the project's own "
                          "real trig/lock content (the SIDECHAIN_TEST-style path)")
    ap.add_argument("--no-audio", action="store_true",
                     help="skip staging heaven.wav/isaak.wav (MMTESTDT's own samples)")
    args = ap.parse_args()
    img_path = ROOT / args.image
    project_dir = pathlib.Path(args.project)
    steps = [int(s) for s in args.steps.split(",")]

    audio = []
    if not args.no_audio and project_dir == MMTESTDT:
        for wav in ("heaven.wav", "isaak.wav"):
            src = MMTESTDT_AUDIO / wav
            if src.exists():
                audio.append(f"{src}:AUDIO/ELEKTRON/{wav}")

    mute_frame, cand_pre, cand_post = run_once(img_path, project_dir, args.track, args.gate,
                                                args.pre_ms, args.post_ms, steps,
                                                audio, args.poke)


if __name__ == "__main__":
    main()

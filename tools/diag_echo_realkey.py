#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 58 continued yet again, part 11 HANDOFF, first thing to do: retest the
fresh_bind leak found via a raw MUTE_STATE poke, but this time engage the mute through
the REAL key-handler path -- `FUN_40083ab4(track, 1)`, the "single press -> mute" call
documented from the original Session 9 soft-mute research (NOTES.md, "Does the fix also
cover QUICK MUTE? -- almost certainly yes": `FUN_40040250`'s single-press branch calls
`FUN_40083ab4(track, 1)`, which sets the mute mask and calls `FUN_400836d8()`).

Why this matters: `diag_echo_trigmask.py`'s own leak (2 fresh_bind dispatches reaching
real per-track work for a just-muted track) did NOT reproduce when the mute was engaged
at a different frame in an otherwise-identical run -- consistent with a timing artifact
of THAT script's own raw, frame-asynchronous `MUTE_STATE` memory poke, not a reliably-
reproducible firmware bug. This script controls for that by going through the real
function instead, via `Rtos.call_as_main` (runs the call for real, against the live
scheduler/tasks, "the way a UI action would call it" -- not a cold detour).

    python3 tools/diag_echo_realkey.py [image] [--track 1] [--ms 16000]
"""
import argparse
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SCTEST = ROOT / "out/hw-projects/SIDECHAIN_TEST/test"

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
# NOTES.md, original Session 9 soft-mute research (not re-verified against THIS image's
# disassembly this session -- if this call misbehaves, that is the first thing to check):
# FUN_40040250(track, evt) is the real per-key dispatcher; its single-press branch calls
# this function with a literal "1" for evt, which sets the mute mask bit and calls
# FUN_400836d8() -- the same convergence point QUICK MUTE also uses.
MUTE_KEY_FN = 0x40083ab4

DT_SILENCE_ENTRY = 0x4000d498
FB_ENTRY = 0x40006820
DT_PASS = 0x400d7676
DT_SILENCE = 0x400d766e
FB_PASS = 0x400d76d2
FB_SILENCE = 0x400d76cc


def run_once(img_path, project_dir, track, gate, pre_ms, post_ms, steps):
    card, name = er.stage_project(str(project_dir), "SCTEST", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"  boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "SCTEST", name, run_ms=6000, mount_ms=3000)
    print(f"  load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    for step in steps:
        rt.poke_mask(0x00, step, track=track)
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 0))
    rt.uc.mem_write(GATE, struct.pack(">I", gate))

    dt_decisions, fb_decisions = [], []

    def make_hook(store, label, reg):
        def on_hit(u, addr, size, ctx):
            store.append((rt.frame_count, u.reg_read(reg) & 0xff, label))
        return on_hit
    D3, D1, A7 = er.eb.UC_M68K_REG_D3, er.eb.UC_M68K_REG_D1, er.eb.UC_M68K_REG_A7
    # fresh_bind's own prologue (patch_softmute.s hook 10 comment): pushes %a2 then %d2
    # before loading track from (12,%sp) -- so at this point [sp+8] holds the ORIGINAL
    # caller's return address (one of FUN_40006820's documented 7 callers: one inside
    # FUN_4000f450, already covered by hook 9/dt_trig; six independent ones elsewhere).
    # Capture it on "pass" hits to see whether the leaked dispatches are duplicate calls
    # for the same trig event or genuinely distinct call sites.
    def make_fb_hook(store, label):
        def on_hit(u, addr, size, ctx):
            sp = u.reg_read(A7)
            ret = struct.unpack(">I", u.mem_read(sp + 8, 4))[0]
            trk = u.reg_read(D1) & 0xff
            # relparam_46c7dfba[trk]: the 45-frame release watchdog (emu_mute.py's own
            # address map); DAT_8000184a bit trk: the note-off/release-pending flag
            # FUN_40008f84 sets. Sampled at every fresh_bind entry (pass or blocked) to see
            # whether the watchdog is being repeatedly re-armed (explaining a fading-over-
            # cycles cadence) or just decays once and sits at 0 (which would NOT explain a
            # multi-cycle fade on its own).
            wd = struct.unpack(">I", u.mem_read(0x46c7dfba + trk * 4, 4))[0] if trk < 8 else -1
            noteoff = (u.mem_read(0x8000184a, 1)[0] >> trk) & 1 if trk < 8 else -1
            store.append((rt.frame_count, trk, label, ret, wd, noteoff))
        return on_hit
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_hook(dt_decisions, "pass", D3), begin=DT_PASS, end=DT_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_hook(dt_decisions, "silence", D3), begin=DT_SILENCE, end=DT_SILENCE + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_fb_hook(fb_decisions, "pass"), begin=FB_PASS, end=FB_PASS + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, make_fb_hook(fb_decisions, "silence"), begin=FB_SILENCE, end=FB_SILENCE + 1)
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=pre_ms)

    # engage the mute through the REAL key-handler path, not a raw poke
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    mute_before = rt.uc.mem_read(MUTE_STATE, 4)
    # FUN_40083ab4's own body (fresh Ghidra decompile, "part 11 addendum" follow-up session):
    # `uVar1 = param_1 - 0x10;` then uVar1 is used DIRECTLY as the 0-7 track index (bit-shift
    # amount, compare against DAT_100b14cc). So param_1 must be a KEYCODE (track+0x10), not a
    # bare track index -- passing plain `track` here makes uVar1 negative, so `1 << (uVar1&0x3f)`
    # shifts out to 0 and no track's mute bit is ever set, regardless of which track is asked
    # for. This reconciles with the original Session-9 doc's "FUN_40040250(track, evt) ...
    # single press -> FUN_40083ab4(track, 1)": FUN_40040250's own "track" parameter is itself
    # already a keycode (the button-table dispatch feeds it raw), passed straight through.
    d0 = rt.call_as_main(MUTE_KEY_FN, args=(track + 0x10, 1))
    mute_after = rt.uc.mem_read(MUTE_STATE, 4)
    mute_frame = rt.frame_count
    print(f"  called FUN_40083ab4({track + 0x10:#x}, 1) [track {track}] at frame {mute_frame}: D0={d0:#x}, "
          f"MUTE_STATE {mute_before.hex()} -> {mute_after.hex()}")
    if mute_after == mute_before:
        print("  !! MUTE_STATE did not change after the real call -- this is EXPECTED, not a "
              "bug in the call (see below): _DAT_80000008's mute bits are NOT derived from "
              "_DAT_460fab40 by any sync task. GhidraMute11/12/13 (session 58 part 12 "
              "follow-up) found they are toggled by a POSTED KERNEL EVENT ('J' case, XOR "
              "0x100<<track, inside FUN_40061a94's message-dispatch loop) -- a completely "
              "separate action from FUN_40083ab4/FUN_400836d8's own _DAT_460fab40 update. "
              "The real per-key dispatcher (FUN_40040250) does NOT post that event itself "
              "either (decompiled in full: only calls FUN_40083ab4/FUN_40083e40) -- the "
              "poster is still unlocated (Ghidra found zero refs to the queue address "
              "0x460d17ae, even from FUN_40061a94's own consumer code -- a real tooling "
              "limitation, not evidence the queue is unused). Manually completing that "
              "second, independent action below so this test still exercises the REAL "
              "audio-mute code path (FUN_40083ab4 -> FUN_400836d8 -> the DSP voice-command "
              "mailbox) while getting MUTE_STATE into the state hooks 9/10 actually gate on.")
    # Manually perform the second, independent half of what a real keypress does (see above):
    # toggle bit (8+track) in _DAT_80000008, matching FUN_40061a94's own 'J'-case transform
    # (`0x100 << track ^ _DAT_80000008`) exactly. MUTE_STATE was zeroed before this call, so
    # this cleanly sets just this track's mute bit -- not a raw guess at the bit position, the
    # XOR shape is lifted verbatim from the real handler's own decompiled code.
    mute_toggled = struct.unpack(">I", mute_after)[0] ^ (0x100 << track)
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", mute_toggled))
    print(f"  manually toggled MUTE_STATE bit (8+{track}): -> {mute_toggled:#010x} "
          f"(real _DAT_460fab40-side mute IS real; only this LED/frame-gate mirror is synthetic)")

    # FUN_40083ab4 sets _DAT_460fab40 SYNCHRONOUSLY and unconditionally (fresh Ghidra decompile
    # this session); _DAT_80000008 (MUTE_STATE) is documented (NOTES.md "V4") as synced from it
    # by a SEPARATE PERIODIC TASK, not written directly. Check both at the end of the window to
    # tell "the call didn't do anything" apart from "it worked but the sync task hasn't fired
    # yet in this harness".
    fab40_before = rt.uc.mem_read(0x460fab40, 4)
    rt.run(ms=post_ms)
    fab40_after = rt.uc.mem_read(0x460fab40, 4)
    mute_end = rt.uc.mem_read(MUTE_STATE, 4)
    print(f"  end of window: _DAT_460fab40 {fab40_before.hex()} -> {fab40_after.hex()}, "
          f"MUTE_STATE (final) = {mute_end.hex()}")

    dt_post = [(f, tr, lab) for f, tr, lab in dt_decisions if tr == track and f >= mute_frame]
    fb_post = [(f, tr, lab, ret, wd, no) for f, tr, lab, ret, wd, no in fb_decisions
               if tr == track and f >= mute_frame]
    leaks = [x for x in dt_post if x[2] == "pass"] + [x for x in fb_post if x[2] == "pass"]
    n_dt_post = len(dt_post)
    n_fb_post = len(fb_post)
    print(f"  post-mute: dt_trig {sum(1 for *_,l in dt_post if l=='pass')} pass / "
          f"{sum(1 for *_,l in dt_post if l=='silence')} silence  |  "
          f"fresh_bind {sum(1 for x in fb_post if x[2]=='pass')} pass / "
          f"{sum(1 for x in fb_post if x[2]=='silence')} silence")
    fb_leaks = [x for x in fb_post if x[2] == "pass"]
    if fb_leaks:
        print("  fresh_bind leak return addresses (which of the 7 callers of "
              "FUN_40006820 dispatched each one):")
        for f, tr, lab, ret, wd, no in fb_leaks:
            print(f"    frame {f}: called from {ret:#010x}, watchdog={wd}, noteoff_bit={no}")

    # Does the mute-blind per-frame staleness check (FUN_40007960's own goto LAB_40008110,
    # return address 0x40008114) keep firing -- and getting BLOCKED -- repeatedly for as
    # long as the track stays muted? If so its rate/watchdog-value over time should show
    # whether the phenomenon's "fades over a couple cycles" character comes from this call
    # slowing down/stopping (or the watchdog being repeatedly re-armed then finally not),
    # or from something else entirely.
    fb_silence = [x for x in fb_post if x[2] == "silence"]
    from collections import Counter
    by_ret = Counter(ret for _, _, _, ret, _, _ in fb_silence)
    print(f"  fresh_bind SILENCE (blocked) calls: {len(fb_silence)} total, by caller:")
    for ret, n in by_ret.most_common(10):
        rows = [(f, wd, no) for f, _, _, r, wd, no in fb_silence if r == ret]
        frames = [f for f, _, _ in rows]
        print(f"    {ret:#010x}: {n} calls, frames {frames[0]}..{frames[-1]}")
        print(f"      first 15 (frame, watchdog, noteoff_bit): {rows[:15]}")
        print(f"      last 15 (frame, watchdog, noteoff_bit):  {rows[-15:]}")
    return mute_frame, leaks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default="out/mainos_relstate_shadow.bin")
    ap.add_argument("--project", default=str(SCTEST))
    ap.add_argument("--track", type=int, default=1)
    ap.add_argument("--gate", type=int, default=1)
    ap.add_argument("--pre-ms", type=int, default=2000)
    ap.add_argument("--post-ms", type=int, default=10000)
    ap.add_argument("--steps", default="1,5,9,13")
    ap.add_argument("--repeats", type=int, default=2,
                     help="run the whole scenario this many times, varying pre-ms "
                          "slightly each time, to test for consistency")
    args = ap.parse_args()
    img_path = ROOT / args.image
    project_dir = pathlib.Path(args.project)
    steps = [int(s) for s in args.steps.split(",")]

    results = []
    for i in range(args.repeats):
        pre_ms = args.pre_ms + i * 733   # deliberately different each repeat, like
                                          # diag_echo_trigmask.py's two runs landed on
                                          # different frames -- tests for consistency
        print(f"\n=== run {i+1}/{args.repeats}, pre_ms={pre_ms} ===")
        mute_frame, leaks = run_once(img_path, project_dir, args.track, args.gate,
                                      pre_ms, args.post_ms, steps)
        results.append((pre_ms, mute_frame, leaks))
        if leaks:
            print(f"  -> LEAK: {len(leaks)} dispatch(es) (frames: {[x[0] for x in leaks][:10]})")
        else:
            print("  -> clean")

    print("\n=== summary ===")
    for pre_ms, mute_frame, leaks in results:
        print(f"  pre_ms={pre_ms} mute_frame={mute_frame}: {len(leaks)} leak(s)")
    n_with_leaks = sum(1 for *_, leaks in results if leaks)
    if n_with_leaks == 0:
        print("\nCLEAN across all runs via the real key-handler path -- the earlier "
              "raw-poke leak does not reproduce this way. Consistent with it having "
              "been a test-injection artifact.")
    elif n_with_leaks == len(results):
        print(f"\nLEAKS on ALL {len(results)} runs via the real key-handler path -- "
              f"this is NOT a poke-timing artifact. A real, consistently-reproducible "
              f"trig-masking bug. This is a strong candidate for the echo mechanism.")
    else:
        print(f"\nMIXED: {n_with_leaks}/{len(results)} runs leaked. Still timing-"
              f"dependent even through the real key path -- narrows the bug but "
              f"doesn't yet explain 'remarkably consistent' on hardware.")


if __name__ == "__main__":
    main()

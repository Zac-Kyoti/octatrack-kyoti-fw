#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 69 (following Session 67's HANDOFF): drives the REAL scheduler + REAL
sequencer (refs/octabam's route-A emulator, `tools/emu_rtos.py`) against a
real project, starts real playback, and injects a manual pattern change
mid-run the way the user's own key press does at the memory level --
poking PEND_PAT/PEND_BANK (0x800065c0 / 0x800065bf) -- instead of hand-
reconstructing per-track state for an isolated single-function Unicorn call.
Session 67's post-mortem: the isolated approach has hit its limit for this
bug (two D7 fixes each passed isolated checks and both failed on hardware).

What this measures, across the switch, for BOTH conditions below:
  * 0x80006604[track]  -- dj_c's seeded per-track phase/tick counter
  * 0x80006500[track]  -- Session 67's never-traced per-track gate (17 refs,
                           the real per-tick dispatcher 0x400a3ca6 checks it
                           before ever touching 0x80006604)
  * FUN_400a536c (0x400a536c) entries -- the actual trig-fire common tail
    (NOTES.md L3025: `FUN_400a536c(track)`, called from the per-track loop
    that decrements DAT_800065c3[t] to 0) -- logged with (frame, track).

Two runs, same image (out/mainos_directjump_v4.bin), same poke, same frame:
  A) DJ_MODE (0x800000d8) poked to 1 before transport start -- functionally
     identical to the user's [PTN]+[YES] combo (dj_toggle just does
     `move.l %d0,DJ_MODE`; the toast/checksum/SRAM-shadow side effects are
     irrelevant to sequencer timing).
  B) DJ_MODE left at its image default, 0 -- stock reference: what "resets
     to step 1" looks like, and what a stock CHAIN-AFTER-gated switch's
     timing looks like, for direct comparison.

Usage:
    python3 tools/emu_directjump_dynamic.py [--frames-before N] [--frames-after N]
                                             [--project DIR] [--pattern-delta N]

No code under tools/patch_directjump.s is touched by this script -- read-only
dynamic analysis only, per the Session 67 handoff ("no hardware flash until
there is positive dynamic evidence the fix changes real trig-fire timing
correctly").
"""
import argparse
import os
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
OCTA_RTOS = OCTABAM / "tools" / "emu" / "emu_rtos.py"
IMAGE = ROOT / "out" / "mainos_directjump_v4.bin"
DEMO_PROJECT = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

# ---- addresses under test (see patch_directjump.s + NOTES.md Session 67) ----
DJ_MODE = 0x800000d8
PEND_PAT = 0x800065c0
PEND_BANK = 0x800065bf
ACT_PAT = 0x800065be
ACT_BANK = 0x800065bd
STEP = 0x800065b6
PHASE_TBL = 0x80006604      # dj_c's seeded counter, 8 bytes (1/track) per Session 67
GATE_TBL = 0x80006500       # Session 67's untraced per-track gate, 8 bytes
TRIG_FIRE = 0x400a536c      # FUN_400a536c(track) -- NOTES.md L3025
CNTDN_TBL = 0x800065c3      # DAT_800065c3[t] -- NOTES.md L3025/3030-3032: decremented every
                            # tick, fires FUN_400a536c(t) at 0 -- one of the FOUR arrays the
                            # ORIGINAL Session 15 design (L3030-3032) said the exit stub must
                            # rewrite after a switch (DAT_800065b6, DAT_800065e4[]/f4[],
                            # DAT_800065c3[], DAT_80006604/14[]) -- dj_c (patch_directjump.s)
                            # currently writes only D7 (feeding 0x80006604/14) and STEP
                            # (0x800065b6); grep confirms it never writes 0x800065c3 or
                            # 0x800065e4/f4 at all.
REFILL_TBL = 0x800064d0     # DAT_800064d0[t] -- refills CNTDN_TBL after a fire (L3025)
# Session 70 14th pass: the four other per-track pointer arrays FUN_400a1eea's own
# SCALE-wrap-check (`if (DAT_800065b6=='\0') { ... uVar25 % iVar15 == 0/1 ... }`) writes
# alongside GATE_TBL/CNTDN_TBL, confirmed from GhidraDirectJump7's outer-loop pointer
# setup (pcStack000000a8 IS &DAT_800065c3 == CNTDN_TBL; already watched above). Track 0
# resolves its own `iVar15` (the length these compares are against) via a DIFFERENT code
# path than tracks 1-7 (reads pattern-blob fixed offsets `+0x50`/`+0x8e53` under a
# SCALE_MODE flag at `+0x8e55`, instead of tracks 1-7's shared `DAT_400d80dc[selector*4]`
# lookup) -- watching these four across the same switch, split by track 0 vs 1-7, is
# this pass's attempt to find exactly where the numeric divergence into DAT_80001904
# (feeding the real audible live-nibble, per the 12th/13th passes) first appears.
LEN_AC = 0x800065d3          # *pcStack000000ac[t]
LEN_9C = 0x8000663e          # *pcStack0000009c[t]
LEN_94 = 0x800064f0          # *pcStack00000094[t]
LEN_A0 = 0x800064e0          # *puStack000000a0[t]
LIVE_NIBBLE_IN = 0x80001904  # DAT_80001904[track + step*8], int x 128 -- Session 70 12th
                              # pass (GhidraDirectJump7.java): written by FUN_400a1eea from
                              # bank/pattern-selection state (DAT_800065bd/be/c1/c2) + a
                              # per-track bit (DAT_80006624), NEVER touched by any DIRECT
                              # JUMP hook; independently identified by refs/octabam's own
                              # ColdFire port (COLDFIRE_PORT.md O9b step 4) as one of the
                              # TWO direct inputs to the exact ColdFire computation that
                              # produces FW_LIVE_NIBBLE -- the sequencer's own live/audible
                              # sub-step byte. Watching the whole 128-byte (16 track x 8
                              # step slots x 4B... actually int x 8 tracks x 16 slots, see
                              # note below) region across a switch is this pass's decisive
                              # test.
STEP_AUDIO_TBL = 0x800065e4  # DAT_800065e4[t] -- per-track step (audio), NOTES.md L2919/3023:
                             # computed at 0x400a4aa2 as `base / trackLen` from a STACK-LOCAL
                             # base (0x3c,SP) set up EARLIER in the same switch-commit code,
                             # NOT from dj_c's D7 register -- a different input than what
                             # feeds 0x80006604/14, per the project's own static RE map.
STEP_MIDI_TBL = 0x800065f4   # DAT_800065f4[t] -- same, MIDI


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=str(DEMO_PROJECT))
    ap.add_argument("--frames-before", type=int, default=400,
                     help="DSP frames to run before the manual pattern poke "
                          "(default 400 -- past one full pattern loop at "
                          "~57.7 frames/step x 6 steps, calibrated this session "
                          "against the default project)")
    ap.add_argument("--frames-after", type=int, default=700,
                     help="DSP frames to run after the poke (default 700 -- "
                          "~2 more pattern loops)")
    ap.add_argument("--pattern-delta", type=int, default=1,
                     help="new pattern = (current active pattern + this) -- same bank")
    ap.add_argument("--bank", type=int, default=None)
    a = ap.parse_args(argv)

    if not OCTA_RTOS.exists():
        sys.exit(f"missing {OCTA_RTOS}\n  -> python3 tools/refs/sync.py")
    if not IMAGE.exists():
        sys.exit(f"missing {IMAGE}\n  -> build DIRECTJUMP_V4 first "
                  f"(python3 tools/build_directjump_v4.py or build_merged.py)")
    if not pathlib.Path(a.project).is_dir():
        sys.exit(f"missing project dir {a.project}")

    emac_lib = OCTABAM / ".venv" / "lib" / "unicorn-emac"
    if not emac_lib.is_dir():
        sys.exit(f"missing the EMAC-patched Unicorn ({emac_lib})\n"
                  f"  -> ( cd {OCTABAM} && PY=$(command -v python3) bash scripts/build_unicorn.sh )")

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401 -- adds tools/{build,harness,emu,hw,verify} to sys.path
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)
    print(f"EMAC       : fixed -- {detail}")

    for cond, dj_on in (("DJ_MODE=1 (DIRECT JUMP ON)", True), ("DJ_MODE=0 (stock reference)", False)):
        print(f"\n{'=' * 70}\n{cond}\n{'=' * 70}")
        run_one(er, a, dj_on)


def run_one(er, a, dj_on):
    card, staged_name = er.stage_project(a.project, "OCTABAM", None,
                                          tree=f"out/_emu_dj_tree_{'on' if dj_on else 'off'}")
    r, rt = er.attach(str(IMAGE), card,
                       ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)

    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live("OCTABAM", staged_name, run_ms=6000)
    bank = a.bank if a.bank is not None else saved_bank
    if bank is not None and final_bank != bank:
        final_bank = rt.select_bank_live(bank)
    pattern = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    seq_bank, seq_pattern = rt.seq_select_live(final_bank, pattern)
    # Without this, a project saved with CLOCK RECEIVE on (external MIDI
    # clock master) waits forever for pulses that never come -- 0 ticks, 0
    # trigs, STEP stuck at 0 (emu_rtos.internal_clock's own docstring; this
    # is exactly what a first pass of this script measured: STEP stayed 0
    # for 3000 frames dead flat). Force the sequencer onto its own clock.
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    if dj_on:
        rt.uc.mem_write(DJ_MODE, struct.pack(">I", 1))
        v = int.from_bytes(rt.uc.mem_read(DJ_MODE, 4), "big")
        print(f"DJ_MODE poked -> {v:#x}")

    # ---- instrumentation: per-track phase/gate snapshots + trig-fire log ----
    fires = []  # (frame, sample, track)

    def on_fire(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        ret, track = struct.unpack(">II", u.mem_read(sp, 8))
        fires.append((rt.frame_count, round(rt.sample, 1), track))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=TRIG_FIRE, end=TRIG_FIRE)
    rt.uc.ctl_flush_tb()

    # NOTE: rt.watch_mem() stores into self.mem_writes, looked up FRESH on every
    # hit -- calling it twice makes the FIRST hook's callback silently start
    # appending into the SECOND call's list too. Use independent closures instead.
    def make_watch(addr, length):
        log = []

        def on_write(u, acc, a, size, val, user):
            log.append((rt.frame_count, rt._cur(), u.reg_read(er.eb.UC_M68K_REG_PC), a, size, val))
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=addr, end=addr + length - 1)
        return log
    phase_writes = make_watch(PHASE_TBL, 8)
    gate_writes = make_watch(GATE_TBL, 8)
    cntdn_writes = make_watch(CNTDN_TBL, 8)
    step_audio_writes = make_watch(STEP_AUDIO_TBL, 16)  # u16 x 8
    refill_writes = make_watch(REFILL_TBL, 8)  # Session 70 12th pass: never watched before --
                                                 # LAB_400a4ba0's own refill-from-quotient write,
                                                 # gated on CNTDN_TBL[t] hitting 0 (Ghidra-traced
                                                 # this session, GhidraDirectJump7.java)
    len_ac_writes = make_watch(LEN_AC, 8)
    len_9c_writes = make_watch(LEN_9C, 8)
    len_94_writes = make_watch(LEN_94, 8)
    len_a0_writes = make_watch(LEN_A0, 8)
    rt.uc.ctl_flush_tb()

    # NOTE (this session): press_play_live() -- through the real PLAY key
    # handler -- silently no-ops against this project. It gates on
    # 0x80000029 ("beqs a bare rts if clear", RTOS_FORK.md 9.4), which is
    # 0x01 for octabam's own tiny validation fixture (out/_testproj) but
    # stayed 0x00 here even after a 20s load budget (ruled out as a load-
    # timing issue) -- this exact gate mechanism has only ever been measured
    # against that one fixture, never a real full project. start_transport_live()
    # is the OTHER validated M6c/M6d route (direct FW_TRANSPORT/FW_START_TRACK,
    # bypassing PLAY's front-end entirely) and DOES advance STEP here (0->2
    # over 60 frames, confirmed by a throwaway probe before this rewrite).
    rt.start_transport_live()
    rt.install_trig_log()
    print(f"after start: TRANSPORT@{0x800065b8:#x}={rt.uc.mem_read(0x800065b8,1)[0]} "
          f"tick_count={rt.tick_count} frame_count={rt.frame_count} pc={rt.pc:#x}")

    frame0 = rt.frame_count + 1
    target1 = frame0 + a.frames_before
    rt.run(ms=a.frames_before * er.FRAME_PERIOD / er.SAMPLE_HZ * 1000.0 * 5 + 3000,
           until=lambda x: x.frame_count >= target1)

    cur_pat = rt.uc.mem_read(ACT_PAT, 1)[0]
    cur_bank = rt.uc.mem_read(ACT_BANK, 1)[0]
    cur_step = rt.uc.mem_read(STEP, 1)[0]
    # Session 70 14th pass: 0x400a299a reads blob[track*0x91a + 0x56] -- the REAL branch
    # (0x400a299e bne) tests THIS BYTE for zero/nonzero, not the track index (that was a
    # decompiler-C misreading, corrected by disassembly). Dump it for all 8 tracks to see
    # whether track 0 genuinely differs in this project's own data.
    blob = 0x400e21e0 + cur_bank * 0x9b340 + cur_pat * 0x8ed8
    print("scale-selector byte (blob[track*0x91a+0x56]) per track: " +
          " ".join(f"t{t}={rt.uc.mem_read(blob + t * 0x91a + 0x56, 1)[0]:#04x}" for t in range(8)))
    new_pat = (cur_pat + a.pattern_delta) & 0xff
    print(f"pre-switch : active bank={cur_bank} pattern={cur_pat} step={cur_step} "
          f"frame={rt.frame_count} fires-so-far={len(fires)} "
          f"TRANSPORT={rt.uc.mem_read(0x800065b8,1)[0]} tick_count={rt.tick_count}")
    print(f"phase tbl  : {rt.uc.mem_read(PHASE_TBL, 8).hex()}")
    print(f"gate  tbl  : {rt.uc.mem_read(GATE_TBL, 8).hex()}")
    print(f"cntdn tbl  : {rt.uc.mem_read(CNTDN_TBL, 8).hex()}  (0xff = never armed/fired)")
    print(f"step-audio : {rt.uc.mem_read(STEP_AUDIO_TBL, 16).hex()}")
    print(f"refill tbl : {rt.uc.mem_read(REFILL_TBL, 8).hex()}")
    live_nibble_pre = rt.uc.mem_read(LIVE_NIBBLE_IN, 256)
    print(f"live-nibble-in (0x{LIVE_NIBBLE_IN:x}, 64 x u32): {live_nibble_pre.hex()}")

    # ---- the manual pattern cue, at the memory level -------------------------
    rt.uc.mem_write(PEND_PAT, bytes([new_pat]))
    rt.uc.mem_write(PEND_BANK, bytes([cur_bank]))
    print(f"poked      : PEND_PAT={new_pat} PEND_BANK={cur_bank} at frame {rt.frame_count}")

    fires_before_poke = len(fires)
    target2 = rt.frame_count + a.frames_after
    rt.run(ms=a.frames_after * er.FRAME_PERIOD / er.SAMPLE_HZ * 1000.0 * 5 + 3000,
           until=lambda x: x.frame_count >= target2)

    print(f"post-switch: active bank={rt.uc.mem_read(ACT_BANK,1)[0]} "
          f"pattern={rt.uc.mem_read(ACT_PAT,1)[0]} step={rt.uc.mem_read(STEP,1)[0]} "
          f"frame={rt.frame_count} total-fires={len(fires)}")
    post_bank = rt.uc.mem_read(ACT_BANK, 1)[0]
    post_pat = rt.uc.mem_read(ACT_PAT, 1)[0]
    post_blob = 0x400e21e0 + post_bank * 0x9b340 + post_pat * 0x8ed8
    print("scale-selector byte (blob[track*0x91a+0x56]) per track: " +
          " ".join(f"t{t}={rt.uc.mem_read(post_blob + t * 0x91a + 0x56, 1)[0]:#04x}" for t in range(8)))
    print(f"phase tbl  : {rt.uc.mem_read(PHASE_TBL, 8).hex()}")
    print(f"gate  tbl  : {rt.uc.mem_read(GATE_TBL, 8).hex()}")
    print(f"cntdn tbl  : {rt.uc.mem_read(CNTDN_TBL, 8).hex()}  (0xff = never armed/fired)")
    print(f"step-audio : {rt.uc.mem_read(STEP_AUDIO_TBL, 16).hex()}")
    print(f"refill tbl : {rt.uc.mem_read(REFILL_TBL, 8).hex()}")
    live_nibble_post = rt.uc.mem_read(LIVE_NIBBLE_IN, 256)
    print(f"live-nibble-in (0x{LIVE_NIBBLE_IN:x}, 64 x u32): {live_nibble_post.hex()}")
    changed = [i for i in range(64)
               if live_nibble_pre[i*4:i*4+4] != live_nibble_post[i*4:i*4+4]]
    print(f"live-nibble-in slots CHANGED across the switch window: {changed}")
    for i in changed:
        pre = int.from_bytes(live_nibble_pre[i*4:i*4+4], "big")
        post = int.from_bytes(live_nibble_post[i*4:i*4+4], "big")
        print(f"   slot {i:2d} (track {i%8}, group {i//8}): {pre:#010x} -> {post:#010x}")

    print(f"\nFUN_400a536c (trig-fire) calls, frame relative to poke, "
          f"{fires_before_poke} before / {len(fires)-fires_before_poke} after:")
    poke_frame = target1
    for i, (fr, s, tr) in enumerate(fires):
        tag = "BEFORE" if i < fires_before_poke else "after "
        print(f"   [{tag}] frame {fr - poke_frame:+5d} (abs {fr:5d})  track {tr}")

    print(f"\n0x{PHASE_TBL:x} writes (dj_c seed), {len(phase_writes)} total:")
    for fr, task, pc, addr, size, val in phase_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\n0x{GATE_TBL:x} writes (Session 67's per-track gate), {len(gate_writes)} total:")
    for fr, task, pc, addr, size, val in gate_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\n0x{CNTDN_TBL:x} writes (trig-fire countdown, DAT_800065c3[t]), {len(cntdn_writes)} total:")
    for fr, task, pc, addr, size, val in cntdn_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\n0x{STEP_AUDIO_TBL:x} writes (DAT_800065e4[t], audio per-track step), "
          f"{len(step_audio_writes)} total:")
    for fr, task, pc, addr, size, val in step_audio_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\n0x{REFILL_TBL:x} writes (DAT_800064d0[t], REFILL_TBL), "
          f"{len(refill_writes)} total:")
    for fr, task, pc, addr, size, val in refill_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    for name, addr, log in (("LEN_AC/0x800065d3", LEN_AC, len_ac_writes),
                             ("LEN_9C/0x8000663e", LEN_9C, len_9c_writes),
                             ("LEN_94/0x800064f0", LEN_94, len_94_writes),
                             ("LEN_A0/0x800064e0", LEN_A0, len_a0_writes)):
        print(f"\n{name} writes, {len(log)} total:")
        for fr, task, pc, a, size, val in log:
            track = a - addr
            print(f"   frame {fr:.1f}  track {track}  [{a:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    return dict(fires=fires, fires_before_poke=fires_before_poke,
                phase_writes=phase_writes, gate_writes=gate_writes,
                cntdn_writes=cntdn_writes, step_audio_writes=step_audio_writes,
                refill_writes=refill_writes)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

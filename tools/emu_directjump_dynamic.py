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
TABLE_ARM_PC = 0x400a2e0c
TRACE_LO = 0x400a2b00
TRACE_HI = 0x400a2e30
TRACE_FRAME_LO = 300
TRACE_FRAME_HI = 700

# Session 79 continued a tenth time: TABLE_ARM_STORE_PC is the exact instruction that
# writes DAT_80001904[slot] (GhidraDirectJump29.java: "0x400a2e18  move.l D0,(0x0,A0,A1*0x4)").
# D0 holds the value about to be stored (confirmed = ACCUM - 0x285ff0 + TBL[idx] + D7,
# GhidraDirectJump29/30/31/32/33 -- ACCUM is a free-running per-frame accumulator,
# FUN_4000ae12 is the real consumer: (slot_value - ACCUM_now) * tempo-rate via EMAC MAC,
# a phase-anchor timestamp). G_ABSTICK (patch_directjump.s) is the ALREADY-EXISTING
# absolute-step-tick counter Hook C uses for the master-step fix, incremented by exactly
# 1 every step tick, never reset. This watch correlates G_ABSTICK against the stored
# table-arm value across several NATURAL (non-DJ) writes to empirically derive the
# G_ABSTICK <-> anchor-value relationship, rather than hand-deriving ColdFire EMAC
# fixed-point math from static disassembly (this session's own established preference:
# measure, don't guess, when the arithmetic is opaque).
TABLE_ARM_STORE_PC = 0x400a2e18
G_ABSTICK = 0x80006a46

# Session 79 continued a sixth time (NEXT item 1/2): GhidraDirectJump22-25.java found
# 0x800065c1/0x800065c2 are a "just-vacated ACT_BANK/ACT_PAT" snapshot, copied from
# ACT_BANK/ACT_PAT (0x800065bd/0x800065be) at TWO points inside FUN_400a1eea, each
# immediately followed by the actual PEND->ACT commit (gated on
# PEND_BANK/PEND_PAT != -1):
#   copy:   0x400a4074 (c1<-ACT_PAT), 0x400a4080 (c2<-ACT_BANK)
#   commit: 0x400a409e (ACT_PAT<-D1), 0x400a40aa (ACT_BANK<-*PEND_BANK)
# and the twin block:
#   copy:   0x400a44a6 (c1<-ACT_PAT), 0x400a44b2 (c2<-ACT_BANK)
#   commit: 0x400a44d0 (ACT_PAT<-D1), 0x400a44dc (ACT_BANK<-*PEND_BANK)
# Hypothesis: for an ordinary switch, copy always executes on the SAME pass as
# commit (so the snapshot is always the just-outgoing pattern). DIRECT JUMP's
# forced-early commit may reach the commit instructions via a different path that
# skips the copy -- this watch checks that directly instead of guessing further.
COMMIT_SITES = {
    "copy1_c1": 0x400a4074, "copy1_c2": 0x400a4080,
    "commit1_pat": 0x400a409e, "commit1_bank": 0x400a40aa,
    "copy2_c1": 0x400a44a6, "copy2_c2": 0x400a44b2,
    "commit2_pat": 0x400a44d0, "commit2_bank": 0x400a44dc,
}
SNAP_C1 = 0x800065c1
SNAP_C2 = 0x800065c2


def install_commit_watch(rt, eb):
    """Hook each COMMIT_SITES address, logging frame_count on every hit. Returns
    dict name -> list[frame]."""
    hits = {name: [] for name in COMMIT_SITES}
    for name, addr in COMMIT_SITES.items():
        def make(name=name):
            def on_hit(u, address, size, user):
                hits[name].append(rt.frame_count)
            return on_hit
        rt.uc.hook_add(eb.UC_HOOK_CODE, make(), begin=addr, end=addr)
    return hits


def print_commit_watch(hits):
    print(f"\ncommit-site PC hits (copy-to-snapshot vs PEND->ACT commit, "
          f"see COMMIT_SITES):")
    for name, addr in COMMIT_SITES.items():
        fr = hits[name]
        shown = fr[:20]
        more = f" ...(+{len(fr)-20} more)" if len(fr) > 20 else ""
        print(f"   {name:14s} (0x{addr:x}): {len(fr)} hits  frames={shown}{more}")


def install_table_arm_watch(rt, eb):
    """(frame, G_ABSTICK, stored_value, slot_index) at every TABLE_ARM_STORE_PC hit."""
    events = []

    def on_store(u, addr, size, user):
        d0 = u.reg_read(eb.UC_M68K_REG_D0)      # value about to be stored
        a1 = u.reg_read(eb.UC_M68K_REG_A1)       # slot index (see GhidraDirectJump29)
        abstick = int.from_bytes(rt.uc.mem_read(G_ABSTICK, 4), "big")
        events.append((rt.frame_count, abstick, d0, a1))
    rt.uc.hook_add(eb.UC_HOOK_CODE, on_store, begin=TABLE_ARM_STORE_PC, end=TABLE_ARM_STORE_PC)
    return events


def print_table_arm_watch(events):
    print(f"\ntable-arm store events (frame, G_ABSTICK, stored D0, slot A1), "
          f"{len(events)} total:")
    for fr, abstick, d0, a1 in events:
        print(f"   frame {fr:.1f}  G_ABSTICK={abstick}  D0={d0:#010x}  slot={a1}")
# Session 79 continued again: the SET side of the DAT_80001904 scheduled-value table,
# found via GhidraDirectJump15.java raw disassembly:
#   D0 = *G_ACCUM(0x4610757c) - 0x285ff0 + table_46c7a830[track] + D7 ; then stored into
#   DAT_80001904[track][slot]. D7 here is READ, not computed locally -- and D7 is exactly
# the register dj_c (patch_directjump.s) writes as its own commit mechanism
# (`D7 = resumeStep*newLen`, deliberately left live on return, never saved/restored,
# by its own header comment's design). FUN_400a1eea has zero static callers (it's the
# per-tick task body itself, a single long-running loop) -- if D7 is not reloaded at the
# top of every tick, dj_c's commit-tick write could leak into this unrelated computation
# on every SUBSEQUENT tick until something else overwrites D7. Watching D7's actual value
# at this exact PC, across both conditions, tests this directly.


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
    ap.add_argument("--groundtruth", action="store_true",
                     help="Session 78: also run the confound-free ground-truth "
                          "comparison (target pattern selected directly from the "
                          "start, no poke) and diff its DAT_80001904 table against "
                          "DJ_MODE=1's post-switch table. Skips the DJ_MODE=0 run "
                          "(shown this session to never actually switch, so it "
                          "cannot answer this question -- see NOTES.md Session 78).")
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

    if a.groundtruth:
        print(f"\n{'=' * 70}\nDJ_MODE=1 (DIRECT JUMP ON)\n{'=' * 70}")
        dj_result = run_one(er, a, True)
        print(f"\n{'=' * 70}\nground truth (target pattern selected directly, no poke, "
              f"run to frame={dj_result['post_frame']})\n{'=' * 70}")
        gt_result = run_groundtruth(er, a, dj_result["new_pat"], dj_result["post_step"],
                                     dj_result["post_frame"])
        compare_groundtruth(dj_result, gt_result, dj_result["new_pat"])
        return 0

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

    d7_at_arm = []  # (frame, D7 value) every time the table-arm site executes

    def on_arm(u, addr, size, user):
        d7_at_arm.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_D7)))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_arm, begin=TABLE_ARM_PC, end=TABLE_ARM_PC)

    # Session 79 continued a fifth time: two single-hypothesis rounds (D7, RESET_FLAG)
    # were both refuted. Rather than guess a third specific register/flag, trace every
    # PC actually EXECUTED across the whole known control-flow region (both scheduling-
    # table blocks, 0x400a2b00-0x400a2e30) within a frame window bracketing the
    # commit -- this directly shows which branch diverges between conditions without
    # needing to know in advance which one matters. Cheap: this code only runs a few
    # times per tick, filtered to a few hundred frames.
    pc_trace = []

    def on_trace(u, addr, size, user):
        if TRACE_FRAME_LO <= rt.frame_count <= TRACE_FRAME_HI:
            pc_trace.append((rt.frame_count, addr))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_trace, begin=TRACE_LO, end=TRACE_HI)

    commit_hits = install_commit_watch(rt, er.eb)
    snap_writes = []

    def on_snap_write(u, acc, addr, size, val, user):
        snap_writes.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_PC), addr, size, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_snap_write, begin=SNAP_C1, end=SNAP_C2)

    table_arm_events = install_table_arm_watch(rt, er.eb)

    # NOTE: rt.watch_mem() stores into self.mem_writes, looked up FRESH on every
    # hit -- calling it twice makes the FIRST hook's callback silently start
    # appending into the SECOND call's list too. Use independent closures instead.
    def make_watch(addr, length):
        log = []

        def on_write(u, acc, a, size, val, user):
            log.append((rt.frame_count, rt._cur(), u.reg_read(er.eb.UC_M68K_REG_PC), a, size, val))
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=addr, end=addr + length - 1)
        return log
    # Session 79 continued again: trace the actual trigger chain for the scheduling-
    # reset (GhidraDirectJump16/17/18.java): RESET_FLAG (0x8000668d, per-track bitmask,
    # tested at 0x400a2d8c) has two SET sites -- 0x400a13dc (unconditional, part of a
    # larger reset block) and 0x400a2264 (D0 = 1 << PREV_BANK_IX, gated on
    # PREV_BANK_IX(0x800065bc) != -1 and FLAG_80001860 set). Watch all three plus the
    # two early-bail globals (0x46107568 -- the SAME flag Hook F already reads at
    # 0x400a4d36 -- and 0x80001860) to see exactly which path fires at the commit.
    reset_flag_writes = make_watch(0x8000668d, 2)
    prev_bank_ix_writes = make_watch(0x800065bc, 1)
    flag_80001860_writes = make_watch(0x80001860, 1)
    flag_46107568_writes = make_watch(0x46107568, 4)
    # Session 79 continued a tenth time: both KNOWN static writers of 0x80006626 (the
    # table-arm-due bitmask) only CLEAR it (0x400a4054, 0x400a1384) -- no SET-bit write
    # was found by resolved-xref lookup or a literal-text scan, almost certainly because
    # it's written via computed/indexed addressing. A runtime write-watch can't miss it
    # regardless of addressing mode -- this settles it dynamically instead of guessing.
    table_arm_due_writes = make_watch(0x80006626, 2)
    # Session 79 continued a tenth time: GhidraDirectJump39.java found the ACTUAL
    # write-path gate is 0x80006682 (tested 0x400a2ae0), not 0x80006626 (which gates a
    # different CNTDN-recompute sub-block). 0x80006680/82/84 are a related per-track
    # bitmask family, all cleared together at every switch commit (0x400a4048-4054) --
    # find what SETS 0x80006682's bit back, dynamically (static text/xref scans keep
    # missing writers via computed addressing).
    bitmask_680_writes = make_watch(0x80006680, 2)
    bitmask_682_writes = make_watch(0x80006682, 2)
    bitmask_684_writes = make_watch(0x80006684, 2)
    # Session 79 continued a tenth time: all four bitmask-family writers above came back
    # silent (never written in either run) -- ruling them out as the dynamic "due"
    # signal. GhidraDirectJump39.java's own gate for the table-arm write path is a
    # BAR_CTR (0x800065b2) mod CHAIN-interval check. BAR_CTR is documented (NOTES.md
    # Session 15 map) as incremented unconditionally on EVERY step==0 body entry,
    # switching or not -- and DIRECT JUMP's own hooks (A-D) are known to force a
    # step==0 entry off the natural loop boundary to make the commit land. If that
    # forced entry ALSO bumps BAR_CTR an extra, out-of-cycle time (a side effect no
    # existing hook corrects for), it would trip this modulo check early -- exactly the
    # same class of bug Hooks A-F already fix elsewhere in this same commit path.
    bar_ctr_writes = make_watch(0x800065b2, 2)
    # Session 79 continued a twelfth time: Hook G/G2's tick-match fix built clean but
    # dynamically STILL doesn't suppress anything (post-build re-test shows every write
    # still going through the "normal" store path). Watch G_SUPPRESS_TICK directly to
    # see what dj_c actually wrote there and cross-check against G_ABSTICK's value at
    # that moment -- narrows whether the bug is in dj_c's write or Hook G's read/compare.
    suppress_tick_writes = make_watch(0x80006a4b, 4)
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
    # Session 79: continuous watch on the live-nibble table itself. Static analysis
    # (GhidraDirectJump9/10/11) found only 2 real writers image-wide (0x4009c220,
    # 0x4009c2ec), both inside an UNBOUNDED code region with ZERO call-type xrefs
    # landing on it anywhere -- meaning either it's reached only via fall-through as
    # part of a one-time init (matching its LEN_94-style neighbours' init-only
    # writes at frame 0) with the VALUE change we measured coming from somewhere
    # else entirely, or there's a genuinely indirect/computed writer no static text
    # scan can find. This watch settles it empirically instead of guessing further.
    live_nibble_writes = make_watch(LIVE_NIBBLE_IN, 256)
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
    post_step = rt.uc.mem_read(STEP, 1)[0]
    post_frame = rt.frame_count
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

    print(f"\n0x{LIVE_NIBBLE_IN:x} writes (DAT_80001904, live-nibble-in table), "
          f"{len(live_nibble_writes)} total:")
    for fr, task, pc, a, size, val in live_nibble_writes:
        slot = (a - LIVE_NIBBLE_IN) // 4
        print(f"   frame {fr:.1f}  slot {slot} (track {slot % 8}, group {slot // 8})  "
              f"[{a:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\nD7 at table-arm site (0x{TABLE_ARM_PC:x}), {len(d7_at_arm)} hits:")
    for fr, d7 in d7_at_arm:
        print(f"   frame {fr:.1f}  D7={d7:#x}")

    for name, log in (("0x8000668d (RESET_FLAG)", reset_flag_writes),
                       ("0x800065bc (PREV_BANK_IX?)", prev_bank_ix_writes),
                       ("0x80001860 (FLAG)", flag_80001860_writes),
                       ("0x46107568 (Hook F's own flag)", flag_46107568_writes)):
        print(f"\n{name} writes, {len(log)} total:")
        for fr, task, pc, a, size, val in log:
            print(f"   frame {fr:.1f}  [{a:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    print(f"\nPC trace over [0x{TRACE_LO:x}, 0x{TRACE_HI:x}], frames "
          f"[{TRACE_FRAME_LO}, {TRACE_FRAME_HI}], {len(pc_trace)} hits:")
    for fr, pc in pc_trace:
        print(f"   frame {fr:.1f}  pc={pc:#x}")

    print_commit_watch(commit_hits)
    print(f"\n0x{SNAP_C1:x}/0x{SNAP_C2:x} writes (the candidate snapshot pair), "
          f"{len(snap_writes)} total:")
    for fr, pc, addr, size, val in snap_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")
    print_table_arm_watch(table_arm_events)
    for name, log in (("0x80006626", table_arm_due_writes), ("0x80006680", bitmask_680_writes),
                       ("0x80006682", bitmask_682_writes), ("0x80006684", bitmask_684_writes),
                       ("0x800065b2 (BAR_CTR)", bar_ctr_writes),
                       ("0x80006a4b (G_SUPPRESS_TICK)", suppress_tick_writes)):
        print(f"\n{name} writes, {len(log)} total:")
        for fr, task, pc, addr, size, val in log:
            print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")

    return dict(fires=fires, fires_before_poke=fires_before_poke, d7_at_arm=d7_at_arm,
                pc_trace=pc_trace,
                reset_flag_writes=reset_flag_writes, prev_bank_ix_writes=prev_bank_ix_writes,
                flag_80001860_writes=flag_80001860_writes,
                flag_46107568_writes=flag_46107568_writes,
                phase_writes=phase_writes, gate_writes=gate_writes,
                cntdn_writes=cntdn_writes, step_audio_writes=step_audio_writes,
                refill_writes=refill_writes, live_nibble_post=live_nibble_post,
                live_nibble_writes=live_nibble_writes,
                commit_hits=commit_hits, snap_writes=snap_writes,
                table_arm_events=table_arm_events,
                table_arm_due_writes=table_arm_due_writes,
                bitmask_680_writes=bitmask_680_writes, bitmask_682_writes=bitmask_682_writes,
                bitmask_684_writes=bitmask_684_writes, bar_ctr_writes=bar_ctr_writes,
                new_pat=new_pat, post_bank=post_bank, post_step=post_step,
                post_frame=post_frame)


def run_groundtruth(er, a, target_pattern, target_step, target_frame):
    """Session 78/79: the DJ-vs-stock-poke comparison in run_one() turned out to be
    confounded -- a raw PEND_PAT/PEND_BANK poke with DJ_MODE=0 never actually
    reaches stock's own switch-commit code path at all (0x400a4c2e's gate write
    never fires, ACT_PAT never changes, across 2+ full pattern loops post-poke --
    see NOTES.md Session 78). So "DJ_MODE=1 vs DJ_MODE=0" cannot answer pass 15's
    question (does DIRECT JUMP's forced-early commit introduce a discontinuity
    into DAT_80001904 vs what that table looks like for an honestly-arrived-at
    pattern?).

    Attempt 1 (frame-count-matched to `frames_before` only): compared runs at
    DIFFERENT STEP values (1 vs 2) -- retracted, see NOTES.md Session 78.

    Attempt 2 (STEP-matched, first-reached): found the SAME 20/64 slots differ
    at matched STEP -- but a continuous write-watch added right after (this
    function's own `live_nibble_writes` hook) showed `DAT_80001904` is written
    roughly every 4 frames continuously throughout playback (362 writes across
    an ~1100-frame run), not once at pattern-selection as Session 70's 12th pass
    assumed -- so it plausibly depends on ABSOLUTE ELAPSED FRAMES since transport
    start (a periodic accumulator), not on STEP or lap count at all. Matching on
    first-reached-STEP left the two runs at wildly different absolute frame
    counts (59 vs 1101) -- a real, unconsidered confound. See NOTES.md Session 79.

    Attempt 3 (this version, frame-matched): select `target_pattern` directly (no
    poke, no DIRECT JUMP involved at all) and run to the SAME ABSOLUTE FRAME
    COUNT DJ_MODE=1's post-switch snapshot was taken at (`target_frame`) -- since
    both runs start their transport at frame ~1, this controls for the periodic
    accumulator directly, whatever drives it. Reports whether STEP also matches
    at that frame as a bonus check on `G_ABSTICK`'s own resume-step design.
    """
    card, staged_name = er.stage_project(a.project, "OCTABAM", None,
                                          tree="out/_emu_dj_tree_groundtruth")
    r, rt = er.attach(str(IMAGE), card,
                       ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)

    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live("OCTABAM", staged_name, run_ms=6000)
    bank = a.bank if a.bank is not None else saved_bank
    if bank is not None and final_bank != bank:
        final_bank = rt.select_bank_live(bank)
    seq_bank, seq_pattern = rt.seq_select_live(final_bank, target_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    # DJ_MODE left at its image default (0) -- this run never touches any
    # DIRECT JUMP hook at all, by construction (no poke, target already active).

    live_nibble_writes = []

    def on_write(u, acc, addr, size, val, user):
        live_nibble_writes.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_PC), addr, size, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write,
                    begin=LIVE_NIBBLE_IN, end=LIVE_NIBBLE_IN + 255)

    d7_at_arm = []

    def on_arm(u, addr, size, user):
        d7_at_arm.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_D7)))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_arm, begin=TABLE_ARM_PC, end=TABLE_ARM_PC)

    def gt_watch(addr, length):
        log = []

        def on_w(u, acc, a, size, val, user):
            log.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_PC), a, size, val))
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=addr, end=addr + length - 1)
        return log
    reset_flag_writes = gt_watch(0x8000668d, 2)
    prev_bank_ix_writes = gt_watch(0x800065bc, 1)
    flag_80001860_writes = gt_watch(0x80001860, 1)
    flag_46107568_writes = gt_watch(0x46107568, 4)
    table_arm_due_writes = gt_watch(0x80006626, 2)
    bitmask_680_writes = gt_watch(0x80006680, 2)
    bitmask_682_writes = gt_watch(0x80006682, 2)
    bitmask_684_writes = gt_watch(0x80006684, 2)
    bar_ctr_writes = gt_watch(0x800065b2, 2)

    pc_trace = []

    def on_trace(u, addr, size, user):
        if TRACE_FRAME_LO <= rt.frame_count <= TRACE_FRAME_HI:
            pc_trace.append((rt.frame_count, addr))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_trace, begin=TRACE_LO, end=TRACE_HI)

    commit_hits = install_commit_watch(rt, er.eb)
    snap_writes = []

    def on_snap_write(u, acc, addr, size, val, user):
        snap_writes.append((rt.frame_count, u.reg_read(er.eb.UC_M68K_REG_PC), addr, size, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_snap_write, begin=SNAP_C1, end=SNAP_C2)

    table_arm_events = install_table_arm_watch(rt, er.eb)
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    print(f"groundtruth: selected bank={final_bank} pattern={target_pattern} directly, "
          f"no poke, DJ_MODE untouched -- running to frame {target_frame} "
          f"(matching DJ_MODE=1's post-switch snapshot frame; want STEP={target_step})")

    rt.run(ms=target_frame * er.FRAME_PERIOD / er.SAMPLE_HZ * 1000.0 * 5 + 10000,
           until=lambda x: x.frame_count >= target_frame)

    cur_bank = rt.uc.mem_read(ACT_BANK, 1)[0]
    cur_pat = rt.uc.mem_read(ACT_PAT, 1)[0]
    cur_step = rt.uc.mem_read(STEP, 1)[0]
    live_nibble = rt.uc.mem_read(LIVE_NIBBLE_IN, 256)
    reached = cur_step == target_step
    print(f"settled    : active bank={cur_bank} pattern={cur_pat} step={cur_step} "
          f"frame={rt.frame_count} (STEP {'MATCHES' if reached else 'DOES NOT MATCH'} "
          f"DJ_MODE=1's own resume step {target_step})")
    print(f"live-nibble-in (0x{LIVE_NIBBLE_IN:x}, 64 x u32): {live_nibble.hex()}")
    print(f"\n0x{LIVE_NIBBLE_IN:x} writes (DAT_80001904, live-nibble-in table), "
          f"{len(live_nibble_writes)} total:")
    for fr, pc, addr, size, val in live_nibble_writes:
        slot = (addr - LIVE_NIBBLE_IN) // 4
        print(f"   frame {fr:.1f}  slot {slot} (track {slot % 8}, group {slot // 8})  "
              f"[{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")
    print(f"\nD7 at table-arm site (0x{TABLE_ARM_PC:x}), {len(d7_at_arm)} hits:")
    for fr, d7 in d7_at_arm:
        print(f"   frame {fr:.1f}  D7={d7:#x}")
    for name, log in (("0x8000668d (RESET_FLAG)", reset_flag_writes),
                       ("0x800065bc (PREV_BANK_IX?)", prev_bank_ix_writes),
                       ("0x80001860 (FLAG)", flag_80001860_writes),
                       ("0x46107568 (Hook F's own flag)", flag_46107568_writes)):
        print(f"\n{name} writes, {len(log)} total:")
        for fr, pc, a, size, val in log:
            print(f"   frame {fr:.1f}  [{a:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")
    print(f"\nPC trace over [0x{TRACE_LO:x}, 0x{TRACE_HI:x}], frames "
          f"[{TRACE_FRAME_LO}, {TRACE_FRAME_HI}], {len(pc_trace)} hits:")
    for fr, pc in pc_trace:
        print(f"   frame {fr:.1f}  pc={pc:#x}")
    print_commit_watch(commit_hits)
    print(f"\n0x{SNAP_C1:x}/0x{SNAP_C2:x} writes (the candidate snapshot pair), "
          f"{len(snap_writes)} total:")
    for fr, pc, addr, size, val in snap_writes:
        print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")
    print_table_arm_watch(table_arm_events)
    for name, log in (("0x80006626", table_arm_due_writes), ("0x80006680", bitmask_680_writes),
                       ("0x80006682", bitmask_682_writes), ("0x80006684", bitmask_684_writes),
                       ("0x800065b2 (BAR_CTR)", bar_ctr_writes)):
        print(f"\n{name} writes, {len(log)} total:")
        for fr, pc, addr, size, val in log:
            print(f"   frame {fr:.1f}  [{addr:#x}] <- {val:#x} ({size}B) at pc {pc:#x}")
    return dict(bank=cur_bank, pattern=cur_pat, step=cur_step, live_nibble=live_nibble,
                reached=reached, live_nibble_writes=live_nibble_writes, d7_at_arm=d7_at_arm,
                pc_trace=pc_trace,
                reset_flag_writes=reset_flag_writes, prev_bank_ix_writes=prev_bank_ix_writes,
                flag_80001860_writes=flag_80001860_writes,
                flag_46107568_writes=flag_46107568_writes,
                commit_hits=commit_hits, snap_writes=snap_writes,
                table_arm_events=table_arm_events,
                table_arm_due_writes=table_arm_due_writes,
                bitmask_680_writes=bitmask_680_writes, bitmask_682_writes=bitmask_682_writes,
                bitmask_684_writes=bitmask_684_writes, bar_ctr_writes=bar_ctr_writes)


def compare_groundtruth(dj_result, gt_result, target_pattern):
    print(f"\n{'=' * 70}\nDJ-commit vs ground-truth DAT_80001904 comparison "
          f"(target pattern {target_pattern}, both sampled at frame={dj_result['post_frame']}; "
          f"STEP {dj_result['post_step']} vs {gt_result['step']})\n{'=' * 70}")
    if not gt_result["reached"]:
        print(f"NOTE: at the matched frame, ground-truth's own STEP ({gt_result['step']}) "
              f"does NOT match DJ-commit's ({dj_result['post_step']}) -- informative on its "
              f"own (a divergence in the resume-step math itself, separate from the table "
              f"comparison below).")
    dj_tbl = dj_result["live_nibble_post"]
    gt_tbl = gt_result["live_nibble"]
    diffs = [i for i in range(64) if dj_tbl[i * 4:i * 4 + 4] != gt_tbl[i * 4:i * 4 + 4]]
    if not diffs:
        print("IDENTICAL across all 64 slots at matched ABSOLUTE FRAME -- no evidence "
              "DIRECT JUMP's forced-early commit disturbs this table.")
        return
    print(f"{len(diffs)} of 64 slots differ, AT MATCHED ABSOLUTE FRAME -- a real "
          f"discontinuity, controlled for both STEP-vs-lap-count and elapsed-time "
          f"confounds. Differing slots:")
    for i in diffs:
        dj_v = int.from_bytes(dj_tbl[i * 4:i * 4 + 4], "big")
        gt_v = int.from_bytes(gt_tbl[i * 4:i * 4 + 4], "big")
        print(f"   slot {i:2d} (track {i % 8}, group {i // 8}): "
              f"DJ-commit={dj_v:#010x}  ground-truth={gt_v:#010x}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

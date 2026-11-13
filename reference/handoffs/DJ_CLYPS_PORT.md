# DIRECT_JUMP_KYOTI <- Clyps' rules (handoff, 2026-11-12)

**What:** DIRECT JUMP (`octabam-modules/direct-jump-kyoti/patch_directjump_v7.s`, FINAL on main, V7.0.1) gets the
trig-condition rule the user approved in Clyps (KYOTI CL25-CL32, worktree `../octatrack-kyoti-fw-trkseq`, branch
`trkseq`, `tools/clyps/patch_clyps.s`), and two questions measured and reported. The user's standing rule
(2026-11-12): what is approved working for Clyps is applied, as applicable, to RELOAD_FROM_PROJECT and DIRECT JUMP.
The user: DIRECT JUMP "works perfectly" -- change nothing beyond item 1 without the user's decision.

Read first: `CLAUDE.md`, `reference/handoffs/CLYPS_SCOPE.md` §1.28-§1.32, NOTES.md "KYOTI CL25" / "KYOTI CL26",
`reference/handoffs/RELOAD_CLYPS_PORT.md` (the shared rules, in detail), the V7 header of patch_directjump_v7.s.

## 1. Implement: a jump keeps the trig conditions where a never-switched pattern would have them

Today `dj_handoff` calls COND_RESET(-1) (`0x400a539c`): every A:B counter restarts at the jump (stock's switch
behaviour). The user (2026-11-12): instant loads -- DIRECT JUMP's jumps included -- set the conditions as if the
incoming sequence had been playing there all along. In Clyps (`cl_cond`, `cl_creset`, `cl_T`): a track's A:B pass
counter 0x46107918[t] = the passes it would have begun since the conditions last restarted, F(now) - F(R) -- see
RELOAD_CLYPS_PORT.md rule 3 for F and the measured stock facts (a pass starts at each own wrap, t' = j*len*tps - tps,
and at the master restart, the wrap body t' = C - tps_M, once when they coincide). For DIRECT JUMP the natural R is
PLAY (its position is clock-locked since START, dj_T): each track's counter = its pass starts since START in the
INCOMING pattern's model (dj_bparams, dj_tprime). Decide (and report) what the latch bytes 0x46107959 / 69 / 79
(FILL / first) should hold: COND_RESET(t) sets 59 = 69 = 0, 79 = 1. Measure against a never-switched reference run
(tools/diag_reflock.py / model_reflock.py, DJ's own REF-LOCK oracle: the reference plays the incoming pattern from
START; after the jump RUN's counters must equal REF's at every tick).

## 2. Measure and report only: the boundary purge race

DIRECT JUMP lands like Clyps CL25 did: stock's landing (D2) fires every track's boundary step on the boundary tick
itself (ahead 1) and dj_purge keeps events whose fire time - the sample clock < 0. On the unit Clyps CL25 showed that
comparison flipping by an audio frame (the old step stayed, the new one was dropped: "offset for one step"); Clyps
CL26 fixed it by landing a tick earlier (ahead 2, the purge a tick ahead). DIRECT JUMP also posts the audio engine's
pattern switch at that sample clock (ENG_ATIME), which may make the engine drop old-pattern events -- so the race may
be harmless here. Find out (the engine side 0x4000b1dc / 0x46c7fa80), and report; do not change it.

## 3. Report only: the incoming Part's settings on the outgoing sound

A jump applies the incoming Part at the jump (the engine's light Part apply 0x40009e00 at ENG_ATIME), so a sample
still ringing from the outgoing pattern hears the incoming settings until the new pattern's first trig -- the thing
the user had removed from Clyps' FULL loads ("a user should simply never hear the incoming sequence's track settings
applied to what they are changing away from": Clyps publishes per track at the first SOUNDING trig, `cl_sptrig`).
It is also stock's pattern-change behaviour. Describe what a per-track deferral would take for DIRECT JUMP; the
user decides.

## How (constraints)

- Own worktree: `tools/worktree.sh new dj-clyps` (from origin/main). Explicit-path commits with DIRECT JUMP's
  `Thread:` line. **Do not push; do not promote** -- report back.
- DIRECT JUMP is FINAL and is in KYOTI (integrated with Clyps in KYOTI-with-Clyps via build_kyoti's SUPERSEDE of the
  phase-D site 0x400a1f72); every form must rebuild (standalone `tools/build_direct_jump_kyoti.py`, the default
  KYOTI image, Bugbuild BUG_DJV7, the octabam module) and stay WIP until the user promotes. Clyps owns
  0x400a539c (its COND_RESET detour, `cl_creset`) in KYOTI-with-Clyps: a DIRECT JUMP detour there would collide --
  coordinate (in KYOTI-with-Clyps, DJ can read Clyps' cl_Tres; standalone, DJ needs its own).
- V6.4 (`tools/build_direct_jump_v6_4.py`) is frozen: do not touch.
- ColdFire / emulator traps as in RELOAD_CLYPS_PORT.md.

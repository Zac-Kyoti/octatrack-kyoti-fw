# RELOAD_FROM_PROJECT <- Clyps' landing rules (handoff, 2026-11-12)

**What:** port the timing / publish / trig-condition rules the user approved in Clyps (KYOTI CL25-CL32, worktree
`../octatrack-kyoti-fw-trkseq`, branch `trkseq`, `tools/clyps/patch_clyps.s`) into the standalone
RELOAD_FROM_PROJECT (`octabam-modules/reload-from-project/patch_reload3.s`, FINAL on main). The user's standing rule
(2026-11-12): whatever is approved working for Clyps is applied, as applicable, to RELOAD_FROM_PROJECT and DIRECT
JUMP. Timing is frozen at Clyps CL29's design (the user: "that version was correct").

Read first: `CLAUDE.md` (Concurrent sessions, hard constraints), `reference/handoffs/CLYPS_SCOPE.md` §1.28-§1.32,
NOTES.md "KYOTI CL25" / "KYOTI CL26" / "CL24 timing investigation", and `patch_reload3.s`'s dated rule comments.

## The rules (Clyps' code in parentheses)

1. **Land one tick BEFORE the boundary, fire for it** (`cl_land` la_tracks, `cl_ffland`, `cl_ffok`, `cl_tpurge`,
   `cl_fixup`). With t' = the master-cycle time of the NEXT tick (signed: t0 + 2, t0 = (MASTER_STEP - 1) * tps_M +
   TICK_CTR, read in phase D), a track lands on the tick where t' = 0 mod its old AND new tps (a pattern / rate
   change: and the master's, old and new), only when t' >= 0 and its CNTDN 0x800065c3[t] < 0 (no stock landing
   pending). Then STEP = (t' / tps) mod len, STEP-1, TICKS 0, the scale cache, RELOAD 0x800065d3[t] = tps - 2, the
   first-fire bit in 0x80006624, its HOLD bit (0x80006626) cleared, and its pending events with fire time >= now
   purged (DIRECT JUMP's pg_table for one track: audio 0x80001904/0x46c7e998/0x46c7fe44 and 0x80001984/0x46c7faa4/
   0x46c7fe8c vs 0x4610757c; MIDI 0x46c76a26/0x46c769c0/0x46c77be2 vs 0x46107564). Phase E builds the step from the
   new record with ahead = 2: it fires exactly where the old boundary event would have. The NEXT tick, RELOAD[t]
   goes back to the never-switched value (unchanged rate: the old one; else max(0, tps_new - tps_M), or 0 for a
   slower track still in its first master cycle -- `cl_ffland` ff_fx).
   *Why:* stock / DIRECT JUMP land on the tick before the boundary with first fire; landing ON the boundary tick
   (RELOAD's rl_ctr: STEP = t0/tps + 1, look-ahead) plays the OLD step at the boundary (a step late). Clyps CL25
   tried first-fire ON the boundary tick: on the unit the old event and the sample clock are a frame apart there,
   so the purge sometimes kept it (heard as "offset by one step"). One tick earlier there is no race (measured
   margin: one full tick in every purge).
   A pattern rate change re-phases the master as stock's landing puts it: MASTER_STEP = (t' / tps_M) mod len,
   TICK_CTR = tps_M - 2 (`cl_mreph`). Non-member tracks keep their built step when rate and place are unchanged.
2. **FULL: the slice (and a new machine's voice restart) reaches the engine when the incoming sequence first
   TRIGGERS a sample that actually sounds** (`cl_spwait`, `cl_sptrig`, `cl_spdo`, `cl_ftrig`). The user: "a user
   should simply never hear the incoming sequence's track settings applied to what they are changing away from".
   At the landing the slice is copied into the Part (the builder reads it) and the publish waits: each tick scan the
   track's pending events for a record with bit 2 set (the builder's 29 / 61 = sample / note trig; 25 = trigless,
   1 = empty) whose fire time >= the landing's clock, and publish (TRK_APPLY / the MIDI apply + the restart bit) on
   the tick where fire time - now < half a tick (audio 0x142ff8, MIDI 8400). Micro-timing and trig conditions are
   thereby honoured (a failed condition is never built). A sequence without any sample trig (mask: the record's
   first 8 bytes, big-endian, bit s = step s) publishes on the boundary tick. A stop publishes at once.
3. **Trig conditions** (`cl_cond`, `cl_creset`, `cl_T`; scope §1.29 C). In-place loads (all of RELOAD's) set the
   landed track's A:B pass counter 0x46107918[t] to the passes it would have begun since the pattern's conditions
   last restarted had it played there all along: F(now) - F(R), F(x) = pass starts before tick x = q * K + f(u)
   (q, u: floor-divided position of x - B in the master cycle C = mlen * tps_M; per cycle K = J + (rem != 0), J =
   floor((C - tps_M + tps) / c), c = len * tps; f(u) = min(floor((u + tps - 1) / c), J) + (rem && u > C - tps_M);
   INF: floor((x - B + tps - 1) / c)); B = this master cycle's first tick. R = the tick of the last COND_RESET(-1):
   a detour at 0x400a539c (stock bytes 4feffff4 48d70c04) notes it; stock's switch (return address 0x400a4856)
   counts from the next tick. Measured exact (M1-M3, every track every tick). FIRST trigs then do not fire.
4. Already in RELOAD, keep: skip MASTER_STEP == 0 (or adopt the signed t' of rule 1), generations, the cancel,
   unchanged slices not re-published, a link change judged against the sounding Part, the unmasked copy.

Not applicable to RELOAD: Clyps' arrows / LEDs / [PAGE] / header, cl_back, the Part shadow (RELOAD's FULL source is
the card), the pattern reload is RELOAD's own.

## How (constraints)

- Own worktree: `tools/worktree.sh new reload-clyps` (from origin/main). Commit explicit paths with the RELOAD
  thread's `Thread:` line (tools/githooks/threads.txt). **Do not push; do not promote** -- report back.
- RELOAD is FINAL: every form must rebuild (standalone `tools/build_reload_from_project.py`, the default KYOTI image,
  Bugbuild BUG_RL3, the octabam module), WIP until the user promotes; `seal()` pins stay untouched until then.
- Gates: RELOAD's own (`tools/diag_reload_quant.py`, `diag_reload_oracle.py`, `diag_reload_ptn.py`) with their
  expectations moved to the new rules exactly as Clyps' `diag_clyps_quant.py` was (landing tick = the tick before
  the boundary: t0 + 2 = 0 mod tps; ticks before the copy = tps - 2; slices published on the first sounding trig's
  tick; master after a re-phase: tick tps - 2). Clyps' `tools/diag_clyps_lock.py` + `check_clyps_lock.py --rules`
  + `check_clyps_full.py` show how to grade tick-by-tick against DIRECT JUMP's model; adapt them to RELOAD's gestures.
- ColdFire traps: no predecrement movem; cmpi only Dn; no move.l #imm,abs; widen .b branches; bclr #n only on
  (An) / Dn; emu_rtos's call_as_main leaks args (use the restoring main_call); runs take 30-120 min, parallel with
  distinct --name; a dead emulator with no traceback = another session rebuilt the shared Unicorn: rerun.

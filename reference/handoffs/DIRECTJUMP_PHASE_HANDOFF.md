# DIRECT JUMP — handoff: the non-1x sub-step PHASE bug

Written at the end of Session 89; **current state rewritten Session 104 (2026-09-26)**.
Read §0 first — everything after it is the history of how the thread got here.

## 0. CURRENT STATE (Session 105) — read this, then `reference/AR_SEQUENCER_ENGINE.md` §3 and §6, then NOTES.md Session 105

**GOLD IS RETRACTED (2026-09-26, user, hardware).** `GOLD_S87` reproduces step-fractional
playback at 1x, NORMAL mode, no scales, a 16-step ↔ 7-step switch. Nothing below that
calls gold or V5.3 "correct" or "a gate" holds any more; they are regression references
only. **Root cause, architectural:** every OT build since Session 79 committed a jump by
re-entering the pattern-boundary body with an absolute offset (`0x80006628`) — AR's
*wrap-change* path (ceil / remainder / hold / catch-up / deferred landing), which AR uses
only at natural cycle wraps and never for a jump. AR's actual DIRECT JUMP commit is a
separate phase of its tick ISR that runs before the per-track scheduling: countdown to
the next master step boundary, synchronous rebuild of every track (step, tick 0,
`cntdn = tps−1`, no hold, no catch-up), master phase set to `tps−1` so the step body runs
the same tick. It carries **no sub-step remainder** — V5.7–V5.11's `dj_mrem` came from a
mis-attribution (the remainder pair is AR's pause/Song-Position mechanism) and is
withdrawn. The port restarts from `AR_SEQUENCER_ENGINE.md` §6.

**Session 105 continued — the OT measurements are DONE and the design is fixed (NOTES.md
"Session 105 continued", read the whole block).** OT's tick handler is AR's phase for phase,
and it already contains AR's DIRECT JUMP landing: the countdown `0x80006687` path at
`0x400a1f72`–`0x400a222e` rebuilds all 16 tracks from a snapshot (`0x80006516[t]` step words,
`0x80006536[t]` ticks, `0x8000663a` master step), sets `TICK_CTR = tps−1`, the first-fire mask
`0x80006624 = 0xffff` and `CNTDN = −1`, and runs BEFORE the scheduler (`0x400a2982`). **V6 =
one 6-byte detour at `0x400a1f72`** (arm: `0x80006687 = tps − TICK_CTR`; land: swap ACT←PEND,
`0x80006638 = MASTER_STEP mod masterLen`, `0x80006516[t] = new_step mod len_t`, ticks 0)
**+ one at `0x400a221c`** (no MIDI `0xFA` on a jump) + the existing UI pieces. Every V4/V5
sequencer hook (`dj_a/b/c/d7/scaleix`, Z/X/V) is deleted; the boundary body stays stock.
The builder does not exist yet — next session writes `patch_directjump_v6.s` /
`build_directjump_v6.py` and runs the gate order given at the end of the NOTES block.

*(Session 104 text follows, kept as history.)*

**Baseline, formerly believed hardware-confirmed:** the Session 87 GOLD image (`out/GOLD_S87_*`,
sha256 `0657157f…`; rebuild from commit `16df386` with `build_directjump_v4.py`
*there* — at HEAD that builder assembles today's shared `patch_directjump.s` and no
longer reproduces gold, so it is SUPERSEDED). Was thought correct at a 1x master scale for
everything: master time, landing steps, odd track lengths, track scales, NORMAL and
PER-TRACK modes, MASTER LENGTH incl. INF. **Retracted in Session 105 — see above.**

**Current line: V5.11** (`build_directjump_v5.py`, WIP tier — `KYOTI_ALLOW_WIP=1`;
mainline `9b6b27b5`, diag twin `V5_11D` `12396a2e`) = gold's six detours + ONLY the
master-remainder seed (`dj_mrem`: Hook H's `ticks mod tps_in` written into the master
tick counter at the armed commit where stock writes 0 — a byte-equal no-op at 1x, and
AR's own mechanism, `reference/AR_DIRECT_JUMP.md` §9). Emulator: identical to V5.3 at
uniform 1x, DJ-on-idle identical, feature-off identical. **Hardware check PENDING** —
the user verifies lengths / NORMAL / PER-TRACK / track scales first.

**Rolled back:** V5.5–V5.10's per-track preserve/defer machinery (Hooks Z/X/V, masks
`dj_keep_pend`/`dj_keep_pend2`) — still in source behind `DJ_PRESERVE=1`, OFF. It
improved 1x↔2x on the unit but never generalised, and V5.10 regressed gold at odd
track lengths / NORMAL mode (toast `W=7608`: pending bits for tracks the audio tail
never applies — MIDI 8-15 and more — were never consumed).

**Open:**
1. Non-1x master scales — to be REDESIGNED from AR's architecture: rebuild every
   per-track value from ONE time-true anchor, preserve nothing. Gates from day one:
   gold equivalence at 1x (diff vs `out/V5_3_*`), DJTEST2 (odd lengths, mixed scales),
   DJMAST2 (master scales), and the fire-timestamp oracle.
2. The DJ-OFF-persistent fractional latch (seen on V5.9/V5.10): if it recurs on V5.11
   the seed is the only suspect left → build V5.11 minus the seed.
3. MIDI twin sites of the patched blocks (`0x400a4cb0` area) — never covered.

**Tools that survive:** `tools/diag_tablearm_phase.py` (THE audible observable —
scheduled fire timestamps `DAT_80001904`, per-writer class counts), `diag_fire_phase.py`
(`FUN_400a536c` = reposition callback, not trig dispatch), `diag_phase_correlate.py`
(advances; the wrong observable on its own), `diff_stock_vs_patch.py` (`--patched`
required; `--dj-on`; `--stock` any image), `emu_djdiag.py` (toast path). Diag toast
`A Z X W N R M` overflows the screen at large counts — keep future toasts short.

---

## History (Sessions 89-103), oldest framing first

> **SESSION 97/98 UPDATE — §3's fix is BUILT (V5.5, `e3e5d232…`), oracle-clean, and
> was FLASHED: HARDWARE REPORTS NO CHANGE in the failing case.** The user adds a
> discriminating observation: per-track LENGTHS and SCALES (multipliers) all hold time
> against the metronome; the fractional offsets appear ONLY when a master scale other
> than 1x is involved — pointing at the MASTER domain (Hook H discards `ticks mod
> tps_in` when reseeding the master position, and stock zeroes the master tick counter
> at the commit), and/or at the third writer below, which the Session 97 emulator
> fixtures NEVER EXERCISED (PAIR read 0 at every commit — a measured blind spot, not
> evidence of absence). Emulator detail below stands as logic-evidence only:
> `re-phased? = no` on every armed commit in DJMAST2 0↔1, and zero
> re-phasing anywhere at uniform 1x. Built as *suppression*, not snapshot/restore: the
> commit tail turned out to be CNTDN-deferred per track, with both destroying writes in
> the same tick per track, so Hook Z (0x400a4bea) skips the zero and Hook X (0x400a3542)
> consumes a per-track cave-resident arm bit (`dj_keep_pend`, 0x400d791e — NOT
> 0x80006a40+) and reduces the preserved counter mod the track's new tps. §4's snapshot
> buffer and restore-site question are OBSOLETE. A third destroying write was found
> (hold-consume → 0x80006624 bit → 0x400a355e copies PAIR into the counter at first
> wrap+1); it never fired in the fixtures (PAIR=0 throughout) and is the designated
> suspect if hardware still shows fractional steps at armed commits — its detour window
> 0x400a3556 is pre-verified. §6 (natural-wrap re-phasing) remains open and is now the
> ONLY re-phasing source left at non-1x in the emulator. Full detail: NOTES.md
> Session 97.

---

## 1. State, and what is on the unit

| build | mainos sha256 | status |
|---|---|---|
| `GOLD_S87_*` | `0657157f` | Session 87 baseline, 1x-only. Commit `16df386`. |
| `V5_0_*` | `60230e02` | Hook P removed. Commit `95812d9`. |
| `V5_1_*` | `34fec20c` | **DO NOT FLASH** — hardware-rejected. |
| `V5_2_*` | `6d09452b` | + `0x80006638` pairing. Commit `6e22cc1`. |
| `V5_3_*` | `8cb167ae` | + time-domain conversion. Commit `0e2726c`. Hardware: 1x fine; the 2x position invariant held. The 1x gold-equivalence reference image for V5.11's gates. |
| `V5_4_*` | `77809aca` | + Hook S (PAIR→CATCHUP). PARTIAL. Commit `deb8d12`. |
| `V5_5_*` | `e3e5d232` | − Hook S, + Hooks Z/X (preserve). Oracle-clean. **HARDWARE: NO CHANGE in the failing case** (fractional step-time on master-scale switches persists; 1x baseline + per-track lengths/scales confirmed nominal). Session 97/98. |
| `V5_5D_*` | `ab0d806f` | Session 99 diagnostic (V5.5 + counters). **FLASHED — readings `A5 Z40 X16 Y0 P0 R0` (X/R vary run-to-run; R=0 on fractional runs)**: third writer dead, master remainder not the cause, and the 0x400a354a copy fires for only a timing-dependent minority of tracks on hardware. NOTES Session 100. |
| `V5_11_*` | `9b6b27b5` | **Session 104 — ROLLBACK, the current line (hardware check pending).** V5.10 regressed gold-confirmed 1x behaviour (odd lengths, NORMAL/PER-TRACK): Hooks Z/X/V + masks are now OPT-IN (`DJ_PRESERVE=1`) and OFF; detour set == V5.3's six; only the master-remainder seed (`dj_mrem`, a byte-equal no-op at 1x, AR's own mechanism) is kept. Diag twin `V5_11D_*` `12396a2e`. **The non-1x thread restarts from AR's architecture (rebuild every per-track value from ONE time-true anchor) with gold + DJTEST2 odd lengths + DJMAST2 scales as day-one gates.** OPEN: DJ-OFF-persistent latch (seed is the sole remaining suspect). |
| `V5_10_*` | `ab8a41bb` | Session 103 — SUPERSEDED (hardware: regressed gold at odd lengths / NORMAL mode; W=7608). Hook V @0x400a4bb6: while a preserve is pending, `CNTDN[t] = tps_t − counter[t]` per tick, deferring each track's WHOLE apply (STEP write + reposition fire) onto its own boundary — no duplicate, no missing trig, no lurch, wraps and armed commits alike. Hook W retired (site stock); masks split (`dj_keep_pend` consumed by Z at the apply, `dj_keep_pend2` by X) after the gate chain caught an infinite re-apply. Diag twin `V5_10D_*` `78a995b8` (trigscale relocated to 0x400d7bc0 under DJ_DIAG only). **OPEN: the DJ-OFF-persistent fractional latch** — correlate with N on the next flash. |
| `V5_9_*` | `e46cc4b2` | Session 102 — superseded. Hardware: missing/spurious step-1 trig every cycle (Hook W's suppression was wrong at wraps). Hook W @0x400a4bdc: the tail's reposition fire is suppressed only when the preserved counter is mid-step at fire time (the once-per-cycle half-step spurious trig that appeared with V5.8's wrap-preserve; stock's zero made the two fire paths exclusive). Diag twin `V5_9D_*` `2bcbac11`, toast `A Z X W N R M`. |
| `V5_8_*` | `285fadb8` | Session 101 — THE WRAP FIX, superseded. Hardware: large 1x↔2x improvement (fractional confined to the landing interval, heals at cycle restart) but introduced the per-cycle spurious trig. The audible observable is the fire-timestamp table DAT_80001904 (oracle: tools/diag_tablearm_phase.py); the fractional flip originates at NATURAL WRAPS (§6 = the audible bug, not a separate thread) and the preserve carried it forever. V5.8: preserve covers every commit incl. wraps while DJ is ON. Diag twin `V5_8D_*` `27257715`. |
| `V5_7_*` | `83a551c8` | Session 100: BOTH hardware-proven holes closed — mod-reduce moved INTO Hook Z (deterministic, Z=8·A), and dj_c seeds the master tick counter with Hook H's remainder (`dj_mrem`) instead of stock's zero (second reading R=4 proved commits land mid-master-step and the incoming grid re-anchored r ticks late). Diag twin `V5_7D_*` `116d1678`, toast `A Z X Y P R M`. |

Hashes in `out/BUILDS_SHA256.txt`, provenance in `out/BUILDS_README.txt`. The `V4`/`V5`
*names* get reused by builds; the hashes do not. Never overwrite `GOLD_S87_*`.

`tools/build_directjump_v5.py` refuses to build if the image differs from gold anywhere
outside the patch cave (declared detour sites excepted).

## 2. What WORKS on hardware as of V5.3

- The full Session 87 1x baseline: master time held through switches, correct landing
  steps, mixed track LENGTHS, MASTER LENGTH incl. INF, no doubled trigs.
- Master scale 2x on a single pattern, no switching: nominal, and the trig-content
  dependence is GONE (that was Hook P).
- **The user's position invariant now holds**: with two 16-step tracks and pattern 2 at
  master 2x, pattern 1 step 1 coincides with pattern 2 step 1, and pattern 2 step 1 with
  pattern 1 step 1 **or 9**.

## 3. The remaining bug, and its exact specification

Pattern switches leave tracks in **fractional step-time relative to the metronome** —
usually, occasionally clean, never self-correcting, in both directions.

Stock destroys the track's tick counter twice at a commit:

```
0x400a4bf0   TICKS_IN_STEP[t] = 0        ; inside the tail's CNTDN_TBL[t] == 0 body
0x400a354a   TICKS_IN_STEP[t] = CATCHUP[t]  ; move.b (a2),(a1), gated on CNTDN_TBL[t] == 0
                                            ; at 0x400a353e. CATCHUP = 0x800065d3[t] =
                                            ; max(0, tps_t - tps_master), set at 0x400a49aa.
                                            ; It is 0 at 1x -- hence invisible there.
```

**THE DERIVED SPEC (tools/diag_phase_correlate.py):** if the track last advanced at tick
`A`, its counter must read `(C - A) mod tps_t` at commit tick `C`. Minus the per-tick
increment that follows, that is **exactly what the free-running counter already holds**.

```
commit  prevAdv  REQUIRED  PAIR  rem  catchup  0x354a  match?
    42       41         1     0    0        3       0   NONE of them
    90       89         1     0    0        3       3   NONE of them
   201      197         4     0    0        0       0   NONE of them
```

No quantity stock computes can equal it — the required value depends on where the commit
falls relative to THAT TRACK's last advance, which is not a function of the master
position. **So do not compute a replacement phase. Preserve the counter.**

## 4. The implementation, and why it is not one hook

Our detour site `0x400a4d36` lies **between** the two destroying writes. So a single hook
there is always overwritten by `0x400a354a`. It needs:

- a **snapshot** of `TICKS_IN_STEP[0..15]` before the tail (Hook H's site `0x400a47f6`
  runs early enough), and
- a **restore** after `0x400a354a`.

Both gated on `DJ_MODE` + an armed commit, so DJ-OFF and 1x stay untouched.

Hazards to design around, not discover:
- 16 bytes of scratch are needed. `0x80006a40..4a` is under suspicion from the QLREC
  thread (`0x80006a60` proved unreliable; a static "no references" scan cannot see
  register-indirect writes). `tools/diag_dj_scratch_clobber.py` found no stock writer over
  260 ticks of transport + armed jumps, but that does NOT cover sequence editing (the
  trigger for RELOAD's report #7), menus, arranger, or project load/save.
- A restore site after `0x400a354a` has not been chosen. It must run before the per-tick
  increment at `0x400a3ce2` in the same tick.
- Session 89 faulted the emulator with a register-frame mismatch (save 16 B / restore
  32 B). Assert save and restore agree, in the build, every time.

## 5. DO NOT RE-TRY — four measured dead ends

1. **Clearing the hold mask `0x80006626`** (Hook Q). Hardware-rejected: did not fix the
   fractional state and ADDED an extra trig. `PAIR[t] = D7 mod tps_t` is the correct
   sub-step phase and stock's position is `ceil(D7/tps_t)`, which overshoots by one step
   exactly when `PAIR != 0`; the hold **skips one advance to convert that ceil to floor**.
   It is stock's compensation for its own rounding, not a bug.
2. **`PAIR` → `TICKS_IN_STEP` from `0x400a4d36`** (Hook R). No effect — `0x400a354a`
   overwrites it later in the same tick.
3. **`PAIR` → `CATCHUP`** (Hook S, V5.4). Fixes only the commits where `PAIR` coincides
   with the required value.
4. **`(PAIR + rem) → CATCHUP`**. Strictly worse; re-phased commits that had been clean.

Also already settled and not to be relitigated: `CNTDN_TBL[t] = max(1, tps_master + 1 -
tps_t)` is a commit-time phase-alignment delay, NOT AR's rate reload, and is identical to
the 1x control in the failing case. Hook P is gone because stock's rebuild already produces
`ceil(D7/tps_t) mod trackLen_t` at `0x400a4976` and covers all 16 tracks
(`0x400a4be6` audio, `0x400a4cb0` MIDI).

## 6. Separate open thread

`t90` and `t189` are **natural master-cycle wraps**, not armed commits, and they re-phase
too (`0x400a354a` writes 3). So at non-1x, stock shifts a track's grid on **every wrap**,
switching or not. The user reports a single 2x pattern as nominal, so this may be inherent
OT character — but if armed commits get fixed and wobble remains on one pattern, this is
where it comes from.

## 7. Tools, and the oracle

`tools/diag_phase_correlate.py` is the pass/fail oracle: per commit it reports armed state,
whether our hook ran, what `0x400a354a` wrote, the REQUIRED value, and whether the track
re-phased. **A fix means the `re-phased?` column reads `no` for every armed commit.**

Others added in Session 89: `diag_track_phase_trace.py` (every write to a track's counter
across a commit, with PCs), `diag_step_align.py` (advance ticks mod tps, segmented by
commit), `diag_commit_phase.py`, `diag_startoffset.py`, `diag_hookh_inputs.py`,
`diag_dj_scratch_clobber.py`, `diag_master_scale*.py`, `diag_step_writers.py`,
`diag_dj_hooks.py` (counts hook entries from the cave using symbols read from the built ELF
— the only way to PROVE a run armed).

## 8. Environment

- **`refs/octabam` needs commit `d5b84fb` on branch `emu/map-audio-sdram`** (maps the audio
  SDRAM bank at `0x4f000000`). Without it NO image boots — `UC_ERR_WRITE_UNMAPPED` at
  `gate_m6a()`. That repo is on a detached HEAD at `origin/main`, and its local `main` has
  diverged.
- **Serialise emulator runs.** Two Unicorn instances desynchronise the wall-clock-derived
  PIT and produce spurious boot faults; results taken under contention are not trustworthy.
  A second session works in this repo concurrently — commit with explicit pathspecs.
- Toolchain is `-mcpu=5407`: `divul.l`/`divsl.l` are REJECTED in every form. Use
  subtraction loops.

## 9. Rules this project paid for

1. Never snapshot at a detour site — a Unicorn code hook fires *before* that instruction.
2. Poison `0x80006a40..0x80006a60` with `0xAA` before any inertness gate.
3. A gate that cannot fail proves nothing; build the failing control.
4. AR↔OT array mapping is by role, not semantics. Measure OT's own writers and readers
   before copying any AR write.
5. **The emulator is not a sufficient gate.** Session 88 passed every gate in this repo and
   still broke the unit. Hardware decides.
6. `str.replace` fails silently — assert every patch-source edit matched.

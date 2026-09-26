# DIRECT JUMP — handoff: the non-1x sub-step PHASE bug

Written at the end of Session 89. Read this before touching DIRECT JUMP again.

---

## 1. State, and what is on the unit

| build | mainos sha256 | status |
|---|---|---|
| `GOLD_S87_*` | `0657157f` | Session 87 baseline, 1x-only. Commit `16df386`. |
| `V5_0_*` | `60230e02` | Hook P removed. Commit `95812d9`. |
| `V5_1_*` | `34fec20c` | **DO NOT FLASH** — hardware-rejected. |
| `V5_2_*` | `6d09452b` | + `0x80006638` pairing. Commit `6e22cc1`. |
| `V5_3_*` | `8cb167ae` | **ON THE UNIT.** + time-domain conversion. Commit `0e2726c`. |
| `V5_4_*` | — | + Hook S (PAIR→CATCHUP). PARTIAL. Commit `deb8d12`. Tree is here. |

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

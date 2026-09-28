# Octatrack OS 1.40C — sequencer bugs we have actually determined

Recallable summary (Session 108, 2026-09-27). Status tags: **measured** (emulator oracle),
**HW** (confirmed on the author's MKI), **reasoned** (from code, not separately measured).
Details: NOTES.md Sessions 5, 48–49, 105–108; `reference/handoffs/DIRECTJUMP_V7_DESIGN.md`.

## A. Pattern switching — root of the shift / fractional family
1. **Incoming position comes from the outgoing pattern, not the clock.** Stock cueing (DJ off,
   NORMAL): new pattern starts at step 1 exactly where the old one ends; if the old one's length
   doesn't nest in the bar (7 steps, 3/4x…), the new one is shifted whole steps against the
   metronome. *Measured (16↔7: −5/−2/−3 steps) + HW. Unfixed in stock; cue policy PARKED (design
   doc §6a). Only deliberate odd-meter composition wants this rule.*
2. **Same rule → fractional states when scales differ:** old pattern ends off the new pattern's
   grid (e.g. 2x ending mid-1x-step) → new pattern starts mid-step. *Mechanism measured on the
   V6/AR landing; stock-cue variant reasoned.*
3. PER-TRACK cueing NOT affected (*HW*: no shift DJ off) — CHANGE / master length quantise
   switches to the master grid.

## B. AR DIRECT JUMP (= V6.4 parity build) — all fixed in V7
4. Whole-step shifts, NORMAL and PER-TRACK (`new_step = outgoing master step mod len`).
   *Measured +2/−2/+4; PER-TRACK HW.*
5. Master-scale lurch (landing quantised to the outgoing master's grid). *Measured.*
6. Landing duplicate (old due trig + landing's first trig both sound). *Measured.*

## C. Scale / mode
7. **Bug 1 — MIDI Plays-Free stall:** PER-TRACK mode reads MIDI tracks' scale with the audio
   layout (`0x4009b6f2`) → scale 0xff → Plays-Free + Direct MIDI track sticks on step 1 after a
   manual trig. *HW; fixed (`patch_trigscale`, in every DJ build).*

## D. Pattern-change state
8. **Bug 3 — Part carryover:** pattern-triggered Part change runs the light apply
   (`0x40009e00`, not `0x40009094`) → PICKUP→FLEX keeps the old loop; switching into PICKUP marks
   the Part edited. *HW; fixed (PARTREAPPLY).*
9. **Bug 2 — p-lock-only pattern shows empty** (LED unlit; `0x4009a464` scans trig masks only).
   *HW; fixed (PATTERNLED).*

## E. Latent
10. Landing countdown `0x80006687` seeded at PLAY from `0x80006688` (arranger writes a raw word's
    low byte; never cleared at boot) → can sit stale. *Blocked V6 on HW; no stock symptom confirmed.*

## F. Measured NOT bugs — don't re-chase
- A single pattern played from START is exact in every setting (model = engine on 10 references:
  lengths 7–16, scales 2x–1/4x, master 1x/2x/3/4x, master length 7/16/INF).
- PER-TRACK master length restarts every track each master cycle — by design.
- Tracks faster than the master finish their step tps_M − tps_t ticks past each master wrap
  (stock's deferred landing) — by design, on-grid.
- The metronome never drifts (phase I `0x80006511/12`, independent of the pattern).
- Stock re-sends the current pattern's MIDI Program Change at every cycle end (next-pattern
  decision `0x400a4210`), not only when the pattern changes — measured; behaviour, not a bug.
- A stock pattern switch changes the Part with the LIGHT apply `0x40009e00` (engine hand-off),
  never the full `0x40009094` — which is exactly why Bug 3 exists.

## G. Not investigated
- Chains: no chain-specific bug measured; they switch at the outgoing end, so should inherit
  1–2 with mixed lengths/scales (*reasoned*).
- Arranger: untested.

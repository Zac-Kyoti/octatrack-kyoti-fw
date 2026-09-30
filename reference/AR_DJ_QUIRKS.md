# Analog Rytm DIRECT JUMP — behaviours we do NOT want to inherit

A running record, kept in both repos (`ar-kyoti-fw/AR_DJ_QUIRKS.md`,
`octatrack-kyoti-fw/reference/AR_DJ_QUIRKS.md`). The OT implementation's first goal is to reproduce the AR's behaviour
**exactly** (`AR_SEQUENCER_ENGINE.md` §6); the stretch goal is to change the
items below to the author's preference, one at a time, each behind a measurable gate.

**Status 2026-09-27: both goals reached on the OT.** The AR-exact baseline — OT DIRECT JUMP
**V6.4** — was confirmed on hardware (instant, persistent, and faithful to AR including all
three items below). **V7** then deviated on purpose and was hardware-confirmed the same day:
a jump lands the new pattern exactly where it would be had it played since START, which fixes
all three items at once. V6.4 stays buildable in the OT repo as the parity build, so the
AR-exact behaviour remains reconstructible (OT `NOTES.md` Session 108,
`reference/handoffs/DIRECTJUMP_V7_DESIGN.md`).

Each item: what the AR does (hardware observation or measured code), where in the code,
and — clearly marked — any hypothesis about the mechanism.

| # | AR behaviour (observed / measured) | Where | Status |
|---|---|---|---|
| 1 | **One-step SHIFT of the 16-step track relative to the master pulse, after certain DIRECT JUMP cadences, NORMAL scale mode, tracks of 16 and 7 steps.** Observed on AR MKI hardware 2026-09-27, **restated by the author 2026-09-27 (Session 107)**: with two tracks in NORMAL mode, lengths 16 and 7, switching *from* the 7-step pattern can leave the 16-step pattern offset by **exactly one whole step** relative to the master (metronome) pulse. Stock AR behaviour. **This is a whole-step phase shift, not fractional/half-step timing** — the earlier "half-step-fractional" and "fractional step time" wordings (Sessions 105-106) were the author's first approximation and are WITHDRAWN: step *durations* are correct, the pattern's step *index* is off by one against the master. This is the DIRECT JUMP **stretch goal**, not a blocker. | **Localised (measured on the OT's exact reproduction of the AR's behaviour, V6.4).** The DJ commit (`FUN_4009905c` D2, `new_step = master_step mod patLen` at `0x40099274`) takes `master_step` from the **outgoing** pattern, whose counter wraps with that pattern's own length — so after a 7-step cycle it no longer says where a 16-step pattern would be. OT oracle: perfect whole-step time shifts (+2/−2/+4 steps), 100% of ticks at one offset, no fractional part. Stock cueing has the same class of error (new pattern at step 1 on the outgoing pattern's end). | **fixed on OT (V7, 2026-09-27)** — land at the position since START from an absolute clock counter |
| 2 | **Occasional spurious trig at the jump** (user-confirmed on AR). The outgoing pattern's step event, scheduled one step earlier, and the landing's immediate fire coincide on the boundary tick; stock's dedupe kills only *equal* fire times, so microtiming splits them into two audible hits. | scheduler phase E, `0x40099664`–`0x400996ee` (dedupe) | **fixed on OT (V7, 2026-09-27)** — the outgoing pattern's pending events are cancelled at the landing with stock's own purge idiom (the new pattern's first trig wins); measured on the OT as two live events on the landing tick before, one after |
| 3 | **Master-scale changes lurch.** The landing is quantised to the *outgoing* master's step boundary (`countdown = tps_out − phase`, `0x40099146`–`0x40099158`), which is mid-step for the incoming scale whenever the two tick grids don't share that boundary (e.g. 2x → 1x on an odd 2x step). The incoming grid restarts from the landing instant. | `FUN_4009905c` D1/D2 | **fixed on OT (V7, 2026-09-27)** — superseded by the clock-locked landing: the incoming grid comes from the absolute clock, never from the outgoing master, and V7 lands only where every incoming track is at a step start (the lcm idea, in the incoming pattern's own domain) |

### Notes on item 1

**Item 1, refined by OT hardware (2026-09-27, V6.3 flashed, LED fix confirmed so cue-vs-jump
is now visible as well as audible).** The one-step shift is **not a DJ artifact**: it
reproduces on the OT with DJ **OFF** (i.e. bone-stock OT cued switching) as well as ON, and
stock AR exhibits it too. The author's mechanism reading: with two different track sequence
lengths, the outgoing pattern is cued to switch at the end of its 16-step length, which need
not be the same step position the switched-to pattern would occupy had it kept running in the
background — so the switch brings the new pattern in shifted by a step relative to the master
(metronome) pulse. Reproducibility matrix as measured on the unit:

| pattern scale modes | DJ OFF | DJ ON (V6.3) |
|---|---|---|
| both NORMAL | **shifts** | **shifts** |
| both PER-TRACK | does **not** shift | **shifts** |

The PER-TRACK row is the notable asymmetry: stock per-track cueing preserves the master
phase, and our DJ landing does not — so PER-TRACK + DJ ON is currently a deviation from
stock-OT behaviour, not just an inherited AR trait. The author's framing: this is **not so
much a bug as a musically undesirable characteristic** across both machines.

**The author's eventual design goal (recorded verbatim in intent):** every single track
retains its step-time position relative to the overarching master metronome pulse, regardless
of its unique track/pattern settings, lengths and scales (cognisant that pattern
lengths/scales override/control the actual track length and reset behaviour), such that a
DIRECT JUMP — or even a non-DJ regular sequential cue — ALWAYS brings the pattern back in
locked step-time and phase relative to the master pulse. **Reached for DIRECT JUMP by OT V7** (hardware-confirmed 2026-09-27). Non-DJ cued switches
are stock on the OT; the author parked the question of extending the lock to them (OT design
doc §6a — BAR-RESTART vs START-LOCK, with the odd-meter case that argues for stock).

Add items in order of discovery; never delete one — mark it *fixed on OT (build X)* when
the OT deviates from AR on purpose, so the AR-exact behaviour stays reconstructible.

# Analog Rytm DIRECT JUMP — behaviours we do NOT want to inherit

A running record, kept in both repos (`ar-kyoti-fw/AR_DJ_QUIRKS.md`,
`octatrack-kyoti-fw/reference/AR_DJ_QUIRKS.md`). The OT port's first goal is to behave
**exactly like the AR** (`AR_SEQUENCER_ENGINE.md` §6); the stretch goal is to change the
items below to the author's preference, one at a time, each behind a measurable gate.
Nothing here is to be coded until the AR-exact baseline is confirmed on the OT hardware.

Each item: what the AR does (hardware observation or measured code), where in the code,
and — clearly marked — any hypothesis about the mechanism.

| # | AR behaviour (observed / measured) | Where | Status |
|---|---|---|---|
| 1 | **One-step SHIFT of the 16-step track relative to the master pulse, after certain DIRECT JUMP cadences, NORMAL scale mode, tracks of 16 and 7 steps.** Observed on AR MKI hardware 2026-09-27, **restated by the author 2026-09-27 (Session 107)**: with two tracks in NORMAL mode, lengths 16 and 7, switching *from* the 7-step pattern can leave the 16-step pattern offset by **exactly one whole step** relative to the master (metronome) pulse. Stock AR behaviour. **This is a whole-step phase shift, not fractional/half-step timing** — the earlier "half-step-fractional" and "fractional step time" wordings (Sessions 105-106) were the author's first approximation and are WITHDRAWN: step *durations* are correct, the pattern's step *index* is off by one against the master. This is the DIRECT JUMP **stretch goal**, not a blocker. | Not localised yet. The DJ commit itself (`FUN_4009905c` 0x40099174-0x4009936c) rebuilds every track from `new_step = master_step mod patLen`, so a whole-step offset points at the *step index* the commit derives, not at tick phase — candidates (HYPOTHESES, unmeasured): `new_step mod len_t` against a master step that has already been advanced (an off-by-one in which side of the boundary `master_step` is read on), or the 7-step pattern's own cycle wrap having advanced the master step before the landing reads it. | recorded; mechanism open; **stretch goal** |
| 2 | **Occasional spurious trig at the jump** (user-confirmed on AR). The outgoing pattern's step event, scheduled one step earlier, and the landing's immediate fire coincide on the boundary tick; stock's dedupe kills only *equal* fire times, so microtiming splits them into two audible hits. | scheduler phase E, `0x40099664`–`0x400996ee` (dedupe) | recorded; OT fix designed (purge the outgoing pattern's pending slots at the landing) |
| 3 | **Master-scale changes lurch.** The landing is quantised to the *outgoing* master's step boundary (`countdown = tps_out − phase`, `0x40099146`–`0x40099158`), which is mid-step for the incoming scale whenever the two tick grids don't share that boundary (e.g. 2x → 1x on an odd 2x step). The incoming grid restarts from the landing instant. | `FUN_4009905c` D1/D2 | recorded; OT fix designed (quantise to the lcm of both grids; derive `new_step` in the incoming tick domain when scales differ) |

Add items in order of discovery; never delete one — mark it *fixed on OT (build X)* when
the OT deviates from AR on purpose, so the AR-exact behaviour stays reconstructible.

# DIRECT JUMP V7 — design (Session 107/108, 2026-09-27)

> **STATUS: V7.0.1 built and emulator-verified, awaiting hardware** (`build_directjump_v7.py`,
> `140C_KDJ7`, mainos `fac16421de73c3aa`, cave `0x400d7000`). V7.0 (`bd39dfc6`) was
> hardware-confirmed for timing; the ship check then found it never changed the Part on a jump
> (§8) — V7.0.1 fixes that and Program Change on re-cues. Scope: DIRECT JUMP ON only (DJ OFF = stock). Not yet on
> hardware: MIDI tracks. Parked: cued-switch policy (§6a), V7.1 mid-window landing (not
> recommended). V6.4 (`build_directjump_v6.py`, SUPERSEDED) is the OT↔AR parity build.

V6 is now the **OT↔AR parity build** (V6.4, `4a6c1b5e3fb8562c`, hardware-confirmed: instant
jumps, persistent, LEDs correct, behaviour matching stock AR — including AR's faults). V7 is
the first deliberate deviation from AR. This document is the contract V7 is built and graded
against. Read it before touching V7 code.

## 1. The specification (the author's, 2026-09-27, in his terms)

1. The pattern switched to MUST ALWAYS be locked to the master clock pulse, respectful of its
   own track/pattern settings. **It plays exactly as it would if it were the only pattern
   ever programmed on the machine and no switch had ever happened.** Example: a 16/16
   pattern with trigs on 1, 5, 9, 13 fires on pulses 1, 5, 9, 13 after being switched to —
   never 2, 6, 10, 14, never anywhere in between.
2. **No fractional step time**, ever — except what a scale produces by nature, and then the
   fractions are EXACT (2x = steps exactly on the start and middle of a 1x step).
3. A 7/16 pattern's downbeat may legitimately sit on a different step than a 16/16 pattern's;
   each pattern keeps ITS OWN phase against the clock.
4. **Primacy**: if the math forces a trig/voice to be dropped at the switch, the first
   incoming trig of the new pattern wins over the last trig of the old one. (A musical
   philosophy — the author will judge by ear.)
5. "Master clock pulse" = the OT's clock (internal, or external MIDI clock when slaved),
   counted from transport START. The metronome is only a readout of it.

## 2. Why V6/AR shift (and why stock cueing does too)

V6's landing (= AR's D2) rebuilds every track from `new_step = MASTER_STEP mod len`, where
`MASTER_STEP` (`0x800065b2`) is the **outgoing pattern's** master step counter. That counter
is pattern-relative: it wraps at the outgoing pattern's length (7 in the author's case) and is
re-seeded at every wrap-change. So after a 7-step cycle it no longer says where a 16-step
pattern would be; the incoming pattern lands on (outgoing position mod len), not on its own
position against the clock. Stock cueing (DJ OFF) starts the incoming pattern at step 0 at the
outgoing pattern's wrap — same class of error. This matches every row of the author's
hardware matrix for NORMAL mode. (The PER-TRACK + DJ ON row is expected to follow from the
same fact; to be confirmed by the oracle rather than asserted.)

The clock itself is never disturbed: the metronome counters (`0x80006512` tick-in-beat,
`0x80006511` beat-in-bar, phase I `0x400a4d36`) advance every tick independent of the pattern
— which is why the click stays solid while patterns shift against it (Session 70 and 107).

## 3. The V7 idea in one line

**Land the incoming pattern at the position it would occupy if it had been playing since
START, computed from absolute clock ticks — never from the outgoing pattern's counters.**

With `T` = clock ticks since START (all scales are integer ticks/step: 2x=3, 3/2x=4, 1x=6,
3/4x=8, 1/2x=12, 1/4x=24, 1/8x=48), every quantity is an exact integer — "no fractional
steps" is guaranteed by construction, and exact scale fractions come for free.

Reference position of pattern B at tick `T` (to be CONFIRMED against the engine's own
never-switched run before any ColdFire is written — see §5):

- NORMAL mode: `Tr = T mod (len·tps)`; every track `step = ⌊Tr/tps⌋`, tick-in-step `Tr mod tps`.
- PER-TRACK mode: `Tr = T mod (masterLen·tps_M)` (INF: `Tr = T`); master step `⌊Tr/tps_M⌋`;
  track t: `step_t = ⌊Tr/tps_t⌋ mod len_t`, tick-in-step `Tr mod tps_t`.
  (A master-length reset that falls mid-step of a slower track restarts it — the engine's own
  reference run decides the exact convention.)

## 4. Architecture — keep everything V6 proved, change one input

V6's machinery is hardware-proven and stays: the landing detour at `0x400a1f72` (phase D,
before the scheduler), stock's own synchronous all-track landing body, the boundary-tick
same-tick commit (V6.4), the `{0x15}/{0x11}` UI posts, Hook N, the toggle. **Nothing enters
the wrap-change body** (`0x400a4568`+), nothing writes `0x80006628`, no remainder seeds, no
per-track deferral machinery — the V1–V5 failure modes are structurally excluded.

What changes:

1. **Absolute clock counter `T`** (cave, 32-bit): zeroed at transport START, +1 per clock tick
   while running (same gating as phase I). Validated in the oracle against the metronome
   counters (same clock ⇒ fixed relationship at every tick).
2. **Landing position**: `dl_commit` fills stock's landing snapshot (`0x80006516[t]` step,
   `0x80006536[t]` tick-in-step, `0x80006638` master step) from the reference position of B at
   the landing tick (§3), instead of `MASTER_STEP mod len`.
3. **Landing tick**: the next tick on which B's reference master step boundary falls
   (`T ≡ 0 mod tps_M(B)`) — at most one master step of latency, as V6; at 1x every track lands
   on a step start. Tracks on other grids (e.g. 1/2x) land mid-step, which stock's snapshot
   already supports via its per-track tick field.
4. **Mid-window scheduling**: a track landing r ticks into its step must still get that step's
   event at the reference fire time (the engine schedules one step ahead). Stock's first-fire
   path (`ahead −= reload`, `tick_in_step = reload`) is the mechanism; the exact counter values
   come from the reference run, not from reasoning.
5. **Primacy purge**: at the landing, cancel the outgoing pattern's pending events (fire table
   `0x80001904[t + slot·8]`, MIDI table `0x46c76a26`, record longs `0x46c7e998`/`0x46c769c0`,
   slot masks `0x46c7fe44`/`0x46c77be2`) using stock's own purge idiom (`0x400a2530`+,
   `0x400a4408`–`0x400a44e0`). This also removes AR quirk 2 (the landing duplicate).
6. Master-scale changes need no special case: B's grid is derived from `T`, never from A's.
   AR quirk 3 (the lurch) disappears by construction.

## 5. How V7 is graded — the method that V1–V5 lacked

**The oracle is the spec, literally** (`tools/diag_reflock.py` + `tools/cmp_reflock.py`):

- REF: PLAY on B, never switch. RUN: PLAY on A, switch to B (and back) at chosen ticks.
- PASS ⇔ from the landing on, RUN's full per-tick engine state equals REF's at the same tick,
  and the fire table carries B's events only. Metronome counters must match throughout (same
  clock). A failing segment reports its best-fit shift in ticks/steps.
- The engine is deterministic given its state and the data, so state equality one tick after
  the landing implies correctness for ever after.

Order of work, each step gated by the previous:

1. **Validate the oracle** — DONE (Session 107/108). REF-vs-REF: PASS (both references, all
   ticks, fire tables equal). V6.4 on the 16↔7 fixture (start 7-step, jumps at t100/190/280):
   pre-switch segment LOCKED; every post-landing segment a **perfect whole-step time shift**
   of the reference (100% of ticks match at d = +12/−12/+24 ticks = +2/−2/+4 steps — no
   fractional part), plus extra fire events at each landing tick (AR quirk 2). The run's
   master step after the first landing is 3 = the OUTGOING 7-step pattern's position since its
   wrap; the reference says 1 — §2's mechanism, measured. Stock DJ OFF: every post-cue segment
   a perfect whole-step shift too (−5/−2/−3 steps). The oracle sees what the author heard.
2. **Model first**: a Python `ref_state(pattern, T)` that reproduces the engine's own REF
   traces exactly, across NORMAL/PER-TRACK, every scale, odd lengths, master length incl. INF.
   `tools/model_reflock.py`. Measured convention (sample point = phase-G entry of ISR t, t=1
   the first running tick): track `step = (⌊t/tps_t⌋+1) mod len_t`, `ticks = t mod tps_t`;
   master `m_step = (⌊(t−1)/tps_M⌋+1) mod mlen`, `m_tick = (t−1) mod tps_M` (tracks lead the
   master by one tick inside the ISR: F advances before G). **PASS on NORMAL 16 and NORMAL 7,
   all 16 tracks, all 382 ticks.** PER-TRACK / scale references in flight.
3. Only then ColdFire: `T`, the reference snapshot, mid-window counters, the purge.
   **V7.0 BUILT** (`bd39dfc6`): window-start landings only (no mid-window counters yet);
   `DJ_TOFS` measured 0 (the first build's guess of 1 landed one tick early — oracle d = +1).
4. Matrix: NORMAL 16↔7 1x; NORMAL 1x↔2x/3/4x patterns; PER-TRACK mixed lengths + scales (incl.
   1/2x, 3/4x, 3/2x); master length INF and odd; MIDI tracks; cues aimed at every master-tick
   phase incl. the boundary tick (the V6.4 lesson). All must PASS. Plus DJ-OFF and DJ-ON-idle
   identity with stock.
   **V7.0: 16↔7 (4 cue phases incl. same-tick), A07↔A08 PER-TRACK master 1x↔2x, DJMAST2
   master 1x↔2x, NORMAL 7 → 3/4x+3/2x+1/4x tracks — ALL PASS** (state locked from the tick
   after each landing; live events with content identical at every tick). Details: NOTES
   Session 108.
5. Hardware. **V7.0 HARDWARE-CONFIRMED 2026-09-27** ("the true DJ gold standard"): 16↔7 vs the
   metronome, master 1x↔2x, swing/microtiming, rapid switching all good; MIDI tracks not yet
   tested on HW. V7.1 (mid-window landing) parked as NOT RECOMMENDED — NOTES Session 108 cont.

## 6a. PARKED by the author (2026-09-27) — cued-switch behaviour, revisit later

**V7's scope is DIRECT JUMP ON only.** With DJ OFF the sequencer switches patterns exactly as
stock (V7 DJ-OFF identity gate: IDENTICAL, 16/16 tracks moving). Precise wording for users:
"DJ OFF = stock sequencing, plus the manual-trig bug fix every DJ build carries
(`patch_trigscale`)"; the `[PTN]+[YES]` toggle/toast and V7's background clock counter are
present but change nothing; DJ comes up OFF at power-on.

Two decisions the author parked, to think about before any cued-switch work:

1. For cued (non-DJ) switches: **BAR-RESTART** (new pattern starts at step 1 on the next
   metronome bar at/after stock's switch point — new behaviour for NORMAL mode; the closest
   stock analogue is PER-TRACK mode's CHANGE quantisation) vs **START-LOCK** (V7's jump rule).
   The deciding example: a 16-step intro played 3 bars, then cue a 64-step verse with a fill in
   bar 4 — BAR-RESTART starts the verse at its bar 1; START-LOCK enters at its bar 4. Odd-meter
   composition (a 12-step pattern used as a 3/4 bar) is the case that wants STOCK, and the
   argument for a `CUE: STOCK / BAR` setting. Full case table in the Session 107/108 notes.
2. Whether chains follow that cue setting (the arranger stays stock either way: its rows carry
   explicit start-offset and length fields).

## 6. Open items (decisions and edges, none blocking)

- **Trig conditions** (1:2, A:B, fill) depend on per-track cycle counts. "As if it were the only
  pattern ever" implies cycle counts from START too; include if the engine state makes it
  cheap, otherwise record as a deliberate follow-up.
- **Negative microtiming / swing on the landing step**: with primacy, the incoming step's trig
  fires (at most a micro-offset late) rather than being dropped. By-ear judgement.
- **Sustaining voices**: an old-pattern note still ringing at the landing is cut by the next
  incoming trig on that track, as with any stock pattern change.
- **External sync edges**: a MIDI Song Position Pointer relocates the clock origin; `T` must
  follow it (later).
- **Non-DJ cues — a choice, not a replacement** (discussed with the author 2026-09-27). The
  same landing, fired at the outgoing pattern's end instead of the next step, makes ordinary
  cued switches clock-locked too; the oracle already shows stock cueing failing the lock by the
  same whole-step shifts (5, 2, 3 steps on the 16↔7 fixture). But this IS a change to the
  sequencer's DNA: stock is **phrase-relative** (a switch restarts the pattern at its step 1 —
  the near-universal convention; identical to clock-relative whenever lengths/scales nest, e.g.
  all-16/32/64 patterns cued at their ends) while V7 is **clock-relative** (Ableton's "legato"
  launch). Restart-on-switch looks deliberate (predictable downbeats for intros, fills,
  intentional odd-length phrases); the fractional states under mismatched master scales look
  like an unexamined side effect; stock PER-TRACK mode's CHANGE/master-length quantisation is
  already clock-relative in spirit. Plan: prove V7 on DIRECT JUMP first, then offer "lock" for
  cued switches as a separate explicit setting with stock restart as the default, keeping
  chains/arranger (which assume restarts) out of it — so both models can be A/B'd by ear.
- **Cave**: the DJ cave (`0x400d7400..`, budget to `0x400d7b00`) overlaps the repitch cave by
  478 B already (MERGE.md); V7 will grow it.

## 8. V7.0.1 — stock's switch hand-off, and Program Change that follows re-cues (2026-09-27/28)

**Found by the pre-ship check, not by hardware:** jumping into a pattern on another Part set the
UI's current Part but the engine never applied it (`tools/diag_dj_part.py`, pattern 4 poked to
Part 3). Stock's wrap-change, on a REAL switch (`d6`: PEND ≠ ACT, `0x400a432a`–`0x400a4350`),
does a whole hand-off between its `{0x15}` and `{0x11}` posts that V7.0 — which never enters the
wrap-change — skipped entirely:

| stock (`0x400a4568`–`0x400a4856`) | what it is |
|---|---|
| post `{0x14, part}` (template `0x400d8169`, arg `0x400d816a` = blob `+0x8e57`) | UI "select Part P" (dispatcher case `0x13`, `0x400621a6` — where PARTREAPPLY hooks) |
| `0x46c7fa80` = 1\|2\|bits 8–15 | audio engine flags; track bits = START SILENT (track byte +3 = 1, or −1 with `0x8000004f`) |
| `0x800019e4` = sclk + `a3` | when it takes effect (`a3` = one master step: stock switches a step ahead) |
| `0x46c7ff40` / `0x46c7ff62` | bank / Part → the engine's light Part apply `0x40009e00` from `0x4000b1dc` |
| `0x46c7a120` = 3\|bits; `0x46c76aa6` / `0x46c76a22` / `0x46c76aaa`; `0x46c7a850` / `0x46c7a934` | the MIDI engine's twin (times in the MIDI clock domain, settings-dependent offsets) |
| `FUN_400a539c(−1)` | reset A:B cycle counters / pending FILL for all tracks |

V7.0.1 replays exactly this at the landing (`dj_handoff`), with every time = "now" because V7's
landing sounds the new pattern's first step immediately. **Measured against stock, value for
value**: flags 3/3, bank 0, Part 2, the reset call, both UI Part writes, and the light Part apply
from the SAME engine site `0x4000b1dc` (stock stamps +6 ticks = one master step; V7.0.1 now).
Stock never uses the full apply `0x40009094` for a pattern switch; neither does V7.

**Program Change (measured, `pc_*` runs).** V7 sends PC with stock's own sender
`FUN_4009e884(bank, pat)` the moment it first sees a cue (early warning for external gear).
V7.0 left gear on the wrong program when the cue changed during the landing wait (cue 4 then 5:
PC(4), 5 landed; cue 3 then back to 5: PC(3), 3 never played, and 5 re-landed onto itself).
V7.0.1: the ARMED state re-checks the cue every tick and, if it changed, takes the countdown back
and handles the new cue on the same tick (a new pattern re-arms with its own PC; the playing
pattern cancels the jump and re-sends its PC; a −1 can never reach the landing); the latch
compares bank too. Measured after: PC(4), PC(5), 5 lands; PC(3), PC(5), no landing. A cue in
the outgoing pattern's last step still yields a same-tick duplicate PC (ours + stock's
next-pattern decision) — accepted: **stock itself re-sends the current PC at every cycle end**
(`0x400a4214`), and the timing lock holds in that race (graded PASS).

**Gates on `fac16421`:** timing matrix 5/5 PASS (16↔7 four cue phases, A07↔A08, DJMAST2, mixed
3/4x/3/2x/1/4x, master length INF), last-step race PASS, DJ-OFF and DJ-ON-idle IDENTICAL,
bug-fold DISJOINT / ALL PRESERVED / NO STRAYS. Cave moved to `0x400d7000` (zero in stock, inside
the vetted zone) for room: 1980 B mainline, 2240 B DIAG.

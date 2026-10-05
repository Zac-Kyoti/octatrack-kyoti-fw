# OT-303 — feasibility scope

Written 2026-10-04. **Nothing is built.** This is a feasibility study for a new synthesis
machine, "OT-303", based on Robin Schmidt's Open303 and midilab's jc303, with a
303-flavoured grid on the tracks that use it. Scoped against **stock OS 1.40C**: how it
would sit beside the KYOTI features is deliberately left out (user's instruction).

Markers: ✅ measured (on our image or on hardware, source named) · 🟡 estimate or proposal ·
❓ unknown, with the gate that settles it.

---

## 0a. Decisions (user, 2026-10-04)

- **Architecture A**, a DSP-resident voice.
- **Accent = ACC p-lock** plus a shortcut.
- **Fidelity: full 4× oversampling (tier T1)**, accepting a **maximum of two instances**, on
  the condition that *nothing else on the OT degrades*. Consequences:
  - The two instances are **one per DSP core**: one on tracks 1–4, one on tracks 5–8. The
    UI refuses a second OT-303 on the same half. Two on one core would double that core's
    load.
  - "No degradation" is defined as: **every configuration that plays clean on stock still
    plays clean.**
  - **No FX restrictions, on the OT-303 track or anywhere else.** Every effect still on
    the menu stays usable in FX1 and FX2 (user, 2026-10-04). Donating whole effects is
    allowed. That frees P memory *and* lowers the worst-case cycle load, because a donated
    effect can no longer be in anyone's configuration.
  - **Oversampling may drop to 3× or 2×** if, with a filter built to sound the same, it is
    virtually inaudible against 4×. **The filter design is the priority** (user). Settled
    by the Phase 1 filter study (§9), not assumed.
  - Whether the chosen tier meets the bar is what Phase 0 measures.
- **SPRING REV may be given up, but keeping it is preferred.** Try the FX2-slot tails
  first (§4: no stock effect lost, but slower fetches and an init patch). Fall back to the
  SPRING donor (internal P, full speed, the proven path) if the measured cost from the
  tails pushes 4× over budget or the code doesn't fit.
- **Machine: a mode of THRU first, a new machine type (id 5) as the final destination.**
  The THRU mode is a hardware test vehicle, **not a release** (§7).

## 0. The answer in brief

- **Feasible, on the DSP, at a "DSP-native" fidelity tier, not as a literal port.** Open303
  is a double-precision, 4×-oversampled design with 12 mip-mapped 2048-sample wavetables
  and a 12th-order direct-form elliptic decimator. None of those three survive the move to
  a 24-bit fixed-point core with about 2 K words of free data memory. What survives
  unchanged is the *model*: the 303's oscillator → pre-HP → TeeBee ladder with its
  feedback high-pass → post-HP/allpass/notch → VCA, its envelopes (MEG, the accent RC
  pair, the VCA envelope), and its slide and accent behaviour. All of that is MIT-licensed
  and portable.
- **Instances (🟡, priced by instruction count; §3):** recommended tier ≈ 240–300
  cycles/voice. That is about one and a half stock FX1 FILTERs. **8 instances (one per
  audio track) fit in the cycle budget** if the rest of the part is reasonable. A
  heavy-reverb core supports 2–3. A faithful 4× Open303 port (≈ 650 cycles) fits about 2
  per core, 4 total.
- **The binding constraint is DSP program memory, not cycles.** Both payloads' P memory is
  full. The engine needs a donor effect (SPRING REV, 1,063 words, is the proven one;
  ≈ 500–700 words needed).
- **MIDI tracks: yes, as the sequencer; no, as the sound's home.** MIDI tracks have no
  audio path. An OT-303 must live on an audio track's DSP chain. A MIDI track can *drive*
  it: notes, velocity → accent, overlapping LEN → slide, arp, CC p-locks. A cable loop
  (MIDI OUT → IN) gets that with almost no extra code; an internal loopback removes the
  cable (§6).
- **The grid can be a combo without shrinking the OT's.** Trig = gate, trigless trig =
  tie, slide trig = slide, plus one new per-step ACCENT bit. Trig conditions, micro-timing,
  p-locks, LFOs and scenes all keep working because the stock sequencer still fires the
  events (§5). Capping tracks at 16 steps isn't needed: default OT-303 tracks to 16 with
  the existing per-track length.
- **Size:** larger than anything this project has shipped. The DSP engine alone is
  roughly 2–3× REPITCH's DSP half (420 code words, 16 revisions). Phase plan in §8.

---

## 1. What we'd be porting

### Open303 (MIT, © 2009 Robin Schmidt) ✅ read

Per output sample (`rosic_Open303.h` `getSample`):

| stage | rate | what it is |
|---|---|---|
| pitch slew (`LeakyIntegrator`) | 1× | the 303 slide, an RC on the oscillator frequency |
| MEG `DecayEnvelope` + RC1/RC2 `LeakyIntegrator` | 1× | filter envelope; RC2 is the accent "wow" path |
| cutoff = `cutoff · 2^(env…)` + `TeeBeeFilter::setCutoff` | 1× | `pow()` plus a 12th-order and an 8th-order polynomial for the ladder coefficients, **every sample** |
| `AnalogEnvelope` + `BiquadFilter` de-clicker | 1× | VCA envelope |
| `BlendOscillator` | **4×** | saw/square blend from two `MipMappedWaveTable`s (12 tables × 2048, linear interpolation); the square is a tanh-shaped saw |
| `highpass1` (one-pole) | **4×** | pre-filter HP |
| `TeeBeeFilter` (TB_303 mode) | **4×** | 4-pole ladder, coupled stages, one-pole HP in the feedback path |
| `EllipticQuarterBandFilter` | **4×** | **12th-order IIR, direct form**, coefficients up to ±308 |
| allpass, `highpass2`, notch biquad, VCA, level | 1× | post-filter voicing |

The inner loop runs four times per output sample, so it dominates the cost.

### jc303 (GPLv3 wrapper; its Open303 engine stays MIT) ✅ read

What it adds on top of Open303:

| addition | cost / verdict |
|---|---|
| LFO → cutoff / volume / pitch | trivial. **We don't need it:** the OT's own three LFOs already modulate any page-1 parameter. |
| `DiodeLadderFilter` (ZDF, optional octave-up first pole) | ≈ 35 ops per oversampled sample, plus `tan()`, divisions and `pow()` per coefficient update. 🟡 a second filter model costs a whole extra kernel's P words; option, not v1. **GPLv3: reference only**, reimplement from the published diode-ladder literature. |
| GuitarML/BYOD overdrive (LSTM, 40 hidden units) | ≈ 6,500 MACs plus 160 non-linearities per sample. **Impossible on this DSP.** A tanh-table waveshaper (≈ 10 instructions) stands in. |
| Aciduino-V2 16-step sequencer (rest / accent / slide / tie, 50% gate, generative fill) | the *semantics* are what §5 maps onto the OT grid; the code is GPLv3 and the wrong CPU anyway. |

**Licence rule for this feature:** port only from Open303 (MIT, keep the copyright
notice; our repo is MIT). Treat every jc303-specific file as reference, the same policy as
the GPL Paulstretch implementations.

---

## 2. Where the synth could run — the two architectures

The OT already has both shapes in stock, which is why both are real options:

- **Sample playback** is split: the ColdFire copies/format-converts sample data
  (`0x40008752` forward / `0x400087b6` reverse, four straight copy loops, no interpolation)
  and ships it per frame into a 128-word ring per voice. The DSP's voice engine
  (`P:0x3a1`, payload A) interpolates it. ✅ REPITCH scope §1.
- **The stock DELAY runs on the ColdFire** (EMAC loop over SDRAM rings, the result
  returned to core 0 at `X:0x4400`). ✅ octabam `DSP.md`.

### A. DSP-resident voice (recommended)

The synth replaces the 2-tap interpolator **for OT-303 tracks only**, exactly the way
REPITCH's RPS9/RPSP replace it today. Everything after the voice (AMP, FX1, FX2, level,
cue, scenes) is untouched.

Data paths it can use that are already proven on this hardware:

| need | channel | status |
|---|---|---|
| note-on, sample-accurate | DSP trig flag: voice word `X:(x:$419+$1E)` bit 12, bits 8–11 = start offset inside the 16-sample frame | ✅ REPITCH gate 0b |
| note pitch | the voice **increment** the ColdFire already computes from PTCH (+ p-locks, LFO, scenes). Oscillator frequency = base × increment. | ✅ REPITCH rides it |
| CUT/RES/ENV/DEC/ACC | the machine's page-1 slots, published every frame in the 84-word per-track record | ✅ (SC, REPITCH page-1 knobs) |
| tempo (for gate length) | tempo24 in halfword 31 of every track's record | ✅ octabam `DSP.md` §6c |
| accent / slide / tie flags | **needs a channel.** REPITCH's 2-bit increment tag is fully used, so a record word or companion byte must be found. | ❓ Phase 3 |
| per-voice state (~40–80 words) + tables (exp2, tanh: ~512 words) | Y:`$A00`–`$FFF` region (stock free from `$795`) | ✅ free on stock (octabam hardware probe) |

Pros: deterministic real time, cycle budget *measured* (3,120 usable per core), and the
toolchain (`tools/dsp_xasm.py`, bit-exact twin checks) is hardware-proven twice.
Cons: needs a donor effect's P words (§4), and the DSP is the harder plane to debug.

### B. ColdFire-rendered voice

The synth runs on the ColdFire in place of the copy loops and writes finished audio into
the voice ring at increment 1.0. The DSP never knows.

Pros: no DSP code, no P-memory donor. Every DSP stage downstream works unchanged, and the
Unicorn emulator covers it well.
Cons:
- **The ColdFire budget is unmeasured.** octabam models the core at ~176 MIPS, and there
  is **no FPU** on the MCF54454 (EMAC fixed point only).
- The ColdFire also runs the UI, the sequencer, Flex timestretch grains, the DELAY and CF
  streaming.
- An overrun here doesn't just glitch one track. It lags the panel and starves *every*
  track's delivery.
- 🟡 Recommended tier ≈ 200–300 ColdFire instructions/sample ≈ 9–13 MIPS per voice, so
  5–8% of the CPU each, before any headroom measurement. That suggests **2–4 instances**,
  with UI risk.

**Recommendation: A.** Keep B as the fallback if the P-memory donor becomes unacceptable,
and price it with a ColdFire burn probe first (§8 Phase 0).

---

## 3. Processor load and instance count

### The budget ✅ (octabam `CHIP.md`, hardware burn-probe sweeps, 22 Sep 2026)

- 4,532 cycles/sample/core at 199.9 MHz; stock's own share ≈ 1,410; **≈ 3,120 usable** for
  FX work per core.
- One FX1 FILTER = **192 cycles/sample**. Measured cost is about **2 cycles per simple
  instruction**, and displaced addressing costs 4–6.
- Core 1 = tracks 1–4, core 0 = tracks 5–8. Instances are budgeted **per core**.
- ~~Two stock reverbs on one core glitch~~ (corrected 2026-10-04: octabam's glitch is a reverb in
  **FX1**, which stock's menu forbids; no stock-legal configuration is known to overrun).
  Stock effect costs: measured in §10.

### Engine tiers 🟡 (instruction counts at 2 cycles/instruction; Phase 0 replaces these with burn-probe numbers)

| tier | design | ≈ instr/sample | ≈ cycles | per core (budget only) |
|---|---|---|---|---|
| **T1 "faithful"** | Open303's structure at 4×; wavetable osc → computed saw + tanh-shaped square; elliptic decimator re-cut as 6 biquad sections | ~330 | **~650** | 4 only with near-zero FX; **2 comfortable** |
| **T2 "DSP-native" (recommended)** | 2× oversampling, polyBLEP saw + tanh-table square (as the real 303 derives it), TPT ladder with feedback HP and a saturating table, polyphase-allpass halfband decimator, coefficients from tables updated per frame, Open303's envelopes, slide, accent and post voicing | ~120–150 | **~240–300** | **4** (≈ 1,000–1,200) with stock-ish FX; 2–3 next to a reverb |
| **T3 "lean"** | 1×, ZDF ladder, polyBLEP | ~70 | ~140 | 4, CPU never the limit |

What this means in practice (T2):
- All 8 audio tracks as OT-303 is within the cycle budget on paper. At that point each
  core's 3,120 is about 1,100 synth + whatever FX you add.
- **Planning number: 4 OT-303s (2 per core) under any FX load, up to 8 with light FX.**
  An OT-303 track usually wants FX1 = NONE, since it already has its own filter, which
  gives back 192 cycles per track compared with the default part.
- Only the burn probe sets the real ceiling. Instruction count is a floor, not a
  measurement (octabam `CHIP.md`, "Words are not cycles").

### Where fidelity is spent

- **Oversampling** is the cost lever. The 303's resonant peak near the top of its range
  aliases at 1×. 2× with a cheap halfband captures most of the benefit.
- **Fixed point:**
  - Ladder states at low cutoff (b0 ≈ 10⁻³) lose low bits in 24 bits. They need 48-bit
    (double-word) states or error feedback, about +10 instructions.
  - The direct-form 12th-order elliptic is numerically unusable in fixed point. Any tier
    re-cuts it.
- **Per-sample transcendentals** (`pow`, `tan`, 12th-order polynomials) become table
  lookups with per-frame (16-sample) coefficient interpolation. That is inaudible at
  control rate.
- **Memory:** Open303's wavetables are 12 × 2048 × 2 ≈ 49 K words, about 25× the free Y
  region. They have to go. That costs nothing audible, because the real 303's square is
  waveshaped from its saw anyway.

---

## 4. Memory — the real constraint

- **P (program):** both payloads are full; there are no gaps (octabam `DSP.md` §7). New
  DSP code must take a donor effect's words, on both payloads.
  - Proven donor: **SPRING REV** (1,063 words, FX2-only; ids null-stubbed on both buses).
  - Its X tables are unread at runtime ✅ (REPITCH gate 0a).
  - Keep DARK REV's 35-word routine inside SPRING's module stock (the rev-10..13 lesson).
  - T2 estimate 🟡 ≈ 450–650 words incl. init and control; T1 ≈ 700–900; a second
    (diode) filter +150–250.
- **No-donor placement (preferred: keeps SPRING REV; §0a):** the last ~605 words
  of every FX2 slot (`slot+$3da3..$3fff`) are never written by stock.
  - ✅ Highest stock write `+$3da2`, NOTES Session 115.
  - The shared window holds two FX2 slots per core, so that's ≈ 1,210 words per core, and
    it is program-addressable. Stock already executes there (payload B's entry stub at
    `0x38000`, the bootstraps).
  - Costs:
    - 1 wait state per P fetch;
    - the code splits into two pieces;
    - the init loop at `P:0x40` zeroes the window after upload, so it must be patched to
      skip the tails.
- **X/Y data:** per voice ~40–80 words of state + ~512 words of tables, shared by all
  voices on a core. Fits in the stock-free Y region.
- **ColdFire:** the machine page descriptor, UI view and trig plumbing are cave code. On
  stock 1.40C the classic cave is free. ⚠️ Read `reference/kb/caves.md` before naming an
  address.

---

## 5. The grid — a 303 that keeps the OT's sequencer

The principle: **don't replace the stock sequencer.** Reinterpret its existing trig layers
on OT-303 tracks. Then trig conditions, micro-timing, p-locks, parameter slides, scenes,
LFOs, copy/paste, pattern chaining and the arranger all keep working, because the stock
code still decides *whether and when* each step fires. The OT-303 code only decides *what
the step means to the voice*.

| 303 step property | OT-303 meaning of the existing OT data | storage |
|---|---|---|
| gate (note / rest) | sample trig = note; no trig = rest | mask `+0x09` ✅ |
| note | PTCH p-lock on the step (CHROMATIC trig mode plus live record already enters these) | p-lock byte `0x00` (🟡 map L) |
| **tie** | **trigless trig** = hold the previous note, apply this step's locks without retriggering. It's nearly the stock meaning already. | trig-type layer ✅ |
| **slide** | **slide trig.** The OT puts it on the *destination* step; the 303 flags the *source* step. Same musical event, placed one step later. | mask `+0x41` (swing/slide) 🟡 |
| **accent** | new per-step bit; see below | ❓ |
| gate length | 303 = 50% of a step; a GATE param (SETUP page, default 50%) | page-2 |
| step count | OT per-track length 16/32/64 + scale. **Default OT-303 tracks to 16; don't forbid 64.** | ✅ `+0x59` |

**Accent storage, two options:**
1. Lock the ACC slot. A step with an ACC p-lock is accented at that amount. No new
   storage, stock-compatible files, per-step accent *amount* for free. Entry via a shortcut
   (e.g. [TRIG]+[YES] toggles it; REC_TRIG_MUTE's [TRK]+[YES]/[NO] is the precedent).
   **Recommended.**
2. Take an unused trig-type layer. Cleaner LED display, but it's a new meaning stored in
   bytes the stock OS reads differently.

**Interactions to design for:**
- **Slide needs look-ahead.** A 303 holds a note past 50% when the *next* step slides.
  - The handler can read the next step's slide trig from the pattern arrays when the
    current note is triggered.
  - **Trig conditions break look-ahead.** If the next step's slide is conditional and its
    condition fails, the held note gets released late, at that step instead of at 50%.
    Acceptable, and worth documenting.
- **The OT AMP envelope** retriggers on every voice trig. On an OT-303 track the synth's
  own VCA envelope is the gate:
  - slides and ties must not reach the DSP as voice trigs;
  - AMP should default to ATK 0 / HOLD max / REL max, as an outer level stage only.
- **Micro-timing** survives as long as notes arrive through the stock trig path. The DSP's
  start-offset bits are sample-accurate.

**The display side:** a "303 view" is a screen overlay, not a new sequencer. On the
active OT-303 track it shows the current 16-step page as rows N / A / S / T (note name,
accent, slide, tie), drawn by the same text primitives the KYOTI toasts use. The
monochrome 128×64 LCD fits 16 columns at 8 px, enough for flags and a short note row.
Trig LEDs keep their stock trig-type colours.

---

## 6. MIDI tracks

- **The synth can't live on a MIDI track.** MIDI tracks are ColdFire-only: they emit MIDI
  bytes and own no DSP chain. Every audible voice in the OT goes through one of the 8 audio
  tracks' chains.
  - A "ninth voice" summed straight into the DSP mixdown is possible in principle.
  - It would have no AMP, FX, level, cue or scene infrastructure, and every one of those
    would need rebuilding.
  - Not recommended for v1.
- **A MIDI track can be the OT-303's sequencer, and it's arguably the better one:**
  - per-trig NOTE, VEL (→ accent above a threshold, as jc303 does at ≥ 100) and LEN
    (overlap into the next note → slide, Open303's own legato rule);
  - the ARP, a 303 classic;
  - CTRL-page CC p-locks and the MIDI LFO;
  - trig conditions and micro-timing, all native.
- **Zero-code version:** MIDI track → MIDI OUT → cable → MIDI IN → the OT-303 audio track
  on its auto/track channel. Stock audio tracks already play MIDI notes chromatically, so
  the OT-303 only has to treat incoming notes as note events (with velocity accent and
  legato slide), which v1 needs anyway.
- **Internal version (later):** a SETUP param on the OT-303 track, "SEQ = OWN / M1…M8",
  and a ColdFire hook where the MIDI track emits note on/off, delivering a copy straight to
  the voice. Cost: one audio track *plus* one MIDI track per instance, but MIDI tracks are
  often idle. This project already knows MIDI-track playback code (MIDI_PLAYS_FREE_FIX).

---

## 7. Machine plumbing and the page

**How the OS selects a machine (✅ dumped from our image this session):**
- Per-machine-type function tables:
  - source supplier `0x400d6434`: STATIC/FLEX/PICKUP → `0x40004008`, THRU `0x40004424`,
    NEIGHBOR `0x4000466c`; **slots 5–7 are already present** and point at a default
    handler `0x400047f0`;
  - per-trig resolver `0x400d6454`: `0x4000f450` ×3, THRU `0x400043f4`, NEIGHBOR
    `0x4000463c`, then `0`, `0x400047d0` (mark voice active), `0` — **index 5 is null**;
  - packer `0x400d61d0`/`0x400d61f0`;
  - page dispatch `FUN_40097168` (5 entries).
- The 5-byte per-track slot record is indexed by `+type`. A type 5 that ever reached it
  would alias the next track's STATIC slot.

**Option M1: a real sixth machine type (id 5).**
- Cleanest UX: "OT-303" in the machine list.
- Costs: every per-type table and bound checked or extended. The null resolver entry is a
  guaranteed crash until filled.
- **A project saved with type 5 is undefined on a stock OS.**

**Option M2: a mode of an existing machine.**
- The REPITCH precedent is a SETUP-page attribute. Stock-loadable files (stock sees a
  plain machine), and it reuses that machine's delivery path.
- THRU is the natural host: no sample slot, and its page has spare meaning.

**Recommendation:** prototype as **M2**, promote to **M1** once the engine is proven.

**Why THRU first is the natural route to M1 (user's final goal), and what it costs:**

- **Carries over to M1 unchanged:**
  - the DSP engine;
  - the trig → note/tie/slide/accent mapping and its flag channel;
  - the SRC page descriptor and parameter layout;
  - AMP defaults, MIDI-in handling, the 303 view.

  That's essentially all of the sound and the feel.
- **M1 replaces:** the single "is this an OT-303 track?" predicate (THRU + SETUP flag →
  type byte 5) and the THRU SETUP toggle. That's the throwaway part, and it's small.
- **M1 adds, and it is the invasive part:**
  - an audit of **every reader of the machine-type byte**: the chooser list, the
    per-type tables (resolver index 5 is NULL, a guaranteed crash), the page dispatch
    bound 0–4, `+type` indexing of the 5-byte slot record (type 5 lands on the next
    track's STATIC slot), the `type ≥ 2` special cases (NOTES ~L1847), part copy/paste,
    project load;
  - the stock-OS story for type-5 projects.

  This audit is pure RE (static reading plus the emulator) and can run **in parallel**
  with the engine work.
- **Why not go straight to M1:** the first hardware flashes would test the engine and the
  type plumbing at once, so a crash couldn't be attributed to either. Through THRU, every
  engine flash runs on stock-proven plumbing, and test projects still load on a stock OS.
- **Rule:** the THRU mode is a test vehicle, **never a release**. Don't ship it, so there
  are no THRU-mode user projects to migrate when M1 lands.
- ❓ **Open host question (Phase 3, first item):** THRU's source handler `0x40004424`
  builds the per-track DSP record directly and never calls the ColdFire sample renderer
  `0x40007960`. Whether the DSP's voice engine `P:0x3a1` even runs for a THRU track (versus
  an input-routing path) is unread. Settle it with `ot_emu --dsp-watch` before choosing the
  DSP hook site.
  - If THRU doesn't use the voice engine, the synth hooks THRU's input path instead.
  - If that turns out awkward, FLEX with a SETUP mode (exactly the REPITCH precedent) is the
    fallback host.

**The SRC page (6 knobs, page 1 = p-lockable, LFO-able, scene-able for free):**

| A | B | C | D | E | F |
|---|---|---|---|---|---|
| **PTCH** (note) | **CUT** | **RES** | **ENV** | **DEC** | **ACC** |

That's exactly the 303's front panel, with PTCH standing in for TUNE plus the note.

**SRC SETUP (page 2):** WAVE (saw ↔ square blend), TUNE (fine), SLID (slide time, 60 ms
stock), GATE (50%), DRV (tanh drive), and Devil-Fish extras if words allow (AMP DEC/SUS,
accent decay, filter model). Page 2 isn't p-lockable on stock, so the six that matter most
are deliberately on page 1.

---

## 8. Phases (each one gated, nothing hardware-facing before Phase 4)

0. **Measure.** Build a burn-probe diagnostic image (octabam's method: a knob that burns
   24×N cycles) and sweep it on the MKI under:
   - default part;
   - 4× FILTER;
   - each stock reverb.

   That gives real per-core spare. Optionally do a ColdFire burn in the voice renderer to
   price architecture B. *Settles §3's ❓ and picks the tier.*
1. **Reference model.** Python/C fixed-point twin of the T2 engine. Render A/B against
   Open303 offline (spectra and levels, not sample-exact). This is where the 303 sound gets
   decided, off the hardware.
2. **DSP engine.** Assemble through `tools/dsp_xasm.py` into the SPRING donor. Must be
   bit-exact against the twin under `dsp_host`/`ot_emu`, including poisoned-frame and
   trig-offset cases (the REPITCH recipe).
3. **ColdFire plumbing.**
   - M2 mode switch and the SRC page descriptor;
   - trig → note/tie/slide/accent mapping and the flag channel;
   - AMP defaults;
   - MIDI-in note handling.
4. **First flash:** one OT-303 track, stock grid semantics.
5. **303 view + accent shortcut**, then the internal MIDI-track loopback.
6. **Options:** M1 type id, diode filter, T1 tier where cycles allow.

**Open decisions for the user:**
- fidelity tier (T2 recommended);
- architecture A vs B;
- M2-first;
- accent storage (ACC p-lock recommended);
- whether a 16-step default is enough or the 303 view should enforce 16.

---

## 9. 4× oversampling — the case for and against, beyond instance count

**For it (why 4× isn't just a luxury):**
- Open303's TB_303 ladder is an *explicit* discretisation (`y1 += 2·b0·(y0−y1+y2)` …).
  Its tuning, resonance and stability are calibrated for a sample rate far above the
  cutoff, together with polynomial-fitted coefficients for that structure.
  - At 4× it *is* Open303's filter.
  - At 2× it would detune and misbehave near the top of the range, so a 2× build has to
    swap in a different filter (TPT) voiced to match.
  - **4× is the only tier where the filter is Open303's.**

**Against it, and none of these are about instance count:**

1. **The core gets heavier, which threatens the "no degradation" condition even with one
   instance per core.**
   - 🟡 ≈ 650–850 cycles/voice once the double-precision states (item 3) are counted.
   - Stock's heaviest legal configuration leaves ≈ 890 cycles spare per core (emulator +
     FILTER calibration, §10). Saturating 4× + Heun (~760) fits by ~130; hardware
     calibration (Phase 0b) decides.
   - Levers, in order (FX restrictions are ruled out, §0a):
     1. polyphase-FIR decimation;
     2. per-frame coefficients;
     3. 3× or 2× if the Phase 1 study says it's inaudible;
     4. donating the most expensive stock effect(s), which lowers the worst case itself.
2. **Per-frame timing on core 1 (tracks 1–4).**
   - octabam hit a measured hardware failure: a track whose processing ran late put its
     output copy inside the read-back DMA pull, and the ColdFire DELAY received torn
     blocks (`FAILURE_MODES.md`, images 36–43). Stock copies at ~+2 samples; the pull
     reaches T1 at ~4.5 ± 0.5.
   - A 4× voice adds ≈ 2.3 sample-periods per frame to its track's processing (2× would
     add ~1), *if* the voice runs inside the track's slot of the frame (unread).
   - This is the one way a 4× voice could harm *another* feature (the stock DELAY) without
     any overload.
   - Measure it in Phase 0/2. Mitigations: a placement rule for the core-1 instance, or
     running the voice outside the per-track window.
3. **Fixed-point precision.** At 176.4 kHz every one-pole coefficient sits ~4× closer to
   1. The ladder and high-pass states then need 48-bit (two-word) storage, or the low
   cutoffs and the self-oscillating resonance pick up noise and DC limit cycles. That
   costs more cycles and words: a cost, not a blocker.
4. **"Faithful" is still not literal.**
   - Open303's oscillator wavetables (≈ 49 K words) don't fit anywhere, so the oscillator
     becomes polyBLEP saw + tanh-shaped square. At 4× that is effectively alias-free.
   - The direct-form elliptic decimator is unusable in fixed point. A polyphase FIR
     (1 output per 4 inputs) replaces it: cheaper, linear-phase, ~0.1 ms latency.
   - Fidelity loss: inaudible by design, but it should be checked in Phase 1.
5. **The audible return over 2× may be small.** The oscillator is already band-limited,
   and Open303's ladder is linear in TB_303 mode, so 4× buys filter accuracy, not
   anti-aliasing of a non-linearity. Cheap to settle offline in Phase 1: render the 4×
   model against a 2× TPT model on the same patterns and compare (levels/spectra, and
   ears).

### The filter study (Phase 1, decides the oversampling factor)

- **Oracle:** Open303's own C++ (`TeeBeeFilter`, TB_303 mode, 4×, double precision),
  compiled unchanged.
- **Candidate:** the *same continuous-time model* (coupled 4-pole ladder, the feedback
  high-pass, the same resonance and cutoff mapping), discretised as a zero-delay-feedback
  (TPT) filter with prewarping, at 4×, 3× and 2×, in the fixed-point twin the DSP will run.
  - Open303's update equations are an explicit (Euler-style) discretisation whose errors
    are corrected by fitted polynomials, and they only hold when the cutoff is far below
    the sample rate.
  - A ZDF version tracks the analogue model by construction. So at 2× it can match the
    model as well as Open303 at 4×, but with *its own* small deviations at the very top of
    the range, not Open303's.
- **Measures:**
  - magnitude and phase over a cutoff × resonance grid;
  - resonance peak frequency and height;
  - self-oscillation pitch and level;
  - time-domain renders of real acid patterns (env mod, accent, slide, decay sweeps) with
    level and spectral difference against the oracle.
  - Then a blind A/B (ABX) by the user. **The user's ears decide; the numbers shortlist.**
- **One question it can also answer:** Open303's TB_303 filter is *linear*. A real 303
  ladder saturates, and jc303's diode option models that (GPLv3, reference only;
  implement from the published diode-ladder literature).
  - A saturating stage *creates* harmonics, and that is where oversampling stops being
    about filter accuracy and becomes about aliasing.
  - If a non-linear filter is wanted, 2× is far less likely to be inaudible.

---

## 10. Results so far (2026-10-04, worktree `ot303`)

### Phase 1, filter study (offline; `tools/ot303/`)

- **Harness:** `voice_study` renders Open303's own voice with only the filter and the
  oversampling swapped. It is **bit-exact to `rosic::Open303`** when set up as Open303 (4 scenes).
- **The model:** Open303's TB_303 mode is exactly Zavalishin's linear diode ladder (*VA
  Filter Design 2.1.0* eq. 5.18) with ω_c = 2 × Open303's stage rate, plus a 150 Hz one-pole
  HP in the feedback. Checked term by term.
  - Zavalishin's nonlinear form (§6.9: tanh on the input and on every stage difference)
    linearises to exactly that, so the saturating filter *is* Open303's filter at low drive.
  - Andy Sloane's measurements of a component-exact x0xb0x (github.com/a1k0n/303, no
    licence, facts only) say the real 303 ladder matches the theoretical model except for
    the HP in the resonance loop. That is this structure.
- **Linear (`filter_linear.py`, exact transfer functions, inside −40 dB of each peak).**
  ZDF/TPT error against the analog model:

  | rate | worst level | peak pitch | peak height |
  |---|---|---|---|
  | 4× | 0.86 dB | 0 c | 0.31 dB |
  | 3× | 1.54 dB | 0 c | 0.61 dB |
  | 2× | 3.7 dB | 20 c | 1.8 dB |

  - The 2× error only appears at cutoffs ≥ 6.4 kHz; below 3.2 kHz every rate is ≤ 0.84 dB.
  - **Open303 at 4× is itself ≤ 4 dB / 40 c from the model above 6 kHz** (its fitted
    coefficients).
- **Time domain (`run_study.sh`, `compare.py`; STFT log-magnitude, mean / p95 dB).** Worst
  scene "hot" (env mod 100, res 100, accent 100):

  | rate | method error at own rate | rate cost vs 8× | saturating, Heun |
  |---|---|---|---|
  | 4× | 0.10 / 0.38 | 0.06 / 0.24 | 0.09 / 0.49 |
  | 3× | 0.17 / 0.68 | 0.13 / 0.48 | 0.17 / 0.87 |
  | 2× | 0.39 / 1.6 | 0.29 / 1.0 | 0.38 / 1.9 |

  - Every other scene is ≤ 0.1 / 0.4 at all rates.
  - **Open303's own filter vs the model, same scene: 1.21 / 5.9.**
  - Saturation itself moves the sound 2–9 dB (D 0.5–2): a voicing decision, by ear.
  - **Heun (one corrector) matters more than 3×→4×:** 2×+Heun beats 4× without it, at equal
    solve count.
- **Real-303 lead (Whittle, Devil Fish docs):** the accent sweep is diode + 47 kΩ into
  1 µF, discharged through the 100 kΩ ACCENT pot + 100 kΩ mixing resistor.
  - That is an asymmetric RC (charge ~47 ms, discharge ~100–200 ms), so consecutive accents
    stack ("wow").
  - Open303 uses a symmetric 15 ms leaky integrator.
  - Candidate improvement at control rate. 🟡 Verify the values against the x0xb0x schematic.
  - Stinchcombe: the coupling caps add ~5–6 poles near 10 Hz, covered by Open303's
    sub-bass HP/allpass voicing.

### Phase 0a, stock DSP effect costs (emulator; `tools/ot303/phase0_fxcost.py`)

Method:
- `ot_emu` (octabam port, private copy of `8d0ad6f4`), stock 1.40C, the user's BOTLI project
  playing.
- All four tracks of a core set to one effect via the live id arrays.
- `--dsp-stopwatch` at the dispatcher call sites.
- Instructions per sample per track instance, identical on both cores and slots (±1%):

| effect | instr/sample | effect | instr/sample |
|---|---|---|---|
| DJ EQ | 300 | PHASER | 189 |
| LO-FI | 280 | PLATE REV | 189 |
| SPRING REV | 264 | EQ | 144 |
| CHORUS | 260 | FLANGER | 122 |
| FILTER | 207 | COMB | 100 |
| DARK REV | 199 | COMPRESSOR | 72 |
| SPATIALIZER | 69 | NONE / DELAY (ColdFire) | 4 |

- **Calibration:** FILTER = 192 cycles on hardware (octabam burn sweep) vs 207 instructions
  here, so stock effect code ≈ **0.93 cycles/instruction**.
- **Worst legal stock configuration per core:** DJ EQ in FX1 and FX2 on all four tracks ≈
  2,400 instr ≈ 2,230 cycles, against the 3,120 usable, so **≈ 890 cycles spare.** That is
  the "no degradation" budget for one OT-303 voice per core (its own track's FX are part of
  the worst case).
- 🟡 OT-303 voice estimates (instructions, before the real code exists):

  | variant | instr/sample |
  |---|---|
  | saturating 4× + Heun | ~760 |
  | saturating 3× + Heun | ~580 |
  | saturating 2× + Heun | ~400 |
  | linear 4× | ~350 |
  | linear 3× | ~275 |
  | linear 2× | ~200 |

  **Everything but saturating 4× + Heun fits with margin; that one fits by ~130.**
- **Not yet covered:** the cycles/instruction of *our* code; contention; the core-1 read-back
  timing (§9.2).

  Phase 0b (one hardware burn-probe image) calibrates the first and confirms the worst-case
  spare directly.

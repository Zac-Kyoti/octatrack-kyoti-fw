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

### Phase 0b, the burn-probe image (built 2026-10-04, emulator-verified, NOT flashed)

`tools/build_ot303_burnprobe.py` (WIP) → `out/OCTATRACK_OS1.40C_OT303_BURNPROBE.syx`
(version `140C_303BP`).

What the image contains:
- Stock plus a BURN knob on DJ EQ page 2 (slot 6, 24 cycles/sample per step), via
  `tools/ot303/burn_djeq.asm`, octabam's RIG BURN body.
- SPRING REV removed (its words hold the routine).
- 107 bytes changed; no ColdFire code.

`tools/ot303/verify_burnprobe.py`, against stock, with BOTLI playing: **ALL GOOD**.
- BURN 0 = +8 instructions per call.
- BURN n = +3·8·n·16 instructions, on the targeted track only, both cores and both slots.
- SPRING's id → the 69-instruction passthrough.
- DARK REV identical to stock.

Not covered by the emulator: the knob's drawing, and real cycles (the point of the image).

**Procedure (the user):**
1. Flash, power-cycle, and work in a *copy* of a busy project. A raised BURN is stored in
   the Part, but stock firmware ignores it, so reflashing the normal image always recovers.
2. All 8 tracks playing continuously.
3. Heavy run:
   - FX1 = FX2 = DJ EQ on all 8 tracks; check every BURN reads 0.
   - On T1, raise FX1 page-2 BURN step by step (~5 s each) until the audio breaks
     (crackle, dropout, squeal or a stalled sequencer).
   - Note the last clean value N1, then back to 0.
   - The same on T5 → N0.
4. Light run: all FX NONE except T1 FX1 = DJ EQ → L1; except T5 FX1 = DJ EQ → L0.
5. Results:
   - spare in the worst legal config = 24·N per core;
   - 7 DJ EQ instances = 24·(L − N) cycles, which calibrates cycles/instruction against
     the 300-instruction count.

### Phase 1 listening results (user, 2026-10-05)

ABX against the ideal 8× (saturating, D1 + Heun), 10 trials each:

| scene | 2× correct | p |
|---|---|---|
| Hot | 6/10 | 0.377 |
| Sweep | 6/10 | 0.377 |
| Squelch | 3/10 | 0.945 |

**2× is not distinguishable** in any scene, including Hot, which has the largest measured
error (0.38 / 1.9 dB). Ten trials only catch obvious differences, which matches the user's
bar ("virtually inaudible"). **Decision input: 2× + Heun.** 3× stays the fallback if hardware
listening ever disagrees.

Voicing favourites (RMS-matched, all 4×):

| scene | favourite |
|---|---|
| Hot | Drive 0.5 |
| Sweep | Open303 as shipped |
| Squelch | Open303 as shipped |

So the target is **Open303's own response**, not the bare circuit model, with light
saturation available.
- Open303's fitted coefficients pull its response 1–2 dB lower above ~2 kHz at high cutoffs
  and move the peak up to 40 c (§10). That is most likely what was heard.
- Next: fit the ZDF's cutoff/resonance mapping to Open303's measured response (keeping the
  saturating stages), then ABX "Open303-matched ZDF @2×" against Open303 itself, aiming for
  "not distinguishable".
- Drive becomes a user parameter (SETUP page): 0 = Open303-like, ~0.5 default per Hot. The
  DSP cost is the same at any drive.

### Phase 1c, voicing (2026-10-05)

**The user's target:**
- rich, gummy, complex, deep, chirpy, squelchy;
- pleasing and not fatiguing over long sessions;
- the top end kept available at the source (easy to carve away later, impossible to add
  back).

Round-1 notes: Drive 1/2 were "too dark, a loss of sheen and 3D complexity"; Open303 and the
linear model a touch bright/harsh.

**Rule for every control (user):** a knob must give an apparent, usable change across its
whole range. No near-inaudible ranges. A DRIVE knob is only added if its range passes that test.

**Why drive darkened:** in the tanh-per-stage ladder the stage nonlinearity scales the
integrator gain (Zavalishin §6.9: K = Δtanh/Δx ≤ 1), so level lowers the effective cutoff.
`voice_study` now has `zdf2` (FZdf2) with the nonlinearities placed separately:
- `in` = the input pair, tanh on in − feedback;
- `st` = stage differences;
- `fb` = the feedback path only;
- `comp` = undo the slow (~50 Hz smoothed) mean stage-gain loss;
- the circuit accent (`acc:1`: Whittle's diode + 47 kΩ / 1 µF / 100 k + 100 k, τ 47 ms
  charge, 150 ms discharge; normalised so one isolated accent peaks where Open303's rc2 does);
- the `accents` scene (runs of consecutive accents).

Exploration at 2× (spectral change vs linear / 4–16 kHz energy at equal RMS):
- st+comp keeps the top (HF 0 to +7 dB) while changing 4–12 dB;
- `in` −7 dB per unit of drive;
- `fb` a big bass bloom (−15 to −30 dB HF at equal RMS);
- circuit accent vs Open303 accent: 2.1 / 8–11 dB p95.

**Round 2 pack** (same artifact, v4; `tools/ot303/listening_pack2.py`):
- seven voicings per scene behind shuffled letters: Open303 4×, linear, st0.5, st1+comp,
  st2+comp, in1, fb1;
- an accent A/B on Accents and Hot;
- a free-text note per scene.

### Phase 1c results and the voicing decision (user, 2026-10-05)

| scene | keep | second |
|---|---|---|
| Sweep | stage sat, light (st0.5) | linear |
| Hot | Open303 as shipped | input pair |
| Squelch | linear | st0.5 |
| Accents | linear | st0.5 |

- **Accent:** the 303 circuit accent was preferred in both A/Bs (Hot, Accents; blind,
  shuffled numbering).
- **Reading:** 6 of 8 picks are linear or st0.5. The two are nearly identical at normal
  settings (spectral change 0.5 dB, measured) and differ only at extreme
  resonance/env/accent, where st0.5 tames the peak. No compensated, heavy or feedback variant
  was picked. At the extreme (Hot) the softer top won: Open303's fitted high-cutoff response,
  then input-pair.
- **Voicing decision (to confirm by ear on the fixed-point twin):**
  1. Diode-ladder ZDF at 2× + Heun, with a **fixed, built-in light stage saturation (D 0.5)**.
     No DRIVE knob: its audible range is too narrow for the user's control rule. It also
     bounds self-oscillation, which a fixed-point linear ladder at RES 127 would not.
  2. **Open303-style top end:** take Open303's effective cutoff→response mapping above
     ~3 kHz (its fitted b0/k), so extreme sweeps get its softer top. Low and mid cutoffs stay
     on the model. A/B it with and without in the fixed-point listening check.
  3. **The circuit accent** replaces Open303's rc2 path. The discharge time follows the ACCENT
     knob as the real pot does (values to check against the x0xb0x schematic), which gives
     ACCENT a large, usable range.
- **Next:** Phase 2, the fixed-point twin (the DSP's exact arithmetic) of this voice, plus a
  listening check of the twin against the double-precision version.

## 11. Phase 2: the DSP-shaped voice (2026-10-05)

### The algorithm (`tools/ot303/voice_study.cpp`: FNested, OscBlep, HalfBand, Tables, Quant)

**Per output sample (44.1 kHz):** Open303's control path unchanged in function.
- Pitch slew. MEG. The circuit accent in place of rc2.
- Env-mod scaler/offset from Open303's *measured* 303 mapping (`calculateEnvModScalerAndOffset`;
  `n1 = n2 = 1` in Open303).
- cutoff·2^(env) → **one log-domain table g(log2 fc)** with the prewarp folded in.
- AMP envelope + declicker. Post allpass 14 Hz, HP 24.2 Hz, notch, level.

**Per oversampled sample (88.2 kHz):**
- **Oscillator:**
  - polyBLEP saw (Open303's SAW303 = saw with its reset at mid-cycle);
  - the square = −tanh(70.0·saw(p) + 4.37) − DC, 180° on (Open303's SQUARE303), from a
    tanh table;
  - blend (1−b)·saw + b·0.5·square.
- **Pre-HP** 44.5 Hz.
- **Ladder:** TPT diode ladder solved in closed form by back substitution:
  - four stage reciprocals + one loop reciprocal per pass (normalise, 64-entry table, one
    Newton step);
  - stage saturation D = 0.5 via a 256-entry tanh(x)/x table (input pair and feedback linear);
  - optional Heun pass.
- **Decimator:** 79-tap half-band (`halfband79.h`; 41 MACs per output; flat to 19 kHz,
  −92 dB from 25.1 kHz).

**Resonance ceiling, k at RES 100 = 16.5** (was Open303's 16.9988).
- The true saturating model (RK4 8×) starts to *sustain* self-oscillation between k = 16.8
  and 16.9 in Hot.
- At 16.9988 whether a discretisation oscillates is numerical luck: the matrix 2× + Heun did
  (RMS 1.6), the closed form did not (0.22).
- The round-2 "st0.5" Hot clip was oscillating.
- 16.5 keeps every correct method on the same side. A stock 303 rings but does not
  self-oscillate.

### Verified, step by step (mean / p95 spectral dB; scenes Hot, Sweep, Squelch, Accents, Square)

| step | result |
|---|---|
| closed form vs matrix solve (linear) | −36 dB null, 0.03 dB; the solve is right |
| closed form vs true model (RK4 8×) | 0.07–0.64 / 0.25–2.4 (Hot largest), same as the matrix 2× solve |
| BLEP oscillator vs Open303's tables | 0.03–0.29 / 0.1–1.1 (square largest) |
| half-band vs Kaiser | −58 dB in sustain; ~0.3 / 1.5 overall, from the amp envelope (applied after the decimator, as in Open303) meeting a 15-sample shorter delay at note on/off, ~0.34 ms |
| tables + 24-bit signals + 24-bit states | **0.00 / 0.01**: 24-bit states are enough, no double-word storage |
| no Heun corrector | 0.01–0.07 / 0.05–0.41 |
| **DSP twin vs the approved voice** | **0.30–0.49 / 1.26–1.75** |

- The "Open303 top" fit (k vs fc/res for peak height) was dropped: where it brackets,
  Open303's peak height is within ~0.5% of the model.
- `compare.py` alignment fix: the shift went the wrong way for unequal delays. Earlier nulls
  for unequal decimator delays were pessimistic; the spectral metrics were unaffected.

### Cost estimate (instructions per output sample; the DSP code does not exist yet)

| block | with Heun | without |
|---|---|---|
| oscillator ×2 | ~50 | ~50 |
| pre-HP ×2 | ~6 | ~6 |
| ladder ×2 (~105 per pass incl. 5 reciprocals and 4 table gains) | ~440 | ~230 |
| half-band | ~41 | ~41 |
| control + accent + post + level | ~60 | ~60 |
| **total** | **~600** | **~390** |

Budget: ≈ 890 cycles per core in the worst legal stock configuration (§10, ~950 instructions
at 0.93 c/i). Both fit; Phase 0b's burn test confirms on hardware.

**Round 3 pack (artifact v5):**
- ABX twin vs approved (Hot, Sweep);
- ABX Heun on/off (Hot, Sweep);
- Hot preference, twin vs Open303.

### Round 3 results and the top end (2026-10-06)

User:
- ABX twin vs approved, Hot: p = 0.172, not distinguishable. Sweep and the corrector ABX
  were lost to the page losing audio.
- Hot pick: Open303 as shipped. Its extended top matters, but it is "a touch too much at
  the very top" → wanted: Open303, a little more rounded.

**Where Open303's Hot top end comes from** (band energy at equal RMS, 14–18 kHz vs Open303):

| version | 14–18 kHz |
|---|---|
| the linear model with Open303's accent and k 16.9988 (2× or 4×) | −0.1 |
| the twin with Open303's accent | −6 (k ceiling 16.5 and D 0.5 compressing the peaks) |
| the twin with the circuit accent (47 ms charge) | −12 |

**The filter model is not the cause.** The causes are:
1. Resonance near the self-oscillation edge at high cutoffs. Open303's peak at fc 14–20 kHz,
   RES 100 is +26–27 dB against our +17–21.
2. The accent charge time.

**Changes (in `voice_study`):**
- `ktab:Δ` (`tools/ot303/ktab.h`): k(RES, fc) fitted so the 2× ladder's peak = Open303's − Δ
  dB.
  - Applied above ~1.4–2.8 kHz only, and only ever adding resonance; capped at 16.9.
  - Safety, true model (RK4 8×) in Hot: Δ 1.5 sustains oscillation (RMS 1.75), Δ 3
    intermittent (0.65), **Δ 4.5 safe (0.222)**. Δ 4.5 is the one in use.
- `acctc:ms`, the circuit accent's charge time:
  - 47 ms (Whittle's values) → −9.7 dB at 14–18 kHz (with Δ 4.5);
  - 25 ms → −4.7;
  - 12 ms → −2.9.
  - The discharge (150 ms, the stacking) is unchanged.
- Saturation 0.5 vs 0.3: no top-end difference.
- `fmax` (the cutoff ceiling above 20 kHz): no effect; Hot never asks for it.

**Round 4 pack (artifact v6, also served locally on :8303):**
- blind pick on Hot and Accents: Open303 vs 25 ms vs 12 ms (both with Δ 4.5);
- the corrector ABX (Hot, Sweep) on the 12 ms voice.

### Round 4 results and the final voicing (2026-10-06)

User:
- Hot keep = **accent charge 25 ms** (≈ 5 dB under Open303 at 14–18 kHz).
- Accents keep = Open303 as shipped.
- Corrector ABX: Hot 3/10 (p 0.945), Sweep 7/10 (p 0.172), both chance → **Heun dropped**.
  Cost estimate ~390 instructions per sample (§11).

**Fix:**
- The ceiling had been applied as k = 16.5 · r, which cut *every* RES by 3% (Accents at RES
  85 lost resonance).
- Now **k = min(16.998792 · r, 16.5)** (`kcap:1`): Open303's curve is untouched below
  RES ≈ 92%, and only the top is held.
- Safe by construction (never above the RK4-checked 16.5 Hot case). Re-checked: the true
  model with the final mapping does not sustain oscillation in any scene.

**Final voicing (round-5 candidate):**
- 2×, no Heun, stage saturation 0.5;
- k = min(16.998792 r, 16.5), plus ktab Δ 4.5 above ~1.4–2.8 kHz (adds only, capped 16.9);
- circuit accent with 25 ms charge and 150 ms discharge.

Against Open303 at equal RMS, 0.5–10 kHz is within about ±1 dB in every scene, then 1–2 dB
under at 10–18 kHz (5 dB in Hot, the user's pick).

**Round 5 (artifact v7, local :8303):** blind keep on Accents and Squelch, Open303 vs final.

Voicing constants that stay tweakable on hardware (data, not code):
- the accent charge/discharge;
- Δ;
- D;
- the RES ceiling.

### Round 5 → the engine becomes Open303's own algorithm (2026-10-06)

User: Accents keep = Open303, Squelch keep = Open303 (vs the final ladder voice).

**Reading, over five rounds:** Open303, or the linear model that mirrors it, wins at normal
settings. A slightly rounder top wins only at the extreme (Hot). Never picked at normal
settings: stage saturation, the circuit accent's charge, our discretisation.

**Decision: the DSP engine is Open303's TB_303 algorithm at 4×** (`o303q`, FO303Q: the filter
transcribed from rosic_TeeBeeFilter.h, **bit-exact to it** through the whole voice in 4 scenes):
- BLEP oscillator;
- two half-band stages (`halfband4x.h` 23 taps 4×→2×, −62 dB from 63.1 kHz; then the 79-tap
  stage);
- tables, 24-bit.

| step | result |
|---|---|
| vs Open303 as shipped | ±0.1 dB per band below 14 kHz; spec 0.29–0.42 / p95 1.2–1.8, from the envelope/decimator-delay timing as before |
| 48-bit states | buy nothing over 24 |

**No RES ceiling.**
- Open303 (linear Euler) does not self-oscillate in any scene, even at RES 100 (Hot RMS 0.225).
- The ceiling existed for the saturating ladder.
- With Open303's RES skew a k 16.5 cap already bites from RES ≈ 85% (it changed Squelch at
  RES 95).

**Cost:** cheaper than the ladder, ~320 vs ~390 instructions per sample.
- No divisions, no tanh-ratio tables.
- Per 4× sample ≈ oscillator 25 + HP 3 + TB filter ~24 → ×4 ≈ 210.
- Decimation 13·2 + 41 ≈ 67 MAC per output.
- Control/post ~60.

**"Slightly rounder top at the extreme":** a fixed one-pole rounding (on the DSP it folds into
the 79-tap decimator design, at no cost):

| scene | 16 kHz rounding (10–14 / 14–18 kHz) | 13 kHz rounding |
|---|---|---|
| Hot | −0.9 / −2.2 dB | −2.1 / −4.3 dB |
| other scenes | same relative change, in bands holding −62…−74 dB of their energy | |

**Round 6 (artifact v8, local :8303):**
- Hot pick: Open303 / 16 kHz / 13 kHz;
- ABX Squelch and Accents: Open303 vs DSP + 13 kHz.

The harness bug found on the way: the tanh table was only built for the ladder path; now
built always.

### Round 6 results: VOICING FINAL (user, 2026-10-06)

- **Hot pick:** the DSP version with **16 kHz rounding**.
- ABX vs Open303 as shipped, with the *stronger* 13 kHz rounding:

  | scene | correct | p | reading |
  |---|---|---|---|
  | Squelch | 8/10 | 0.055 | borderline |
  | Accents | 5/10 | 0.623 | chance |

  The chosen 16 kHz rounding changes about half as much as the 13 kHz one (Squelch 10–14 kHz:
  −0.8 vs −1.9 dB; 14–18 kHz: −1.6 vs −4.0 dB, bands holding ~−62…−74 dB of the energy).

**The OT-303 voice, as the DSP will run it:**
- Open303's TB_303 voice: oscillator blend, envelopes, the measured env-mod mapping, slide,
  Open303's accent, pre/post voicing;
- the TB_303 filter at 4× (explicit update, Open303's fitted b0/k/g, 150 Hz feedback HP), no
  RES ceiling;
- BLEP saw + tanh-table square;
- 23-tap + 79-tap half-band decimation with a fixed one-pole rounding at 16 kHz folded into
  the 79-tap design;
- 24-bit data and states.

Est. ~320 instructions per sample per voice. Reference renders: `voice_study o303q 4 hb2
blep:1,tab:1,q:1,stbits:24,top:16000`.

Superseded (kept in the harness, not shipped): the ZDF diode ladder (FNested), stage
saturation, ktab, the circuit accent, the RES ceiling.

**Next (Phase 2b): the DSP engine.**
1. An **integer-exact twin**: DSP56300 arithmetic, 24-bit words, 56-bit accumulators, the
   rounding the asm will use. The current Quant model is quantise-on-store in double.
2. The engine in DSP56300 assembly through `tools/dsp_xasm.py`, **bit-exact against that
   twin**. Placement: the FX2-slot tails if it fits (keeps SPRING), else SPRING.
3. The burn test (Phase 0b, still not flashed) confirms the cycle budget on hardware.

### Phase 0b on hardware (user, 2026-10-06): the burn test

Image `140C_303BP` (syx `d2abc4d3…`), BURNTEST project, all 8 tracks looping one long Flex
sample.

| run | core 1 (T1–4) | core 0 (T5–8) |
|---|---|---|
| heavy: DJ EQ in FX1 + FX2 on all 8 tracks, last clean BURN | **N1 = 26 → 624–648 cycles/sample spare** | **N0 = 12 → 288–312 cycles/sample spare** |
| light: one DJ EQ on the core, everything else NONE | L1 = 127+ (≥ 3,048) | L0 = 127+ (≥ 3,048) |

**What it means:**
- **The emulator's ~890 was optimistic.**
  - 7 extra DJ EQ instances cost ≥ 101 steps (core 1) / ≥ 115 steps (core 0), i.e.
    ≥ 346 / ≥ 394 cycles each, against 300 instructions.
  - So DJ EQ runs at ≥ 1.15–1.3 cycles/instruction, not the 0.93 FILTER suggested.
  - These are lower bounds: the light runs never broke.
- **Core 0 has much less room than core 1** in the same configuration (288 vs 624). Core 0
  also carries the mixdown, the DELAY's return block and cue/main routing (DSP.md §6c).
- **Against the voice (~300–320 instructions ≈ 300–420 cycles at 1.0–1.3 c/i):**
  - core 1 hosts one OT-303 with margin;
  - core 0 does not, in the worst legal configuration, unless the engine gets well under
    ~280 cycles or the worst case is lowered (donate DJ EQ, and maybe LO-FI; re-measure with
    the new worst case).

### Decision after the burn test (user, 2026-10-06)

- **Option 3: build the engine lean.** Savings that cannot change the voice, each accepted only
  if it measures (and, if in doubt, ABX-tests) as indistinguishable from the final voice:
  - the square only computed when WAVE ≠ pure saw (identical output; helps typical load, not
    the worst case);
  - Open303's per-sample coefficient formulas (b0, the k polynomial, g; divisions) replaced
    by small interpolated tables over log-cutoff;
  - a shorter second decimator, co-designed with the 16 kHz rounding.
  - Not on the table: lower oversampling, envelopes updated less than every sample.
- **Option 1 is the guaranteed baseline:** one OT-303 on T1–4 (core 1) fits the worst legal
  configuration with margin.
- **Option 4: the no-degradation rule is relaxed for now on core 0.** Two OT-303s (one per
  core) is the target; the build is **caveated**: in the heaviest FX configurations on T5–8
  (many DJ EQ / LO-FI / SPRING / CHORUS instances) the second instance can overrun the core.
  The caveat's exact boundary is measured once the engine exists.

### Phase 2b, step 1: the integer twin (2026-10-06, `tools/ot303/twin.h`)

The final voice in the DSP56300's own arithmetic: 24-bit words, 56-bit accumulators, stores that
saturate and truncate, convergent `rnd` (SR RM = 0, the reset default ❓ confirm the OT leaves it
there) on every recursive state. Host words (note/knob events; the ColdFire's job) are separate
from the per-sample DSP work. `voice_study twin SCENE OPTS OUT`, `voice_study twinunit`,
`tools/ot303/twin_check.py TAG OPTS`.

**What the twin needed (found by measurement, each against the approved voice):**

| issue | fix | effect |
|---|---|---|
| truncating stores in the slow post filters build a DC offset (notch 7.5 Hz, allpass, HP) | convergent rounding on recursive states | notch null −29 → −61 dB, one-poles −54 → −89 dB |
| the filter envelope (MEG) decaying in 24 bits drifts the resonance's path (Hot 4–10 kHz error −15 dB) | **48-bit MEG** (≈3 instructions per sample) | Hot −25 → −34…−46 dB; other scenes −51…−65 dB |
| 24-bit phase increment: ≤ 0.14 cent off (0.27 at C1) | kept (lean) | inaudible: detuning the approved voice by 0.05 cent moves the spectral metrics more |

**The lean savings (option 3), each measured with the reference oscillator and latency matched:**

| saving | result |
|---|---|
| coefficient tables over log2(cutoff), 1/32 octave, linear interpolation (no exp2, no division) | vs exact formulas: same within −60 dB |
| second decimator 79 → **43 taps** (pass to 16 kHz, −99 dB from 28.1 kHz): 22 MACs, was 40 | same within −60 dB |
| first decimator 23 → **15 taps** (pass to 18 kHz, −88 dB from 70.2 kHz): 8 MACs, was 12 | same within −60 dB |
| square only when WAVE > 0 | identical by construction |

The shorter decimators cut the filter→VCA latency by 10 samples (0.23 ms); that moves toward the
analog 303 (no latency), and is the one change not hidden by latency matching.

**The lean twin as it will run** (own oscillator, 24-bit phase, knob words every 16 samples) vs the
approved voice: spec 0.33–0.45 dB, p95 1.5–2.0, the same size as the approved voice against
itself detuned by 0.05 cent (0.37–0.71 / 1.6–3.3). **Round 7 ABX** (local :8303): A approved,
B lean, on Hot, Squelch, Accents, Square.

**Cost estimate (instructions per output sample, to be measured on the asm):** control ~50,
oscillator + pre-HP + TB filter ×4 ≈ 110–120 (square +40), decimation ≈ 45, post ≈ 22, overhead
~10 → **≈ 240 saw, ≈ 280 square** (was ≈ 320).

### Round 7 results (user, 2026-10-06): the lean engine is accepted

| scene | correct | p |
|---|---|---|
| Hot | 0/4 | 1.000 |
| Squelch | 4/10 | 0.828 |
| Accents | 1/5 | 0.969 |
| Square | 6/10 | 0.377 |

All at chance. **The twin (`twin.h`, options `hb2:43,hbfp:16,hb1:15,hb1fp:18,meg48:1`) is the
contract the DSP assembly must match bit for bit.**

### Phase 2b, step 2: the DSP engine (2026-10-06/07, `tools/ot303/ot303_engine.asm`)

**Bit-exact against the twin on dsp56kEmu, all five scenes** (695,423 samples each:
sample-accurate notes, slides, accents, square, knob words every 16 samples).
`python3 tools/ot303/engine_check.py`: assembles through `tools/dsp_xasm.py` (every word
disassembled and checked), has `voice_study`'s twin log each scene's host segments, and replays
them through the twin and the emulated DSP (`engine_probe.cpp`).

- Standalone routine `ot303`: renders r7 samples into `x:(r3)+`; the host words and the
  trigger pokes (S48, M48, AMP2) are memory words. Position-independent (relative branches).
- **543 words of P** (413 instructions, 128 of them two-word); fits SPRING's 1,063 or one
  FX2-slot tail (~605).
- Data: Y tables 1,886 words (coefficients 860, tanh 1,026) + ~100 words of state and
  constants; X ~140 words incl. the half-band buffers. Placement still to check against the
  free regions (Y `$795..$FFF` = 2,155 words on stock: tight but fits).
- **Cost, instructions per output sample** (emulator count; cycles ≈ +15% for two-word
  instructions and stalls, measure on hardware):

  | path | instructions |
  |---|---|
  | saw (WAVE 0) | **360** |
  | square / blend | **472** |

  Breakdown (saw): control 81 (envelopes, accent, log cutoff, coefficient tables, amp
  declicker), oscillator 29, 4× pre-HP + TB filter 116, half-band 1 32, half-band 2 32, post
  54, loop and I/O ~15.

- This is above the ~240/280 estimate: the control block (48-bit envelopes, the 2nd-order
  declicker) and the post filters (the 7.5 Hz notch SVF needs scaled coefficients) cost more
  than budgeted. Further hand-tuning (fewer two-word moves, square path) is worth maybe
  10–15%.
- **Against the burn test:** core 1 (624 cycles spare, worst legal config) hosts one OT-303
  with margin. Core 0 (288 spare in the worst config) overruns in the heaviest FX
  configurations, as accepted (option 4, caveated); its headroom in normal configurations is
  the next measurement.

**Toolchain lessons (dsp_asm, the emulator's assembler):**
- `mpy/mac` operand pairs must be one of the 8 QQQ orders; anything else silently becomes
  `mpysu`.
- Immediate shifts (`asl #n`), long-immediate ALU ops (`and #>`), `mpy S,#n` take **no**
  parallel move; the move is silently dropped.
- The X:R / R:Y move classes are not encoded (one half dropped).
- A bare `tfr a,b` encodes as `rnd b`.
- `dsp_xasm` catches all of these by disassembling every word; it now also builds XY+ALU
  instructions whose halves are writes (commit `ec96d45`, REPITCH output unchanged).
- Stock DSP code leaves SR RM = 0 (`move #$300,sr` at boot; no other writer): convergent
  rounding, as the twin assumes.

**Next:**
1. The host side, still standalone: triggers from a flag (the DSP pokes S48/M48/AMP2 itself),
   the host words from the OT's per-track record.
2. Phase 3's first item: does THRU run the voice engine (`P:0x3a1`)? That picks the hook.
3. Hardware cost: a burn-style measurement of the real engine on core 0 and core 1.

### Phase 2b, step 2 continued: cycles, not instructions; the research pulled in on 2026-10-07

**Correction.** The 360/472 figures above are *instructions*. Priced by the emulator's own cycle
table (`dsp56k::calcCycles`, internal P, no interlocks; the probe now runs octabam's
host-stepped interpreter one instruction at a time), v3 cost **508 cycles/sample (saw) and 690
(square)**: an absolute address costs 3 cycles, a long immediate 2, a long branch 5.

**What the upstream research (whatsnew, 2026-10-07) changed:**

| source | finding | used |
|---|---|---|
| octabam `AGENTS.md`, `tools/patches/dsp56300.patch` (4 Oct 2026, pin `8ccdd843`) | dsp_asm now encodes an ALU op with two parallel moves, the X:R / R:Y classes, the one-word `(rN+d)` move; the emulator fixes DO-loop ends and modulo bounds | built privately in `out/ot303/dsp56300_new` (`OT303_DSP=new`), the shared `vendor/` untouched; the engine re-verified bit-exact under the fixed emulator |
| octabam VOCODER (Ignorato's MKII, 4–5 Oct 2026) | real cost 850–940 cycles for 760 counted: **hardware runs ~12–25% above the cycle table** (one-word displaced moves ~4 cycles); two per core fit beside four FX1 FILTERs; an effect at a core's first track (T1/T5) gave click bursts (finishing before the ColdFire's pull); 48-bit envelope followers; DJ EQ donated to free X memory for tables; a branch-free polyBLEP with a per-note 1/du table | the cost margin below; the T1/T5 caveat noted for the hook choice; our 48-bit MEG is the same lesson |
| octamad `OPTIMIZATION_LEVERS.md` §3 | stock's DSP load is fixed (~1,410 of 4,532 cycles/core); idle tracks take a *more* expensive DSP path (~60 instructions/sample/core, memoisable 🟡); no CPU lever is shown to buy DSP headroom yet | context only: nothing frees core 0's heavy-config budget |

**v4 (`89f7592`, then the square path):** every once-per-sample word read by an X or a Y
walker in use order (no absolute addressing on the sample path); half-bands as polyphase pairs
(odd branch read oldest-first and back, even branch a delay: no pointer arithmetic); the
oscillator writes straight into the 4× state banks. Bit-exact in all five scenes.

| | v3 | **v4** | hardware estimate (×1.12–1.25) |
|---|---|---|---|
| saw, mean (worst 16-sample call) | 508 | **364 (387)** | ~410–480 |
| square | 690 | **498 (541)** | ~560–680 |

Saw breakdown: control 78, oscillator 33, 4× filter + first half-band 153, second half-band 39,
post 58. P: 556 words (fits SPRING; one FX2 tail is ~605).

Against the burn test (heaviest legal FX): core 1 (624 spare) hosts the saw voice with margin
and the square voice about at the limit; core 0 (288 spare) overruns there, as accepted. The
hardware measurement of the real engine is the next number that matters.

### Phase 2b, step 3: the engine on the unit -- the hardware probe (2026-10-07, built, NOT flashed)

**Engine change first.** S48/M48 were L moves (high word in X at the Y word's address). On the unit
no address has both its X and its Y word free (Y `$795..$FFF` is free; X there is stock's curve
bank `X:$438 +6305`), so they are now Y pairs, hi then lo: +2 instructions, **366 / 500 cycles per
sample**, still bit-exact. The layout is three bases (`XB`, `YS`, `LT`, `;@LAYOUT` lines rewritten
per payload by `asm_macros.layout`).

**The image:** `tools/build_ot303_hwprobe.py` (WIP) → `out/OCTATRACK_OS1.40C_OT303_HWPROBE.syx`
(sha256 `3868cd3c64b5ec5d89e16dbf4ffa63b4b7fe476cc1e90dc39b4b057cac46a6fe`, version `140C_303HP`;
`.bin` `2e500aa9…`).
- DJ EQ page 2: **BURN** (slot 6, 24 cycles/sample a step, as in the burn probe) and **303**
  (slot 7: 0 off, 1–63 saw, 64–127 square). With 303 up, the engine replaces the track's audio
  ahead of DJ EQ with a built-in 16-step riff (Hot's first bar, 130 BPM) -- the approved voice.
  `out/ot303/hwprobe/expected_saw_riff.wav` is what it renders (bit-exact bench output).
- **The square is cost-only:** it runs the real square code path, but its tanh table is not built,
  so it renders silence.
- One engine per core (global state): 303 up on one track of 1–4 and/or one of 5–8.
- SPRING REV removed (as the burn probe). Nothing on the ColdFire but descriptor data.

**Placement** (`tools/ot303/hwprobe_image.py`, both payloads):

| | what | words |
|---|---|---|
| P, SPRING up to DARK REV's helper | engine 558 + wrapper (burn, knob, save, render loop, table build) | 756 / 820 |
| P, after the helper | the riff's step events (`hwprobe_ev.asm`) | 79 / 208 |
| X, SPRING's records `89a4×216` / `8464×216` | the engine's X block, the wrapper's words, loaded ready | 216 |
| X, `8afc×500` / `85bc×500` | b0 and kp/64, 216 each (the slopes are differences) | 432 |
| Y `$7a5..$f02` | LT (860, built in 15 calls) + TH (1,026, cleared) | built |
| Y `$f40..$feb` | the Y state block | built |

**Memory, the finding that matters for the product:** engine (558) + glue (~200–350) + tanh's
data (257: odd, half stored) + the coefficient data (432) + the X block (~150) is **~80–200 words
more than SPRING's P (1,028) + X records (716) give**. Ways out, for the product:
1. generate the tanh table on the DSP at boot with an integer recipe the twin defines too
   (tanh's addition formula, th[j+1] = (th[j] + t)/(1 + th[j]·t), one division per entry).
   That frees 257 words for an LSB-level table change (re-check with twin_check; no ABX expected);
2. the same for b0/kp (the polynomial and rational forms of fc = 200·2^(i/32)), which frees 432 more;
3. donate a second effect (COMB, SPATIALIZER), or the FX2-slot tails (~605 words a slot, §4).

Recommendation: 1, then 2 if the glue needs it. Both keep the DSP bit-exact with the twin.

**Verified:**
- Bench, `tools/ot303/hwprobe_check.py`:
  - both payloads, run the way the dispatcher calls them: two calls a frame, the split varying,
    `n7 = 0` included;
  - r0/r6/r7/n7 and m0–m7 kept;
  - the track's audio is untouched while the tables build, and the built LT matches the twin
    word for word;
  - **4 bars bit-exact with the twin, saw and square;**
  - 393 / 528 cycles/sample including the wrapper; worst frame 418 / 579; the table-build frame
    is 87/sample once.
- Firmware, `tools/ot303/verify_hwprobe.py` (ot_emu `8d0ad6f4`, BOTLI playing, DJ EQ ×4 on a
  core):
  - 303 at 0: +11 instructions a call;
  - 303 up on the core's second track: only that track's calls grow (core 1 +3,425 saw / +4,446
    square a call; core 0 +5,423 / +7,056 with its own split);
  - SPRING's id → the passthrough stub;
  - DARK REV as stock. Its fourth track varies call to call in stock too, 3,207–3,277 seen.
- **Not verified:**
  - Audio out of the firmware: ot_emu's `--audio-out` capture is all zeros, stock included.
  - Real cycles: that is the point of the flash.

**Procedure (the user):**
1. Flash; use a copy of BURNTEST (8 tracks looping a Flex sample).
2. **Listen:** T2 FX1 = DJ EQ (flat), page 2 `303` = 32. T2 now plays the riff (compare
   `expected_saw_riff.wav`). Turn 303 up first: the tables build on the first calls, an
   extra ~87 cycles/sample for one frame.
3. **Core 1 cost** (the burn test's heavy config: DJ EQ in FX1 + FX2 on all 8 tracks):
   - On T2 FX1, raise BURN until the audio breaks, three times: with 303 = 0, 32 and 100.
   - 24 × (N₀ − N₃₂) = the saw voice's real cost (engine + wrapper), and the same with 100 for
     the square.
   - Breaking at BURN 0 means the voice alone overruns that config.
4. **Core 0 cost:** the heavy config with T7 and T8 FX2 = NONE (core 0 overruns at the full one
   with the voice), T6 FX1 = DJ EQ; the same three sweeps.
5. **Normal setups:** your own projects, 303 = 32 on one track per core; listen for breakup.
6. Use tracks 2 and 6, not the first track of a core (VOCODER's T1/T5 click caveat). Recover from
   a crash by power-cycling; reflash the normal image to finish.

### Probe 1 on hardware (user, 2026-10-07), and DIAG2 (built, NOT flashed)

**Probe 1 (`140C_303HP`, `3868cd3c…`)**, one DJ EQ on one track, no other FX anywhere:
- **T2 (core 1):** the riff is audible, with medium-sparse crackle and pops ("scratched vinyl, no hiss").
- **T6 (core 0):** the riff is audible, with a uniform grain/distortion grind.
- **With T2 muted:** the crackle is reduced but not gone. Pops come from the mains, left channel,
  with the transport running or stopped. A STATIC machine playing a loop changes nothing.

Not DSP time (light configuration). Not register clobbering of the caller: the stock track loop
(B `P:18b..2cc`) reloads every register after the effect call. The interrupt handlers save what
they touch. The dispatcher's two calls are one 16-sample frame split at the trig offset
(`$20c = a`, `$20d = 16 - a`, `$20e = 2a`, `a` = 0..15), as the bench assumed.

Candidates, and what DIAG2 does about each:
1. **m registers:** probe 1 forced m0–m7 linear on exit. DIAG2 saves and restores them; the bench
   now enters with them non-linear and checks they come back.
2. **Y below $800:** octabam advises absolute scratch at $800 or above. LT moves to $ba7 (TH, the
   square's cleared table, takes $7a5).
3. **Memory-bus contention:** the engine makes two X/Y accesses most cycles. The burn image's nop
   loop makes none, and it was clean at 3,048 cycles. DMA starved by the core would click the I/O
   on the mains even with the track muted.
4. **Arithmetic** that differs on silicon. DJ EQ is bypassed while 303 is up, so a 24-bit
   recording of the track is the engine's output bit for bit and can be compared with the bench.

**DIAG2:** `tools/build_ot303_hwprobe.py` → `out/OCTATRACK_OS1.40C_OT303_DIAG2.syx`
(`bac0c74e775fb283d12f6862cdad275983a13a2b470806274b00f82869d5fdba`, version `140C_303D2`).
- DJ EQ page 2 slot 7 `303`, in sixteens:

  | 303 | mode |
  |---|---|
  | 1–15 | TONE (110 Hz saw) |
  | 16–31 | ENG+TONE |
  | 32–47 | RIFF |
  | 48–63 | WATCH (riff + a checksum of the engine's constants; a change latches 880 Hz) |
  | 64–79 | NOPS+TONE |
  | 80–95 | READS+TONE |
  | 96–127 | SQUARE (cost only) |

- No BURN knob.
- Bench: all modes bit-exact on both payloads, a corruption test fires the alarm. Firmware (ot_emu):
  inert +4 instructions a call, the engine only on its track, SPRING → stub, DARK REV as stock.

**How to read the result:**

| result | cause |
|---|---|
| TONE dirty | the injection/bypass path |
| TONE clean, ENG+TONE dirty, NOPS clean, READS dirty | contention |
| READS clean, ENG+TONE dirty | the engine's writes/state |
| WATCH beeps | something overwrites the engine's constants |
| RIFF dirty, everything else clean | arithmetic (then a 24-bit recording) |

**DIAG2 in the firmware emulator (2026-10-07).**
- **Capture:** ot_emu's `--audio-out` works with `--load-ms 20000`. Core 0's slots 2–5 are
  MAIN/CUE (BOTLI's own tracks are silent under this emulator; the probe's tone shows).
- **Engine state:** with 303 = 40 on T2 and every other FX cleared, the engine's memory after 4,448
  riff samples equals the bench's (`HWP_NOSPLIT=1 HWP_DUMP=1 hwprobe_probe`) word for word: all of
  the Y state block, the X block, and the wrapper's riff position.
- **m registers:** the saved entry values (MSAV) are all `$ffffff`, so stock calls DJ EQ with m0–m7
  linear. Candidate 1 is out, at least under the emulator.
- **Call pattern:** one call a frame, `n7 = 16`, `r0 = 0`. `r6` rotates over the stock
  triple-buffered parameter blocks (`$283/$303/$383`).
- **The MAIN capture** equals the bench × 0.7957 bit for bit through every note's attack and
  sustain. It departs in the releases. The engine's state is equal, so the departure is
  downstream: the test project's own T2 settings (unidentified).

**Conclusion:** on the emulator the engine and the wrapper are correct inside the firmware. The
crackle on the unit is hardware-specific: contention, or silicon behaviour the emulator lacks.
DIAG2's NOPS/READS/ENG+TONE modes are the test.

**Learned from octabam's ANALOG BD (repeat98; HW-tested on an MK1, ANALOGBD1) and SYNTH (Tim Hastie):**
- **Host:**
  - ANALOG BD runs at the per-track SOURCE seam: `move a,x:>$20e` (A `P:0x39c` / B `P:0x1a2`)
    becomes a jsr, and the DSP continues at A `P:0x426` / B `P:0x221`.
  - The voice renders 16 samples into X:0, upstream of stock AMP and both FX slots.
  - FLEX tracks carry a signature in the source record (`w0 $ab09`, `w2 $0909`).
  - The trig flag is in the record, and the trig's sample offset is `x:$20c`.
  - It sets m0/m5/m6 linear itself.
  - **This is the OT-303's host for the product** (both FX slots stay free; no THRU question).
- **Data memory:** octabam's loader boots a rebuilt DSP upload (pre-boot payload) with one more X
  record: ANALOG BD's tables and voice blocks sit at X:$2840–$3940, free in octabam's measured
  ledgers on both cores. **The OT-303's full tables can load as data:** no packing, no build at
  boot, and the square's tanh fits.
- **P:** DARK REV's 35-word helper relocated to the donor's end, with its three callers
  retargeted, gives one contiguous 1,028-word region.
- **Registration:**
  - ANALOG BD is machine row 5 on FLEX + `AB\x01` in unused NEIGHBOR bytes.
  - MACHINEDRUM / SYNTH / POLY conflict with those seams: a shared registry is needed before an
    OT-303 machine composes with them.
- **SYNTH:**
  - FM on the ColdFire into a FLEX stream.
  - Its pops and crackles were its own limiter and its START/retrigger handling.
  - Since 2.9 it owns the AMP envelope (the DSP sees an always-open AMP), a model for the
    OT-303's VCA against stock AMP.

### DIAG2 on the unit (user, 2026-10-07): the read-back pull, and DIAG3 (built, NOT flashed)

**DIAG2 results** (T2, nothing else running):

| 303 | mode | heard |
|---|---|---|
| 8 | TONE | clean track, clean master |
| 16 | ENG+TONE | distortion on the track, plus a similar, quieter distortion on the master's LEFT channel (heard with the track muted) |
| 32 | RIFF | the same distortion, now rhythmic |
| 48 | WATCH | **clean riff, clean master** |
| 64 | NOPS | steady distortion, then the voice stopped; the rest of the unit was fine |

**Reading:**
- WATCH is RIFF plus ~1,900 cycles of reads before the render, and it is clean. NOPS spends the
  engine's ~6,400 cycles without the engine, and it is dirty. So the cause is **when the call
  ends**, not the engine's arithmetic or its memory traffic.
- This is octabam's read-back pull hazard (`docs/contributing/FAILURE_MODES.md`, "Junk on main R",
  and VOCODER's T1/T5 bursts):
  - after FX2, stock copies each track's block into the read-back buffer (`X:$2600`/`$4600`);
  - the ColdFire's DMA pulls that same buffer during the frame;
  - a call ending inside the pull's window for its track tears the block: junk on the track and
    on the opposite main channel.
  - BusDelay's fix is 8,192 nops before its rts. VOCODER avoids position 0.
- Stock DJ EQ (~4,800 cycles), the tone (~600) and WATCH (~8,500) all land outside the window on T2;
  the engine (~6,400) lands in it.
- NOPS's stop is probably its `rep #400`: a REP is not interruptible, and the host-port DMA
  handlers waited it out.

**DIAG3:** `out/OCTATRACK_OS1.40C_OT303_DIAG3.syx`
(`4d5bfc65d923d416c4634a57e23d754f1ee78e0e33307c117280bde2165a9255`, version `140C_303D3`).
- DJ EQ page 2: BURN on slot 6, 303 on slot 7.
  - 303 = 0: BURN runs before DJ EQ (the burn probe).
  - 303 > 0: BURN runs **after** the render, moving the call's end later.
  - 303 bands: 1–15 TONE, 16–31 ENG+TONE, 32–63 RIFF, 64–127 SQUARE (cost only).
- No long REP in the wrapper (DO loops, interruptible).
- Bench: all modes bit-exact on both payloads; BURN 10 = +240.6 cycles/sample.
- Firmware (ot_emu): inert +13 instructions a call, the engine only on its track, SPRING → stub,
  DARK REV as stock.

**The test:** riff (303 = 40) on T2, sweep BURN 0, 1, 2, …. Record the clean range on the track and
the master. Then T6. WATCH's extra ~1,900 cycles a call is ≈ 120 cycles/sample ≈ BURN 5.

**For the product:** the voice's call must end outside the pull window wherever its track sits and
whatever runs before it. Options:
1. A fixed exit pad, costly. BusDelay pays 2 samples a frame.
2. Wait until a safe point read from a DSP timer: free when the frame is already late.
3. Render the voice where its timing cannot land a copy in the window.

The sweep says how wide the window is.

### DIAG3 on the unit and the first recordings (user, 2026-10-07); DIAG4 (built, NOT flashed)

**DIAG3:**
- **T2:** the riff is never clean. BURN after the render changes nothing, up to 127 with no crash.
  Muted: distortion on the master's left channel, low hiss on the right.
- **T6:** less distorted (crackle). BURN 17 silences the voice and crashes the sequencer. The tone
  with BURN 127 is fine on T6.
- **After a power cycle:** T6 played the riff **clean** at 303 = 32 (dirty after earlier power
  cycles).
- **Stock operations change T2's timbre,** some permanently: transport start, the recorder setup
  menu, recording.

**Recordings** (`~/Desktop/303coretest.wav` = T2, `303coretest2.wav` = T6; 24-bit stereo, 8 s; the
recorder's source was the track; analysis scripts in `tools/ot303/hwrec/`):
- **T6 (clean):**
  - Per-note spectra equal the bench's within 0.2 dB at unity level; the bar period and the
    pitches are equal.
  - It is not sample-identical, as expected: TONE / ENG+TONE (303 swept through 8 and 20) advance
    the riff's events without advancing the voice, so the voice's phase differs.
  - **The engine computes correctly on the chip.**
- **T2 (dirty):**
  - Whole 16-sample frames are junk. Each holds a run of byte values `b << 16`, each byte
    repeated, with L and R offset by one word (`L[i] = R[i-1]`).
  - That is the DSP→ColdFire read-back torn: stock stores each sample as two halves
    (`P:0x55a`, mpy by `$8000` and `$80`), and the ColdFire paired halves from different moments.
  - It is octabam's "Junk on main R" (random full-scale words, the opposite main channel).
  - 194 record-like runs in 8 s, bursty, mostly 1–2 samples or exactly 16.

**Reading (lead, not proven):**
- The pull is DSP DMA channel 1 streaming the read-back buffer from X memory.
- The engine reads X on nearly every cycle and may starve that DMA, so the pull overlaps the
  copies and tears.
- Consistent with:
  - TONE clean (no traffic);
  - WATCH clean (the engine started ~1,900 cycles later);
  - BURN-after no help (it leaves the engine's start unchanged);
  - NOPS dirty (an uninterruptible `rep` delayed the DMA re-arm handlers);
  - session- and operation-dependence (the ColdFire's load moves the pull).

**DIAG4:** `out/OCTATRACK_OS1.40C_OT303_DIAG4.syx`
(`cf9cbb743a2172f79e83707b2c3dab2df75bf487d01455a21d748c7ca737f30c`, version `140C_303D4`).
- 303 bands:

  | 303 | mode |
  |---|---|
  | 1–15 | TONE |
  | 16–31 | ENG+TONE |
  | 32–63 | RIFF with PRE = 303 − 32 (24 cycles/sample a step BEFORE the render; 32 = none) |
  | 64–79 | XREADS+TONE |
  | 80–95 | YREADS+TONE |
  | 96–127 | SQUARE |

- XREADS and YREADS each spend ~400 cycles/sample on reads of the engine's own X or Y block, with
  no arithmetic and no writes, in interruptible DO loops.
- BURN (slot 6) as in DIAG3. Page-2 slot 8 has no enable nibble in DJ EQ's descriptor (the enable
  word covers params 0–7), so PRE rides the 303 knob.
- Bench: all modes bit-exact on both payloads; PRE 10 = +242 cycles/sample. Firmware (ot_emu):
  ALL GOOD.

**The test** (fresh power cycle, T2, then T6):

| result | cause |
|---|---|
| XREADS dirty, YREADS clean | X-bus contention |
| both clean | the engine's writes or its arithmetic timing |
| riff clean from some PRE upward | a start-time window (and its width) |

### DIAG4 on the unit (user, 2026-10-07): it is REP; DIAG5 (built, NOT flashed)

**DIAG4 results:**

| 303 | T2 (core 1) | T6 (core 0) |
|---|---|---|
| 1–15 TONE | clean | clean |
| 16–35 (ENG+TONE, RIFF with PRE 0–3) | junk; junk on the master with T2 muted | 16–31 junk, on the master too; 32–35 a little distortion |
| 36–63 (RIFF with PRE ≥ 4) | clean riff, clean master | 36–49 mostly clean (a couple of ticks) |
| 64–95 (XREADS / YREADS + tone) | clean | — |
| 96+ SQUARE | static, pops, junk on the master | — |
| crash | — | at 303 = 50 (PRE 18): voice silent, sequencer crashed |

**The crash also garbled ColdFire state:** project name garbage, "never saved", set "not mounted".
A power cycle restored everything (RAM only).

**Reading:**
- Memory traffic is innocent: XREADS / YREADS spend the engine's time in X / Y reads and are clean.
- The engine is harmful only in the first ~1,500 cycles of its call: PRE ≥ 4 steps is clean.
- The one thing the engine does that the read loops do not is `rep`. It had three: a 21-cycle
  half-band MAC per sample, and two 24-cycle DIVs in the BLEP. The square uses the BLEP twice per
  cycle, hence its junk.
- **Stock P code on both payloads contains no `rep` at all.**
- A REP is not interruptible. The host-port handlers (IRQA/IRQB `P:0x588/0x597`, which arm DMA0
  from `M_HORX` words) must answer at once. A late answer slips the ColdFire's transfer stream by
  a word, which is:
  - the recorded junk (sample halves one word apart, L/R offset);
  - lasting until something resyncs;
  - and, when worse, ColdFire RAM written out of place (the garbled project name).
- The early window is where the host transfers fall relative to our call.

**DIAG5:** `out/OCTATRACK_OS1.40C_OT303_DIAG5.syx`
(`2d2064655e0330cccd78ef59be31d1cad28b3a57e805ae8f4240de60a676fda1`, version `140C_303D5`).
- The engine's three REPs became DO loops (`do #10` of two MACs + the tail; `do #12` of two DIVs).
  Still bit-exact in all five scenes, 366 / 500 cycles.
- The X/Y read modes are dropped. Bands: 1–15 TONE, 16–31 ENG+TONE, 32–63 RIFF with PRE, 64–127
  SQUARE.
- `hwprobe_image.py` **refuses any REP** in the assembled code.
- Bench all modes bit-exact; firmware (ot_emu) ALL GOOD.

**Rule for every DSP module here:** no REP, ever. Stock has none.

**The test** (fresh power cycle, transport stopped, **do not save the project under a test image**):
1. 303 = 20 (ENG+TONE) and 303 = 32 (RIFF, no PRE) on T2, then T6: clean track, clean master
   (track muted)?
2. Then BURN 0 → 30 at 303 = 32: no crash until a real overrun.
3. Then 303 = 100 (square: silent, but must not junk).

### DIAG5 on the unit (user, 2026-10-08): core 1 clean; core 0 has a second problem; DIAG6 (built, NOT flashed)

**DIAG5 results:**

| 303 | T2 (core 1) | T6 (core 0) |
|---|---|---|
| 1–31 (TONE, ENG+TONE) | clean tone | (as DIAG4) |
| 32–63 (RIFF, PRE 0–31) | **clean riff, clean master, no crash** | 32–41 dirty, junk on the master with T6 muted; 38, 43, 44, 47 near-clean (rare quiet pops); 42, 45, 46 clean; 48 plenty of pops |
| 64+ (SQUARE, silent) | silent, no crash | not reached |
| crash | none | **303 = 49 (PRE 17)**: voice silent, sequencer stuck; no garbled project this time |

**Reading:**
- REP was core 1's whole problem.
- Core 0's remainder needs the engine to run. The tone with BURN up to 127 (DIAG3) never junked
  or crashed on T6, and the engine plus ~400 cycles/sample crashes whether the 400 come before the
  render (PRE 17) or after it (DIAG3's BURN 17).
- So it is neither the call's end time alone nor the cycle budget: the light burn test gave core 0
  ≥ 3,048 spare.
- Stack depth is ruled out: firmware emulator, `--dsp-pcwatch` at the BLEP DIV loop shows SP = 7 on
  both cores, and the host and DMA handlers add at most 2.
- **What only core 0 has:** the ESAI audio DMA. The boot module `P:$3001d` (payload A only; B's stub
  `P:$38000` calls only `$30082`/`$3008a`) arms:
  - DMA2: TX from `X:$8000`, 256 words, `M_DCR2 = $cc6220`;
  - DMA3: RX into `X:$8100–$833f`, `M_DCR3 = $ac59c0`.

  The engine's X block sat in SPRING's X records, `X:$89a4–$8cef`: the same memory block, read and
  written on nearly every cycle. Core 1 runs no ESAI DMA, and T2 is clean.
- **Lead (not proven):** core/DMA contention in that block holds up the DMA controller. The
  host-port DMA (DMA0/1, same controller) then answers late: the same torn transfers as REP. When
  it lands on a host write, the crash follows.
- Also consistent:
  - the tone (two X words a sample there) is clean;
  - DIAG4's XREADS on T2 (core 1) were clean;
  - the PRE map is a scan of the engine across the frame's host-transfer windows.

**DIAG6:** `out/OCTATRACK_OS1.40C_OT303_DIAG6.syx`
(`a7a5a82175ff8123c2c8cca5470cf298eff03403d210dca076af7dbb4a30f00e`, version `140C_303D6`).
- **Payload A (core 0):** the engine's X block runs at `X:$3224–$356f`, inside Analog BD's free
  private region `$2840–$3940`, with no DMA in that memory block.
  - The loader still puts the words in SPRING's records, `xd = $5780` above.
  - On the first call with 303 up, `hq_reloc` (region 2) copies them: run 1 is 216 words, run 2 is
    500.
  - `RFLAG` (the loader's copy of STG, zeroed by the boot loader) marks the copy done.
- **Payload B:** unchanged; the call site is two nops.
- **Band 16–31 is now XHAM+TONE:** the tone, plus `KCNT × 256` X reads in the engine's ORIGINAL
  block, with no engine. On core 0 that is the ESAI DMA's block.
- **Checks:**
  - Bench: all modes bit-exact on both payloads, the relocated block poisoned before the first call.
  - Firmware (ot_emu): ALL GOOD. Core 0's flag and stage confirmed: boot loader writes 0, `hq_reloc`
    writes 1, STG = 2.
  - Stock never writes `X:$3224`/`$3400`/`$356f` on core 0 (BOTLI, 1,500 frames).
  - Wrapper 818/820 words; region 2 174/208.

**The test** (fresh power cycle, transport stopped, DJ EQ on the track's FX1 only, BURN 0, **do not
save the project**):

| step | settings | contention confirmed if… |
|---|---|---|
| 1 | T6, 303 = 32 → 48, one step at a time | clean riff, clean master |
| 2 | T6, 303 = 49 → 63 | no crash |
| 3 | T6, 303 = 20 (XHAM+TONE) | dirty tone, junk on the master |
| 4 | T2, 303 = 20 | clean (no ESAI DMA on core 1) |

If 1–2 stay dirty, the memory block is not the cause and the lead is dropped.

### DIAG6 on the unit (user, 2026-10-08): the X-read test kills core 0; DIAG7 (built, NOT flashed)

**DIAG6 results:**
- **T2 (core 1):** clean. At 303 = 20 (XHAM+TONE) it plays the tone; the riff starts at 32.
- **T6 (core 0):** the tone at 1–15 is fine, so `hq_reloc`'s one-time copy passed. At **16
  (XHAM+TONE)** the voice goes silent at once and the sequencer crashes.
- **Recovery:** only a power cycle undoes the crash. A project reload does not, which fits a stuck
  DSP-side DMA/host state.

**Reading:**
- XHAM runs no engine. It only reads `X:$89c0–$89ff`, on every cycle of its loop, in the memory
  block that holds core 0's ESAI DMA buffers.
- On core 0 that alone is fatal at once. On core 1 (no ESAI DMA) it is harmless.
- So **back-to-back core access to `X:$8000–$8FFF` on core 0 starves the DMA**: the engine's
  partial density gave the junk, and XHAM's 100% gave the crash. The memory-block lead is now
  well supported.
- The relocated riff could not be tested: the band order put XHAM between 0 and the riff.

**Rule for every DSP module here:** keep core 0's working data (anything touched on most cycles) out
of `X:$8000–$8FFF`.

**DIAG7:** `out/OCTATRACK_OS1.40C_OT303_DIAG7.syx`
(`ed314ad40707acdf691a2061f1d488fd3cafee59455cc5c3ef273aa4f4b1c42a`, version `140C_303D7`).
- DIAG6 without XHAM: 1–31 TONE, 32–63 RIFF with PRE, 64–127 SQUARE (cost only).
- `hq_reloc`'s copy is paced to one read of the old block every 4 cycles.
- Bench bit-exact on both payloads; ot_emu ALL GOOD. Wrapper 816/820 words, region 2 161/208.

### DIAG7 on the unit (user, 2026-10-08): relocation changes nothing; DIAG8 measures (built, NOT flashed)

**DIAG7:**
- **T6:** 32–48 dirty riff, with junk on the master when muted (some steps may be a clean riff with
  dirt only on the master; the two are hard to separate by ear). 49 and up still crash.
- **Same as DIAG5:** the X block's place does not matter for the riff. The memory-block lead is
  dropped for the riff.
- **What still stands:** XHAM, a 100%-dense read loop with no engine, killed core 0 at once (DIAG6).
  So dense memory traffic on core 0 is harmful in some way, whatever the address.
- **Facts the next step has to explain:**
  - only memory-touching code junks core 0; nops (BURN, PRE) and the tone do not;
  - the crash comes at a fixed amount of extra time after the engine runs;
  - only a power cycle recovers.
- **Leading hypothesis:** core 0's memory accesses cost far more on the chip than the cycle table
  says (DMA contention; stock leaves the core's SR CP bits at 0, the lowest core priority). If
  true, the engine on core 0 costs ~2,700 cycles/sample, and PRE 17 crosses the budget.
- **Against it:** DJ EQ ×8 cost only ~14% more on core 0 in the burn test. So the penalty would
  have to depend on the code or the region. Hence a measurement, not another guess.

**DIAG8:** `out/OCTATRACK_OS1.40C_OT303_DIAG8.syx`
(`21b91d89d0d5ad5fd52a51fa4f84b965b37423f898733ef2c53b59ef5994e5ff`, version `140C_303D8`).
- **303 bands:** 1–31 TONE; 32–63 plain RIFF (no PRE, so no crash band); **64–127 METER** (the
  square is gone).
- **METER** (`hq_meng`, region 2):
  - each render restarts core timer 0 (`M_TCSR0`/`TLR0`, CLK/2, unused by stock on both payloads);
  - it writes `TCR0 << 7` as the render's first sample, and `-(KCNT << 16)` in the rest. The ruler
    makes the reading gain-proof.
  - mode = (303 − 64) >> 3:

    | 303 | mode | what runs |
    |---|---|---|
    | 64 | 0 | the engine |
    | 72 | 1 | an empty loop (3 nops) |
    | 80 | 2 | X reads, the engine's block |
    | 88 | 3 | X reads, the loader's copy (`X:$89c0` on A) |
    | 96 | 4 | X reads, stock's instance state `X:$5900` |
    | 104 | 5 | Y reads, the engine's state `Y:$f40` |
    | 112 | 6 | Y reads, an FX1 slot `Y:$1000` |
    | 120 | 7 | Y reads, the coefficient table `Y:$bc0` |

    Modes 1–7 run 32 × KCNT iterations of 3 instructions (1/3 density, unlike XHAM's 100%).
    Expected on the cycle table: mode 1 ≈ 192 cycles/sample, if probe 57's 2 cycles/instruction holds.
- **Decoder:** `tools/ot303/hwrec/meter.py REC.wav` prints the median cycles/sample per stretch of
  the recording. Tested on a synthetic recording with gain 0.5 and a junk frame.
- **Checks:** bench all modes run and return with registers kept, the riff and tone bit-exact (the
  emulator's timer is too coarse to check the counts); ot_emu ALL GOOD. Wrapper 818/820, region 2
  207/208. The tone moved into region 1. `tools/dsp_xasm.py` learned the timer register names.

**The test:** a track recording of T6, then of T2, stepping 64 → 120 by 8 with ~3 s each.
- The core 0 / core 1 ratio per mode tells whether memory traffic costs more on core 0, and where.
- Mode 0 against the bench's 366 gives the engine's real cost on each core.

### DIAG8 on the unit (user, 2026-10-09): the METER readings

The recordings are `out/ot303/hwprobe/hw/diag8_t6.wav` and `diag8_t2.wav` (from `~/Desktop/DIAG8*.wav`).
- Track recordings, 24-bit, about 48 s each, 303 stepped 64 → 120. The transport was stopped, so
  every render was 16 samples.
- Every render decoded on both tracks: 132,996 on T6 and 136,647 on T2. L = R throughout, and the
  ruler read the gain as exactly 1.

| | T6 (core 0) | T2 (core 1) |
|---|---|---|
| mode 0, the engine (riff) | **426.2** cycles/sample (worst render 451.6) | **426.2** (451.6) |
| modes 1–7: 96 instructions/sample, none / X / Y reads | 99.2–100.0, all modes alike | 97.7–100.1, all modes alike |

**What this settles:**
- **The engine costs 426 cycles/sample on the chip, on both cores:** 1.16× the cycle table's 366,
  inside the VOCODER's 1.12–1.25 margin.
- **Memory reads cost the same as nops on both cores, in every region tested.** There is no
  core-0 memory penalty, and the cycle budget is nowhere near: the engine plus PRE 17 is ~850 of
  ~3,120.
- So **the crash is not running out of time.** The cost-penalty hypothesis is dead.
- **T6's track signal was bit-clean for the 5 s the engine ran (mode 0):** not one torn frame.
  - The riff's dirt that the user hears may therefore not be in the track's read-back at all, but
    on core 0's audio output: core 0 alone runs the ESAI DMA to the DACs and mixes the master.
  - This matches the "dirt on the master with T6 muted" every round, and the user's own note that
    some steps may be a clean riff with dirt only on the master.
- **Next, decisive and with no flash:** a track recording of T6's riff (303 = 40) while it sounds
  dirty.
  - Clean recording → the dirt is downstream: core 0's mix/ESAI path, starved or disturbed by the
    engine's memory traffic. XHAM's instant crash (100% X reads, 4,096 cycles at a time) is the
    extreme case.
  - Torn recording → the read-back after all.

**The T6 riff recording** (user, 2026-10-09; `out/ot303/hwprobe/hw/diag8c_t6_riff.wav`, DIAG8, 303 = 40,
recorder source T6, 12 s). The riff sounded dirty and the master was dirty with T6 muted.
- **The recording is clean:** L = R in every sample.
- **Its click statistics match the bench render's:** median second difference 4,494 vs 4,644;
  outliers 5,358/s vs 5,455/s (the saw's edges); max/median 1,140 vs 1,165; rms 0.053 vs 0.054.
- **No junk words:** 4 of 377,906 are multiples of 65,536, which is chance.
- **So T6's track data reaches the ColdFire intact. The dirt is downstream,** in core 0's
  master/output path: the master mix, the ColdFire→core 0 return block `X:$4400`, or the ESAI DMA.
- **Next, no flash:** a recorder on SRC3 = MAIN with T6 muted (nothing else playing).
  - A dirty recording → the master's digital mix is corrupted (the `X:$4400` transfer, or
    core 0's mix).
  - A clean recording while the speakers are dirty → the ESAI output DMA (starved, like XHAM's crash).

### The MAIN recording, T6 muted (user, 2026-10-09), and DIAG9 (built, NOT flashed)

**The recording:** `out/ot303/hwprobe/hw/diag8d_main_t6muted.wav`, DIAG8 at 303 = 40, recorder
SRC3 = MAIN, T6 muted, nothing else playing.
- **It is not silent.** 28.8% of the 16-sample frames carry audio, mostly every other frame
  (`#.#.#...#.#...`), aligned to frame boundaries. L = R in 99.9% of samples.
- **The audio is the muted riff itself.** Its note sequence per quarter-step (64, 129, 86, 107 Hz,
  rests where the pattern rests) matches T6's track recording.
- **Its level is in the range of a normally mixed track:** per leaked frame ~0.005 rms, against
  the track tap's 0.053.
- **So on some frames core 0's master mix treats T6 as unmuted:** it uses mix parameters other
  than the current frame's. The frame gating is the "dirt".
  - With T6 unmuted, the same wrong frames change its gain, which explains why the riff itself
    sounds dirty while its track data is perfect.
  - With the tone, or an unmuted constant level, wrong-parameter frames are inaudible. So the
    tone + BURN tests could never show this.
- **Lead:**
  - The ColdFire's per-frame host transfers into core 0 (records `X:$080`, the `x:$41f`
    ping-pong, the `X:$4400` return block) arrive late or torn when the engine's dense memory
    traffic holds up DMA channel 0/1, so the mix reads stale parameters on some frames.
  - It fits: only memory-dense code harms (engine, XHAM; never nops); the X address doesn't
    matter; the riff's timing (PRE) moves the effect around; XHAM (100% X, ~4,000 cycles) kills the
    protocol outright (a power cycle is needed).
  - Core 1's transfers do not feed the master mix.

**DIAG9:** `out/OCTATRACK_OS1.40C_OT303_DIAG9.syx`
(`91aa7f8c54a81af375b024357379088f6f2f335c6e3ca3a08c7010c1861cfc86`, version `140C_303D9`).

| 303 | mode |
|---|---|
| 1–31 | TONE |
| 32–47 | plain RIFF |
| **48–63** | **YIELDING RIFF** |
| 64–71 | METER plain |
| 72–127 | METER yielding |

- **The yielding riff** (`hq_yield`):
  - one sample at a time;
  - before each, a bounded poll (≤ 512 × 4 instructions) of `M_DSTR` until DTD0 and DTD1 are both
    set, i.e. no ColdFire block in flight. Both host channels run DTM 001: DE and DTD clear for the
    length of a block.
  - `brkeq` leaves the poll; `dsp_xasm` knows `M_DSTR`.
- **Dropped:**
  - DIAG6/7's core-0 X relocation (it changed nothing; `xd = 0` again);
  - the METER's calibration modes (memory reads cost nops on both cores, settled).
- **Checks:** bench bit-exact for the plain and yielding riffs on both payloads (the yielding riff
  is +128 cycles/sample on the cycle table: per-sample calls); ot_emu ALL GOOD, the engine running
  on core 0 in both riff modes.

**The test** (T6 muted, master):
1. 40 → dirt expected.
2. 56 → silence if the lead holds.
3. Then unmuted.

### DIAG9 on the unit (user, 2026-10-09), and DIAG10 (built, NOT flashed)

**DIAG9:**
- **The yielding riff (48) silenced the voice and crashed the sequencer at once.** The likely reason:
  DSTR's DTD0/DTD1 are not both set as often as assumed, so each sample polled its full 512 times
  (~2,500 cycles) and core 0 overran.
- **Mute checks on DIAG9, T6 muted:**
  - 303 = 8 (tone): master **silent**.
  - 303 = 8 with BURN 10/20/30/40 (up to ~960 cycles/sample, no memory work): master **silent**.
  - 303 = 40 (riff): the usual dirt.
- **So the master leak needs the engine's work, not time and not the wrapper.**
- **What the DSP56300 Family Manual says** (local copy `out/ot303/refs/56300fm.pdf`):
  - §2.3.2: DO loops are interruptible; only REP is not.
  - §10.3.2: if the core and a DMA channel want the same internal memory partition, **the core
    always wins**, and the DMA waits until the core leaves that partition alone for a cycle. The
    partition is 256 words on older parts; NXP's engineering bulletins give 1,024 words on HiP4/HiP7
    derivatives (the DSP56721's own size is unconfirmed).
  - The DSP56721 errata (ES151–153) say nothing about loops or DMA.
- **Emulator write map** (BOTLI, 600 frames, stock): stock writes Y only below `$800` on both
  cores, so the engine's Y blocks are not shared. Core 0 alternates its buffer sets `X:$2000–$25ff` /
  `X:$4000–$45ff` frame by frame (ping-pong).

**DIAG10:** `out/OCTATRACK_OS1.40C_OT303_DIAG10.syx`
(`d17059df20144ba505011e9f88be1d1897c00dea614849703dd9c0dff7627af3`, version `140C_303DA`).
- **303 bands:** 1–31 TONE; 32–63 plain RIFF; **64–127 STRESS + TONE**.
- **STRESS:** a workload of `n7 × 128` iterations of a three-instruction body, run once per call
  before the tone (~400 cycles/sample, like the engine). Mode (303 − 64) >> 3, safest first:

  | 303 | workload |
  |---|---|
  | 64 | `div`, no memory |
  | 72 | `mac`, no memory |
  | 80 | Y reads |
  | 88 | Y writes (`Y:$ff0`, 16) |
  | 96 | X:Y parallel reads |
  | 104 | `mac` + X:Y reads (the half-band's shape) |
  | 112 | the engine itself (no events) |
  | 120 | X reads (the engine's X block) |

- **The detector:** T6 muted, listen to the master. Any tone or crackle means the workload breaks
  core 0's mix.
- **Dropped:** the meter, the yielding riff, the per-call TINC store (the loader presets it).
- **Checks:** bench bit-exact for every band on both payloads, every mode ~427–430 cycles/sample;
  ot_emu ALL GOOD.

### DIAG10 on the unit (user, 2026-10-10), and DIAG11 (built, NOT flashed)

**DIAG10:**
- No tone or crackle leaked at any STRESS step (64–127).
- **But the riff at 32 crashed the sequencer first, so all STRESS results were taken with the
  sequencer down: void.** With transfers frozen, the master may simply have stayed muted.
- The knob kept changing the sound after the crash. So the DSP and the knob → DSP parameter path
  stayed alive; it is the sequencer side that stops.
- **The riff crash is random in time:** 49 (DIAG5, PRE 17), 48 (DIAG9, assumed to be the yield),
  32 (DIAG10). It comes after some seconds of riff, not at a knob value.
  - So DIAG5's "crash at PRE 17" and DIAG9's "yield crash" may both be this.
  - The engine without riff output (DIAG8's METER mode 0, DIAG10's 112) never crashed.

**DIAG11:** `out/OCTATRACK_OS1.40C_OT303_DIAG11.syx`
(`0550c63241bde2493dd40782ca8f243d6400620c9853a16903f927080d7d2f1a`, version `140C_303DB`).
- **The 303 knob, safest first** (`hq_mode` sets D_BAND once per call):

  | 303 | mode |
  |---|---|
  | 1–15 | tone |
  | 16 / 24 / 32 / 40 | STRESS + tone: Y reads, Y writes (`Y:$ff0`), mac + X:Y reads, the engine without events |
  | **48–71** | **ENG + TONE: the riff's whole work, events included, the tone heard** |
  | **72–87** | **RIFF / 8** |
  | **88–103** | **RIFF** |
  | 104–127 | X reads + tone (DIAG6's crash shape, three-instruction body) |

- **BURN (slot 6) is inert.** Its code went for space, along with the X:Y-only stress mode.
- **The question:** does the leak/crash need the riff's *work* (48) or its *sound* in the track
  output (72 / 88)?
  - DIAG8's meter ran the same work with other output and never crashed.
- **Checks:** bench bit-exact for every band on both payloads (riff / 8 = `asr #3` of the twin);
  ot_emu ALL GOOD.

### DIAG11 on the unit and the track tests (user, 2026-10-10); DIAG12 (built, NOT flashed)

**DIAG11, T6 muted:** 1–24 clean; 25–39 loud dirt; 40 quieter; 41–47 loud; 48–71 quieter; 72–87
very quiet riff-pattern dirt; 88–103 louder riff-pattern dirt; 104–127 loud. No crash.

**The crash, described:**
- The first or second step LED lights yellow.
- STOP clears it and PLAY relights it, but the sequencer never advances past step 1–2.
- T6 is silent.
- This is octabam's documented "core 1 killed at project load (sequencer stuck on step 1, AED
  preview silent)", which they saw when heavy compute sat in core 0's handshake path.

**Track tests (DIAG11, riff at 88, one DJ EQ at a time):**

| track | result |
|---|---|
| T5 | silent at first. After sweeps up into 104+ and back: **L only, then R only, then stereo, then silent**; each state persists until the next disturbance. Muted: sparse pops on L / R / both / none, matching the state. |
| T7 | like T6 (dirty) |
| T8 | **can be 100% clean (stereo, silent master when muted)**; sweeps flip it into the same L / R / stereo / none states, with no discernible pattern |

**Reading (with the user's push: "T2 is clean — what is different on T6?"):**
- The engine can run fully clean on core 0 (T8), so cost and arithmetic are excluded.
- Whether it is clean depends on where in core 0's frame the work lands: T5 and T8 are clean until
  disturbed, T6 and T7 are dirty from the start. This matches DIAG5's PRE map (some delays clean).
- The damage is a **persistent** misalignment in core 0's per-frame handoff (silent / L / R / stereo),
  set by memory-heavy work and flipped only by the next disturbance.
  - So DIAG10/11's per-band verdicts are unreliable: the first disturbance carries over into
    every later band.
- **Core 0's frame, from the code:**
  1. The wait at `P:$4a` polls `M_DSR2` (the ESAI TX DMA source) for `$80f0` / `$8070`.
  2. It picks the `$2xxx` or `$4xxx` buffer set, patches the host masks and sends the ping.
  3. It unpacks the ColdFire's return block (`x:$204`, 512 words, all eight tracks).
  4. It mixes into the ESAI TX half (`x:$203` = `$8000` / `$8080`) with the main ramp.
  5. It copies the TX half into the read-back's upper 256 words (what the recorder's MAIN reads).
  6. It clears the DMA2 watchdog `x:$20f`, writes the staging back to `X:$30000`, then runs T5–T8.
  7. After each track it copies the track into the read-back at `P:$55a`.
- **Most likely mechanism:**
  - DSP56300 FM §10.3.2: on a shared internal partition the core wins and the DMA waits.
  - The DSP5672x family has a "DMA stall monitor" for exactly that kind of stall.
  - Core 0 alone runs ESAI DMA (`X:$8000–$833f`) and its host DMA ping-pongs between `X:$2400–$28ff`
    and `X:$4400–$48ff`.
  - Our X working set sat at `$89a4` (ESAI's 8K block) and in DIAG7 at `$3224` (the `$2xxx` host
    buffers' 8K block). Both are DMA blocks, which is why the relocation "changed nothing".
  - Unknown: the DSP56721's private-memory partition size (the RM was not retrievable;
    `out/ot303/refs/` holds the 56300 FM and AN3653).
- The emulator's `--audio-out` capture is all zeros in this build (stock too, BOTLI and MMTESTDT), so
  no emulator reproduction.

**FX1 instance blocks on core 0** (`--dsp-pcwatch` at `hq_entry`, `r7`): T5 `$6100`, T6 `$6400`, T7 `$6700`,
T8 `$6a00`. Stock tables live at `$6c00–$7a91` (TABLES.md). With 8 DJ EQs, DJ EQ writes `$6a10–$6a41`
(its T8 block, `P:$1e98`); `$6a50–$6bff` are unwritten in that run.

**DIAG12:** `out/OCTATRACK_OS1.40C_OT303_DIAG12.syx`
(`aa516fb9e44f10cbfd0da6fe6d50240c80d7da2971ab07644c5f7921a3d2ccda`, version `140C_303DC`).
- **Payload A's run 1** (the engine's X working set and the wrapper's words, 216 words) runs at
  `X:$6424–$64fb`, inside **T6's own FX1 instance block** (`$6400–$64ff`): a partition of stock tables
  and FX state, with no DMA.
  - The loader still places it in SPRING's records (`xd = $2580`); run 2 (b0/kp, read only while
    the tables build) stays at `$8afc`.
  - `hq_reloc` copies run 1 when `SIGA` (`X:$6404` = `r7 + 4`, a word DJ EQ writes whenever it runs)
    is not `$5a5a5a`. So a stretch at 303 = 0 is recovered by a re-copy and a table rebuild.
- **For T6 only.** Payload B is unchanged.
- **303:** 1–47 tone; 48–71 ENG + TONE; 72–87 riff / 8; 88–103 riff; 104–127 X reads (now in the new
  block) + tone. BURN is inert.
- **Checks:** bench bit-exact for every band on both payloads (run 1 poisoned before the first call);
  ot_emu: T6's STG in the new block reaches 2 under the firmware; verify ALL GOOD.
- **The test:**
  - T6 riff at 88, unmuted and muted, 30 s+.
  - Then sweep to 120 and back several times: does the state still flip?

### DIAG12 on the unit (user, 2026-10-11): T6 CLEAN — the cause was DMA memory contention

**Results (T6, DJ EQ FX1 only, after a power cycle):**
1. 303 = 88, unmuted, 30 s+: **clean stereo riff**.
2. T6 muted: **master silent**.
3. Swept to 120 (X reads, now in the new block) and back several times: **no flips, stereo every
   time**.
4. 48 (the riff's work, tone heard) muted: **silent**.

**Conclusion:**
- On core 0, the DMA traffic is the ESAI audio DMA (`X:$8000–$833f`) plus the ColdFire's host
  transfers (`X:$2400–$28ff` / `$4400–$48ff`, ping-pong). Dense core access to an internal memory
  partition that DMA uses stalls the DMA: DSP56300 FM §10.3.2, the core always wins.
- The stalls slip the per-frame handoff between core 0 and the ColdFire into persistent wrong
  states (silent / L / R / stereo, mute leaks), and in the worst case lose it: the sequencer stuck
  on step 1–2 until a power cycle.
- The engine's X working set had sat in a DMA partition both times: SPRING's records at
  `$89a4` (ESAI's block), then `$3224` (the host buffers' block).
- Moved to the host's own FX1 instance block (`$6400`, tables and FX state only), it is clean.
- Core 1 runs no ESAI DMA and its host buffers are not where our block was, hence T2 clean all along.

**Rules from here (every DSP module in this repo):**
- **No REP** (DIAG4).
- **Keep dense working data out of any memory partition a DMA uses.** On core 0 that means
  `X:$8000–$8FFF` and the `$2xxx` / `$4xxx` host buffer blocks. Use the host's own FX instance block
  (`r7`) or another partition with no DMA. Y has no DMA on either core.
- The partition size of the DSP56721's private memory is still unconfirmed (no RM). The safe
  reading is the whole 8K block.

**Open before the product:**
- **A soak test:** the riff for 10+ minutes on T6 (and T2), transport running with other tracks
  playing. The random riff crash of DIAG5/9/10 is presumed the same mechanism, but octabam's rare
  events needed 10-minute takes.
- **The product placement:** the working set addressed from `r7` (any track, any core) instead of
  fixed addresses, or a fixed no-DMA region per core.
- **Then the BURN cost measurements** (heavy configurations) that were pending since step 3.

### The soak (user, 2026-10-11) and DIAG13 (built, NOT flashed)

**DIAG12 soak:** a 10-minute run on T6 was clean, and T1 and T5 also ran clean, with no crash at any
time.
- So the random riff crash (DIAG5/9/10) was this same mechanism.
- T5 was clean because payload A's block sat in T6's (empty) FX1 instance block.

**Partition size, bounded by the unit:**
- `$3224` (shares a block with the `$2xxx` host buffers) failed, so blocks are ≥ 4K.
- `$6400` (vs `$4400–$48ff`) worked, so blocks are ≤ 8K.
- **4K or 8K words.**

**DIAG13:** `out/OCTATRACK_OS1.40C_OT303_DIAG13.syx`
(`70395721e32a7366a801b17322e46e8594ccfe470314699fcca1d5198d8ed4f1`, version `140C_303DD`).
- **Run 1** (216 words) at **`X:$7b24–$7bfb` on both cores.** That is stock's unreferenced `X:$7a92–$7fff`
  (DSP.md; never written in the BOTLI write map), in a partition of stock tables only, with no DMA
  under either size.
  - `hq_reloc` copies it once from SPRING's records (A `xd = $e80`, B `$940`).
  - `SIGA` `X:$7b04` marks the copy.
  - Run 2 stays in SPRING's records (read only while the tables build).
- **Any track, either core;** one engine per core.
- **303:** 1–31 tone, 32–127 riff; 0 = stock DJ EQ with BURN before it (the burn probe).
  **BURN (slot 6) is back:** 24 cycles/sample per step, after the render when 303 > 0.
- **Checks:**
  - bench bit-exact on both payloads (tone and riff, BURN 0/10/20);
  - ot_emu: STG = 2 at `X:$7bb0` with the riff on T2 (core 1), T5 and T7 (core 0); verify ALL GOOD.

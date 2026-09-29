# repitch-kyoti — fidelity scope: making RPS9 and RPSP behave like the real machines

Written Session 109 (2026-09-28). **Rev 11 implements it; rev 12 corrects its tone; rev 13 fixes RPSP's render; rev 14 makes RPSP channel 1/2 and fixes the trig crack — see the status sections.** This scope follows the
shipped rev 10 (`eb8f022`: RPCH / RPS9 / RPSP, hardware-confirmed working) and the
listening render that showed how little RPS9 changes (`tools/repitch_dsp_listen.py`).
It supersedes `REPITCH_KYOTI_SCOPE.md` §2's machine descriptions, which were wrong
about the Akai (see §2 below).

Markers: ✅ **stated by the manufacturer** (service manual, schematic, operator's
manual), 🟡 **derived by us** from manufacturer data (arithmetic, circuit analysis,
engineering inference; says how), ❓ **not documented anywhere we found**, 📎 secondary
source (forum, press), used only where flagged.

---

## ⏩ Implementation status — rev 14 BUILT (Session 112, 2026-09-28): channel 1/2, full tables, the trig crack

**Built, verified in emulation, NOT flashed** (rev 13 is on the unit). Detail: NOTES "Session 112"
and "Session 112 continued"; the channel 1/2 design: `REPITCH_SP_CH12_SCOPE.md`.
- **RPSP = the SP-1200's channel 1/2**: rev 13's staircase through an SSM2044-style 4-pole
  (resonance 0) whose cutoff the track's own AMP envelope opens (envelope A). `RPK_CH12=0`
  builds rev 13's raw 7/8 sound (with the other two changes).
- **Full-fidelity tables again**: RPS9 = rev 12's exact table (its output is bit-identical to rev
  12 except the samples right after a trig), RPSP = rev 13's retuned 12-tap design, all 16
  half-rows each — stored in SPRING REVERB's orphaned X data, copied to Y at first use.
- **The crack at each trig start (user report on rev 13) is fixed**: at a trig the ring holds stale
  audio behind the new sound, which RPS9/RPSP (reading 8–13 frames behind) replayed for their first
  8–12 samples at full AMP; the frames behind a new sound are now silence. RPCH never had it.
- DARK REVERB works again (rev 10–13 overwrote a routine it calls inside SPRING's module).
- Cost: RPS9 61 DSP instructions/sample, RPSP ≈ 173. P cave 400 words; Y `$A00-$F8F`.
- **Rev 14 flashed ("very nice"). Rev 15** (built, not flashed): the trig fix also covers trigs landing
  exactly on a frame boundary (rev 14 missed them — a pop on step 2 of every second cycle in a
  16-trig pattern), and channel 1/2's capacitor now updates once per frame. Cave 403 words. QUAN pressed + turn =
  one ratio per detent (3× the plain turn). `…_REV15.syx` sha256 `47c99c75…`.

## ⏩ Implementation status — rev 13 BUILT (Session 111 cont., 2026-09-28): RPSP's band-limited render

**Built, verified in emulation, NOT flashed** (rev 12 kept as a separate file for an
A/B). Rev 12 = rev 11 without the output filter; that exposed the box render's
folded images (a staircase at 26.04 kHz averaged per 44.1 kHz period rejects its
images above 22 kHz by only 6–8 dB, so they fold to 18.06k − f: −23…−35 dB on tones).
Rev 13 renders the staircase through a 10-sample band-limited kernel (flat to 19 kHz,
18k −1.2 / 20k −4.8 / 21k −7.6 dB, ≥ 42 dB from 26 kHz; exact at any tick time via a
161-point table of its step response). Folds now −50…−85 dB on tones, −44…−47 dB on
drums/hats; residual: 0–4 kHz content's images between 22 and 26 kHz fold to
18–22 kHz at ≲ −34 dB. Cost: RPSP 125–137 DSP instructions/sample (rev 12: 68–73,
rev 11: 114); latency +4.5 samples (RPSP at 1/1: 11.85 samples = 269 µs). To fit, the
virtual-ADC tables are stored as 9 of 32 rows (≤ −54 dB from the designed rows);
cave 671 words; Y now `$A00-$F40`. Detail: NOTES "Session 111 continued".

## ⏩ Implementation status — rev 12 BUILT (Session 111, 2026-09-28): the tonal correction

**Built, verified in emulation, NOT yet flashed.** Rev 11 is on the user's MKI and
working, but by ear both modes were duller than rev 10 and RPSP duller than the
other modes. Measured against rev 11's own model that was partly by design (RPS9's
32 kHz virtual rate) and partly a fault (RPSP: an 8-tap record kernel rolling off
2–3 dB early, the box render's sinc(f/44100) droop stacked on top, and channel 5's
filter removing the staircase images above 13 kHz). Rev 12 changes exactly three
things (NOTES "Session 111"):

- **RPSP is heard as the raw outputs 7/8** — no output filter (Q2 answered: 7/8,
  the community's usual "dirtiest drums" choice; ch 3–6 stay modelled in
  `tools/repitch_engine_model.py` for a future selectable channel). The DSP's
  filter stage is gone and RPSP got cheaper.
- **RPSP's virtual ADC = 12 taps, least squares** (no windowed sinc): flat to
  10 kHz, a 7-pole (42 dB/oct, E-mu's own description) shape through the transition,
  ≥ 40 dB rejection from 17.5 kHz, and the box's droop folded out. At 1/1:
  kernel × box 8 kHz +0.3 dB, 10 kHz −1.4 (worst phase), 18–22 kHz −59.5 dB; overall
  (× the real 26.04 kHz staircase droop) 5k −0.6, 8k −1.1, 10k −3.5, 12k −9.0,
  13k −13.2, 15k −25.6 against the estimated real SP out 7/8 row −0.5 / −1.5 / −3.4 /
  −9.4 / −14.4 / −26.4.
- **RPS9 records at a virtual 40 kHz** (16 kHz bandwidth, the S900's maximum;
  Q1 answered for now: 40 kHz fixed): 16 taps fitted by least squares to the
  MF6CN-50's 6th-order Butterworth at 16 kHz, within 0.15 dB of it to 18 kHz on
  every phase. (Akai's fixed 18 kHz 2-pole after the MF6CN-50 is not modelled.)

Everything else is rev 11's. Cost (full firmware, per playing pass): RPSP 1086–1174
instructions = 68–73 per sample (rev 11: 1823 = 114), RPS9 935 = 58 (rev 11: 936).
Cave 674 of 675 words. **Known and now audible:** the box render folds the
staircase's images above 22 kHz back into the band (a 3 kHz tone at 1/1 leaves a
−27 dB component at 15.06 kHz; 5 kHz → −25 dB at 13.06 kHz). Rev 11's channel 5
filter masked this by 6–16 dB; a real SP recorded at 44.1 kHz does not have it.
A band-limited step render is the fix, and needs cave space rev 12 does not have.

## ⏩ Implementation status — rev 11 BUILT (Session 110, 2026-09-28)

**Built, verified in emulation; flashed and working on the MKI (reported before
Session 111). Superseded in tone by rev 12 above.** Gate 0 was answered in
`ot_emu` against the real firmware and octabam's hardware measurements, and
tiers 1–2 of both modes were built in one engine. What changed from the plan below,
and why (details: NOTES "Session 110"):

- **RPS9 is not a literal variable-clock emulation.** Rendering a 32 kHz
  staircase at 44.1 kHz folds its ultrasonic images into the audible band
  (−25 dB at 18 kHz for a 6 kHz tone), which the real Akai never did — its
  MF6 output filter removes them. What leaves an Akai is the source band-limited
  by the **record** filter, stored at 12 bits, pitched cleanly. RPS9 is exactly
  that: a 16-tap polyphase "virtual ADC" shaped like the MF6CN-50 (6th-order
  Butterworth @ 12.8 kHz = a 32 kHz sample; within ~1 dB to 12 kHz, −50 dB at 18 kHz)
  with 12-bit output. Q1 is therefore answered for now with **32 kHz fixed**.
- **RPSP = the virtual sampler as scoped**, one tick per output at most (the
  26.04 kHz clock is slower than 44.1 kHz): SP grid via the 7-bit-style
  accumulator (exact ratios, Q4), 8-tap virtual ADC (the record filter, ~4th
  order @ 11 kHz), 12-bit, box-rendered staircase, then **channel 5's** filter
  as a digital 3-pole fitted to the schematic's 5-pole within 0.5 dB to 18 kHz
  (Q2: channel 5 fixed for now). Q3: 1/2 and 2/1 allowed.
- **No pre-filter over the ring, no tracking post-filter**: the virtual ADC
  is evaluated only where a stored sample is needed, so the cost does not
  grow with pitch and the ring is never written. RPCH is untouched stock.
- **Cost (instruction counts, ot_emu full firmware):** RPSP ~113 instr/sample,
  RPS9 ~61, per track in that mode, replacing stock's ~10. On octabam's
  measured ~2 cycles/instruction that is ≈ one FX1 FILTER (192 cycles) per RPSP
  track, half that per RPS9 track. Four RPSP tracks on one core (T1–4 or
  T5–8) with a heavy reverb is the case to watch on hardware.
- **Memory:** P = the last 667 words of SPRING's module (SIDECHAIN3's first
  388 still free); Y:`$A00-$DFF` (octabam: free on stock; SC3 keeps `$800-$9FF`).
- **Verification:** `tools/repitch_dsp_engine_check.py` — 80/80 bit-exact
  (4 signals × 5 ratios × 2 modes × 2 cores) against the model's integer twin,
  with undelivered ring frames poisoned; mode switch away and back bit-exact;
  full firmware in `ot_emu` with the part's TSTR set: tag on every playing
  pass, levels equal to RPCH, no clicks. Listening pack: `tools/repitch_dsp_listen.py`.

## 0. Summary

We went looking for how the machines actually change pitch, and found it in E-mu's
and Akai's own service documentation. Both machines turn out to be
**"a sample stored at one rate and played back as a staircase at another,
then analog-filtered."** They differ only in which rate is fixed:

| | stored at | played back at | how pitch changes | after the DAC |
|---|---|---|---|---|
| **SP-1200** | 26.04 kHz, fixed | 26.04 kHz, fixed | skip or repeat stored samples (7-bit accumulator) | per-channel: dynamic SSM2044 (1-2), fixed 5-pole LPF (3-6), none (7-8) |
| **S900/S950** | user-chosen rate (bandwidth) | that rate × pitch ratio, per voice | the voice's DAC clock is sped up or slowed down; **every stored sample plays exactly once** | per-voice 6th-order Butterworth, switched-capacitor, own programmable clock |

Neither machine interpolates. What we ship today does: RPS9 is the OT's linear
interpolator + 12-bit storage, and RPSP is zero-order hold + 12-bit, both running at 44.1 kHz.
So **the fidelity work is one new DSP engine, a "virtual sampler", run with two
parameter sets**. The shared engine is cheaper to build and verify than two separate
ones.

**Gate 0 is the whole risk.** The engine needs (a) cycles we have never measured and
(b) a few words of memory per voice that survive between blocks, which the stock voice
kernel does not have. Nothing below can be committed to until both are answered (§6).

---

## 1. What the manufacturers' documents say

### 1a. E-mu SP-1200

Sources: **SP-1200 Service Manual (E-mu, 1987)**: Theory of Operation (pp. 40–55) and
schematics DOC# SK103 pp. 15–17 of 18; **SP-1200 Owner's Manual** (Anderton, E-mu PN FI 332).

- ✅ **One playback rate.** "Sample period is fixed at (1/26.04) kHz"; "SP1200 has
  only one playback rate, 26.04 kHz" (MIDI sample-dump section).
  🟡 26.04 kHz = the listed 20 MHz crystal ÷ 768 (26,041.7 Hz).
- ✅ **12-bit linear** storage and DAC: "The DAC is a standard 12 bit linear device."
  Sampling is successive-approximation through that same DAC.
  🟡 SAR conversion rounds toward the lower code (floor), which is what our
  `and #$fff000` does: **our truncation is the right kind**.
- ✅ **Pitch = drop/repeat through an adder with a carry.** Quote: *"On each channel's
  cycle the appropriate pitch number is loaded into the Increment Latch. This number is
  added to the previous value in order to generate a carry value of either 0 or 1. A
  carry of 0 will cause the same sample to be played twice. A carry of 1 will increment
  the sample's address. If A0 is set to a 1 and the carry out of the lower adders is
  always 1, then the address will be incremented by 2 … an octave higher. To shift
  down an octave, the A0 bit is set to 0 and the increment value is set so that the
  carry out … will always be 0 … Intermediate pitch values (neither 0000000 or
  1111111) will cause alternating 0 and 1 values at the carry out … The CPU only sends
  values to the µController pitch register which create semitone tuning intervals."*
  🟡 So the pitch word is **A0 (whole part) + a 7-bit fraction**. Speed = A0 + N/128,
  and the skip/repeat pattern is exactly that of a 7-bit phase accumulator.
- ✅ **Tuning range ±a fifth, in semitones** (owner's manual: "individual tuning (plus
  or minus a fifth)"; MIDI pitch keys 69–83 = 15 notes).
- ✅ E-mu's own description of the artifact: *"due to the nature of the SP-1200's
  tuning change hardware … SP-1200 tuning creates more of a ring modulation type of
  effect"* (owner's manual, tuning cymbals).
- ✅ **Output stage.** 8 channels share the DAC, de-multiplexed by a 4051 into
  per-channel sample/holds ("caps and bi-FET op amps"), so each channel is a **26.04 kHz
  staircase**. Level is set by an **8-bit multiplying DAC on the main DAC's reference**,
  i.e. volume is applied in analog after the 12-bit value, and quiet sounds keep all 12
  bits. 🟡 Our 12-bit quantisation happens on the stored sample, before the OT's
  volume, which **matches this**.
- ✅ **Three filter types** (owner's manual): *"Channels 1 and 2 have dynamic filters
  whose bandwidth varies in time, channels 3, 4, 5, and 6 are filtered by a constant
  amount, and channels 7 and 8 are totally unfiltered."* Individual-output tip =
  unfiltered, ring = filtered; MIX OUT = filtered.
- ✅ **Channels 3–6 (schematic p. 17, "Output Channels")**: each is one RC pole into two
  unity-gain Sallen-Key stages (TL084): C = 4700 pF / 0.01 µF / 1000 pF, with
  **different resistors per channel**, so each channel is progressively brighter.
  🟡 Our nodal analysis (`tools/sp1200_filter_response.py`, ideal op-amps):

  | channel | −3 dB | at 10 kHz | at 13 kHz | at 20 kHz |
  |---|---:|---:|---:|---:|
  | 3 | 7.9 kHz | −10.0 dB | −20.9 dB | −39.5 dB |
  | 4 | 9.6 kHz | −3.8 dB | −12.7 dB | −31.1 dB |
  | 5 | 11.6 kHz | −1.1 dB | −6.1 dB | −23.3 dB |
  | 6 | 13.1 kHz | +0.1 dB | −2.9 dB | −18.6 dB |

- ✅ **Channels 1–2 (schematic p. 16, "Dynamic Filters")**: the parts list has exactly
  **two** SSM2044 VCFs (IL303, qty 2), with caps 0.01/0.01/0.01 µF/820 pF. The cutoff
  control voltage comes from the channel's `GAIN` line through a diode into a 10 µF
  capacitor, so each hit charges it quickly and it then discharges.
  The factory trim sets the filters to self-oscillate at **1.0 kHz**.
  🟡 Read together: the filter **rests dark (~1 kHz) and snaps open on every hit, then
  closes**, with decay τ on the order of 0.15 s (15 kΩ × 10 µF; the network has
  other paths, so this is approximate).
- ✅ **Input anti-alias filter**: "a very steep cutoff on the order of 42 dB per octave
  and a cutoff frequency of less than half the sample rate". ❓ exact values: the
  manual's page reference points to a schematic page that is different in the
  revision we have. Follow-up.
- 📎 A forum post paraphrases Dave Rossum saying the pitch "algorithm" is lost forever.
  The service manual documents the hardware mechanism above, so what could genuinely be
  lost is only the **table of semitone increment values** the OS wrote. That table would
  be recoverable from an SP-1200 OS disk image, and we don't need it (§5, Q4).

### 1b. Akai S900 / S950

Sources: **Akai S900 Service Manual** incl. "S900 VOICE BLOCK DIAGRAM No. 860913A" and
parts list; **Akai S950 Operator's Manual**. No S950 service manual found.

- ✅ **Per-voice playback chain** (block diagram): 12-bit × 4-word FIFO → **BA9221 12-bit
  DAC read out by that voice's own sampling clock `DSCn`** (uPD71054 programmable
  timers IC19–21) → **MF6CN-50** (6th-order switched-capacitor Butterworth low-pass)
  **clocked by that voice's own filter clock `FCKn`** (uPD8253 timers IC22–24) →
  BA6110 VCA, driven by an 8-bit DAC (BA9201) envelope → output. Eight copies.
  🟡 So pitch is changed by **reprogramming the voice's DAC clock**: no interpolation,
  every stored sample is played once, as a staircase at (recorded rate × ratio).
- ✅ **Record chain**: MF6CN-50 anti-alias **fc = fs × 0.4, 36 dB/oct**, then a fixed
  **18 kHz, 12 dB/oct** LPF, a sample-and-hold, and 12-bit SAR (BA9221 + AM2504).
- ✅ S900: 7.5–40 kHz sampling, 8 voices, 6-octave range, 16 MHz master crystal,
  "Filter (Key tracking, Velocity)".
- ✅ S950 (operator's manual): 12-bit, max 48 kHz; **you choose an AUDIO BANDWIDTH of
  3,000–19,000 Hz and the sample rate follows from it** ("bandwidth is variable up to
  19.2 kHz"). 🟡 19.2 kHz = 0.4 × 48 kHz, the same fs × 0.4 rule as the S900's
  anti-alias filter. Per keygroup: FILTER 0–99 (99 = open), a filter ADSR, and
  KEY-FILTER (default 50: *"the sound will get mellower further up the keyboard"*).
  "Resample at half bandwidth" exists as an edit function.
- ✅ The S950 also has an offline, pitch-preserving **TIMESTRETCH** edit function. That is
  a different thing from what RPS9 emulates, which is varispeed playback.
- ❓ **Does the playback filter clock follow the voice clock?** Both are separate
  programmable timers, so the CPU can do either. The manuals do not say. 🟡 engineering
  inference: a clock-varied staircase puts images at (playback rate − f), so the
  filter only removes them if its cutoff follows the playback rate. At FILTER 99 we
  **assume cutoff = 0.4 × playback rate**, and flag it.
- ❓ Timer input clock, and therefore the S900's pitch step size. Not needed for us:
  we keep exact ratios.
- 📎 The S950 using the MF6CN-50 comes from forum posts (Mod Wiggler/ALM M8), not an
  Akai document.

### 1c. Sources

- SP-1200 Service Manual, text: <https://archive.org/stream/emu-sp-1200-service-manual-1987/Emu-SP-1200-Service-Manual-1987_djvu.txt>;
  PDF (schematics): <https://archive.org/details/emu-sp-1200-service-manual-1987_202010>
- SP-1200 Owner's Manual: <https://archive.org/stream/synthmanual-emu-sp-1200-owners-manual/emusp-1200ownersmanual_djvu.txt>
- Akai S900 Service Manual: <https://archive.org/details/Akai_S900_service_notes> (voice block diagram = PDF p. 28)
- Akai S950 Operator's Manual: <https://archive.org/details/manualzilla-id-7440972>

Manual files are not committed (copyright). Page references above are enough to re-find them.

---

## 2. What this changes in our current approach

1. **RPS9 is modelled on a wrong premise.** Rev 10's RPS9 keeps the OT's linear
   interpolator and adds 12-bit. The S900/S950 had **no interpolator**. The original
   scope's "The Akai S900/S950 **did** interpolate" (REPITCH_KYOTI_SCOPE §2) is wrong. The
   Akai sound is: **reduced recording bandwidth** (steep 36 dB/oct at 0.4 × rate) +
   12-bit + stepped playback at a varied clock + a steep 6th-order post-filter. The
   bandwidth is the largest audible ingredient, and we don't emulate it at all.
2. **RPSP's missing 26 kHz clock is confirmed as the central ingredient**, not a
   detail. The real skip/repeat happens on a 26.04 kHz grid, and the images of a
   26.04 kHz staircase land at 13–26 kHz, i.e. **in the audible band**. Ours happen at
   44.1 kHz, where they mostly fall above hearing. That is why RPSP ≡ RPS9 at 1/1
   today, whereas a real SP-1200 at 1/1 is still band-limited (<13 kHz) and stepped.
3. **The SP-1200's output filters are part of its sound and are fully documented.**
   Emulating "a channel" is concrete: choose ch 3/4/5/6 (fixed 5-pole LPF, values
   known), ch 7/8 (raw staircase), or ch 1/2 (dynamic SSM2044, the hardest).
4. **Where we quantise is right for both machines**: 12-bit on the stored sample,
   level applied afterwards. Keep.
5. **Both machines are the same engine** (§3), so one DSP implementation, one
   verification model and one listening harness serve both modes.

---

## 3. Target design: one "virtual sampler" engine

Per voice, per 44.1 kHz output sample, per channel (L/R):

```
 source (44.1k, ring) ─► PRE-FILTER ─► VIRTUAL SAMPLING ─► 12-bit ─► STEP/HOLD ─► RENDER ─► POST-FILTER ─► out
                        (machine's     at grid rate G      floor    at tick rate T  to 44.1k   (machine's
                         anti-alias)   (the "stored"                (the DAC's      (box-      output
                                        samples)                     staircase)     integrate) filter)
```

| stage | SP-1200 (RPSP) | S900/S950 (RPS9) |
|---|---|---|
| grid rate G (stored samples) | 26,041.7 Hz | chosen bandwidth ÷ 0.4 (e.g. 32 kHz for 12.8 kHz) |
| pre-filter | ~42 dB/oct just under 13 kHz ❓values | 6th-order Butterworth at 0.4·G + 18 kHz 2-pole ✅ |
| tick rate T (DAC clock) | **26,041.7 Hz, fixed** | **G × ratio** |
| address step per tick | ratio, as carry pattern (drop/repeat) | exactly 1 (no drop, no repeat) |
| post-filter | per chosen channel: 5-pole fixed (3–6) / none (7–8) / SSM2044 + envelope (1–2) | 6th-order Butterworth at 0.4·T (🟡 tracking assumption) |

- **Tempo lock is preserved by construction.** SP: T = G, step = r ⇒ source consumed
  at r. Akai: T = G·r, step 1 ⇒ source consumed at r. The OT's increment and ring
  contract are untouched. The cross-chip data contract, the expensive class of change in
  the original scope, **is not reopened**.
- **Virtual sampling** reads the pre-filtered source at non-integer positions
  (g × 44100/G) by linear interpolation. That is accurate here because the signal is
  already band-limited well under Nyquist by the pre-filter.
- **Rendering a 26 kHz staircase at 44.1 kHz.** Picking "whichever step is active"
  (what I originally promised as the "hold") folds the staircase's own images back down.
  Box-integrating each 44.1 kHz output period over the at most two steps it overlaps
  costs one multiply-add and is much closer to what a converter recording the real
  machine would capture. 🟡 recommended.
- **SP pitch quantisation.** The real machine can only do A0 + N/128, in semitones.
  We keep the **exact** QUAN ratio (tempo lock needs it). The skip/repeat pattern is
  then aperiodic instead of 128-periodic. 🟡 inaudible difference; flag in §5 (Q4).

### Fidelity tiers: what each adds, in order of audible impact

**RPSP**
1. 26.04 kHz tick + drop/repeat + staircase + box render + 12-bit, with a cheap
   2-pole pre-filter. *The core SP sound: stepped, aliased, ring-mod-like when
   repitched, dull-but-gritty at 1/1.*
2. Channel filter choice: fixed ch 3/4/5/6 responses above, or raw 7/8.
3. Exact input anti-alias filter (needs the schematic values; ❓).
4. Dynamic ch 1/2: SSM2044 4-pole + per-hit envelope. **Needs a note-on signal from
   the ColdFire**, because the DSP kernel doesn't know when a trig fires. The riskiest item.

**RPS9**
1. Variable-clock staircase at T = G·r + 12-bit + box render, at a **fixed** default
   bandwidth. *The core Akai sound: no interpolation smear, band-limited top.*
2. Tracking post-filter (6th-order at 0.4·T) and exact pre-filter (6th-order at 0.4·G + 18 kHz).
3. User-selectable bandwidth (UI, §5 Q1).
4. Not planned: Akai FILTER / KEY-FILTER / filter ADSR. The OT track's own filter
   already covers that job; say so rather than duplicating it.

---

## 4. Cost (all 🟡 until gate 0)

- **Cycles.** Stock inner loop ≈ 10 instructions per stereo frame. A full-tier engine,
  per channel: pre-filter ~3 biquads × up to 2 source frames, post-filter ~3 biquads,
  tick/hold/render ~10. ≈ **100+ instructions per stereo frame, ~10× the stock
  kernel**, for every track in these modes. Tier 1 alone is ≈ 2–3×. DSP headroom has
  never been measured by us or by octabam. **This decides which tiers are possible.**
- **Per-voice persistent state.** Tick phase, grid phase, held values, and filter
  memories (6th-order = 3 biquads × 2 words; ×2 filters × 2 channels): ≈ 30–40 words
  per voice. The stock kernel keeps **none** (the modelled ring/table are rebuilt per
  block), and 12-bit/ZOH didn't need any. The candidate is SPRING REVERB's data
  memory, freed by rev 10. ❓ whether it is exclusive to spring.
- **Program words.** SPRING's 1063-word module: 388 used by SIDECHAIN3_CROSS, 27 by
  rev 10's cave ⇒ 🟡 ~648 free. Engine estimate 150–300 words. Fits, on paper.
- **Mode channel.** Today 2 bits (Q26 bits 2–3). Bandwidth and channel choice need more.
  Options: more low increment bits (the DSP masks them; a 2⁻²¹ speed error if
  it didn't), or a per-voice parameter word written by the ColdFire. To be designed in
  gate 1.

---

## 5. Decisions for you (none needed before gate 0)

- **Q1. RPS9 bandwidth**: (a) one fixed value (🟡 suggest 32 kHz / 12.8 kHz, a common
  S950 working setting); (b) a few RPS9 variants in the TSTR list (costs widget width,
  each is a new enum value); (c) a new parameter (the largest UI job).
- **Q2. RPSP channel**: one fixed channel type, or selectable. If fixed: ch 3 (dark),
  6 (bright), or 7/8 (raw)? Real MIX OUT gives each channel its own filter, so the
  "SP sound" people know depends on which channel the producer used.
- **Q3. QUAN 1/2 and 2/1 on RPSP**: outside the SP-1200's ±fifth *software* range,
  inside its *hardware* range (A0 + carry gives 0.5×–2×). 🟡 recommend allowing.
- **Q4. SP pitch grid**: exact ratios (recommended, tempo-locked) vs. the real 1/128
  quantisation (authentic pattern, drifts against tempo, e.g. 4/3 → 171/128 = +0.2 %).

---

## 6. Build order

- **Gate 0: measure, don't build (may need one diagnostic flash).**
  (a) DSP cycle headroom per block on both cores, with 8 tracks playing. The likely method
  is an idle-loop counter reported to the ColdFire and drawn on screen.
  (b) Per-voice identity inside the kernel (the outer `do #2` loop at P:0x41b, and what
  calls it) plus a home for ~40 words/voice. (c) Whether ring history before `k` survives
  a block (decides pre-filter style: stateless FIR vs. stateful IIR).
  **Exit: a yes/no per tier.**
- **Gate 1: reference models first.** numpy models of both machines built only from
  §1 (the ground truth the DSP must match), plus a listening pack against RPCH/rev 10.
  No firmware.
- **Gate 2: engine tier 1** (both modes) on the emulated DSP via
  `tools/repitch_dsp_render.cpp`, matching the model to the LSB, then build + flash.
- **Gate 3: filters** (RPSP fixed channels, RPS9 tracking post- and pre-filters).
- **Gate 4: UI** (Q1/Q2) and the wider mode channel.
- **Gate 5 (optional): SSM2044 dynamic channel** with a ColdFire note-on signal.

Each gate is independently shippable. If gate 0 says the cycles are not there, the
fallback is tier 1 only, or tier 1 on a limited number of tracks.

---

## 7. Open questions

- SP-1200 input anti-alias filter component values (find the right schematic page).
- SP-1200 ch 1/2 envelope: exact attack/decay from the p. 16 network (needs
  the `GAIN` line's voltage and timing: a SPICE-level job; a forum claim of "5 ms attack"
  is 📎).
- Akai playback filter tracking (❓ above). Could be settled by a recording of a real
  S900/S950 playing one sample at two pitches. **If you have access to either machine,
  a few test recordings would validate the models in gate 1 better than any document.**
- Whether SPRING's data memory is exclusively spring's.

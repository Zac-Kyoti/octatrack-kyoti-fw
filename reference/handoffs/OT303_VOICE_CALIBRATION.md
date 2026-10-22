# BLACKPYRAMIDS_303 — the voice's recalibration (2026-10-20 / 21)

The record of how BLACKPYRAMIDS_303's voice was recalibrated on the TB-303's own circuit and fitted against
recordings of a real TB-303, and of every choice the author made along the way. What the voice is now, and what
of it is Open303's: [`reference/BLACKPYRAMIDS_303.md`](../BLACKPYRAMIDS_303.md). The tools:
[`tools/ot303/body/`](../../tools/ot303/body/) (README there). FINAL 2026-10-21: mainos `ecc85887…`.

## 1. The goal

The author's: keep the voice's clarity, articulation and resolution, and give it a real 303's body, low and
low-mid weight, rubber, squelch and chirp ("zippery, rubbery, wet", never piercing, ringing or whistling),
without whistle, excess sub-bass, lost clarity or lost low-note definition. A slightly quieter voice was
acceptable if it clipped less. Every behaviour had to be built before the whole was judged, because the voice's
parts interact. The author chose each behaviour by ear; fitted values were inputs to those choices, not the
choices.

## 2. The yardstick

- **Din Sync's TB-303 reference recordings** (400 C2 notes, 25 sets, CUTOFF / RES / ENV MOD / DECAY / ACCENT at
  0 / 25 / 50 / 75 / 100 %). Measurement only; not in the repository (`out/dinsync/raw/`).
- **`realref2.py`:** each note's energy in third-octave bands (50 Hz–10 kHz) in time windows from 15 ms to
  1.3 s, a cell counted when it holds two cycles of its band and sits within 40 dB of the note's loudest cell;
  one global gain; the error is the RMS of the dB differences. The same 303 recorded twice: **1.07 dB**.
- **Knob laws:** each version's knob-to-engine mapping (five points a knob) is fitted with it, so a version
  is judged on its best match, not on where its knobs happen to sit.
- **Tone only** (`cfcheck.py`): the same, every note at its own best gain. It sees the tone and its shape in
  time, not the level between notes.

## 3. The circuit

Read from Roland's service notes and the x0xb0x schematics (Whittle's notes for the accent circuit, the gate
and the slide):

| | the circuit | the previous voice |
|---|---|---|
| coupling before the filter | ~0.7 Hz | 44.5 Hz high-pass |
| after the ladder, before the feedback tap | ~92 Hz (56–96 Hz with the transistors' gain) | in the loop: 350 Hz |
| VCA input coupling | 72 Hz, plus a RES-weighted 156 Hz path | 24 Hz |
| ENV MOD depth | independent of RES | — |
| filter envelope τ | 68 ms – 1.07 s | — |
| accent envelope τ | 68 ms | 200 ms (Open303) |
| accent sweep capacitor | charge 85 → 50 ms, discharge 150 → 100 ms with RES (the RES pot's second gang); the ACCENT pot not in the path; a dead zone at the bottom of ACCENT | none |
| VCA decay | τ 1.5 s, truncated: ~1.35 s effective | τ 1.23 s |
| slide | 103.3 kΩ × 0.22 µF = 22.7 ms | — |
| gate | 3.5 of the step's 6 clocks | — |
| ladder drive | ~64 mV peak to peak: it runs nearly linear | — |

## 4. What the fits found (against the recordings, lower is closer)

| version | score |
|---|---|
| the previous voice (MT35) | 5.86 dB |
| the circuit base: couplings as the circuit, the 55 Hz loop, fitted resonance, ring and level laws, the accent sweep | 2.30 |
| + the filter's floor lowered to 100 Hz (it stopped at 200 Hz) | 2.07 |
| + the accent sweep wired to the RES and ACCENT pots, its threshold fitted (60 %) | **2.06** (tone only 1.92) |
| as built, with the author's loudness-against-cutoff curve | 2.36 (tone only **1.91**) |

- **The floor:** 200 Hz 2.28, 140 Hz 2.12, 100 Hz 2.07, 70 Hz 2.06, 50 Hz 2.06: the real 303 closes to about
  70–100 Hz. Built at 70 Hz, 26 table entries an octave, so the 215 entries still reach 20 kHz.
- **The loop high-pass:** 55, 75 and 95 Hz trade body and low resonance against bass loss under high RES;
  45 Hz leaves the circuit's range and lost clarity and bass.
- **Ladder saturation:** none 2.30, 0.25 2.30, 0.5 2.38, 1.0 2.84: the recordings prefer none, as the circuit's
  small ladder signal predicts.
- **The VCA-input pair** (72 Hz + the RES-weighted 156 Hz path) scored worse (2.44) than a single 110 Hz
  output coupling, so it was not adopted.
- **The accent sweep's wiring:** split and timed by the engine's resonance, as first built, the sweep was
  mostly the fast direct path at high RES, where the circuit is mostly capacitor; wired to the pots (the knob
  positions the engine values stand for), the threshold fits at 60 % of ACCENT (40 % read from the
  schematic scored 2.14).
- **Loudness by cutoff:** a real 303 is about 20 dB quieter (A-weighted) fully closed than fully open. The
  author found the bottom of CUT unusably quiet and chose the previous voice's curve (`lg_p` −0.05, × 0.93):
  the tone-only score is unchanged by it.
- **Drive:** +3 dB into the VOL drive keeps the accent peaks as near the recordings' as without it; +6 dB
  compresses them too far and clips the hottest accents.

## 5. Listening rounds and the author's choices

Ten rounds (B1–B10), at most ten cards each, matched in perceived loudness (ISO 532-1), every version played
at the same real-303 knob positions through its fitted law:

- **B1–B4:** the first candidates (a 100 Hz loop with an 80 Hz input high-pass, a crisper onset, a shorter
  accent; joint fits). Rejected: a crisper onset (clicky), heavier versions (overloaded). They showed the
  couplings around the ladder set the body, and that the accent capacitor was missing.
- **B5:** on the circuit base, one behaviour at a time: the loop (55 / 75 / 95 Hz), level following the filter,
  saturation, the ring. Chosen: level as fitted, ring as fitted, no saturation unless it cost no stock effect.
- **B6–B7:** the complete voice. Chosen: the 55 Hz loop; no light saturation.
- **B8:** the filter floor and the pot-wired accent sweep. Chosen: both. The ACCENT knob given a taper like RES.
- **Knob layout** (the author's rule from here on: the fits judge sound and response only; knob layout is a
  playability choice): each 303 knob covers the real 303's range with no dead travel; RES and ACC spaced
  evenly by what they do (`evenknob.py`: the resonance's boost, the accent's lift), proven sound-neutral (the
  old and new layouts render identically at the knobs' ends; the score is unchanged); DEC kept at
  50 ms–2 s (short plucks come from the AMP page); GATE and SLID default to the 303's (74, 73).
- **B8 (cont.), loudness:** option C, the previous voice's loudness-against-cutoff curve.
- **B9:** CUT capped at the real top, or one octave beyond on knob 101–127 (with or without the resonance
  eased there). Chosen: one octave beyond, the resolution 0.35 semitone a step in the real range (capped 0.28,
  the previous voice 0.53); then a guard on the top of RES in the extension only (RES above 100 with CUT
  above 100; at CUT 127, RES 127 rings like RES 115).
- **B10:** more level into the soft drive (as now / +3 / +6 dB). Chosen: +3 dB, ramped in from VOL 65.
- **The VOL 64 / 65 click** (on the unit): the clean path and the drive swap in one frame, and the engine's
  output smoothing ahead of the drive held the old level for a few samples (the ColdFire also eased the level
  while the drive switched at once). Fixed in the ColdFire: the level and the drive trade over ~4 ms, their
  product held. Switch noise on loud accented notes 17–20 dB lower going up and 7–8 dB going down, now 41–49 dB
  under the note.

## 6. Test images

All `tools/build_blackpyramids_303.py` forms of the day (the `.syx` sha256 prefix, the unit's version label):

| image | what it added | on the unit |
|---|---|---|
| `140C_BPB1C` | the first candidate | not flashed, obsolete |
| `140C_BPB2` `cab50691…` | the circuit base in the ColdFire code | not flashed |
| `140C_BPB3` `b301b3bb…` | + the floor, the pot-wired sweep, the ACCENT taper | not flashed |
| `140C_BPB4` `d0b8f3e7…` | + RES / ACC evenly spaced | flashed: the low end of CUT far too quiet |
| `140C_BPB5` `a96c63b8…` | + option C loudness, CUT on the real range, the 303's GATE / SLID | not flashed |
| `140C_BPB6` `d5545387…` | + CUT one octave beyond | flashed |
| `140C_BPB7` `225729ee…` | + the RES guard, +3 dB drive ramped | flashed: "this is it", but clicks at VOL 64 / 65 |
| `140C_BPB8` `84b0b3db…` | + the click-free VOL crossing | flashed: all good; promoted FINAL (mainos `ecc85887…`) |

## 7. Kept on record, not built

- **The full resonance easing in CUT's extension** (the B9 option): every RES value x 1 → x 0.75 over the octave
  above 1,577 Hz (CUT 100 → 127), the make-up gains recomputed by Open303's formulas. Prototype
  `bp_render.cpp` `ext_f 1577 ext_res 0.75`. To build it: scale `rs` in `params.c` by m(engine CUT) above
  `OT_CUT_HI_Q8` (a 129-entry Q20 table from `gen_body.py`, like `OT_RINGF`), before the AG_8 / BG lines.
- **VOL 1–64 through the soft drive**, which would remove the last switching residual at VOL 64 / 65, at the
  cost of rounding clean VOL's loudest peaks.
- **Light ladder saturation:** fits without giving up another effect (re-rolling the second half-band frees
  ~14 program words), at about +60 cycles a sample; the worst case on DSP core 0 is not checked.
- **More drive than +3 dB without clipping** needs a DSP change: the drive's input stage is where the
  hottest accents clip first.

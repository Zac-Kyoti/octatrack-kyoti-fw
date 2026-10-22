# BLACKPYRAMIDS_303 — design and voicing

A TB-303 voice as an Octatrack MKI track machine, shown on the unit as **BLKPYRAMD**. It runs on the
DSP56300 in 24-bit fixed point, its filter 4× oversampled at 176.4 kHz. This is the reference for what
the machine does, how the voice is built, every decision that shaped it, what it costs, and where each
part came from. The development record of the machine (test images MT1–MT35, listening rounds 1–17,
the hardware diagnostics) is [`reference/handoffs/OT303_SCOPE.md`](handoffs/OT303_SCOPE.md); "OT-303" was
the working name. The voice's recalibration on the TB-303's circuit (2026-10-20/21, listening rounds
B1–B10) is [`reference/handoffs/OT303_VOICE_CALIBRATION.md`](handoffs/OT303_VOICE_CALIBRATION.md).

Builder: [`tools/build_blackpyramids_303.py`](../tools/build_blackpyramids_303.py). Sources:
[`tools/ot303/`](../tools/ot303/). The voice's tables and constants:
[`tools/ot303/body/`](../tools/ot303/body/) (generator, data, checks).

## What is Open303's, and what is new

BLACKPYRAMIDS_303 began as a port of Robin Schmidt's Open303 to the DSP56300. On 2026-10-21 its voice was
recalibrated on the TB-303's own circuit (Roland's service notes, the x0xb0x schematics, Robin Whittle's
notes) and fitted against Din Sync's recordings of a real TB-303, with every choice made by the author's ear.
In short: **the filter, oscillator and envelope algorithms are Open303's; the engine, most of the values
that shape the sound, the accent sweep, the output stage and every knob layout are new.**

Against the recordings (400 notes at known knob settings; lower is closer; the same 303 recorded twice
differs by 1.07 dB): the previous voice (MT35) 5.86 dB, this voice **1.91 dB in tone** (2.36 dB with level,
since its loudness by cutoff is deliberately steadier than a 303's).

| part | Open303 | BLACKPYRAMIDS_303 | where the new value comes from |
|---|---|---|---|
| Engine | double-precision floating point, 4× oversampled, a 12th-order elliptic decimator | **24-bit fixed point on the DSP56300**, the filter 4× oversampled at **176.4 kHz**, 15- and 43-tap half-band decimators with a 16 kHz top rounding; an integer twin it matches bit for bit | written for the Octatrack |
| Oscillator | polyBLEP saw, tanh-shaped square | the same, blended saw → square by WAVE at equal loudness | Open303; WAVE gain by ear (round 14) |
| Filter | the TeeBee ladder (TB_303 mode), fitted b0 / k formulas | **the same ladder and formulas**, held in a table | Open303 |
| Lowest cutoff | 200 Hz (the cutoff knob's bottom) | the filter closes to **70 Hz** (the real 303 closes below 200 Hz) | fitted |
| Input coupling (before the filter) | 44.5 Hz high-pass | **0.7 Hz** | the circuit |
| Resonance-loop high-pass | 150 Hz | **55 Hz** | the circuit (the low end of its 56–96 Hz spread), by ear (B5) |
| Output coupling (after the filter) | 24 Hz high-pass | **110 Hz** | the circuit (the VCA's input coupling), fitted |
| Resonance amount | Open303's law, make-up gain by its formulas | the same law and formulas, × a fitted curve by cutoff (0.7 at 200 Hz, 1.02 at 1.2 kHz), a fitted ring term, make-up × 1.3 | fitted |
| Accent sweep | a fast cutoff boost (RC 15 ms), decay 200 ms | the boost's RC **8.9 ms**, decay **τ 68 ms**, plus **the 303's accent sweep capacitor**: a direct path and a slow capacitor path, split by the RES pot; charge 85 → 50 ms and discharge 150 → 100 ms with RES; it conducts above 60 % of the ACCENT pot. Not in Open303 | the circuit; the RC, the threshold and the two amounts fitted |
| Accent loudness | Open303's VCA boost | × 0.83 | fitted |
| VCA decay | τ 1.23 s | **τ 1.35 s** | the circuit |
| Level against cutoff | none | a gentle curve: CUT changes the tone and the level stays usable (a 303 gets ~20 dB quieter from fully open to closed) | the author's choice (B8) |
| Note edges | no soft attack, 1 ms release | soft attack 1 ms (fading out above RES 100), normal release 2 ms | by ear (rounds 9, 11) |
| Output | none | a soft drive on VOL 65–127, up to about +7 dB, ramped in from VOL 65 and handed over click-free at 64 / 65 | by ear (rounds 8–11, 15, B10) |
| Knob jumps | instant | cutoff and env glide (τ 1 ms), resonance steps eased | by ear (round 13) |
| Knobs | the plugin's ranges | every 303 knob covers the real 303's range: CUT evenly in octaves on 0–100 plus an octave beyond on 101–127 (the top of RES eased there), RES and ACC spaced evenly by what they do, ENV and DEC the 303's; SLID and GATE default to the 303's (22.7 ms, 3.5 of 6 clocks) | the author's (no dead knob travel, nothing past a 303 except CUT's top) |
| Playing it | — | the Octatrack machine: the sequencer, accents and slides as a 303 marks them, ties, live play, chromatic, storage | new |

---

## 1. Using it

- **Choosing it.** BLKPYRAMD is the sixth row of a track's machine list: double-tap the track
  key, or `[FUNC]` + `[SRC]` (SRC SETUP) → MACHINE. One per DSP core: one on T1–T4, one on T5–T8.
  A second one on the same half is refused with the toast **ONE 303 PER CORE!**. The side
  columns mark the track with a **3**.
- **SRC page (p-lockable, LFO and scene targets):**
  - **PTCH**: C0–C8, one semitone per value, shown as note names (C3 = 36, the default);
    FUNC + turn, or the knob pushed while turned, steps a whole octave every three detents and keeps
    the note (D#2 → D#3), and does nothing past C0 or C8; with trigs held it moves every held trig's
    lock the same octave;
  - **CUT**: 0–100 is the real 303's whole cutoff range (a base cutoff of about 206 Hz–1.6 kHz), evenly in
    octaves (0.28 semitone a step); 101–127 goes one octave further (to about 3.2 kHz). The default 44 is the
    previous default sound;
  - **RES**: the real 303's range, spaced so that every step adds the same amount of resonance (the knob's
    middle is about half the boost). With CUT above 100, RES above 100 is eased toward RES 100 as CUT rises
    (at CUT 127, RES 127 rings like RES 115 elsewhere), so a held high resonance cannot turn piercing; RES 0–100
    and CUT 0–100 are never touched;
  - **ENV**: env mod, the real 303's range;
  - **DEC**: filter-envelope decay, 50 ms–2 s, exponential (default 72 ≈ 400 ms); the real 303's range is
    0–105, above it longer than a 303;
  - **ACC**: the accent scale for the steps you accent (127 = each lock's amount, 0 = no accents; default
    100), spaced so that every step adds the same amount of accent, its top the real 303's full ACCENT; the
    accent sweep comes in from 60 % of it, as the 303's does.
- **SETUP page:**
  - **WAVE**: saw (0) → square (127), a continuous blend at equal loudness;
  - **TUNE**: A4 = 400–480 Hz, 64 = 440 Hz;
  - **SLID**: slide time, 0–198 ms; the default 73 is the 303's slide (τ 22.7 ms: 103.3 kΩ × 0.22 µF);
  - **GATE**: note length, (GATE + 1)/128 of a step; the default 74 is the 303's gate (3.5 of the step's
    6 clocks, Whittle);
  - **VOL**: 0 off; 1–64 clean (−30 dB to full); 65–127 driven into a soft clip: the drive rises from 0 dB
    at 65 to about +5.3 dB at the default 99 and +7.1 dB at 127 (a plain line, against VOL 64), smoothly.
    Crossing 64 / 65 the level and the drive hand over in about 4 ms, so there is no click. Clean VOL can
    still hard-clip on bright, low-RES accents (the 4,320-setting sweep: 87 of 1,440 accented notes touch
    the ceiling at VOL 64); driven VOL never clips hard anywhere in the engine (the same sweep at VOL 99).
- **Notes:** a trig plays a note with the knobs at that step, so p-lock PTCH for a melody.
- **Accent:** p-lock ACC on the step (the lock is that step's amount, scaled by the ACC knob: lock ×
  ACC / 127; the knob defaults to 100). A note without an ACC lock is never accented. Live MIDI notes with velocity above 100 are accented.
- **Slide:** an OT slide trig on a note glides into it from the previous note without
  retriggering. The previous note holds into it.
- **Ties:** trigless locks and/or trigless trigs straight after a note hold it, in any mix.
  A trigless trig still does its stock job (it resets LFOs and FX envelopes) and never
  retriggers the voice. *Trade-off:* a trigless trig placed after a note only to reset an LFO
  also ties that note.
- **Live play (MT18):**
  - The track key (TRACKS, SLOTS and SLICES key modes), the chromatic trig keys and MIDI notes
    play the voice. MIDI notes 36–43 trigger the tracks; 72–96 play chromatic around 84.
  - Chromatic and MIDI notes transpose around the track's PTCH.
  - A live note is held while the key or note is down, and its release closes the gate. The DSP
    host's release event (EV bit 2) never starts a note.
  - TRIG + YES previews the held step with its locks, as often as you press it.
  - One-shot trigs play once until re-armed.
  - The voice's tables load right after power-on (MT22): an idle OT-303 track renders through the
    silent renderer's hook (`0x400047f0`) until its core has had two chunk passes (~82 frames), so the
    first trigs after the transport starts sound, and so does the first live note.
- **AMP attack (MT20):** stock's AMP (mode RTRG) drops a track's level to near zero at every trig
  when ATK > 0, with no fade. A sample restarts there; this voice can still be sounding (a long gate,
  an accent's tail, a slide, a held live note), and that was a click. While the voice is estimated
  to sound (gate + 7 release time constants), the trig frame's AMP record (`0x80000110` + 0x200·ping
  + 64·track, halfword 0x15) is switched to the ANLG twin, so the level isn't reset. A note from
  silence keeps ATK's fade-in. In ot_emu, overlapping notes are sample-identical to ATK 0.
- **Short AMP HOLD / REL (MT21):** the AMP envelope can close while the voice still sounds (its
  gate outlasts HOLD + REL). With ATK 0, the next trig re-opened it in one sample onto a sounding
  voice, which popped; a sample would restart from its start there. While the voice sounds, a trig's
  AMP now gets at least ATK 1 for 24 frames: a linear ~5 ms fade from wherever the level is. In
  ot_emu (GATE 127, HOLD/REL 6): the output step at the trig went from 0 → −0.23…−0.46 FS to
  0 → −0.001, with no gain jumps. HOLD/REL 127 and notes from silence are sample-identical to MT20.
- **RES steps (MT20):** the resonance words (RS, BG, AG_8) ease to each new value over a few frames
  (1/6 per frame, ~2 ms), set by the ColdFire. The engine glides cutoff and env amount itself.
- **Trig-key modes (MT23):**
  - CHROMATIC plays absolute notes over four octaves. `[FUNC]` + `[RIGHT]` / `[LEFT]` steps the
    octave up / down 0–3, wrapping at the ends (`0x460d16fc`; the author's choice on the unit; stock
    toggles 0/1); the page LEDs show it. Trig 1 is C1 / C2 / C3 / C4; `[PAGE]` plays the note above
    trig 16 on every octave (E2 .. E5; stock only on its first, hook `0x4004fde4`). Live recording stores the same note.
  - MIDI's follow-the-trig-mode path stays a transpose around PTCH. Other tracks keep stock's 0/1
    octave; one coming from an OT-303 track's 2 or 3 is reset to 0.
  - SLOTS and SLICES: their trig LEDs stay dark (stock's own no-slot path) and the keys do nothing.
    Before, they played the voice and SLICES recorded CUT locks.
  - Hooks: `0x40044006` (LEDs), `0x4004f8dc` / `0x4004fa54` (the keys), `0x40045918` (the octave),
    `0x40050254` (other tracks), `0x4004fba8` (idx up to 51), `0x40044968` (the full keyboard image).
- **The track's own pages work as on any track:** AMP (attack/hold/release act on the 303's
  output), FX1, FX2, the three LFOs (PMTR lists PTCH CUT RES ENV DEC ACC), scenes,
  trig conditions and micro-timing.
- **Limits:**
  - SPRING REVERB is removed from the FX menus: its DSP program space holds the voice.
  - (Fixed in MT19: a chromatic key or MIDI note recorded live now stores the PTCH lock in this
    machine's units, PTCH knob + semitones. Stock's FLEX value was 64 + 5 × semitones, written via
    `0x40042158` from `0x4004fd1a` and from the MIDI path at `0x40062604`.)
  - The track is stored as FLEX plus a signature. FLEX's own settings are kept aside and put
    back when the track leaves the machine. The machine's own knobs are kept in the same unused
    NEIGHBOR bytes while the track is another machine, so switching away and back keeps them, as
    with stock machines; SRC SETUP's BLKPYRAMD row shows and edits them there (MT35). On a stock OS the project opens with the track as
    a FLEX track.
  - In a combined build with ERASE_EMPTY_TRIGLESS_LOCKS, that feature must skip these tracks:
    an empty trigless lock is a tie here. Not built yet, because no combined image contains
    both.

## 2. The voice

Open303's TB_303 algorithm (Robin Schmidt, 2009, MIT), ported to the DSP56300's 24-bit fixed
point, 4× oversampled (176.4 kHz), and since 2026-10-21 recalibrated on the TB-303's circuit
(the values: "What is Open303's, and what is new" above).

```
saw (polyBLEP) ─┬─ blend (WAVE) ─ input coupling 0.7 Hz ─ TeeBee ladder (4×) ─ half-band 4×→2× (15 taps)
square (tanh)  ─┘     resonance feedback ─ one-pole HP 55 Hz ┘           ─ half-band 2×→1× (43 taps, 16 kHz top rounding)
  ─ allpass 14 Hz ─ output coupling 110 Hz ─ notch ─ VCA (amp envelope, de-clicker) ─ soft drive (VOL 65–127) ─ track

cutoff = base (CUT, ENV's offset) + ENV × filter envelope + accent RC + the accent sweep capacitor (ColdFire, a frame at a time)
```

- **Filter.** The ladder is transcribed from Open303's `rosic_TeeBeeFilter.h`: an explicit
  update, Open303's fitted b0/k/g formulas held in a 1/32-octave table, and no resonance
  ceiling. Open303's TB_303 mode is exactly Zavalishin's linear diode ladder (*The Art of VA
  Filter Design*, eq. 5.18) plus a one-pole high-pass in the resonance loop, checked term by term.
- **Oscillator.** A BLEP saw. The square is Open303's tanh-shaped saw, from a 513-point tanh
  table.
- **Envelopes.** Open303's main envelope (the filter decay), the accent's RC path, the VCA decay
  and release, the slide (a pitch slew), and the accent switch, as Open303, with the 303's time
  constants (the accent decay τ 68 ms, the VCA τ 1.35 s, the accent RC 8.9 ms).
- **The accent sweep capacitor (not in Open303).** The 303 sends its accent envelope to the cutoff two
  ways, set by the second gang of the RES pot: directly (strongest with RES down) and through a
  capacitor that charges on each accent and drains slowly (strongest with RES up), so accents in a row
  stack into the 303's rising "wow". It conducts only above about 60 % of the ACCENT pot. The ColdFire
  runs it a frame at a time ([`cf/record.c`](../tools/ot303/cf/record.c)): charge 85 → 50 ms and discharge
  150 → 100 ms with RES (the circuit), the threshold and the two paths' amounts fitted against the
  recordings. It reads the pot positions the knob values stand for, through the fitted laws.
- **The cutoff table** covers 70 Hz–20 kHz in 215 entries (26 an octave); the ColdFire scales its
  cutoff words to it, so the DSP code is unchanged.
- **Decimation.** Not Open303's 12th-order elliptic, which won't fit: a 15-tap then a 43-tap
  half-band, with a fixed one-pole top rounding at 16 kHz folded into the second.
- **Integer twin.** [`tools/ot303/twin.h`](../tools/ot303/twin.h) is the contract. The DSP
  code matches it bit for bit, on both payloads, in every bench.
- **Parameters.** The ColdFire compiles the knobs into the engine's words each frame
  ([`cf/params.c`](../tools/ot303/cf/params.c)): Open303's own formulas in fixed point (held within
  3 LSB of Open303's double-precision values by [`params_check.cpp`](../tools/ot303/params_check.cpp)
  for the previous voice), with the recalibration's tables on top
  ([`cf/body_tables.h`](../tools/ot303/cf/body_tables.h), generated by
  [`tools/ot303/body/gen_body.py`](../tools/ot303/body/gen_body.py)). The voice's tables (2,119 Y words)
  are streamed to the DSP in the control record, so the DSP builds none at boot.

## 3. Voicing decisions — what changed from Open303, and why

Every change was picked blind, two to four versions at a time, by the author's ear (listening
rounds 1–17, then B1–B10 for the 2026-10-21 recalibration). The A/B pages of rounds 1–17 are
`tools/ot303/listening_pack*.py`. Open303 is the baseline; anything not listed (here or in "What is
Open303's, and what is new") is Open303 as shipped.

| what | Open303 | here | how it was decided |
|---|---|---|---|
| Filter model | TB_303 ladder | the same | rounds 1–5: a saturating diode ladder (ZDF), stage saturation, a component-level "circuit accent" (Whittle's diode + 47 kΩ values) and an RES ceiling were all tried; Open303 or its linear twin won at normal settings |
| Top end | 12th-order elliptic decimator | half-bands with 16 kHz rounding | round 6: picked over 13 kHz; ABX against Open303 at chance (Accents 5/10) |
| Lean engine (15 + 43 taps, 24-bit) | — | as listed | round 7: ABX against the reference voice at chance in all four scenes |
| Feedback high-pass | 150 Hz | **55 Hz** (2026-10-21; 350 Hz from round 13 until then) | round 13 (twice) chose 350 Hz to keep bass as RES rose. The recalibration put the input and output couplings where the circuit has them; with those, 55 Hz (the circuit's low end) gave the most body, at a 303's bass loss under high RES (B5) |
| Soft attack (the filter envelope's onset smoothed) | none (`rc1` at 0) | **1 ms, fading out from RES 100 to none at RES 115** | round 9 picked 1 ms; round 11 heard clicks on high-resonance material (the smoothed cutoff "rings" the filter), so it fades out with RES |
| Normal (non-accent) release | 1 ms | **2 ms** | round 9 |
| Output drive | none | **tanh soft clip on VOL's top half; +3 dB more since 2026-10-21, ramped in from VOL 65: about +5.3 dB at the default, +7.1 dB at 127** | rounds 8–11: +4.5 dB picked on Hot, +2.5 dB on Line, none on Locks; the author then put it on the VOL knob. B10: +3 dB more brings typical lines up with no hard clipping anywhere in the engine; +6 dB began to clip the hottest accents |
| Note start | free-running oscillator | **free-running** | rounds 10 and 12 (blind, over a kick), then MT13's FREE/SYNC switch on the unit. A restart from silence measured tighter (attack within ~1 ms of the trig, against up to a cycle late) but lost by ear every time |
| Lock and LFO jumps | instant | **cutoff and env amount glide, τ 1 ms, per sample** | round 13: 1 ms over 3 ms and over none. The mean click above 3 kHz drops 3 dB (and 5.7 dB above 8 kHz); gliding resonance as well measured no better |
| Square shaper drive | 36.9 dB | the same | round 9: 32 and 28 dB lost |
| Oscillator grit (saw curve + noise) | — | not added | round 8: indifferent |
| Makeup gain by RES | Open303's formulas | **× 1.3** on Open303's (fitted, 2026-10-21) | round 13: a heavier makeup was "way too heavy"; the fitted one is part of the recalibration |
| WAVE gain | — | **+2.66 dB at WAVE 87, +1.8 dB at 127 (MT29)** | round 14: kept over none in all five (two sweeps, saw against WAVE 64 / 96 / 127), blind order |
| Output stage headroom, driven VOL | hard clip before the drive | **4× headroom into the drive (MT33)** | round 15 (scene 2): bright accents at VOL 65–127 were chopped flat before the soft clip; now the drive rounds them. Below the old ceiling the same to −107 dB; clean VOL unchanged (still clips on bright accents; a knee for it was round 16) |
| Level at the bottom of RES | up to ~9 dB louder at RES 0 than from RES ~48 up | **a trim below RES 20 (MT34)**: −1.4 dB at RES 0, −0.8 at 4, −0.5 at 8, −0.1 at 16, none from RES 20 (the knob above untouched), eased with RES | round 17 (RES 0 held 2.8 s, then swept; 10–50 % of the boost): 15 % picked at RES 0, then the author chose this form, ending at RES 20, over the proportional one. Clean clipping in that scene 3,508 → 2,402 samples |

### The recalibration (2026-10-21)

The author's goal: the clarity and articulation the voice had, with a real 303's body, low-mid weight,
rubber and squelch, and none of the whistle, excess sub-bass or lost low-note definition. Each behaviour
was built, scored against Din Sync's recordings, and chosen by ear before the whole was judged; the full
record is [`OT303_VOICE_CALIBRATION.md`](handoffs/OT303_VOICE_CALIBRATION.md). The author's decisions:

- **The circuit as the base:** the couplings where the TB-303 has them; the 55 Hz loop over 75 and 95 Hz
  (B5): the most body, at a 303's bass loss under high RES.
- **Level follows the filter** as fitted, and **the ring** (resonance decay) as fitted (B5).
- **No ladder saturation**: the real 303's ladder runs a tiny signal, and the recordings moved further away
  with any (B7).
- **The filter floor** at 70 Hz and **the accent sweep wired to the pots** as the circuit is, its threshold
  fitted at 60 % of ACCENT (B8).
- **The knobs** (the author's rule: the fit judges sound and response only; the knob layout is a separate,
  playability choice): each covers the real 303's range with no dead travel; RES and ACC spaced evenly by
  what they do; CUT evenly in octaves, with one octave beyond the 303 on 101–127 (B9) and the top of RES
  eased there; DEC kept at 50 ms–2 s (short plucks come from the AMP page).
- **Loudness against cutoff** steadier than a 303's: CUT changes the tone, and the bottom of the knob stays
  usable (B8). The tone and its shape in time are unchanged by it (the tone-only score is the same).
- **The drive:** +3 dB into the existing soft drive at VOL 65–127, ramped in (B10), and the VOL 64 / 65
  crossing made click-free: the level and the drive used to change in different frames, and the engine's
  output smoothing, ahead of the drive, held the old level for a few samples (a pop going up, a click
  going down).

Kept on record, not built: the full resonance easing in CUT's extension (every RES value eased to 3/4 by
CUT 127), and running VOL 1–64 through the soft drive too (which would remove the last faint switching
residual at the cost of rounding clean VOL's loudest peaks).

Control decisions (the author's):
- **PTCH:** a semitone per value, C0–C8, with note names. Earlier there were two values per
  semitone, and a C0–C6 spread. FUNC + turn steps by octaves and keeps the note, three detents an
  octave (one a detent was too quick on the unit); stock FLEX's
  FUNC + PTCH jumps to −64 / 0 / +64 instead. PERSONALIZE's DISABLE FUNC+ENC turns it off, as on
  stock. Pushing the knob while turning it (MT28) takes the same octave steps. With several trigs held (MT31, 16 Oct 2026), FUNC or push + turn
  moves every held trig's PTCH lock by the same octave, from its own value; a trig with no lock yet
  starts from the knob's value. Before, the stock editor's call per held trig made each tally a
  detent, so only the last trig moved, and a new lock's first detent moved a semitone (stock starts a
  new lock at knob + turn without the handler).
- **DEC:** 50 ms–2 s (MT25, 15 Oct 2026: snappier plucks; the default moved from 38 to 72 so it still
  starts at about 400 ms). Before that it was 200 ms–2 s (MT16, Open303's plugin range), and before
  that 30 ms–3 s, which crowded the audible part into the bottom half of the knob. An accented note
  ignores DEC, as on Open303 and the real 303: its decay is fixed (τ 68 ms since 2026-10-21, the 303's;
  Open303's 200 ms before).
- **CUT and ENV turned by hand (MT24):** when you turn a page-1 knob, the editor slews its base
  value toward the new one by 1/16 a frame, with 8 bits of fraction (`kb/memory-map.md`, "Page 1:
  the base words"). The renderer used only the whole part (`fp >> 8`), so a turn reached the voice
  as a late half-semitone step, after the slew's ~58 ms. CUT and ENV now carry the fraction
  (`ot_params_cont_q8`), so a turn sweeps as on a stock track, and a p-lock still jumps at once
  onto the 1 ms glide.
- **Push-and-turn (MT26):** a coarse step skips the editor's slew (it writes the base value at once),
  so CUT and ENV still jumped several values. When the knob's live byte moves and the value jumps
  more than one knob value in that frame, the renderer slews it the editor's way (1/16 a frame).
  LFOs and p-locks never write the live byte, so they're untouched.
- **VOL:** clean lower half, driven upper half.
- **Ties:** both trigless kinds.
- **Accent (MT27, 15 Oct 2026):** as on a real 303, accent is marked per step and the ACC knob is a
  global control. A step is accented only by an ACC p-lock; it plays at lock × ACC / 127, so the ACC
  knob scales every accent at once (127: the locks at face value; 0: no accents). The default is 100
  (MT30, 16 Oct 2026; MT27 had 127): a lock is set by turning from the knob's value, so at 127 a lock
  could not be turned up, and turning right made none (the likely "ACC lock not working" on the unit). An
  unlocked note is never accented, whatever the knob says, so DEC always applies to it. A live MIDI
  note with velocity above 100 is accented at the knob's amount; the track and chromatic keys are
  not, and a TRIG + YES preview takes its step's lock. The knob's value is read from the Part,
  because the live byte and the engine's base value show a playing step's lock instead.
  Before MT27, any ACC value above 0 accented a note, so a knob above 0 accented every note.
- **Name:** BLKPYRAMD, with a "3" glyph.
- **WAVE (MT29, 15 Oct 2026, WIP; round 14: kept in all five blind comparisons):** the author heard the square end, and more the
  blends, as quieter than the saw. RMS and K-weighted level had read flat (within 0.8 dB), but ISO 532-1
  loudness (`tools/ot303/wave_loudness.py`: every WAVE value, 21 CUT / RES / VOL / register settings)
  puts the blends up to 2.2 phon below the saw on average (WAVE 80–90; −3.1 at worst) and the square
  −1.5. MT29 scales the oscillator words W1..W3 by a WAVE gain (`OT_WGAIN`, Q14, generated by
  `params_check.cpp` from a fitted curve): +2.66 dB at WAVE 87, +1.8 dB at 127, none at the saw. The
  average over the settings is within 0.02 phon of the saw at every value; single settings within ±0.8
  except bright driven ones (CUT 80, RES 0, VOL 99: −1.85, from −2.5), where the voice's output already
  clips. ColdFire words only: the DSP and its cycles are unchanged (`host_check` bit-exact). Open303 has
  no such gain; `params_check` holds the reference with the same table applied.

## 4. Resources

DSP program memory ("words") is the scarce resource, as for effects: both payloads' P memory
is full in stock, so the voice takes **SPRING REVERB's** module space.

| | used | of |
|---|---|---|
| DSP P (each payload) | 1,026 words (A) / 1,022 (B), in SPRING REV's module (DARK REV's 35-word helper moved beside it) | 1,028 |
| DSP X | 216 working words at `X:$7b24–$7bfb` (stock's unreferenced top, outside the DMA partitions), copied from SPRING's X records at the first frame | — |
| DSP Y | 2,119 words `$7a5–$feb`: tables and the voice state, streamed from the ColdFire | — |
| ColdFire | a 39.7 KB DRAM runtime (a 96 KiB, 16-page arena reserve, loader appended after the OS), 44 detours, 7 pokes, the FLEX renderer slot; about 1,200 instructions a frame per voice in ot_emu for the previous voice, of ~29,000 for the whole frame (15 Oct 2026). The 2026-10-21 voice adds a little per-frame work (the accent sweep capacitor, the knob tapers, the VOL hand-over; 32-bit arithmetic, no 64-bit divides): not re-measured | — |

**Cycles per sample** (emulator cycle table, host and engine together; on the chip ×1.16,
from the METER on DIAG8):

| | average | worst frame (a note starting) | ≈ on the chip (worst) |
|---|---|---|---|
| WAVE 0 (saw only) | 455 | 496 | ~575 |
| WAVE > 0 (the square path) | 598 | 646 | ~749 |

(`tools/ot303/host_check.py`, the FINAL build of 16 Oct 2026; MT24–MT35 and the 2026-10-21 voice changed only
ColdFire and data words, not these figures: the 2026-10-21 bench reads 455.1 / 598.0. On the same bench the 14 Oct build `3624a1e7…` measures 473/515 and 620/670. The bench's accounting was corrected the same day: it priced the
instruction a DO runs with by decoding the DO's loop address as an opcode. The earlier figures
here, 471/511 and 616/666, came from it.)

The 15 Oct 2026 optimization pass changes no output word (bit-exact against the twin in
`engine_check.py` and `host_check.py`). It is about 3.7 % off the voice:
- the second half-band's 22 taps are unrolled, so there is no DO setup a sample;
- the tanh tables' index and fraction are one-word shifts, with no 2-word masks;
- the glide's ES8 / L0_16 and the 4× loop's YY4 are reached through the walkers, not absolute
  addresses;
- the drive keeps GD8 in a register instead of reading it twice;
- the host's raw-path test is folded per payload at build time;
- the record unpack is one instruction a word shorter.

Each core has about **3,120 usable cycles per sample**. Measured on the unit with an earlier
426-cycle build of the voice (DIAG13 and the worst-case test, 2026-10-11):

| configuration | core 1 (T1–T4) spare | core 0 (T5–T8) spare |
|---|---|---|
| light (the voice and one DJ EQ) | ≥ 3,048 | ~2,760 |
| heaviest legal: DJ EQ in FX1 and FX2 on all eight tracks, every track playing a sample | ~528 | ~216 |

Scaled to the final voice (an estimate, not measured), the heaviest configuration leaves:

| | core 1 spare | core 0 spare |
|---|---|---|
| saw | ~360–410 | ~50–95 |
| square | ~180–240 | **about −75 to −130** |

So a square-wave voice on core 0 under that stack could overrun, which sounds like crackle.
Any lighter stack, or the saw, fits.

## 5. Attribution

- **Open303** — © 2009 Robin Schmidt, MIT
  ([github.com/RobinSchmidt/Open303](https://github.com/RobinSchmidt/Open303), pinned
  `313bf0d9`). The voice's algorithms: the oscillator blend and square shaper, the TeeBee ladder
  and its fitted coefficient formulas, the envelopes, accent, slide, the voicing filters' structure
  and the knob-to-parameter formulas. Since 2026-10-21 many of the values those algorithms run with
  are the circuit's or fitted (the table at the top). Its licence:
  [`tools/ot303/LICENSE.Open303.txt`](../tools/ot303/LICENSE.Open303.txt).
- **The TB-303's circuit** — Roland's TB-303 service notes and the x0xb0x schematics: the couplings around
  the filter, the accent sweep circuit and its time constants, the VCA and accent decays, the slide RC
  (103.3 kΩ × 0.22 µF). Values read from them; no schematic is reproduced.
- **Robin Whittle**, the Devil Fish notes and "TB-303 unique" pages: the accent sweep circuit, the gate
  (3.5 of the step's 6 clocks), the slide.
- **Din Sync**, *TB-303 reference recordings for x0xb0x*
  ([dinsync.info](http://www.dinsync.info/2010/02/tb-303-reference-recordings-for-x0xb0x.html)): the
  calibration target, 400 notes of a real TB-303 at known knob positions. Measurement only: the
  recordings are not part of this repository.
- **jc303** — midilab, GPLv3, Open303 in JUCE
  ([github.com/midilab/jc303](https://github.com/midilab/jc303)). **Reference only, no
  code.** It suggested the candidates we A/B-tested:
  - a soft attack on the filter envelope (its SOFT ATTACK exposes Open303's `rc1`);
  - a movable feedback high-pass;
  - a rounder square shaper;
  - an output overdrive.
- **ABL3** — AudioRealism (closed source; its manuals only). The idea of drive reached by
  turning VOL past three quarters, and of gate trim (the release), behind the drive and
  release candidates.
- **ANALOG BD for octabam** — repeat98 (Jannik Aßfalg), MIT. The machine registration
  pattern and the DSP route, ported:
  - a sixth machine row stored as FLEX plus a signature in NEIGHBOR's unused bytes;
  - the per-track source seam.
- **octabam** — sambanks, MIT. The DRAM-runtime pattern (arena reserve and boot loader) and the
  emulators every image was verified on. **SYNTH** (Tim Hastie) was studied for the
  FLEX-renderer approach.
- **Research consulted, no code:**
  - Vadim Zavalishin, *The Art of VA Filter Design* (the ladder's structure);
  - Andy Sloane's measurements of a component-exact x0xb0x
    ([github.com/a1k0n/303](https://github.com/a1k0n/303), facts only);
  - Marko Brajković's OCTA303 (MIT, [braikomarko-hub/acidtrack-modules](https://github.com/braikomarko-hub/acidtrack-modules)),
    another 303 for the Octatrack, also calibrated on Din Sync's recordings: studied as a reference during
    the recalibration. No code, tables or values were taken from it.
- **Test tooling only, not in the image:** the dsp56300 emulator core (GPLv3, via octabam),
  for the DSP benches.
- **Zac Kyoti** — the concept, the sonic direction and the tuning: they set the goals, judged
  every candidate blind by ear over seventeen listening rounds and ten more for the recalibration, and chose and refined the
  values. Specifically:
  - **The concept and requirements:** a 303 as a track machine, one per DSP core, no
    degradation of stock, no FX restrictions, the filter design as the priority.
  - **Filter voicing:**
    - kept Open303's linear ladder over saturating, diode-ladder and circuit-accent models;
    - chose the 16 kHz top-end rounding;
    - accepted the lean engine by ABX.
  - **Warmth and body under resonance:** identified the bass loss as RES rises. Chose the 350 Hz
    feedback high-pass over makeup gain and a gentler RES curve, judging how much low end
    survives without the low-RES sound getting heavier; in the recalibration, chose the circuit's
    55 Hz loop for body, accepting a 303's bass loss under high RES.
  - **Declicking and edges:**
    - asked for Open303's declick measures to be examined;
    - specified the edge timings (soft attack 1 ms, normal release 2 ms);
    - heard the soft attack's clicks at high resonance, which led to its fade-out with RES;
    - picked the 1 ms glide on lock and LFO jumps.
  - **"Liquid", "creamy", "weight":**
    - asked for the JC-303 / ABL3 research and the fatness candidates;
    - weighed drive against detail and liquidity across the Line, Hot and Locks scenes;
    - settled the soft clip at +2.5 dB by default and up to +4.5 dB (+3 dB more, ramped, in the
      recalibration);
    - moved it onto VOL's upper half so most of the knob's travel is usable;
    - kept the square's shaper and left out grit.
  - **Saturation:** kept saturation out of the filter (again in the recalibration) and put a single
    output soft clip after the voice, its range chosen by ear.
  - **Timing:** chose the free-running oscillator by ear over a measurably tighter restart, after
    blind rounds and an on-unit FREE/SYNC comparison.
  - **Playability:**
    - the grid mapping: notes, ACC accents, slide trigs, ties on both trigless kinds, with
      trigless trigs keeping their stock reset;
    - PTCH C0–C8 a semitone per step with note names, DEC 50 ms–2 s, the VOL map, the WAVE
      loudness check;
    - the name and glyph.
  - **The recalibration (2026-10-21):** set its goals (body, low-mid weight, rubber and squelch with the
    voice's clarity, none of the whistle or excess sub), asked for the circuit and the real 303's
    recordings to be the reference, required every behaviour built before judging the whole, and chose
    each by ear over ten rounds (B1–B10): the 55 Hz loop, the fitted level and ring, no ladder saturation,
    the filter floor, the accent sweep on the pots, the knob philosophy (the real 303's ranges, even
    spacing, no dead travel, one octave of CUT beyond with its resonance guard), loudness steadier than a
    303's across CUT, the extra drive and the click-free VOL crossing.
  - **Hardware testing** on an MKI: 17 test images, 14 diagnostic probes, recordings and METER
    readings, then the recalibration's eight test images. These found the REP and DMA-contention
    failures, the sequencer races and the VOL 64 / 65 click.

  The candidates, the DSP assembly, the integer twin, the ColdFire runtime, the benches, the
  calibration tools and the listening packs were written with AI assistance (Claude), under the author's
  direction.

## 6. Octabam module — status

Ported 2026-10-14: `octabam-modules/blackpyramids-303/` (see its README). It needs one upstream
addition, sent with the module: `Module.dsp_source`, a generic field naming a module's DSP
integrate step. That step is the hook octabam had hard-wired for ANALOG BD (`build_bus.py`), which
now goes through the field, with its image byte-identical.

- **ColdFire:** one DRAM unit, `bp_runtime.s`, generated by `tools/ot303/octabam_module.py` from
  `tools/ot303/cf/`. Linked alone at 0x40a955e0 it is this image's runtime byte for byte (its
  `reference`), for `-mcpu=5407` and octabam's `54455`. Making that hold took three things:
  - references that crossed files are written absolute long, or gas relaxes them inside one unit;
  - the C's cross-file tail calls are written as `Bcc.L` words, because gas's 54455 table refuses
    the mnemonic although the chip runs it;
  - ld's tail merge of `""` is kept as a `.set`.
- **The manifest:** this builder's 44 detours and 7 pokes, plus the FLEX renderer `SymbolRef`.
- **DSP:** `bp_image.py` writes `bp_dsp_data.py`'s words: this builder's `dsp_patch.py`, with the
  same asserts.
- **Conflicts:** ANALOG BD, SPRING REV, SYNTH MACHINE, TAPE ECHO, SCALE QUANTIZER and
  SIDECHAIN_COMPRESSOR. The build also refuses any other DSP module.
- **In an octabam image** the runtime is linked at this image's own address, and both payloads'
  voice words are this image's.
  - Differences from this image: octabam's platform plumbing (its loader, arena reserve and
    chooser relocation, and its own DSP payload edits).
  - A Part naming SPRING REV keeps SPRING's page (as with ANALOG BD) rather than the NONE page
    shown here.
- **Flashed in that form** for the previous voice (19 Oct 2026, the user's MKI: every check passes). Regenerated
  for the FINAL build of 21 Oct 2026 (the recalibrated voice, runtime 39,736 B, sha256 `2c430200…`), which is
  confirmed on the unit in its standalone form and in this octabam form (21 Oct 2026: all good). octabam merged the 16 Oct
  form as sambanks/octabam#779.

- **Why FLEX plus a signature, not a sixth machine type:** the OS knows five machine types. A sixth
  would have to be taught to the Part validator, the project file (a stock OS would reset the
  track), the page and parameter tables, the DSP's per-track sources, the trig-key modes, MIDI and
  live recording, each one a crash or corruption risk if missed. Stored as FLEX with a signature
  (repeat98's ANALOG BD pattern, proven on hardware), the track is valid everywhere and opens on a
  stock OS. The cost is that FLEX behaviour leaks wherever it isn't intercepted: AMP resets, the
  chromatic range, SLOTS/SLICES, live-record pitch units. Each needs a hook.

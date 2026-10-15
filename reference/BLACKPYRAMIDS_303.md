# BLACKPYRAMIDS_303 — design and voicing

A TB-303 voice as an Octatrack MKI track machine, shown on the unit as **BLKPYRAMD**. This is
the reference for what the machine does, how the voice is built, every by-ear decision that
shaped it, what it costs, and where each part came from. The full development record (test
images MT1–MT17, listening rounds 1–13, the hardware diagnostics) is
[`reference/handoffs/OT303_SCOPE.md`](handoffs/OT303_SCOPE.md); "OT-303" was the working name.

Builder: [`tools/build_blackpyramids_303.py`](../tools/build_blackpyramids_303.py). Sources:
[`tools/ot303/`](../tools/ot303/).

---

## 1. Using it

- **Choosing it.** BLKPYRAMD is the sixth row of a track's machine list: double-tap the track
  key, or `[FUNC]` + `[SRC]` (SRC SETUP) → MACHINE. One per DSP core: one on T1–T4, one on T5–T8.
  A second one on the same half is refused with the toast **ONE 303 PER CORE!**. The side
  columns mark the track with a **3**.
- **SRC page (p-lockable, LFO and scene targets):**
  - **PTCH**: C0–C8, one semitone per value, shown as note names (C3 = 36, the default);
    FUNC + turn steps a whole octave every three detents and keeps the note (D#2 → D#3), and does
    nothing past C0 or C8;
  - **CUT**: 200 Hz–10 kHz, exponential;
  - **RES**: 0–100 %;
  - **ENV**: env mod;
  - **DEC**: filter-envelope decay, 200 ms–2 s, exponential (default 38 ≈ 400 ms);
  - **ACC**: accent amount, 0 = no accent.
- **SETUP page:**
  - **WAVE**: saw (0) → square (127), a continuous blend at equal loudness;
  - **TUNE**: A4 = 400–480 Hz, 64 = 440 Hz;
  - **SLID**: slide time, 0–198 ms;
  - **GATE**: note length, (GATE + 1)/128 of a step;
  - **VOL**: 0 off; 1–64 clean (−30 dB to full); 65–127 the same level driven into a soft clip,
    up to +4.5 dB. The default is 99 = +2.5 dB.
- **Notes:** a trig plays a note with the knobs at that step, so p-lock PTCH for a melody.
- **Accent:** p-lock ACC on the step.
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
    back when the track leaves the machine. On a stock OS the project opens with the track as
    a FLEX track.
  - In a combined build with ERASE_EMPTY_TRIGLESS_LOCKS, that feature must skip these tracks:
    an empty trigless lock is a tie here. Not built yet, because no combined image contains
    both.

## 2. The voice

Open303's TB_303 algorithm (Robin Schmidt, 2009, MIT), ported to the DSP56300's 24-bit fixed
point, 4× oversampled (176.4 kHz).

```
saw (polyBLEP) ─┬─ blend (WAVE) ─ pre-HP 44.5 Hz ─ TeeBee ladder (4×) ─ half-band 4×→2× (15 taps)
square (tanh)  ─┘     resonance feedback ─ one-pole HP 350 Hz ┘       ─ half-band 2×→1× (43 taps, 16 kHz top rounding)
  ─ allpass 14 Hz ─ HP 24 Hz ─ notch ─ VCA (amp envelope, de-clicker) ─ soft clip (VOL top) ─ track
```

- **Filter.** The ladder is transcribed from Open303's `rosic_TeeBeeFilter.h`: an explicit
  update, Open303's fitted b0/k/g formulas held in a 1/32-octave table, and no resonance
  ceiling. Open303's TB_303 mode is exactly Zavalishin's linear diode ladder (*The Art of VA
  Filter Design*, eq. 5.18) plus a one-pole high-pass in the resonance loop, checked term by term.
- **Oscillator.** A BLEP saw. The square is Open303's tanh-shaped saw, from a 513-point tanh
  table.
- **Envelopes.** Open303's main envelope (the filter decay), the accent's RC "wow" path, the
  VCA decay and release, the slide (a pitch slew), and the accent switch, all as Open303.
- **Decimation.** Not Open303's 12th-order elliptic, which won't fit: a 15-tap then a 43-tap
  half-band, with a fixed one-pole top rounding at 16 kHz folded into the second.
- **Integer twin.** [`tools/ot303/twin.h`](../tools/ot303/twin.h) is the contract. The DSP
  code matches it bit for bit, on both payloads, in every bench.
- **Parameters.** The ColdFire compiles the knobs into the engine's words each frame
  ([`cf/params.c`](../tools/ot303/cf/params.c)): Open303's own formulas in fixed point, held
  within 3 LSB of Open303's double-precision values by
  [`params_check.cpp`](../tools/ot303/params_check.cpp). The voice's tables (2,119 Y words)
  are streamed to the DSP in the control record, so the DSP builds none at boot.

## 3. Voicing decisions — what changed from Open303, and why

Every change was picked blind, two to four versions at a time, by the author's ear (listening
rounds 1–13). The A/B pages are `tools/ot303/listening_pack*.py`. Open303 is the baseline;
anything not listed is Open303 as shipped.

| what | Open303 | here | how it was decided |
|---|---|---|---|
| Filter model | TB_303 ladder | the same | rounds 1–5: a saturating diode ladder (ZDF), stage saturation, a component-level "circuit accent" (Whittle's diode + 47 kΩ values) and an RES ceiling were all tried; Open303 or its linear twin won at normal settings |
| Top end | 12th-order elliptic decimator | half-bands with 16 kHz rounding | round 6: picked over 13 kHz; ABX against Open303 at chance (Accents 5/10) |
| Lean engine (15 + 43 taps, 24-bit) | — | as listed | round 7: ABX against the reference voice at chance in all four scenes |
| Feedback high-pass | 150 Hz | **350 Hz** | round 13 (twice): keeps bass as RES rises (−5 dB at the top instead of −10); RES 0 unchanged. A 250 Hz version had lost to 150 Hz in round 8, before the bass loss was the question |
| Soft attack (the filter envelope's onset smoothed) | none (`rc1` at 0) | **1 ms, fading out from RES 100 to none at RES 115** | round 9 picked 1 ms; round 11 heard clicks on high-resonance material (the smoothed cutoff "rings" the filter), so it fades out with RES |
| Normal (non-accent) release | 1 ms | **2 ms** | round 9 |
| Output drive | none | **tanh soft clip on VOL's top half, up to +4.5 dB; +2.5 dB at the default** | rounds 8–11: +4.5 dB picked on Hot, +2.5 dB on Line, none on Locks; the author then put it on the VOL knob |
| Note start | free-running oscillator | **free-running** | rounds 10 and 12 (blind, over a kick), then MT13's FREE/SYNC switch on the unit. A restart from silence measured tighter (attack within ~1 ms of the trig, against up to a cycle late) but lost by ear every time |
| Lock and LFO jumps | instant | **cutoff and env amount glide, τ 1 ms, per sample** | round 13: 1 ms over 3 ms and over none. The mean click above 3 kHz drops 3 dB (and 5.7 dB above 8 kHz); gliding resonance as well measured no better |
| Square shaper drive | 36.9 dB | the same | round 9: 32 and 28 dB lost |
| Oscillator grit (saw curve + noise) | — | not added | round 8: indifferent |
| Makeup gain by RES | — | not added | round 13: "way too heavy" |

Control decisions (the author's):
- **PTCH:** a semitone per value, C0–C8, with note names. Earlier there were two values per
  semitone, and a C0–C6 spread. FUNC + turn steps by octaves and keeps the note, three detents an
  octave (one a detent was too quick on the unit); stock FLEX's
  FUNC + PTCH jumps to −64 / 0 / +64 instead. PERSONALIZE's DISABLE FUNC+ENC turns it off, as on
  stock.
- **DEC:** 200 ms–2 s, Open303's plugin range. It was first 30 ms–3 s, which crowded the audible
  part into the bottom half of the knob.
- **VOL:** clean lower half, driven upper half.
- **Ties:** both trigless kinds.
- **Accent:** an ACC p-lock.
- **Name:** BLKPYRAMD, with a "3" glyph.
- **WAVE:** checked flat in loudness (within 0.8 dB) across the knob.

## 4. Resources

DSP program memory ("words") is the scarce resource, as for effects: both payloads' P memory
is full in stock, so the voice takes **SPRING REVERB's** module space.

| | used | of |
|---|---|---|
| DSP P (each payload) | 1,027 words, in SPRING REV's module (DARK REV's 35-word helper moved beside it) | 1,028 |
| DSP X | 216 working words at `X:$7b24–$7bfb` (stock's unreferenced top, outside the DMA partitions), copied from SPRING's X records at the first frame | — |
| DSP Y | 2,119 words `$7a5–$feb`: tables and the voice state, streamed from the ColdFire | — |
| ColdFire | a 28 KB DRAM runtime (a 16-page arena reserve, loader appended after the OS), 43 detours, 7 pokes, the FLEX renderer slot; about 1,200 instructions a frame per voice in ot_emu, of ~29,000 for the whole frame (15 Oct 2026: the Y table pre-packed, the continuous words made only when their knobs change; −340 a voice) | — |

**Cycles per sample** (emulator cycle table, host and engine together; on the chip ×1.16,
from the METER on DIAG8):

| | average | worst frame (a note starting) | ≈ on the chip (worst) |
|---|---|---|---|
| WAVE 0 (saw only) | 470 | 510 | ~592 |
| WAVE > 0 (the square path) | 615 | 663 | ~769 |

(`tools/ot303/host_check.py`, 15 Oct 2026 source: 1.6 cycles a sample below the FINAL build
`3624a1e7…`, whose figures were 471/511 and 616/666; the record unpack in `host.asm` is one
instruction a word shorter. The voice itself is unchanged.)

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
  `313bf0d9`). The voice's algorithm and constants: the oscillator blend and square shaper,
  the TeeBee ladder and its fitted coefficient formulas, the envelopes, accent, slide, the
  pre/post voicing filters, and the knob-to-parameter formulas (including the plugin's 400 ms
  default decay and its 200 ms–2 s range). Its licence:
  [`tools/ot303/LICENSE.Open303.txt`](../tools/ot303/LICENSE.Open303.txt).
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
  - Robin Whittle's Devil Fish notes (the circuit accent tried and dropped in rounds 1–5).
  No 303 schematic was copied into the voice: its circuit behaviour arrives through
  Open303's model.
- **Test tooling only, not in the image:** the dsp56300 emulator core (GPLv3, via octabam),
  for the DSP benches.
- **Zac Kyoti** — the concept, the sonic direction and the tuning: they set the goals, judged
  every candidate blind by ear over thirteen listening rounds, and chose and refined the
  values. Specifically:
  - **The concept and requirements:** a 303 as a track machine, one per DSP core, no
    degradation of stock, no FX restrictions, the filter design as the priority.
  - **Filter voicing:**
    - kept Open303's linear ladder over saturating, diode-ladder and circuit-accent models;
    - chose the 16 kHz top-end rounding;
    - accepted the lean engine by ABX.
  - **Warmth and body under resonance:** identified the bass loss as RES rises. Chose the 350 Hz
    feedback high-pass over makeup gain and a gentler RES curve, judging how much low end
    survives without the low-RES sound getting heavier.
  - **Declicking and edges:**
    - asked for Open303's declick measures to be examined;
    - specified the edge timings (soft attack 1 ms, normal release 2 ms);
    - heard the soft attack's clicks at high resonance, which led to its fade-out with RES;
    - picked the 1 ms glide on lock and LFO jumps.
  - **"Liquid", "creamy", "weight":**
    - asked for the JC-303 / ABL3 research and the fatness candidates;
    - weighed drive against detail and liquidity across the Line, Hot and Locks scenes;
    - settled the soft clip at +2.5 dB by default and up to +4.5 dB;
    - moved it onto VOL's upper half so most of the knob's travel is usable;
    - kept the square's shaper and left out grit.
  - **Saturation:** kept saturation out of the filter and put a single output soft clip after
    the voice, its range chosen by ear.
  - **Timing:** chose the free-running oscillator by ear over a measurably tighter restart, after
    blind rounds and an on-unit FREE/SYNC comparison.
  - **Playability:**
    - the grid mapping: notes, ACC accents, slide trigs, ties on both trigless kinds, with
      trigless trigs keeping their stock reset;
    - PTCH C0–C8 a semitone per step with note names, DEC 200 ms–2 s, the VOL map, the WAVE
      loudness check;
    - the name and glyph.
  - **Hardware testing** on an MKI: 17 test images, 14 diagnostic probes, recordings and METER
    readings. These found the REP and DMA-contention failures and the sequencer races.

  The candidates, the DSP assembly, the integer twin, the ColdFire runtime, the benches and
  the listening packs were written with AI assistance (Claude), under the author's direction.

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
- **The manifest:** this builder's 43 detours and 7 pokes, plus the FLEX renderer `SymbolRef`.
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
- **Not flashed in that form.**

- **Why FLEX plus a signature, not a sixth machine type:** the OS knows five machine types. A sixth
  would have to be taught to the Part validator, the project file (a stock OS would reset the
  track), the page and parameter tables, the DSP's per-track sources, the trig-key modes, MIDI and
  live recording, each one a crash or corruption risk if missed. Stored as FLEX with a signature
  (repeat98's ANALOG BD pattern, proven on hardware), the track is valid everywhere and opens on a
  stock OS. The cost is that FLEX behaviour leaks wherever it isn't intercepted: AMP resets, the
  chromatic range, SLOTS/SLICES, live-record pitch units. Each needs a hook.

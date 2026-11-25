```
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▐░░  O T   K Y O T I   F W   ·   custom Octatrack firmware  ░░▌
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
```

# OT Kyoti FW

> Welcome Elektron fans. I'm Zac Kyoti, a musician and music tech hacker located
> on the US west coast. This repo contains knowledge and tools that may be used
> to research and explore modifications to the Octatrack stock firmware.
>
> **Design Philosophy:** KYOTI firmware is designed as a set of new or extended features, QOL
> improvements, and bugfixes, not available in the factory firmware, which can be
> applied individually, in combination, or as a comprehensive build. All mods are
> designed to cleanly interlock. The KYOTI firmware design perspective comes
> foremost from a place of deep respect and appreciation for the architecture of
> these instruments before any mod is applied. As such, my approach is to make the
> modded instrument "feel" like stock — customizations appearing seamless,
> respecting existing UX/UI conventions, and (ideally) stage-ready and bug-free.
> KYOTI firmware is not about complete overhaul of the instrument's plumbing (there
> are plenty of other projects that do that, which you may consider combining with
> KYOTI); it's more about making the stock instrument the best version of
> itself it can be. Read on and enjoy!
>
> The features list on the `main` branch will be updated as new builds roll out.

Influenced by the concepts of [`mxldyn/octamax`](https://github.com/mxldyn/octamax)
by Maxolydian and other Octatrack RE projects — full credits in [`CREDITS.md`](CREDITS.md).

---

## Builds

You bring your own copy of the official **OS 1.40C**; the tools here turn it into a
modified image, byte-for-byte reproducibly from *your* copy. No Elektron binary is
included or distributed. Every feature is **off by default** — a freshly flashed unit
behaves like stock until you opt in.

**Every image carries the three [BATCH_BUGFIXES](#batch_bugfixes)**, always on: each feature's
own build, the BATCH_BUGFIXES build and both KYOTI images. There is no build of a feature
without them.

How to build: [`BUILD_KYOTI.md`](BUILD_KYOTI.md). How to flash, and how to get back to
stock: [`FLASHING.md`](FLASHING.md).

### The WIP gate

Everything in this repo is **work in progress until I promote it to final**. Only final
features are listed below. Every other build refuses to run unless you opt in:

```sh
KYOTI_ALLOW_WIP=1 python3 tools/build_<name>.py
```

An update to a final feature is work in progress too, until I promote it: the final
build refuses to produce a changed image without the opt-in.

---

## Features

Hardware testing is on my Octatrack **MKI**; nothing here has been tested on an MKII, but the
MKII panel layout has been considered for every build.

### MUTE_MODES

Choose how an audio track's mute behaves, in **PERSONALIZE → MUTE MODE**:

- `OT` — stock
- `OTFX` — a hard dry cut, but FX inserts ring out their tails and the sequencer keeps
  running underneath, so unmuting picks up where the pattern would have been
- `OTFX-T` — the same, and new trigs stay suppressed until you unmute
- `DT-T` — Digitakt-style: a sounding voice rides out its own amp envelope and FX, and
  only new trigs are suppressed

SOLO follows the same rule as a manual mute; `CUE MUTES TRK` stays a hard cut. The
setting survives a power cycle.

**Hardware:** the feature confirmed; the bug fixes confirmed (their latest change, the `[BANK]` LEDs, in
the KYOTI V1.8BC / V1.8C release candidates); this image not flashed as such.\
**Final build:** [`tools/build_mute_modes.py`](tools/build_mute_modes.py) →
`out/MUTE_MODES/OCTATRACK_OS1.40C_MUTE_MODES`

### DIRECT_JUMP_KYOTI

An optional immediate pattern change, toggled with **`[PTN]` + `[YES]`** (a toast
confirms; it is OFF at every power-on). A cued pattern takes over on the next step
instead of waiting for the current one to finish, **locked to the master clock**: it
plays exactly where it would be had it been running since PLAY, or since the last normal
pattern change if there was one, whatever its track lengths, scales or master settings. The Part and START SILENT change as on a stock pattern
change, but each track's new sound settings take over with its first trig that actually
plays, never on a sound still ringing from the old pattern. Trig conditions (`1:2`, `PRE`,
`FILL`) carry on from the same point instead of starting again, so they stay in step with
what was playing. With SILENCE TRACKS on, a track the jump silences fades out just before the step
instead of popping. The last MIDI Program Change sent always names the pattern that plays.
The arranger and chains are untouched; with DIRECT JUMP off, pattern changes are stock. It
does not combine with CLYPS, which has it built in.

**Hardware:** confirmed: the clock-locked timing, the Part change, trig conditions and the
SILENCE TRACKS fade, and (in KYOTI V1.8C) a jump after a normal pattern change landing in step
with it. Not specifically tested: MIDI tracks, Program Change on fast re-cues, START SILENT.
The bug fixes confirmed (their latest change, the `[BANK]` LEDs, in the KYOTI V1.8BC / V1.8C release
candidates); this image not flashed as such.\
**Final build:** [`tools/build_direct_jump_kyoti.py`](tools/build_direct_jump_kyoti.py) →
`out/DIRECT_JUMP_KYOTI/OCTATRACK_OS1.40C_DIRECT_JUMP_KYOTI`

### SIDECHAIN_COMPRESSOR

An external key input for the stock DynamiX **COMPRESSOR**, with a base-width key filter, on
the effect's page 2:

- `MON` — `OFF` (left) / `ON` (right): auditions the filtered key in place of the track;
  switching it, or changing `KEY` while it is on, fades instead of clicking
- `KEY` — which of the eight audio tracks drives the compression, even while it is muted; one
  position per detent, also with the encoder pressed
- `KGN` — the key's gain, about −24 to +24 dB; centre is unity
- `KBAS` — the filter's base: a high-pass (18 dB/oct) at `OFF` or 20 Hz to 19.6 kHz, shown in
  **Hz** (`40`, `1.2k` = 1.2 kHz)
- `KWID` — the filter's width: a low-pass (12 dB/oct) set this many **octaves** above `KBAS`,
  `0.5` to `9.9` or `OFF`. With `KBAS` at `OFF` it counts up from 20 Hz: a plain low-pass

The base-width filter isolates the key — a kick's fundamental, for example, with `KBAS`
cutting the sub-sonic rumble below it — which reduces distortion and keeps the compression
smooth at short attack and release settings. The two knobs cannot cross.

The DSP space comes from **SPRING REVERB**, which leaves the FX2 list; a project that
still uses it loads it as NONE.

> **Changed on 25 Oct 2026.** `MON` shows `OFF` on the left and `ON` on the right (it was the
> other way round), and a COMPRESSOR saved with any earlier version comes up with `MON` `OFF`.

> **Changed on 22 Oct 2026.** The base-width filter replaced the earlier one-knob `KFLT`,
> and page 2 was laid out again (it was `RMS KEY KFLT KGN MON`). A COMPRESSOR saved with the
> earlier version keeps its `KEY`, but its other page-2 values now land on different knobs:
> `KGN` gets the old `KFLT`, `KBAS` the old `KGN`, `KWID` the old `MON`, and `MON` comes up
> `OFF`. Such a project **sounds different** until you set `KGN`, `KBAS`, `KWID` and `MON`
> again. A COMPRESSOR saved on stock firmware is not affected.
>
> The earlier version is still buildable, though not recommended:
> [`tools/build_sidechain_compressor_light.py`](tools/build_sidechain_compressor_light.py)
> builds it behind the WIP gate (`KYOTI_ALLOW_WIP=1`, see above); OS VERSION reads `140C_SCLT`.

**Hardware:** the feature confirmed; the bug fixes confirmed (their latest change, the `[BANK]` LEDs, in
the KYOTI V1.8BC / V1.8C release candidates); this image not flashed as such.\
**Final build:** [`tools/build_sidechain_compressor.py`](tools/build_sidechain_compressor.py) →
`out/SIDECHAIN_COMPRESSOR/OCTATRACK_OS1.40C_SIDECHAIN_COMPRESSOR`

### BLACKPYRAMIDS_303

A TB-303 voice as a track machine, shown as **BLKPYRAMD**, running on the Octatrack's DSP in 24-bit fixed
point with its filter 4× oversampled at 176.4 kHz. Adapted from Open303 and recalibrated on the TB-303's own
circuit against recordings of a real 303. It is the sixth row of a track's machine list (double-tap the
track, or `[FUNC]` + `[SRC]` → MACHINE). One per DSP core: one on T1–T4, one on T5–T8. A second one
on a core is refused wherever it would arrive (the machine list, TRACK PASTE, an SRC page paste, and Clyps
loads in KYOTI V1.8BC) with `ONE 303 PER CORE!`, and nothing changes; a project saved with two on a core
keeps the lower-numbered one and turns the other back into its Flex track.

- **SRC:** `PTCH` (C0–C8, a semitone a step, shown as note names; `FUNC` + turn or push + turn
  steps by octaves, on every held trig too) · `CUT` (0–100 the real 303's whole range, evenly; 101–127
  an octave beyond, where the top of `RES` is eased) · `RES` · `ENV` · `DEC` (50 ms–2 s) · `ACC`.
  `RES`, `ENV` and `ACC` cover the real 303's range; `RES` and `ACC` are spaced so every step does as much.
  **SETUP:** `WAVE` (saw → square, at equal loudness) · `TUNE` · `SLID` (slide time; default the 303's) ·
  `GATE` (note length; default the 303's) · `VOL` (clean up to 64, driven above, rising smoothly; the
  default 99 adds about +5 dB).
- **Notes:** each trig plays a note with the knobs at that step; p-lock `PTCH` for a melody.
- **Accent:** p-lock `ACC` on the steps to accent, as a 303 marks them; the `ACC` knob scales
  every accent at once (127 plays the locks as set, 0 none; default 100). Accents in a row stack into the
  303's rising sweep. A note without an `ACC` lock is never accented. A MIDI note with velocity above 100
  is accented.
- **Slide:** an OT slide trig glides into its note from the previous one, without a retrigger.
- **Ties:** trigless locks and/or trigless trigs right after a note hold it. A trigless trig
  still resets LFOs and FX envelopes as on stock, so a trigless trig after a note also ties it.
  A note tied to the end of a pattern holds on through ties at the start of the next pattern.
- **Pattern and Part changes:** as a stock machine's sound does, the voice carries over a pattern
  change until the track's own first trig in the new pattern: the last step plays and rings over the
  change, and a BLKPYRAMD on another track of the same core in the new Part takes the voice at its first
  trig. Each note plays with its own Part's GATE from the first step on.
- **Live:** the track key, chromatic keys and MIDI notes play it, held while the key or note is
  down. TRIG + YES previews a step, and one-shot trigs play once until re-armed.
- **Chromatic mode:** four octaves of absolute notes. `[FUNC]` + `[LEFT]` / `[RIGHT]` pick the
  octave (the page LEDs show it); trig 1 plays C1, C2, C3 or C4, `[PAGE]` the note above trig 16.
  SLOTS and SLICES modes have nothing to play here: their LEDs stay dark.
- AMP, FX1, FX2, LFOs (`PMTR` lists the six SRC knobs), scenes, p-locks and trig conditions
  work as on any track.
- **Copy and paste:** its SRC page copies as a BLKPYRAMD: pasted onto another track, it makes that track a
  BLKPYRAMD with the same knobs. A Flex or Static SRC page pasted onto it makes it that machine with the
  pasted values; choosing BLKPYRAMD again brings its knobs back. UNDO puts either back.

**Limits:**
- SPRING REVERB is removed: its DSP space holds the voice.
- On a stock OS, the track opens as a FLEX track.

**Credits:** adapted from [Open303](https://github.com/RobinSchmidt/Open303) (MIT) by Robin Schmidt: its
filter, oscillator and envelope algorithms. The recalibration takes its values from the TB-303's circuit
(Roland's service notes, the x0xb0x schematics, Robin Whittle's notes) and Din Sync's recordings of a real
TB-303. The machine registration follows repeat98's ANALOG BD for octabam. The Octatrack port, design,
calibration and voicing are by Zac Kyoti, every choice made by ear, as is the hardware testing. What is
Open303's and what is new, every voicing decision and full attribution:
[`reference/BLACKPYRAMIDS_303.md`](reference/BLACKPYRAMIDS_303.md) and [`CREDITS.md`](CREDITS.md).

**Hardware:** the voice confirmed; the one-per-core refusals (machine list, TRACK PASTE, SRC page paste,
Clyps), SRC page copy and paste and a project round trip confirmed in KYOTI V1.8BC; Part and pattern changes
(no pop, the last step, ties across, the first note's GATE) confirmed in the octabam form; choosing it in the
machine list (it sounds at once) and switching a track away from it (no stray sample) confirmed in KYOTI V1.8BC
test images (November 20–24, 2026, the last flashed with all tests passed); loading a project saved with two on
a core not tried on the unit. This image, with the three bug fixes, not flashed as such.\
**Final build:** [`tools/build_blackpyramids_303.py`](tools/build_blackpyramids_303.py) →
`out/BLACKPYRAMIDS_303/OCTATRACK_OS1.40C_BLACKPYRAMIDS_303`

### VARISPEED

Tempo-locked varispeed for STATIC and FLEX tracks. SRC SETUP's `TSTR` gets a fifth position,
**VARI**: the sample plays dry, tape-style, its speed and pitch moving together and locked to
the project tempo. RATE still applies. On `TSTR` AUTO, a sample whose TIMESTRETCH (audio
editor → ATTR) is VARI plays the same way.

- **`QUAN`:** on a VARI track `PTCH` becomes `QUAN`, a ratio on the tempo-locked speed:
  1/2, 2/3, 3/4, 4/5, 1/1, 5/4, 4/3, 3/2, 2/1. Leaving VARI gives `PTCH` its value back.
- Above twice the sample's own speed, it folds down an octave.
- A sample or project tempo outside 30–300 BPM plays as `TSTR` OFF.

**Hardware:** confirmed in the KYOTI V1.8BC / V1.8C release candidates and in VARISPEED_EMUS (the same code):
`QUAN` on entering VARI and across a save, a project saved with the earlier version, a held VARI note's speed
through a Part switch; the bug fixes there too. This image not flashed as such.\
**Final build:** [`tools/build_varispeed.py`](tools/build_varispeed.py) →
`out/VARISPEED/OCTATRACK_OS1.40C_VARISPEED`

### VARISPEED_EMUS

VARISPEED with two sampler emulations. On a VARI track `TSNS` becomes **`EMUS`**, which picks
the engine the track plays through:

- `OT`: the Octatrack's own playback, as in VARISPEED
- `S950`: the Akai S900/S950, 12-bit at its 40 kHz rate
- `SP12`: the E-mu SP-1200, 12-bit at 26.04 kHz through its raw outputs, in stereo

A change of engine takes effect at the track's next trig. The engines run on the DSP. A
change that would overload a DSP core is refused and shows `MAX DSP: EMU LIMIT`: an `EMUS`
turn stops at the heaviest engine that fits, an FX type doesn't land, and a track coming
onto VARI plays `OT`. At a pattern change to another Part, the old Part's held notes and the new
Part's sounds overlap until each track's next trig; if that overlap would overload the core, the
held notes drop to `OT` on the downbeat and, only if that is not enough, the new Part's engines step
down (saved at the switch; a cancelled cue changes nothing). Held VARI notes keep their speed
through the change until their own next trig.

The DSP space comes from **SPRING REVERB**, which leaves both FX lists; a project that still
uses it loads it as NONE.

**Hardware:** confirmed (this image's code, flashed with a test OS VERSION: VARISPEED's `QUAN` and its memory,
a project saved with the earlier version, the load guard, the bug fixes).\
**Final build:** [`tools/build_varispeed_emus.py`](tools/build_varispeed_emus.py) →
`out/VARISPEED_EMUS/OCTATRACK_OS1.40C_VARISPEED_EMUS`

### RELOAD_FROM_PROJECT

Reload a track, or a whole pattern, from the CF card **without stopping the transport**:

- **`[PTN]` + `[TRACK n]`** — that track's sequence as the project was saved
- **`[BANK]` + `[TRACK n]`** — the same, plus that track's machine, FX, pages, scene locks and
  LFO designer; every other track is left alone
- **`[PTN]` + `[BANK]` + trig** — that pattern of the playing bank, all its tracks and its Part.
  The pattern you are on reloads in place; another pattern is a pattern change, so it comes in
  at CHAIN AFTER or the pattern end (DIRECT JUMP's next step when it is on)

While playing, a reload lands on the track's next step, in time with everything else (a whole
pattern: on the next step its tracks share). A saved length or scale comes back the same way, with
every track carried on where the saved pattern would be. Several reloads in a row all count; the
latest one for a track wins. Stopped, a reload applies at once. A toast confirms each reload as it
lands. A track's reloaded sound settings take over with its first trig that actually plays, never on a
sound still ringing, and trig conditions (`1:2`, `PRE`, `FILL`) carry on as if the saved sequence had
played all along. `[CUE]` + `[TRACK n]` stays stock. It does not combine with CLYPS, which carries
its own card reloads.

**Hardware:** the feature confirmed; the bug fixes confirmed (their latest change, the `[BANK]` LEDs, in
the KYOTI V1.8BC / V1.8C release candidates); this image not flashed as such.\
**Final build:** [`tools/build_reload_from_project.py`](tools/build_reload_from_project.py) →
`out/RELOAD_FROM_PROJECT/OCTATRACK_OS1.40C_RELOAD_FROM_PROJECT`

### CLYPS

A clip launcher and reload suite for the Octatrack, in the spirit of Ableton Live's Session
view. Every pattern in a bank holds a sequence for each track; Clyps treats each of those as
a clip. While the pattern plays, load any other pattern's sequence onto one track, alone or
with its sound (machine, sample, FX and settings from that pattern's Part), and the other
tracks carry on untouched. Whatever you load, you can put back: the track as originally
loaded, a temp save you took with a key press, or the project as saved on the card.

Press **`[PTN]` + `[BANK]`** together to open Clyps (`[NO]` closes it): the screen and the trig keys
show the active track's sequence in all 16 patterns of the bank. A trig loads that slot; **`[FUNC]`** +
trig loads it with its sound; your own pattern's trig puts the original back. Inside and outside Clyps, **`[TRACK]` + `[YES]`**
temp-saves a track and **`[TRACK]` + `[NO]`** puts the temp save back; **`[PTN]`** / **`[BANK]`** +
`[TRACK]` reload a track's sequence (and sound) from the card.

**Direct Jump Kyoti is built in.** With it off (as at power-on), Clyps keeps stock timing: a new
load is cued and lands where a pattern change would. Turn it on with **`[PTN]` + `[YES]`** and loads
are legato: they take over on the track's next step, in time, as fast as you can press trigs.
Putting something back is always legato. There is nothing to add: Clyps cannot be combined with
DIRECT_JUMP_KYOTI or RELOAD_FROM_PROJECT (the builders refuse), because it carries both jobs itself.

Clyps keeps its originals and working copies in sample memory, about 10 MB of the 85.5 MB.
Everything else, from groups to peeking at a parameter page, is in the
**[Clyps user manual](docs/clyps/MANUAL.md)**, a living document that will keep changing.

**Hardware:** confirmed in KYOTI V1.8BC, the same Clyps code (flashed November 24, 2026: all tests
passed). This image (Clyps, Direct Jump Kyoti and the three bug fixes) not flashed as such.\
**Final build:** [`tools/build_clyps.py`](tools/build_clyps.py) →
`out/CLYPS/OCTATRACK_OS1.40C_CLYPS`, and in [KYOTI V1.8C](#kyoti-v18c), below.

### QUANTIZE_LIVE_REC_TOGGLE

Reach the QUANTIZE LIVE REC setting from the front panel. Hold **`[REC]`** and tap
**`[PLAY]`**: a toast shows the setting, `LIVE REC: QUANTIZED` or `LIVE REC: UNQUANTIZED`.
Tap `[PLAY]` again **while the toast is up** to invert it; if PERSONALIZE is open, its check
mark follows. Once the toast has gone (1 s), a tap just shows the setting again. The first
`[REC]` + `[PLAY]` still starts live recording as on stock.

**Hardware:** the feature confirmed; the bug fixes confirmed (their latest change, the `[BANK]` LEDs, in
the KYOTI V1.8BC / V1.8C release candidates); this image not flashed as such.\
**Final build:** [`tools/build_quantize_live_rec_toggle.py`](tools/build_quantize_live_rec_toggle.py) →
`out/QUANTIZE_LIVE_REC_TOGGLE/OCTATRACK_OS1.40C_QUANTIZE_LIVE_REC_TOGGLE`

### ERASE_EMPTY_TRIGLESS_LOCKS

A trigless lock — a step with parameter locks but no audible trig, on an audio or a MIDI
track — now disappears from the trig row once you erase its last lock, instead of staying lit. One placed
deliberately with `FUNC` + `TRIG` is left alone.

**Hardware:** confirmed on audio and MIDI tracks in the KYOTI V1.8BC release candidate (the same code), with
the bug fixes; this image not flashed as such.\
**Final build:** [`tools/build_erase_empty_trigless_locks.py`](tools/build_erase_empty_trigless_locks.py) →
`out/ERASE_EMPTY_TRIGLESS_LOCKS/OCTATRACK_OS1.40C_ERASE_EMPTY_TRIGLESS_LOCKS`

### REC_TRIG_MUTE

Mute a track's recorder trigs without deleting them. Hold **`[TRACK]`** and press
**`[REC]`**: that track's recorder trigs stop firing — a recording already running finishes —
and a toast reads `REC TRIGS MUTED`. Press it again to bring them back (`REC TRIGS UNMUTED`).
Each track keeps its own state: with several track keys held, each one flips
(`REC TRIGS TOGGLED` when they end up mixed). The toast stays up while you hold the track
key, up to 1 second, as QUANTIZE_LIVE_REC_TOGGLE's does, and closes when you let go. While a
track key is held, `[REC]` does not switch grid recording; on its own `[REC]` works as on stock. It works on any screen and holds
across pattern changes until you unmute; every track starts unmuted at power-on. A muted
track's tab at the screen edge shows two dots, one above the other, beside its machine letter
on the inner side (right of the letter on T1–T4, left of it on T5–T8).

MIDI: **CC 80** on a track's channel mutes it (1–127) or unmutes it (0); on the AUTO
channel it acts on the active track. The keys send CC 80 (1 muted / 0 unmuted) on each held
track's channel. Both need AUDIO CC IN / OUT on, as for every audio-track CC. `[TRACK]` +
`[YES]` / `[NO]` arm and disarm recorder one-shot trigs as on stock.

**Hardware:** confirmed in KYOTI V1.6 (`[TRACK]` + `[REC]`, the per-track toggle, the toast).
MIDI CC 80 not specifically tested. The bug fixes confirmed (their latest change, the `[BANK]` LEDs, in the
KYOTI V1.8BC / V1.8C release candidates); this image not flashed as such.\
**Final build:** [`tools/build_rec_trig_mute.py`](tools/build_rec_trig_mute.py) →
`out/REC_TRIG_MUTE/OCTATRACK_OS1.40C_REC_TRIG_MUTE`

### BATCH_BUGFIXES

Three fixes to stock bugs. Every image here carries all three; this build is the three alone.

- **MIDI_PLAYS_FREE_FIX** — a Plays-Free MIDI track with trig quantize *Direct* and
  pattern scale *Per Track* no longer stalls after its first step on a manual trig.
- **EMPTY_PATTERN_LED_FIX** — a pattern whose only content is parameter locks — trigless
  locks with a locked parameter included — lights its LED under `[PTN]` and `[BANK]`, instead
  of showing as an unused slot; a trigless lock with nothing locked does not.
- **PART_CHANGE_CARRYOVER_FIX** — after a pattern-triggered Part change, a track leaving
  PICKUP for FLEX no longer keeps playing the old Part's pickup loop, and a switch into a
  PICKUP track no longer marks the Part edited when nothing changed.

**Hardware:** each fix confirmed (the `[BANK]` trigless-lock LEDs, also with `[BANK]` held and the sequencer
running, in the KYOTI V1.8BC / V1.8C release candidates and VARISPEED_EMUS); this image of the three together
not flashed as such.\
**Final build:** [`tools/build_batch_bugfixes.py`](tools/build_batch_bugfixes.py) →
`out/BATCH_BUGFIXES/OCTATRACK_OS1.40C_BATCH_BUGFIXES`

### KYOTI V1.8

Every feature above except BLACKPYRAMIDS_303, VARISPEED_EMUS and CLYPS in **one image**:
RELOAD_FROM_PROJECT and DIRECT_JUMP_KYOTI side by side. The boot splash and SYSTEM STATUS →
OS VERSION read `KYOTI V1.8`. It replaces KYOTI V1.7 and earlier, and the withdrawn V1.0
(see below). A COMPRESSOR saved with V1.5 or earlier keeps its `KEY`; set its `KGN`, `KBAS`,
`KWID` and `MON` again.

**Hardware:** each feature confirmed (RELOAD_FROM_PROJECT in its own image, the others in the KYOTI
V1.8BC / V1.8C release candidates); this combined image not flashed as such (RELOAD after a DIRECT JUMP
jump checked in the emulator only).\
**Final build:** [`tools/build_kyoti.py`](tools/build_kyoti.py) →
`out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8`

### KYOTI V1.8C

KYOTI V1.8 with CLYPS in RELOAD_FROM_PROJECT's place: Clyps, with Direct Jump Kyoti built in,
carries its own card reloads. OS VERSION reads `KYOTI 1.8C`. Clyps keeps about 10 MB of
sample memory.

**Hardware:** its Clyps confirmed in KYOTI V1.8BC, the same Clyps code (flashed November 24, 2026: all
tests passed); its other features in the KYOTI V1.8C / V1.8BC release candidates. This image not flashed as
such.\
**Final build:** [`tools/build_kyoti.py`](tools/build_kyoti.py) `--clyps` →
`out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8C`

### KYOTI V1.8BC

KYOTI V1.8C with BLACKPYRAMIDS_303. OS VERSION reads `KYOTI1.8BC`. SPRING REVERB **and** PLATE
REVERB are given up: their DSP space holds the voice and the side-chain; a project saved with either
loads that FX2 as NONE. Clyps loads (FULL, groups, ORIG, temp and card reloads) that would put a second
BLKPYRAMD on a core are refused whole, with `ONE 303 PER CORE!`. ERASE_EMPTY_TRIGLESS_LOCKS leaves a
BLKPYRAMD track's trigless locks alone (there they are ties). Clyps and the voice keep about 10 MB of
sample memory.

**Hardware:** this image flashed November 24, 2026 (with a test OS VERSION, the same build): all tests
passed. With its earlier release candidates and test images (November 19–24): the voice on both cores, the
FX2 list, SIDE-CHAIN keyed from and onto a BLKPYRAMD track, every MUTE MODE on a BLKPYRAMD track, the
trigless-lock erase on audio and MIDI tracks, Clyps and DIRECT JUMP with a BLKPYRAMD track, a project round
trip, the one-per-core refusals, SRC page copy and paste, and choosing BLKPYRAMD in the machine list and
switching away from it. Its BLACKPYRAMIDS_303's Part and pattern changes are confirmed in the octabam form (the
same code), not in this image. Loading a project saved with two on a core not tried on the unit.\
**Final build:** [`tools/build_kyoti.py`](tools/build_kyoti.py) `--clyps-bp` →
`out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8BC`

---

## ⚠️ Before you flash

**KYOTI V1.0 (the earlier all-in-one image) is withdrawn as of 2026-10-06.** It can crash
the unit when an encoder is turned on an FX page set to NONE, and when T8's PLAYBACK or LFO
page is shown with T8 as MASTER. If you flashed it, flash KYOTI V1.8 or V1.8C above, one of the
single-feature builds, or stock OS 1.40C. None of those has this problem.

**KYOTI V1.2 breaks PLATE REVERB** (a damaged page, and its knobs do nothing). Flash KYOTI V1.8 or V1.8C.

**KYOTI V1.1–V1.6 change the stock DELAY's tone**, and so does the VARISPEED_EMUS + BATCH_BUGFIXES
image (OS VERSION `BUG_VEM10`) built before 2026-11-02: at most BASE / WDTH settings, the defaults included, the
repeats are filtered darker than on stock. Flash KYOTI V1.8 or V1.8C, or rebuild VARISPEED_EMUS.

**This is for personal study.** Updating an Elektron unit with anything other than
official firmware is risky: it puts the warranty in question and can leave the unit
needing the bootloader recovery path. Nothing here is endorsed by, supported by, or
affiliated with Elektron. If in doubt, don't flash — just read, disassemble, and learn.

Keep the official `.syx` on hand: **`[FUNC]` + power on → `[TRIG 3]`** recovers the unit
even from a bad OS, because an OS update never touches the bootloader. Never cut power
during `UPDATING FLASH`. The full procedure and recovery net are in
**[`FLASHING.md`](FLASHING.md)**.

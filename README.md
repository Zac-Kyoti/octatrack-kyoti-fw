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
behaves like stock until you opt in. The bug fixes are always on.

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

Hardware testing is on my Octatrack **MKI**; nothing here has been tested on an MKII.

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

**Hardware:** confirmed. Its newest fix (the `OTFX-T` / `DT-T` trig hook no longer
overwrites a register stock code relies on) is emulator-verified, not yet on hardware.\
**Final build:** [`tools/build_mute_modes.py`](tools/build_mute_modes.py) →
`OCTATRACK_OS1.40C_MUTE_MODES`

### DIRECT_JUMP_KYOTI

An optional immediate pattern change, toggled with **`[PTN]` + `[YES]`** (a toast
confirms; it is OFF at every power-on). A cued pattern takes over on the next step
instead of waiting for the current one to finish, **locked to the master clock**: it
plays exactly where it would be had it been running since START, whatever its track
lengths, scales or master settings. The Part, START SILENT and trig conditions change as
on a stock pattern change, and the last MIDI Program Change sent always names the
pattern that plays. The arranger and chains are untouched; with DIRECT JUMP off, pattern
changes are stock.

**Hardware:** confirmed. Not yet tested on hardware: MIDI tracks, and Program Change on
fast re-cues.\
**Final build:** [`tools/build_direct_jump_kyoti.py`](tools/build_direct_jump_kyoti.py) →
`OCTATRACK_OS1.40C_DIRECT_JUMP_KYOTI`

### SIDECHAIN_COMPRESSOR

An external key input for the stock DynamiX **COMPRESSOR**, on the effect's page 2:

- `KEY` — which of the eight audio tracks drives the compression, even while it is muted
- `KGN` — trims the key signal
- `KFLT` — filters the key: below centre low-pass, above centre high-pass, centre off
- `MON` — auditions the filtered key

The DSP space comes from **SPRING REVERB**, which leaves the FX2 list; a project that
still uses it loads it as NONE.

**Hardware:** confirmed.\
**Final build:** [`tools/build_sidechain_compressor.py`](tools/build_sidechain_compressor.py) →
`OCTATRACK_OS1.40C_SIDECHAIN_COMPRESSOR`

### RELOAD_FROM_PROJECT

Reload one track's sequence from the CF card **without stopping the transport**:

- **`[PTN]` + `[TRACK n]`** — reload that track's card-saved sequence, Part untouched
- **`[BANK]` + `[TRACK n]`** — the same, and re-apply the saved Part

It reloads the pattern that is playing, on an audio or a MIDI track, and never restarts
the sequence or the metronome. A toast confirms when the reload has finished, and says
so if the trigs did not land.

**Hardware:** confirmed.\
**Final build:** [`tools/build_reload_from_project.py`](tools/build_reload_from_project.py) →
`OCTATRACK_OS1.40C_RELOAD_FROM_PROJECT`

### REPITCH_REPEAT98_KYOTI

Three new **TSTR** settings on a STATIC or FLEX track's SETUP page (`[FUNC]` + `[SRC]`).
The sample follows the project tempo by **varispeed**, the way a classic sampler or a
turntable would — speed and pitch move together, nothing is stretched. The tempo comes
from the sample's own tempo attribute (audio editor, ATTR); a sample outside 30–300 BPM
plays as stock.

- `RPCH` — the Octatrack's own playback, clean
- `RPS9` — an Akai S900/S950: a virtual 40 kHz, 12-bit sampler
- `RPSP` — an E-mu SP-1200: 26.04 kHz, 12-bit, drop-sample, through its channel 1/2
  low-pass filter, which the track's AMP envelope opens

On a repitch track the **PTCH** knob becomes **QUAN**, an exact ratio against the tempo —
`1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1` — so a loop at 3/4 lines back up with the pattern.
QUAN takes p-locks and scene locks, and PTCH and QUAN are kept separately. In the audio
editor, TIMESTRETCH gains `REPITCH`, `RPS9` and `RPSP`, so under SETUP `AUTO` each sample
plays in its own mode. The DSP space comes from **SPRING REVERB**, as for
SIDECHAIN_COMPRESSOR. Starts from Jannik Aßfalg's Repitch module for octabam
([`CREDITS.md`](CREDITS.md)).

**Hardware:** confirmed. Not specifically tested: RTRG retrigs on a repitch track, and a
full DSP core of RPSP tracks under heavy effects.\
**Final build:** [`tools/build_repitch_repeat98_kyoti.py`](tools/build_repitch_repeat98_kyoti.py) →
`OCTATRACK_OS1.40C_REPITCH_REPEAT98_KYOTI`

### QUANTIZE_LIVE_REC_TOGGLE

Reach the QUANTIZE LIVE REC setting from the front panel. Hold **`[REC]`** and tap
**`[PLAY]`**: a toast shows the setting. Tap `[PLAY]` again **while the toast is up** to
invert it. Once the toast has gone (1 s), a tap just shows the setting again. The first
`[REC]` + `[PLAY]` still starts live recording as on stock.

**Hardware:** confirmed.\
**Final build:** [`tools/build_quantize_live_rec_toggle.py`](tools/build_quantize_live_rec_toggle.py) →
`OCTATRACK_OS1.40C_QUANTIZE_LIVE_REC_TOGGLE`

### ERASE_EMPTY_TRIGLESS_LOCKS

A trigless lock — a step with parameter locks but no audible trig — now disappears from
the trig row once you erase its last lock, instead of staying lit. One placed
deliberately with `FUNC` + `TRIG` is left alone.

**Hardware:** confirmed.\
**Final build:** [`tools/build_erase_empty_trigless_locks.py`](tools/build_erase_empty_trigless_locks.py) →
`OCTATRACK_OS1.40C_ERASE_EMPTY_TRIGLESS_LOCKS`

### BATCH_BUGFIXES

Three fixes to stock bugs. Each has its own build.

- **MIDI_PLAYS_FREE_FIX** — a Plays-Free MIDI track with trig quantize *Direct* and
  pattern scale *Per Track* no longer stalls after its first step on a manual trig.\
  **Hardware:** confirmed. **Final build:**
  [`tools/build_midi_plays_free_fix.py`](tools/build_midi_plays_free_fix.py)
- **EMPTY_PATTERN_LED_FIX** — a pattern whose only content is parameter locks now lights
  its grid LED under `[PTN]`, instead of showing as an unused slot.\
  **Hardware:** confirmed. **Final build:**
  [`tools/build_empty_pattern_led_fix.py`](tools/build_empty_pattern_led_fix.py) →
  `OCTATRACK_OS1.40C_EMPTY_PATTERN_LED_FIX`
- **PART_CHANGE_CARRYOVER_FIX** — after a pattern-triggered Part change, a track leaving
  PICKUP for FLEX no longer keeps playing the old Part's pickup loop, and a switch into a
  PICKUP track no longer marks the Part edited when nothing changed.\
  **Hardware:** confirmed. **Final build:**
  [`tools/build_part_change_carryover_fix.py`](tools/build_part_change_carryover_fix.py) →
  `OCTATRACK_OS1.40C_PART_CHANGE_CARRYOVER_FIX`

---

## ⚠️ Before you flash

**This is for personal study.** Updating an Elektron unit with anything other than
official firmware is risky: it puts the warranty in question and can leave the unit
needing the bootloader recovery path. Nothing here is endorsed by, supported by, or
affiliated with Elektron. If in doubt, don't flash — just read, disassemble, and learn.

Keep the official `.syx` on hand: **`[FUNC]` + power on → `[TRIG 3]`** recovers the unit
even from a bad OS, because an OS update never touches the bootloader. Never cut power
during `UPDATING FLASH`. The full procedure and recovery net are in
**[`FLASHING.md`](FLASHING.md)**.

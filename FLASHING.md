# Safe flashing guide — OT Kyoti FW

How to flash an OT Kyoti FW image onto your Octatrack, with a full safety net.

> **Features are OFF by default.** Straight after flashing, the unit behaves like stock
> apart from the always-on bug fixes. MUTE_MODES lives in PERSONALIZE;
> QUANTIZE_LIVE_REC_TOGGLE, DIRECT_JUMP_KYOTI and RELOAD_FROM_PROJECT are front-panel
> chords that do nothing until you press them (DIRECT_JUMP_KYOTI comes up OFF on every
> power-on); SIDECHAIN_COMPRESSOR only engages on a setting you pick.

> **MKI.** Elektron ships one OS 1.40C image for the MKI and MKII, but all hardware
> testing here is on an MKI.

> **Learn how to recover BEFORE flashing.** A brick here is *soft and recoverable* — the
> Startup Menu (bootloader) lives in a region the OS update doesn't touch, so you can
> always return to a good OS over MIDI. Read §1 first.

---

## 0. What you need

- [ ] An **Octatrack**.
- [ ] A **5-pin MIDI (DIN) interface** between the computer and the Octatrack's MIDI IN.
      ⚠️ **The MIDI upgrade does NOT work over USB** — it has to be MIDI DIN. (Or use the
      CF-card path in §3a, which needs no MIDI.)
- [ ] **SysEx Librarian.app** (Mac) or any tool that sends a raw `.syx`.
- [ ] **The build you want** — the `.syx` (MIDI) or `.bin` (CF card) from `out/`.
- [ ] **The official rescue firmware** (essential!):
      `downloads/extracted/OCTATRACK_OS1.40C.syx`.
- [ ] **Stable power** — don't power from a dubious strip; don't move the unit while
      flashing.

---

## 1. Safety net — the recovery path (READ THIS FIRST)

If something goes wrong (a "Z" screen, won't boot, a hang), **don't panic**:

1. Turn off the Octatrack.
2. Holding **[FUNC]**, turn it on → the **STARTUP MENU**.
3. Press **[TRIG 3]** → **MIDI UPGRADE** → "READY TO RECEIVE MIDI UPGRADE…".
4. From SysEx Librarian, send the **official rescue OS**
   (`downloads/extracted/OCTATRACK_OS1.40C.syx`).
5. Wait for "PREPARING FLASH" → "UPDATING FLASH". **Don't power off.** You're back on the
   factory OS.

This menu works **even if the OS is corrupt** (it's the bootloader), which is why the real
risk of losing the unit is very low.

> **Also:** [TRIG 2] = EMPTY RESET (resets the battery-backed RAM and clears settings,
> **but NOT the CF card**). Rarely needed, but it's there.

---

## 2. Before flashing — backup

Flashing the OS **does not touch the CF card** — your sets, projects and samples stay
intact. Even so:

- [ ] Back up your CF card to the computer (USB DISK MODE and copy everything), or at
      least the projects that matter.
- [ ] Optional: create a **RESTORE POINT** of your active project.

---

## 3a. Flash from the CF card — the fast way (recommended)

Manual §8.5.2. Reads the file off the card instead of trickling it over MIDI, so it takes
seconds rather than minutes.

1. Connect the OT over USB, select **USB DISK MODE**, press **[YES]**. The CF card appears
   as a drive.
2. Copy your build's `.bin` (for example `out/OCTATRACK_MUTE_MODES.bin`) to the **ROOT**
   of the card — not inside any folder.
3. **Eject the card properly**, then leave USB DISK MODE on the OT. Skipping the eject can
   leave the write in cache, and the OT reads a truncated file.
4. **PROJECT → OS UPGRADE → [YES]**, and confirm.

The active project is synced to the card automatically before the upgrade. This needs a
unit that boots; if it doesn't, use §3b.

---

## 3b. Flash over MIDI — for recovery, or if the card path fails

1. **Connect MIDI**: your interface's MIDI OUT → the Octatrack's **MIDI IN** (DIN, not
   USB).
2. **Open SysEx Librarian** and choose your MIDI interface as the destination.
3. **Drag** your build's `.syx` into the SysEx Librarian list.
4. On the Octatrack: turn it off, hold **[FUNC]** and turn it on → **STARTUP MENU**.
5. Press **[TRIG 3]** (MIDI UPGRADE) → **"READY TO RECEIVE MIDI UPGRADE…"**.
6. In SysEx Librarian, select the file and press **Play**. The **[TRIG]** lights turn on
   one by one as it receives. **It takes a while.**
7. When the transfer finishes: **"PREPARING FLASH"**, then **"UPDATING FLASH"**.
   **⚠️ DO NOT POWER OFF OR DISCONNECT** during "…FLASH" — interrupting here corrupts the
   OS (→ "Z" screen).
8. The OT may update the bootstrap afterwards. **Wait** for it to finish or to tell you
   to restart.

> If the OT loses sync, lower SysEx Librarian's send speed in *Preferences* (increase
> "pause between messages", e.g. to 100–300 ms).

---

## 4. Verify the flash

**Power-cycle once** before judging anything (see §6 (a-bis)). Then check
**SYSTEM → SYSTEM STATUS → OS VERSION**:

| build | OS VERSION |
|---|---|
| MUTE_MODES, SIDECHAIN_COMPRESSOR, RELOAD_FROM_PROJECT, QUANTIZE_LIVE_REC_TOGGLE | `140C_KYOTI` |
| SIDECHAIN_COMPRESSOR light (the earlier version, WIP) | `140C_SCLT` |
| KYOTI V1.6 (the features in one image) | `KYOTI V1.6` |
| KYOTI V1.5 (the previous one) | `KYOTI V1.5` |
| KYOTI V1.4 (the previous one) | `KYOTI V1.4` |
| DIRECT_JUMP_KYOTI | `140C_KDJ7` |
| REC_TRIG_MUTE | `140C_RTM` |
| BLACKPYRAMIDS_303 | `140C_BP303` |
| VARISPEED | `140C_VARI1` |
| VARISPEED_EMUS | `140C_VEM10` |
| ERASE_EMPTY_TRIGLESS_LOCKS and the BATCH_BUGFIXES builds | `1.40C` (stock string — check by behaviour) |
| a feature + BATCH_BUGFIXES | `BUG_` + the feature (`BUG_MUTEDT`, `BUG_DJV7`, `BUG_SC3X`, `BUG_RL3`, `BUG_QLREC`, `BUG_TRIGLK`, `BUG_RTM`, `BUG_BP303`, `BUG_VARI`, `BUG_VEM10`) |

PERSONALIZE is reset by every flash, so features are off until you re-enable them. A
quick check for each:

- **MUTE_MODES** — PERSONALIZE → MUTE MODE → `OTFX`. Mute a track playing through a
  reverb: the dry sound cuts, the tail rings out, and unmuting picks up in time.
- **DIRECT_JUMP_KYOTI** — hold `[PTN]`, tap `[YES]` → toast `ON`. While playing, cue
  another pattern: it takes over on the next step, in time with the metronome.
- **SIDECHAIN_COMPRESSOR** — COMPRESSOR on a track, page 2 (`RMS MON KEY KGN KBAS KWID`) →
  `KEY` = another track playing a kick. The compressed track ducks on the kick; `MON` lets you
  hear the key. Turn `KBAS` and `KWID` through their ranges (Hz, then octaves); with `MON` on,
  raising `KBAS` moves the whole band up, and `KBAS OFF` + `KWID` sweeps a plain low-pass.
  A project saved on stock firmware with a COMPRESSOR in it: that compressor's page 2
  reads `MON OFF`, `KEY OFF`, `KGN` centred, `KBAS` and `KWID` `OFF`, and it compresses as it
  did on stock; a KEY you set on this firmware is kept. A COMPRESSOR saved with the earlier
  version (before 22 Oct 2026) keeps its KEY; its other page-2 knobs need setting again. With a keyed COMPRESSOR running, DARK REV
  and PLATE REV in FX2 on T1 and on T5 (long settings) ring clean, with no other track's
  audio in them.
- **RELOAD_FROM_PROJECT** — save the bank, change a track's trigs, then `[PTN]` +
  `[TRACK n]` while playing: the saved trigs come back without the transport stopping.
  **MIDI tracks (fix of 2026-10-25):** in a pattern, give MIDI track 2 and audio track 2 a few
  trigs each, SAVE the project, then change both tracks' trigs (unsaved). On the MIDI tracks
  (`[MIDI]`), `[PTN]` + `[TRACK 2]` → `TRK SEQ RELOADED`: M2 is back to its saved trigs, and
  audio T2 (back on the audio side) still has your unsaved change. Same with `[BANK]` +
  `[TRACK 2]` (sequence + the saved Part; change a MIDI track setting after saving the Part to
  see the Part come back). On the audio side `[PTN]` + `[TRACK 2]` still reloads T2 only.
- **QUANTIZE_LIVE_REC_TOGGLE** — hold `[REC]`, tap `[PLAY]` → toast `LIVE REC: QUANTIZED` or
  `LIVE REC: UNQUANTIZED`; tap `[PLAY]` again while it is up → the setting inverts. With
  PROJECT → PERSONALIZE open, the QUANTIZE LIVE REC check mark changes at the same moment.
- **ERASE_EMPTY_TRIGLESS_LOCKS** — make a trigless lock with one p-lock, erase that lock
  in live record: the step goes dark.
- **REC_TRIG_MUTE** — a track with recorder trigs on every pattern cycle: hold its
  `[TRACK]`, press `[REC]` → toast `REC TRIGS MUTED`, the edge icon shows `..▶`, GRID REC
  does not switch, the current recording finishes and the next cycle does not record.
  `[TRACK]` + `[REC]` again → `REC TRIGS UNMUTED`, recording resumes. Stopped, a muted track
  shows `..■`. Mute T1 alone, then hold T1 + T3 and press `[REC]` → `REC TRIGS TOGGLED`, T1
  unmuted and T3 muted. The toast lasts 1 s while the track key stays held (also after
  `[REC]` is let go), and closes the moment the track key is released. `[REC]` with no track
  key held still switches GRID REC; `[TRACK]` +
  `[YES]` / `[NO]` show stock's `ARM REC TRK` / `DISARM REC TRK`.
- **BLACKPYRAMIDS_303** — double-tap T1, pick `BLKPYRAMD`, put trigs on a few steps: each plays
  a 303 note. P-lock `PTCH` and `ACC` on a step; put a trigless trig after a note (it holds) and a
  slide trig on the next note (it glides). FX menus no longer offer SPRING REVERB. Choosing it on
  T2 as well is refused with `ONE 303 PER CORE!`; on T5 it is allowed. Stopped, right after
  power-on: the track key plays a held note; TRIG + YES on a step replays it every time; a
  MIDI note on the track's channel plays (AUDIO NOTE IN on). Hold three trigs and push-turn
  `PTCH`: all three locks move by the same octave and the display follows. An `ACC` lock of 127
  with the knob at 127 is the strongest accent; at 0 the step plays unaccented. Sweep `WAVE` on a
  held line: the level holds. A bright line (CUT high, RES 0) with full accents at VOL 99:
  rounded, no fizz. Sweep RES up from 0: a touch less boom below RES 20, the same from 20 up;
  RES locks between 0 and 20 on alternate steps do not click. A line with accents on neighbouring steps
  at high RES: the accents stack into a rising sweep. Sweep CUT from 0 to 127: still clearly audible at
  0, brighter all the way, one octave more above 100; at CUT 127 with RES 127 the resonance stays below
  piercing. Turn VOL across 64 / 65 and back while a note holds: no click or pop. Turn RES and ACC
  through their range: every part of the knob changes the sound.
- **VARISPEED** — a FLEX loop whose ATTR TEMPO matches it, TSTR on `VARI` (SRC SETUP, the
  fifth position): PTCH reads `QUAN`. Change the project tempo: the loop speeds up and slows
  down with its pitch and stays in time. QUAN `2/1` plays it an octave up at double speed.
  TSTR back to BEAT: PTCH shows its old value.
- **VARISPEED_EMUS** — as VARISPEED, and TSNS reads `EMUS` on a VARI track: `OT`, `S950`,
  `SP12` from low to high. Retrigger after a turn: `S950` adds grit, `SP12` sounds duller and
  crunchier. FX menus no longer offer SPRING REVERB. Put `SP12` on all four tracks of one core
  with a heavy FX stack: a turn or an FX choice that would overload the DSP is refused with
  `MAX DSP: EMU LIMIT`.
- **MIDI_PLAYS_FREE_FIX** — a PLAYS FREE MIDI track, trig quantize DIRECT, SCALE MODE PER
  TRACK, notes on steps 1 and 2: a manual trig keeps it running instead of stalling.
- **EMPTY_PATTERN_LED_FIX** — a pattern whose only content is a p-lock on a MIDI track:
  its LED lights under `[PTN]`. Hold `[BANK]` for a few seconds: the grid stays lit and
  responsive.
- **PART_CHANGE_CARRYOVER_FIX** — a track that is PICKUP on one Part and FLEX on
  another: switching patterns across the Parts plays the FLEX sample, not the old loop.

---

## 5. Reverting to the official firmware

Reflash the official one with the **same steps in §3**, sending
`downloads/extracted/OCTATRACK_OS1.40C.syx`. Your CF card and projects are not affected.
Nothing the features store survives a revert except the PERSONALIZE block, which an EMPTY
RESET clears, and one VARISPEED setting:

- **VARISPEED / VARISPEED_EMUS / KYOTI: set every VARI back to OFF, AUTO, NORM or BEAT
  before reverting, and save.** A track's `TSTR` VARI is saved in the Part, and a sample's
  audio-editor TIMESTRETCH VARI is saved in its `.ot` file. Stock firmware does not know
  the value: it plays such a track with NORMAL timestretch instead of tape-style, and its
  `TSTR` field may show junk text.

---

## 6. If flashing fails, or the flashed OS misbehaves

**First, always: get back to a known-good OS** — the §1 recovery path works even from a
black or "Z" screen. Then work out what happened.

### (a) The transfer or flash never completed

Symptoms: SysEx Librarian errors or stalls; the TRIG lights stop advancing; "PREPARING
FLASH" never appears; the CF `.bin` path reports `-2` (not a valid OS), `-3` (length) or
`-4` (checksum).

This is almost never the patch — it's the transport. The builds differ from stock by at
most several kilobytes and repack through the same checksummed container as the
official file.

- **MIDI:** lower SysEx Librarian's send speed. Use a real 5-pin DIN interface; try
  another interface or cable.
- **CF card:** re-copy the `.bin` to the card **root**, **eject properly** (a cached,
  truncated write is the usual `-4`), and re-seat the card.
- Re-verify the file: `elektron-firmware-tool -i <file>.syx` must print `checksums : ok`;
  for the `.bin`, `python3 tools/bin_decode.py <file>.bin` must print `✓ COINCIDE`. If
  either fails, rebuild it.

### (a-bis) It boots, but audio is garbled — power-cycle first

An OS upgrade rewrites program memory but does **not** clear the DSP state RAM, so audio
can be garbled right after `UPDATING FLASH` — worst on delay and reverb. **Turn the unit
fully off and on before judging anything.**

### (b) It finished "UPDATING FLASH", but won't boot, traps or hangs

The feature you flashed is suspect. Recover with §1, then flash stock or another final
build to confirm the unit itself is fine, and report which build failed. You are never
stuck: the §1 recovery path always brings the unit back.

### (c) It boots and runs, but a feature doesn't work

- **Did the flash take?** Check OS VERSION against §4. PERSONALIZE is reset by every
  flash — features are off until you re-enable them.
- **Re-run the quick check** from §4.
- **A regression** (something that worked on stock misbehaves): note the exact steps and
  whether it also happens on stock. Report both.

---

## Risk notes

- This firmware is **modified by you, for your own unit, for study.** It is not official
  Elektron firmware and has no support from them.
- Every patch is checked in emulators before it is flashed. That is necessary, not
  sufficient: builds that passed every emulator check have still misbehaved on hardware.
  Each feature's hardware status is in [`README.md`](README.md) — read it before you
  flash, and have the recovery net ready (§1, §6).
- The only truly delicate moment is **"UPDATING FLASH"**: don't cut power there.
- The risk of a *hard*, unrecoverable brick is very low: a normal OS update does not
  touch the bootloader.

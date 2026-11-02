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
| KYOTI V1.7 (the features in one image) | `KYOTI V1.7` |
| KYOTI V1.6 (the previous one) | `KYOTI V1.6` |
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

- **KYOTI V1.7 walk-through** (FINAL 2026-11-02, flashed: all of it passed; `out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.7.syx`).
  V1.6's features unchanged; only addresses move (NOTES 2026-11-01).
  1. A track with FX2 = DELAY at its defaults (BASE 0, WDTH 127), FB up: the repeats stay as bright as on
     stock 1.40C. On V1.6 they were low-passed around 5 kHz and darkened with every repeat.
  2. Sweep BASE and WDTH: the tone moves smoothly; no setting turns the echo thin / phasey.
  3. DIRECT JUMP (now from DRAM): `[PTN]`+`[YES]` -> `DIRECT JUMP ON`; cued patterns land on the next step, in
     time, as on V1.6.
  4. The moved pieces, one look each: PERSONALIZE lists MUTE MODE and switching it works; COMPRESSOR page 2
     (MON switch, KEY, KBAS, KWID); MIDI PLAYS FREE; the pattern LEDs under `[PTN]`; `[TRACK]`+`[REC]`
     `REC TRIGS MUTED`.
  5. `BUG_VEM10` (rebuilt, WIP): the same DELAY check; a pattern change between Parts with PICKUP/FLEX
     plays the right sample; the pattern LEDs under `[PTN]`.

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
- **KYOTI CL3 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = KYOTI V1.7 (FINAL, `ea1ffc08…`: the DELAY fix) with Clyps (as CLYPY) in place of RELOAD_FROM_PROJECT, tied to DIRECT
  JUMP (scope §1.10). (CL1 / CL2 were built on V1.6: never flash them.)
  1. Boot: OS VERSION `KYOTI CL3`. A Flex list's FREE MEM reads ~10 MB less than on V1.7 (Clyps' buffers).
  2. Hold `[PTN]`, press `[BANK]`, let go of `[BANK]` only, press `[YES]`: `DIRECT JUMP ON` toast, Clyps stays
     open, nothing loads, no SELECT PATTERN when `[PTN]` is released. Again: `DIRECT JUMP OFF`.
  3. DIRECT JUMP ON, playing: load a slot onto a track in Clyps: it lands at the next step (not at the
     pattern's end), in time with the other tracks. An ALL load (`[FUNC]`) too.
  4. DIRECT JUMP OFF, playing: a load lands at the pattern's end (or its CHAIN AFTER point), as in CLYPY.
  5. DIRECT JUMP ON: jump to another pattern while playing: as in V1.7; Clyps loads keep working after it.
  6. RELOAD_FROM_PROJECT's chords outside Clyps are gone ([PTN]/[BANK]+TRACK outside Clyps = stock);
     inside Clyps they are the card reloads, as in CLYPY.
  7. The rest of KYOTI beside Clyps: `[FUNC]`+TRACK mutes inside Clyps follow MUTE MODE; `[TRACK]`+`[REC]` (outside
     and inside Clyps) = `REC TRIGS MUTED`; `[YES]`+TRACK (YES first) = `TRACK n TEMP SAVED`; a VARI track: an ALL load from
     a slot whose track has another TSTR / QUAN, then check PTCH / QUAN read right and the pitch follows.

- **CLYPS — CLYPY.** Image `140C_CLYPY` = CLYPX (flashed 2026-10-31, all good) + temp save / reload toasts:
  `[YES]`+TRACK `TRACK n TEMP SAVED` (one line); MIDI `MIDI TRACK n` / `TEMP SAVED`; `[NO]`+TRACK `TRACK n` /
  `TEMP RELOADED`, MIDI `MIDI TRACK n` / `TEMP RELOADED` (two lines: 122-143 px in one, the line holds 113).

- **CLYPS — CLYPX walk-through.** Image `140C_CLYPX` = CLYPW + no stray `!` beside the machine glyph in the
  group, and the card reload toast with ALL back.
  1. In Clyps, hold `[CUE]`: the active track's tab goes away with no `!` beside its glyph.
  2. Still holding `[CUE]`, TRACK 2 and TRACK 4: whole tabs, no `!`. Add the active track too: whole tab, no `!`.
  3. Release `[CUE]`, `[NO]`: the tab is back on the active track, no `!` anywhere.
  4. Card reloads in Clyps: `[BANK]`+TRACK shows `TRACK n ALL` / `RELOADED FROM PROJ` (MIDI side: `MIDI TRACK n
     ALL` / `RELOADED FROM PROJ`); `[PTN]`+TRACK still `TRACK n SEQ` / `RELOADED FROM PROJ`.

- **CLYPS — CLYPW walk-through.** Image `140C_CLYPW` = CLYPT + the whole sidebar tab for the group,
  "FULL" renamed "ALL" in the Clyps labels, no ALL in the save / reload toasts, one-line toasts where they
  fit. (CLYPV, the same without the toast change, was never flashed.) (CLYPT flashed 2026-10-31: track LEDs correct; the tab
  followed the group in its upper half only, the play-status half stayed on the active track.)
  1. In Clyps, hold `[CUE]`: no tab anywhere (both halves: machine glyph AND play-status glyph plain), no
     `!` beside a machine glyph.
  2. Still holding `[CUE]`, TRACK 2 and TRACK 4: each gets the whole tab (both halves inverted), exactly like
     a stock active-track tab; T8 (or whichever is active) none. TRACK 4 again: out; again: in.
  3. Release `[CUE]`, then `[NO]`: the whole tab is back on the active track.
  4. ALL wording: `[FUNC]` held reads `LOAD: TRK ALL` (MIDI `LOAD: MIDI TRK ALL`); on ORIG `LOAD: ORIG TRK ALL`
     / `LOAD: ORIG MIDI ALL`; in a group `LOAD: ALL` / `LOAD: ORIG ALL`.
  5. Toasts, no ALL, one line where it fits (the toast line is 113 px): `[YES]`+TRACK `TRACK n SAVED`, MIDI
     `MIDI TRACK n SAVED`; `[NO]`+TRACK `TRACK n RELOADED`, MIDI two lines `MIDI TRACK n` / `RELOADED` (one
     line would be 1 px too wide). Card reloads in Clyps stay two lines: `TRACK n SEQ` / `RELOADED FROM PROJ`
     ([PTN]+TRACK) and `TRACK n` / `RELOADED FROM PROJ` ([BANK]+TRACK).

- **CLYPS — CLYPT walk-through.** Image `140C_CLYPT` = CLYPR + multi-track loads with a `[CUE]` group
  (scope §1.9). Run CLYPR's three steps below too (CLYPR was never flashed).
  1. In Clyps, hold `[CUE]`: the header's left reads `MULTI BNK A`, the right `LOAD: SEQ`; the sidebar tab
     leaves the active track; the track LEDs show only mute / cue (green, off, flashing). Nothing is cued.
  2. Still holding `[CUE]`, press TRACK 2 and TRACK 4: both get the sidebar tab and the active track's LED
     colour (red; yellow if muted). TRACK 4 again: out; again: in. Release `[CUE]`: the group stays.
  3. Pick a slot (trig or `[YES]`): T2 and T4 each load their OWN sequence from that slot; the active track
     (not a member) keeps its own. Hold `[FUNC]`: `LOAD: FULL`, and a load brings machine / FX too.
     Transport running: each member lands as a one-track load does.
  4. Box on ORIG: `LOAD: ORIG SEQ` (`[FUNC]`: `LOAD: ORIG FULL`); `[YES]`, `[PAGE]`, `[FUNC]`+`[PAGE]`: every
     member gets its own original back.
  5. A plain TRACK 3: the slots now show T3's sequences; the tabs and LEDs stay on T2 / T4, and loads still go
     to them.
  6. Hold `[CUE]`, press `[MIDI]`, TRACK 1, `[MIDI]`, release: MIDI track 1 joins (tab on the MIDI side).
  7. `[NO]`: the group is gone, the tab and the LED colours are back on the active track, Clyps stays.
     `[NO]` again closes Clyps. Outside Clyps, `[CUE]`+TRACK cues as in stock.
  8. Wording to judge: in a group the right label drops `TRK` / `MIDI TRK` (`LOAD: SEQ`, `LOAD: ORIG FULL`):
     the long per-track labels collide with `MULTI BNK A`.

- **CLYPS — CLYPR walk-through.** Image `140C_CLYPR` = CLYPQ + three fixes.
  1. Put the box on your own pattern's slot (the highlighted one) and load it (`[YES]` or its trig):
     the highlight bar flashes like any other slot.
  2. On a Part you have saved (SAVE PART), make a FULL load that changes a track's machine / FX, then
     bring it back (`[FUNC]`+`[YES]` on ORIG, or a FULL load of the original): when the Part is again
     identical to its saved version, stock's Part-edited mark is gone; while it differs, it shows.
  3. Hold `[PTN]`+`[BANK]` inside Clyps and press `[PAGE]` (or `[YES]`): the `ORIG PTN+PART` box flashes.

- **CLYPS — CLYPQ walk-through.** Image `140C_CLYPQ` = CLYPP + SEQ / FULL on the MIDI side + new toasts.
  1. MIDI side: header `LOAD: MIDI TRK SEQ`; hold `[FUNC]`: `LOAD: MIDI TRK FULL`. A plain trig loads only
     the sequence (the track's channel / program / CCs stay); `[FUNC]` + trig brings them too. On ORIG:
     `LOAD: ORIG MIDI SEQ` / `LOAD: ORIG MIDI FULL` (`[YES]` / `[FUNC]`+`[YES]`, also `[PAGE]` / `[FUNC]`+`[PAGE]`).
  2. Card reload toasts: `TRACK n SEQ` / `RELOADED FROM PROJ`, `TRACK n FULL` / ..., `MIDI TRACK n ...`,
     and `PATTERN A06` / `RELOADED FROM PROJ`.
  3. Temp save / reload toasts: `TRACK n FULL SAVED`; MIDI `MIDI TRACK n FULL` / `SAVED`; reload
     `TRACK n FULL` / `RELOADED` (MIDI: `MIDI TRACK n FULL` / `RELOADED`); nothing saved:
     `TRACK n: SAVE FIRST!` (MIDI: `MIDI TRACK n` / `SAVE FIRST!`).

- **CLYPS — CLYPP walk-through.** Image `140C_CLYPP` = CLYPO + reloads from the CF card (scope §1.8).
  Use a throwaway copy of a project and SAVE it first (the reloads read the saved `.strd`).
  1. In Clyps, change a track's trigs, its machine settings and an FX. Hold `[PTN]` alone and press
     its TRACK key: toast `TRK n` / `CF SEQ RELOAD`; the trigs are back as saved, the machine / FX
     settings stay as you changed them. The transport keeps running if it was.
  2. Change them again. Hold `[BANK]` alone + TRACK: toast `TRK n` / `CF FULL RELOAD`; trigs AND that
     track's machine, FX, pages, scene locks come back. Other tracks of the same Part keep your
     changes (not the whole Part). No SELECT BANK after letting go of `[BANK]`.
  3. MIDI side: the same with `MIDI TRK n` (channel, program, CCs come back with FULL).
  4. Hold `[PTN]`+`[BANK]` and press a TRACK key: no reload.
  5. Change several tracks of a pattern and its Part. Hold `[PTN]`+`[BANK]` (from outside Clyps) and
     press that pattern's trig: toast `PTN A05 CF RELOAD`; the whole pattern and its Part are as saved;
     Clyps closes. Pressed inside Clyps: the same, Clyps stays. Try another pattern than the
     playing one too (it reloads that one, of the playing bank).
  6. A project never saved: stock's "THIS BANK HAS NEVER BEEN SAVED!" message, nothing changes.

- **CLYPS — CLYPO walk-through.** Image `140C_CLYPO` = CLYPN (flashed, all good) with a shorter load
  confirmation: after a load the select box flashes inverted 3 times in 0.5 s (was ~0.75 s, faster).

- **CLYPS — CLYPN walk-through.** Image `140C_CLYPN` = CLYPM + new header words and the chord's grid.
  1. Header left: `T6 BNK A`, always (never hidden). Right: `LOAD: TRK SEQ`; `[FUNC]`: `LOAD: TRK FULL`;
     on ORIG `LOAD: ORIG TRK SEQ` / `LOAD: ORIG TRK FULL`; MIDI side `LOAD: MIDI TRK`, on ORIG
     `LOAD: ORIG MIDI TRK`; chord held `LOAD: ORIG PTN+PART`.
  2. In Clyps, hold `[BANK]` then `[PTN]`, and also `[PTN]` then `[BANK]`: the grid shows the same
     pattern view both ways (your pattern red, patterns with data green). `[BANK]` alone still
     shows the bank view. With the chord held a trig does nothing yet (the pattern reload comes next).
  3. `[PTN]` then `[BANK]`, let go of `[BANK]` first: `[PTN]` + trig is again a stock pattern change.
  4. While `[PTN]`+`[BANK]` are held (begun outside or inside Clyps) the select box is gone from the
     slots; let go of either key: it is back on the slot it was on.
  5. `[PTN]`+`[BANK]` held + `[YES]`: the same ORIG PTN+PART restore as + `[PAGE]`; chord begun
     outside Clyps: Clyps closes after; begun inside: it stays open.

- **CLYPS — CLYPM walk-through.** Image `140C_CLYPM` = CLYPL (its 4 steps below) + the audio temp
  reload now brings the whole sound back.
  1. On an audio track, hold `[YES]`+TRACK (temp save). Change its machine settings, FX and a scene
     lock, and edit a trig. Hold `[NO]`+TRACK: the sequence AND the machine, FX, page values, scene
     locks and LFO designer are back as saved (stopped: at once; playing: at its next step).
  2. The Part shows as edited afterwards (as after any load with machine / FX).
  3. Load an unnamed sequence from another bank: your pattern's slot reads e.g. `B14 06 TR` (bank,
     2-digit pattern, 2-digit trig count); `B04 LOCKS` / `B04 ---` for the other kinds.
  4. Empty slots: `---` sits in the middle of the label (places 4-6).
  5. Unnamed slots with trigs read like that: `A01 15 TR` (bank, pattern, trig count; no dashes).
  6. Load confirmation: after a trig or `[YES]` load, the select box flashes as an inverted bar
     (text inverted) for about 0.75 s. An arrow, `[BANK]`+arrows, or a TRACK key during it stops
     it at once; another trig restarts it on the new slot. `[YES]` / `[PAGE]` with the box on
     ORIG flashes the ORIG header box the same way.
  7. Mutes in Clyps: `[FUNC]`+TRACK mutes / unmutes that track as in stock; Clyps stays open and the
     active track does not change.
  8. Parts menu in Clyps: `[FUNC]`+`[MIDI]` opens the Parts menu over Clyps; leave it (`[NO]`): Clyps
     is still there, as it was. Other stock menus / windows opened from Clyps now also open over it
     instead of closing it -- tell me if any of them misbehaves that way.
- **CLYPS — CLYPL walk-through.** Image `140C_CLYPL` (CLYPK, all points passed + new wording).
  1. Audio: `LOAD: TRK SEQ`; hold `[FUNC]`: `LOAD: TRK SEQ/MCH/FX` (the left side then reads only
     `T6`, there is no room for `BANK X` beside it).
  2. Box on ORIG: `LOAD: ORIG TRK SEQ`; with `[FUNC]`: `LOAD: ORIG TRK SEQ/MCH/FX` (left: `T6`).
  3. MIDI side: `LOAD: MIDI TRK`, the box on `MIDI TRK`; on ORIG: `LOAD: ORIG`.
  4. Chord held: `LOAD: ORIG PTN/PART` (unchanged).

- **CLYPS — CLYPK walk-through.** Image `140C_CLYPK` (CLYPJ + your changes after flashing it).
  1. Boxes: the highlight bar and the select box have square corners again.
  2. Header: `LOAD: ` then `SEQ` / `SEQ/MCH/FX` (`[FUNC]`) in a dark box (square corners). On ORIG:
     `LOAD: ` then `ORIG SEQ` / `ORIG SEQ/MCH/FX` (`[FUNC]`) / `ORIG` (MIDI) in a dark box; with the
     chord held: `LOAD: ` + a dark `ORIG PTN/PART`. Holding `[BANK]` alone: `BANK X` in a dark box.
  3. The select box's trig LED looks like a stock p-locked trig: red, with a short yellow flash
     at stock's own rate. Compare it with a real p-locked trig outside
     Clyps (GRID REC). Your pattern stays solid red; a cued load solid yellow.
  4. Box on ORIG (track changed): all four page LEDs red with the same p-lock yellow flash. Run ORIG
     (`[YES]`, or `[PAGE]`): solid red. Cued while playing: solid yellow until it lands, then red.
     Chord held: the same for the whole pattern; chord + `[PAGE]`: solid red after.
  5. Slots without a name read `-06 TRGS-` (two digits, a leading 0 below 10); `LOCKS` / `---` as before.

- **CLYPS — CLYPJ walk-through.** Image `140C_CLYPJ` (CLYPH + your 2026-10-29 changes; CLYPI was
  never flashed).
  1. Looks: the highlight bar and the select box have their 4 corner pixels off. Header: an
     outline (no fill) round `BANK X` while you hold `[BANK]` alone; `LOAD: ` then an outlined
     `SEQ` / `SEQ/MCH/FX` (`[FUNC]`); on ORIG `LOAD: ORIG SEQ` / `ORIG SEQ/MCH/FX` / MIDI `ORIG`.
  2. `[BANK]` outside Clyps: nothing on press; SELECT BANK on release. `[BANK]`+trig still picks a
     bank. Entering Clyps `[BANK]` first: no SELECT BANK flash, and no box round `BANK X`.
  3. Grid: your pattern red, a cued load solid yellow, the select box flashing red.
  4. `[PAGE]`: this track's original sequence; `[FUNC]`+`[PAGE]`: with its machine / FX.
  5. Hold `[PTN]`+`[BANK]` (from outside): Clyps opens showing `LOAD: ORIG PTN/PART` (left side
     `T6` only); all four page LEDs: red if the pattern is all original, flashing red if not. Press
     `[PAGE]`: the whole pattern and its Part come back (cued while playing), and Clyps closes.
     Same chord pressed inside Clyps + `[PAGE]`: the same restore, Clyps stays open.
  6. Box on ORIG: all four page LEDs red (original) / flashing red (changed) / yellow (restore cued);
     move off ORIG and let go of the chord: the page LEDs step as normal again.
  7. Temp save a track (`[YES]`+TRACK), load another slot onto it, reload it (`[NO]`+TRACK): your
     pattern's slot reads `SAVED SEQ`; nothing reads SAVED in the header.

- **CLYPS — CLYPH full test list.** Image `140C_CLYPH` (CLYPG + FULL loads; CLYPG was never
  flashed, so its items are in here). Use a **throwaway copy** of a project with: patterns using
  different Parts (different machines / FX on a track), one PER TRACK pattern with CHAIN AFTER = 4,
  one NORMAL pattern, a 2x-scale track, and MIDI tracks with different channels / programs.
  A. Boot and basics
     1. The unit boots and plays a project; samples load as usual.
     2. Open with `[PTN]` held + `[BANK]`, and again with `[BANK]` held + `[PTN]`: no SELECT window
        or toast; letting go of both keys keeps Clyps open; `[NO]` closes it.
     3. After closing: stock `[PTN]` / `[BANK]` taps open their windows, trigs edit, no key stuck.
  B. `[BANK]` / `[PTN]` inside Clyps (new in CLYPG)
     4. Hold `[BANK]`: `BANK X` in the header is boxed and inverted (like `ORIG`); the arrows page
        the bank; let go: box gone, no SELECT BANK.
     5. Tap `[BANK]`: SELECT BANK opens over Clyps and stays; `[NO]` closes it, Clyps stays. Tap
        `[BANK]` twice: the second tap closes it.
     6. `[BANK]` held + trig: bank pending (`BANK X: SELECT PTN`), Clyps stays, nothing changes yet;
        then a trig: real bank + pattern change, Clyps closes. Once with `[BANK]` let go between.
     7. Tap `[PTN]`: SELECT PATTERN over Clyps; `[NO]` closes it. `[PTN]` + trig: real pattern
        change for all tracks, Clyps closes.
     8. The `[PTN]`+`[BANK]` chord pressed again inside Clyps: nothing.
  C. MIDI side
     9. In Clyps, `[MIDI]`: view and grid switch side at once; again: back.
     10. MIDI side: no `LOAD: SEQ` in the header; `[FUNC]` changes nothing; `ORIG` reads `ORIG`.
  D. Loads, stopped
     11. Plain trig on an audio track: sequence only; machine / FX unchanged.
     12. `[FUNC]` held: header `LOAD: SEQ/MCH/FX`; `[FUNC]` + trig on a slot whose pattern has
         another Part / machine: sequence + machine, FX, page values, scene locks, LFO designer;
         the pages show the new values; Part marked edited. `[FUNC]`+`[YES]` on the box: the same.
     13. MIDI track: a plain trig brings channel, bank, program, page values with the sequence.
         Tell me if anything stays behind (e.g. the arpeggiator note sequence).
  E. Loads, playing (never confirmed on hardware so far)
     14. Default CHAIN AFTER: trig -> slot flashes yellow, lands at the end of the pattern, red.
     15. PER TRACK pattern, CHAIN AFTER = 4: lands at the next 4-step point, in step with the other
         tracks (a 64-step sequence picked near step 9 enters at its own step 9-ish, not step 1).
     16. A 2x track onto a 1x track and the reverse: lands on time at its own rate.
     17. Pick a slot, then pick the slot already playing: the cue is cancelled.
     18. Cue a load, then a stock pattern change that lands first: the Clyps cue is dropped.
     19. Cue on several tracks (TRACK keys between picks): all land together.
     20. `[FUNC]` + trig while playing: the machine / FX change lands with the sequence; the other
         tracks play on undisturbed. Try FLEX -> STATIC or THRU, and to / from PICKUP.
  F. Originals
     21. Box on `ORIG`: `ORIG SEQ`; with `[FUNC]`: `ORIG SEQ/MCH/FX`. After a FULL load, `[YES]` puts
         the sequence back (machine stays new); `[FUNC]`+`[YES]` puts both back.
     22. `[PAGE]` undoes a load and a grid edit on the track; `[FUNC]`+`[PAGE]` restores every changed
         track of the pattern on one landing; playing: cued like a load.
     23. NORMAL pattern: load a slot of another length (it turns PER TRACK), then `[PAGE]`: NORMAL
         again, plays as before.
     24. The "x" left of a slot number: appears after a change, goes after a restore.
  G. Saved sequences (outside Clyps)
     25. Hold `[YES]` + TRACK n: `TRK n SAVED` toast. Change the track, hold `[NO]` + TRACK n:
         `TRK n RELOADED`, at once (stopped) / at its next step in step (playing). Nothing saved:
         `TRK n: SAVE FIRST`. Quick `[YES]` / `[NO]` taps still ARM / DISARM.
     26. MIDI track: save, change its channel, reload: the channel comes back too.
  H. Names (passed in CLYPF; one quick check)
     27. A named slot keeps its name after a load / ORIG / save + reload project.
  I. Lifetime and stress
     28. LOAD PROJECT, and a power cycle: saved sequences gone, `ORIG` = the project as loaded.
     29. Repeat B, D, E in a loop, both chord orders, different release orders: no stuck window,
         dead key or frozen panel.

- **CLYPS — CLYPG walk-through.** Image `140C_CLYPG`. As CLYPF (below), plus stock `[PTN]` /
  `[BANK]` inside Clyps and the BANK box. Open Clyps with the chord and let go of both keys first.
  1. Hold `[BANK]`: the header's `BANK A` turns into a dark box with lit letters (like `ORIG`).
     With it held, the arrows page the shown bank. Let go: the box goes, and no SELECT BANK
     appears.
  2. Tap `[BANK]` (no arrows): SELECT BANK opens over the Clyps view and stays. `[NO]` closes it;
     Clyps is still open. Tap `[BANK]` again, then tap it once more: the second tap closes it.
  3. Hold `[BANK]`, tap a trig: that bank is picked (`BANK x: SELECT PTN`), Clyps stays open and
     the playing bank has not changed. Tap another trig: a real bank + pattern change (cued if
     running), and Clyps closes. Try it once with `[BANK]` let go between the two trigs too.
  4. Tap `[PTN]`: SELECT PATTERN opens over Clyps; `[NO]` closes it, Clyps stays. Hold `[PTN]` and
     tap a trig: a real pattern change for all tracks, and Clyps closes.
  5. In Clyps, press the `[PTN]`+`[BANK]` chord again: nothing happens (no window, no change).
  6. After each of the above, outside Clyps: the trigs edit the sequence as normal, and a stock
     `[PTN]` / `[BANK]` tap still opens its window (nothing left stuck).
  7. In Clyps, press `[MIDI]`: the view and the grid switch to the MIDI track (slots, red / green)
     at once; press it again: back to the audio track.
  8. On the MIDI side: the header's right side shows no `LOAD: SEQ`, and holding `[FUNC]` changes
     nothing there. (A MIDI load still copies the sequence only; the track settings come later.)

- **CLYPS — CLYPF walk-through.** Image `140C_CLYPF`. As CLYPE (below), plus the new layout and
  names saved with the project. **Use a throwaway copy of a project for steps 4–5.**
  1. Layout: the "x" sits left of each number; the bars / boxes are narrower and the x is outside
     them; column 2's x is clear of column 1's bar / box; the select box is a full box, also
     right under the highlight.
  2. Name a slot (`[FUNC]`+`[BANK]` in Clyps), then SAVE PROJECT. Power-cycle, open Clyps: the
     name is there. Rename it, then RELOAD PROJECT: the saved name is back. Same with SAVE BANK /
     RELOAD BANK.
  3. LOAD another project and back: each project keeps its own names.
  4. EXPORT TO SET the throwaway project: the export finishes with no error; load the exported
     copy: its names are there.
  5. DELETE PROJECT the throwaway project: it is deleted with no "COULD NOT COMPLETELY DELETE"
     message (that message means our files were left behind -- tell me).
  On the card, each project folder now has clyps01..16.work / .strd files (2.5 KB each).

- **CLYPS — CLYPE walk-through.** Image `140C_CLYPE`. As CLYPD (below), plus the "edited" mark:
  1. After power-on or a project load, open Clyps: no slot has the small "x" left of its number.
  2. Load a sequence onto your pattern: your slot gets the x. Edit a trig in another pattern
     (outside Clyps), come back: that slot has it too.
  3. `[PAGE]` / `ORIG` (or a temp reload of the original, or a reload from the project): the
     x goes away. Edit the trig back by hand: it goes away too (the slot equals its original).
- **CLYPS — CLYPD walk-through** (names; still valid in CLYPE):
  1. In Clyps, put the box on a slot and press `[FUNC]`+`[BANK]` (EDIT): stock's name editor
     opens, titled `RENAME SEQUENCE`. It stops taking characters after 9. Check the screen under
     the editor looks normal (an emulator render showed odd text there).
  2. Type a name, `[YES]`: you are back in Clyps and the slot shows the name instead of its trig
     count. `[NO]` in the editor keeps the old name. On `ORIG`, `[FUNC]`+`[BANK]` does nothing.
  3. Load that slot onto your pattern: your slot shows the name too. A temp save / reload of the
     track keeps it; `ORIG` / `[PAGE]` brings back the name it had when loaded (none, for now).
  4. Names are not saved yet: a project load or a power cycle clears them.

- **CLYPS (WIP, test image `140C_CLYP9`)** — not in it yet: DIRECT JUMP timing, FULL loads, the
  page LEDs. New since CLYP7: its code and ~9.6 MB of buffers live in DRAM (the FREE MEM / MEMORY
  page still reads the stock total), saved sequences (F), originals (G). Use a project with a few
  patterns whose tracks differ (lengths, a 2x track, one pattern in PER TRACK mode with CHAIN
  AFTER = 4, one in NORMAL mode). Save the project on the card before you start.
  0. Boot: the unit starts normally and plays a project; samples load as usual.
  A. Opening and closing
     1. Hold `[PTN]`, press `[BANK]`: the Clyps window opens (header `T<n> BANK <x>`,
        `LOAD: SEQ`, 2 × 8 slots); the trigs light (full green = sample/note trigs, half green
        = other data only, off = empty, red = the sequence on the track). Release: no SELECT
        PATTERN, no SELECT BANK, no toast. Repeat with `[BANK]` first (SELECT BANK may flash
        for a moment: no release deferral in this image).
     2. Released without loading: the window stays (latched). `[NO]` closes it.
     3. After every close: `[PTN]` alone → SELECT PATTERN, `[BANK]` alone → SELECT BANK,
        trigs edit, every key responds.
  B. In Clyps (held or latched)
     4. UP/DOWN move the cursor 1 → 16 and wrap; LEFT/RIGHT change the bank A ↔ P and wrap,
        holding repeats quickly; the slots and trig LEDs follow.
     5. A TRACK key changes the track; the header, slots and LEDs follow. Then press `[MIDI]`
        and open Clyps on the MIDI side: the header reads `M<n>`, and the slots and trigs show
        the MIDI tracks' sequences (CLYP6 showed the audio tracks here). Load one: it lands on
        the MIDI track. (Double-tapping a TRACK key runs stock's double tap and closes Clyps.)
     6. Holding `[FUNC]` shows `LOAD: SEQ/MCH/FX` in the header (label only for now).
     6a. With the chord held, `[YES]` does nothing. Latched, hold `[PTN]` and tap `[YES]`: nothing
         loads and Clyps stays (DIRECT JUMP's toggle in KYOTI; this image has no DIRECT JUMP).
  C. Loads, transport STOPPED
     7. Chord held, tap a trig: that slot's sequence is on the track at once, its LED red;
        Clyps stays until you release the chord, then closes.
     8. Latched: move the cursor, `[YES]` → loads it and closes; or tap a trig → loads, closes.
     9. The bank shows unsaved changes afterwards (a load is an edit); stock reload brings the
        saved sequence back.
  D. Loads, transport PLAYING
     10. Pattern with CHAIN AFTER at its default: chord held, tap a trig → the slot turns
         **yellow**; at the end of the pattern it turns **red** and the new sequence plays from
         step 1, on time.
     11. PER TRACK pattern, CHAIN AFTER = 4: the load lands at the next 4-step point and plays
         **in step with the other tracks**; e.g. a 64-step sequence picked around step 9 enters
         at its own step 9 (or the next 4-step point), not at step 1.
     12. A 2x-scale track loaded onto a 1x track (and the reverse): lands on time at its own rate.
     13. Pick a slot, then the slot already playing: the yellow cue is cancelled.
     14. Cue a sequence, then cue a stock pattern change that lands first: the Clyps cue is
         dropped.
     15. Cue on several tracks (change track with TRACK keys between picks): all land at the
         same point.
  F. Saved sequences (one per track)
     16. In Clyps, `[FUNC]`+`[YES]`: the header shows a dark `SAVED` box (until the next key);
         Clyps stays.
     17. Load another slot onto the track, then `[FUNC]`+`[NO]`: the saved sequence is back.
         Stopped: at once. Playing: at the track's next step, in step with the other tracks
         (not from step 1). While it plays, the header shows `SAVED` and no slot is red.
     18. Change bank and pattern, `[FUNC]`+`[NO]` there: the saved sequence plays on that track.
         `[FUNC]`+`[NO]` on a track with nothing saved does nothing.
  G. Originals
     19. Load a slot onto a track, then UP from slot 1 (or DOWN past 16): the cursor reaches
         `ORIG` (no slot highlighted, a dark `ORIG` box in the header). Latched: `[YES]` puts the
         track back as it was before Clyps and closes. A track Clyps never touched has no `ORIG`.
     20. Load two different slots one after the other onto the same track, close Clyps, edit a
         trig, open Clyps again, `[PAGE]`: the track is back as it was before the FIRST load
         (the edit is gone too).
     21. Load onto three tracks, then `[FUNC]`+`[PAGE]`: all three come back on one landing.
     22. Playing: `[PAGE]` is cued like a load (lands at the end of the pattern / the next
         CHAIN AFTER point, in step).
     23. A NORMAL pattern: load a slot with another length (the pattern turns PER TRACK), then
         `[PAGE]`: the pattern is NORMAL again and plays as before.
  H. Lifetime
     24. LOAD PROJECT (or reload it): no `ORIG`, `[FUNC]`+`[NO]` does nothing.
     25. Power cycle: the same; the saved project's own sequences are intact.
  E. Stress: repeat A–D and F–G in a loop, both chord orders, holding and releasing in
     different orders. Nothing sticks: no stuck window, no dead keys, no frozen panel.

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

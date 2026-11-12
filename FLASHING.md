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
  (`[MIDI]`), `[PTN]` + `[TRACK 2]` → `TRK SEQ` / `RELOADED FROM PROJ`: M2 is back to its saved
  trigs, and audio T2 (back on the audio side) still has your unsaved change. On the audio side
  `[PTN]` + `[TRACK 2]` still reloads T2 only.
  **Part-slice + pattern-reload + quantized-landing walk-through (FINAL 2026-11-09; passed on the
  author's MKI with KYOTI V1.7).** `[BANK]` + `[TRACK n]` now brings back track n's sequence AND
  track n's machine / FX / pages / scene locks / LFO designer *as the project was saved*; no
  other track changes. Start each step from a SAVE PROJECT, on a pattern whose Part T1 and T2
  share, with the transport running.
  1. Change T1's trigs, its FX1 type and a few knobs (SRC, AMP, FX), and one knob on T2.
     `[BANK]` + `[TRACK 1]` → `TRK FULL` / `RELOADED FROM PROJ`. T1's trigs and settings are
     back, and the knobs on screen show them at once. T2 keeps its change, and the transport
     never stops.
  2. Change T1's machine (e.g. Flex → Static) → `[BANK]` + `[TRACK 1]`: the saved machine is
     back and plays its saved sample. The old machine doesn't hang on.
  3. Change T1's scene locks (a scene A/B lock) and its LFO designer wave → `[BANK]` +
     `[TRACK 1]`: both come back.
  4. A Part never saved with SAVE PART works the same (no `SAVE PART FIRST!` any more). After a
     SAVE PART *since* the project save, `[BANK]` + `[TRACK n]` brings back the PROJECT's
     version of the track, not the SAVE PART one.
  5. `[MIDI]`: change M2's channel / program / a CC value and its trigs, and M1's channel.
     `[BANK]` + `[TRACK 2]` → `TRK FULL` / `RELOADED FROM PROJ`: M2 is back, M1 keeps its
     change.
  6. `[PTN]` + `[TRACK n]` still brings back only the trigs (`TRK SEQ` / `RELOADED FROM PROJ`).
  7. **Pattern reload, stopped.** Edit pattern A05 (trigs on several tracks, a Part setting of
     its Part) while on A01. Hold `[PTN]`, then `[BANK]`, tap trig 5 → `PATTERN A05` /
     `RELOADED FROM PROJ`, and the OT is on A05 with its saved trigs and settings. While the two
     keys are held the trigs show the patterns, not the banks; neither SELECT PATTERN nor
     SELECT BANK appears, on any press or release.
  8. **The other order, running.** Edit A05 again, then while A01 plays hold `[BANK]`, then
     `[PTN]`, tap trig 5: A05 is cued and starts where a stock pattern change would (with
     DIRECT JUMP on, at its landing point). The transport never stops.
  9. **The playing pattern.** While A05 plays, edit it, then `[PTN]` + `[BANK]` + trig 5: its
     trigs and its Part come back in place, and the knobs show the saved values.
  10. **No trig.** Hold `[PTN]` + `[BANK]` and let go of both: nothing happens, no window. Then a
      plain `[PTN]` tap still opens SELECT PATTERN, a plain `[BANK]` tap SELECT BANK, and
      `[PTN]` + trig / `[BANK]` + trig pick a pattern / bank as usual.
  11. With `[PTN]` + `[BANK]` held, a `[TRACK]` key only changes the track (no reload).
  12. **Quantized, track.** A busy 16-step loop on T1, transport running. Change T1's trigs, then
      `[PTN]` + `[TRACK 1]` anywhere inside a step: the saved trigs take over exactly on a step,
      in time — nothing early or late, no doubled or swallowed note at the changeover. The toast
      appears as the change is heard, not before.
  13. **Quantized, FULL.** Change T1's FX and a filter on a sustained sound, `[BANK]` + `[TRACK 1]`:
      the sound changes exactly on the step where the trigs change, not partway through.
  14. **Quantized, different rates.** T1 at 2x or 3/4 (PER TRACK), edit, reload: it lands on one
      of its own steps and stays in phase with the other tracks afterwards.
  15. **Quantized, pattern.** On the pattern that plays, edit several tracks and the Part, then
      `[PTN]` + `[BANK]` + its trig: every track changes on the same next step, in phase — with DIRECT
      JUMP on or off alike. A pattern you are NOT on still waits for CHAIN AFTER / the pattern end
      (or DIRECT JUMP's next step when it is on), as a pattern change does.
  16. **Length / scale.** NORMAL mode, 12 steps saved: set the length to 16, play to step 14, then
      `[PTN]` + `[TRACK 1]`: on the next step the pattern is 12 long again and every track carries on
      where a 12-step pattern would be (step 14 of 16 → step 3 of 12), in time. Same for a scale
      change, and for a pattern reload with a changed master length.
  17. **Several chords.** Within one step, `[PTN]` + `[TRACK 1]` then `[PTN]` + `[TRACK 2]`: both
      come back. `[PTN]` + `[TRACK 1]` then `[BANK]` + `[TRACK 1]`: T1 comes back with its sound
      (the later one wins). **Stopped:** a reload applies at once; press STOP while one waits: it
      still applies.
  18. **No click.** Hold `[PTN]` + `[BANK]` and tap trigs on a running pattern: no click on any press,
      whether the pattern is cued or reloads.
  19. **Cancel a cue.** On A01, cue A02 with `[PTN]` + trig 2, then before it lands `[PTN]` + `[BANK]` +
      trig 1: A01 reloads and A02 never comes in.
- **QUANTIZE_LIVE_REC_TOGGLE** — hold `[REC]`, tap `[PLAY]` → toast `LIVE REC: QUANTIZED` or
  `LIVE REC: UNQUANTIZED`; tap `[PLAY]` again while it is up → the setting inverts. With
  PROJECT → PERSONALIZE open, the QUANTIZE LIVE REC check mark changes at the same moment.
- **ERASE_EMPTY_TRIGLESS_LOCKS** — make a trigless lock with one p-lock, erase that lock
  in live record: the step goes dark.
- **REC_TRIG_MUTE** — a track with recorder trigs on every pattern cycle: hold its
  `[TRACK]`, press `[REC]` → toast `REC TRIGS MUTED`, two dots appear beside the track's machine letter
  (one above the other, the top one level with the letter's top row, one blank pixel from the
  letter, on the inner side: right of it on T1–T4, left on T5–T8; inverted on the active
  track's tab), the play/stop icon below stays stock, GRID REC
  does not switch, the current recording finishes and the next cycle does not record.
  `[TRACK]` + `[REC]` again → `REC TRIGS UNMUTED`, recording resumes. Stopped, the dots stay; unmuted, they go. Check
  BOTH dots on a left-side tab (T1–T4) as well as a right-side one: the 2026-11-06 build lost the
  top dot on T1–T4. Mute T1 alone, then hold T1 + T3 and press `[REC]` → `REC TRIGS TOGGLED`, T1
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
- **KYOTI CL26 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL25 (flashed: landings in time, three issues reported) + every landing one tick before its boundary, the new
  step scheduled for the boundary itself and the old one removed a tick ahead (on the unit the old event and the
  sample clock were a frame apart at the boundary, so it sometimes stayed). DJ on, transport running:
  1. **No one-step offset:** switch T1 between its 64 steps and a 16-step slot at many points in the bar (OT DEMO):
     the incoming sequence never plays one step off before falling into place.
  2. **FULL loads arrive together:** [FUNC] + trig 5 / 13 / 16 (A05 / A13 / A16 have other Parts): the new machine /
     volume / FX start with the new sequence's first step, never on the old sequence's last step.
  3. **Differing scales (CL25 check 4, DJ on):** the same FULL switches, no early settings and no loud click.
  4. **Card pattern reload, FULL** ([PTN]+[BANK]+trig of the pattern you are on): listen for the quiet click on the
     press -- report whether it is still there (it may be the card read itself, not the landing).

- **KYOTI CL25 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL24 (flashed) + loads land as DIRECT JUMP lands (the user's CL24 report and decisions, 2026-11-11). Transport
  running:
  1. **DIRECT JUMP on, the user's case (OT DEMO P1, T1 64 steps <-> a 16-step slot):** press the load just before a
     bar line -> the new sequence's step 1 plays ON the bar line (CL24: the old step played there and the new one
     came in at step 2). Any press: the new sequence sounds from the next master step, never a step later.
  2. **In place ([PAGE] / [FUNC]+[PAGE] ORIG, [NO]+TRACK temp reload, [PTN]/[BANK]+TRACK card reload):** the
     restored sequence sounds from the track's very next step.
  3. **The cycle's last step:** [PAGE] pressed during the last step of the master cycle -> the track stays on the
     grid and on its step (CL24: it jumped mid-step to a wrong step until the next wrap).
  4. **Scales:** a load that changes the track's scale (e.g. 1x <-> 3/4x) at a CHAIN AFTER point (DJ off): the new
     sequence's step at the point plays on the point.
  5. **Master edits stay:** change the pattern's master scale or length on the unit, then load a track and [PAGE] it
     back: the master keeps your edit (CL24 put the as-loaded value back, mid-cycle).
  6. **Trig conditions:** DJ on (or [PAGE] in place): a loaded sequence's A:B trigs (e.g. 1:2, 4:4) fire on the same
     passes as an untouched track of the same length would. DJ off, a cued load: they start again from pass 1.
  7. FULL loads: the new track sound arrives with the new sequence's first step (as CL24, now one step sooner with DJ on).

- **KYOTI CL24 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL23 (never flashed; its list below is CL24's too) + the last two RELOAD_FROM_PROJECT rules:
  1. A pattern landing that changes the Part link (the pattern's Part was changed since the save, then the card reload
     or ORIG PTN+PRT brings it back): every track lands, and a track whose machine differs from the one that SOUNDED
     restarts its voice.
  2. A landing whose track slice did not change sends nothing to the engine for that track (no needless re-apply).

- **KYOTI CL23 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL22 (its list below still applies) + card reloads and ORIG restores land in place (RELOAD_FROM_PROJECT's rules),
  and FULL loads change the sound with the new sequence. Transport running unless said:
  1. **FULL load timing (OT DEMO, P1 T1 <- [FUNC] + trig 5):** P5 T1's track volume / machine / FX arrive WITH its
     first step, not a step before (any FULL landing: slot loads, [FUNC]+[NO], [BANK]+TRACK, ORIG SEQ+MCH/FX).
  2. **Card track reload** ([PTN] alone or [BANK] alone + TRACK, inside Clyps): lands on the track's next step, in
     phase (no restart); its toast at the landing. Several chords before it lands: all land; the same track twice =
     the later kind wins.
  3. **Card reload of the pattern you are ON** ([PTN]+[BANK] + its trig): every changed track lands together on the
     next step they all share, in phase; no "cued" toast, no pattern change. A pattern you are NOT on: the OT goes to
     it (CHAIN AFTER, or DIRECT JUMP's next step).
  4. **Cancel:** on P1, reload P2 (cued), then reload P1 before P2 lands -> P2 never plays (try early and late).
  5. **NORMAL pattern, length edited, [PTN] + TRACK:** the length comes back and every track stays on the beat.
  6. **ORIG restores in place:** [PAGE] / [FUNC]+[PAGE] / [YES] on ORIG land on the track's next step (not at the
     CHAIN AFTER point); ORIG PTN+PRT (chord + [PAGE]) lands every changed track together, in place -- no pattern
     change, DIRECT JUMP on or off (no restarts, conditional trigs keep counting).
  7. **Mixed [YES] in a group:** one member's arrows on its own slot (a restore), another's on another slot (a load):
     both land together at the cued point.
  8. Stopped: card reloads and restores land at once, as before.

- **KYOTI CL22 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL21 (its list below still applies) + persistent arrows, stock picks keep Clyps, a project load closes it:
  1. Move the arrows to a slot, then load anything (a trig, [YES], [FUNC]+trig, [PAGE], a group load, a temp
     reload, a card reload): the arrows stay where they were; the loaded slot still flashes.
  2. Hold [PTN]+[BANK] (the ORIG PTN+PRT header): the arrows hide while held; after [PAGE]/[YES] or release they
     are back where they were.
  3. In Clyps: [PTN] + trig, a [PTN] tap then a trig (SELECT PATTERN), or [BANK] + bank trig + pattern trig:
     the pattern changes and Clyps stays open on top; another bank: the view goes to it.
  4. With Clyps open, LOAD PROJECT or RELOAD PROJECT: Clyps closes.
  5. Arrows on some slot, then a pattern change of any kind (a stock pick, the card's pattern reload, ORIG
     PTN+PRT): the arrows stay where you left them.

- **KYOTI CL21 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL20 (its list below still applies) + lean ORIG PTN+PRT while playing + REC_TRIG_MUTE's top-dot fix:
  1. Playing, edit one track, [PTN]+[BANK]+[PAGE]: the pattern comes back as loaded at the switch, as before
     (DIRECT JUMP off: stock's switch; on: a jump). Power-cycle: the unit comes back with the restored pattern.
  2. Unnamed slots with locks and no trigs still read `A01 07 LK` with the same counts.
  3. REC_TRIG_MUTE: a muted T1-T4 tab shows BOTH dots (top and bottom), also on the active track.

- **KYOTI CL20 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL19 (its list below still applies) + the "full span" cells (the approved mock-ups, 2026-11-07):
  1. Each edited "x" sits 1 px before its slot number; the highlight bar and the select box reach left over the
     "x" and the arrows, 1 px short of the window's border (column 1 on the left, column 2 on the right).
  2. Arrows on the highlight: dark notches on its edges, the inverted "x" 1 px clear of the left point.
  3. Arrows on the select box: the box loses the pixel just above and below each arrow's column (corner, gap,
     arrow, gap, corner on each side); the select box alone keeps its full outline and corners.
  4. Arrows on a slot without a box: the arrowheads at the same edges, 1 px clear of the "x".

- **KYOTI CL19 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL18 (its list below still applies, except its step 5) + the group's tabs redrawn:
  1. Hold [CUE], add T6, T7, T1: T1 (the active track) is the normal filled tab; T6 and T7 show a one-pixel
     outline of the tab's own edge (rounded corners), unfilled, their letters and icons visible.
  2. [CUE] up, TRACK 6: T6 becomes the filled tab, T1 an outline; no leftovers.
  3. [NO] ends the group: every tab back to stock (the active track filled, the others plain).
  4. The track LEDs still light every member as before.

- **KYOTI CL18 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL17 (its list below still applies) + the pattern reload switches pattern, a new tab line, and the
  REC_TRIG_MUTE mute dots:
  1. Stopped, in Clyps: hold [PTN]+[BANK], trig 5 (another pattern than yours): `PATTERN A05` /
     `RELOADED FROM PROJ`, and the OT is on pattern 5 at once -- Clyps stays, its highlight and box on 5.
  2. Same from outside Clyps (the chord opens it): Clyps closes and you are on that pattern.
  3. Playing, DIRECT JUMP off: the reload cues the pattern the stock way (it lands at CHAIN AFTER / the
     pattern end). DIRECT JUMP on: it lands as a jump.
  4. Your own pattern: reloaded in place, no pattern change (as before).
  5. A [CUE] group: the active member's tab shows one vertical line on its outer side, over the straight part of
     the edge (not at the rounded corners); no top or bottom strokes.
  6. REC_TRIG_MUTE: a recorder-trig-muted track shows two stacked dots beside its tab letter (inner side); the
     play / stop icon is stock (FLASHING §4 REC_TRIG_MUTE).

- **KYOTI CL17 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL16 (flashed 2026-11-06; its list below still applies) + the active-track tab line fixed:
  1. Hold [CUE], add T1 then T2 then T3 (left side): only the newest member's tab has the line, top and bottom
     halves both; the earlier members' tabs are back to plain.
  2. Same on the right (MIDI) side with the first member: a full line in the upper half too (not line / gap /
     single pixel / gap).
  3. [CUE] up, TRACK of another member: the line moves to it and leaves the old tab clean.
  4. [NO] ends the group: no tab keeps a line, top or bottom.

- **KYOTI CL16 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL15 (its list below still applies; CL15 was never flashed) + the new multi-select and executions:
  1. Every execution ([YES] or a trig, with or without [FUNC]) takes, per track: its pre-select arrows, else its select
     box (last loaded), else its highlight (its original). A load of data the track already plays does nothing.
  2. Group: hold [CUE], add tracks. The active track (the one on screen) has a line inside its sidebar tab.
  3. [CUE] up: TRACK of a member makes it active (its own slots, its own arrows); TRACK of any other track does
     nothing. Arrows move the active member's pre-select only.
  4. [YES]: every member loads its own (arrows, else select box, else original). A trig: the active member that slot,
     every other member its own.
  5. [CUE] held: the arrows move every member's pre-select to the same slot; a trig loads that slot into every
     member.
  6. [NO] ends the group (Clyps stays); [NO] again closes Clyps.
  7. The columns realigned: a 9-letter name (e.g. `SNAREROLL`) clears the pre-select arrows by a pixel on both sides;
     every "x" clears the boxes, the arrows and the window's border.

- **KYOTI CL15 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL14 (flashed 2026-11-06) + LED / name fixes and pre-select arrows per track:
  1. The grid's solid yellow shows only while the pre-select arrows are on screen -- on any slot, also over the
     last-loaded slot and your pattern's slot (it wins over red / yellow and red there). When the arrows go (a load,
     a track change, a restore...), the yellow goes with them.
  2. ORIG SEQ, ORIG FULL and ORIG PTN+PRT bring back the slot's name as loaded (or none) -- no garbage characters,
     also right after power-on.
  3. Pre-select arrows per track: on T1 move the arrows to slot 5, go to T2 (its own arrows, or its last-loaded slot),
     come back: T1's arrows are on 5 again. Close and reopen Clyps: still there. An execution on a track (a load,
     [PAGE], a temp save / reload) clears that track's arrows; a project load clears every track's.
  4. A `[CUE]` group: moving the arrows moves every member's to the same slot.
  5. Hold `[CUE]` without adding a track, then `[FUNC]`+`[YES]` (or a trig, or `[PAGE]`): nothing loads and nothing
     flashes.

- **KYOTI CL14 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL13 (its list below still applies; CL13 was never flashed) with the pre-select box as arrowheads and the
  locks label:
  1. Arrows: two small arrowheads, one at each side of the slot, pointing in at its text (no flashing); the grid's
     solid yellow follows them. Over the highlight bar they show inverted. They go at the next execution.
  2. The select box (full frame on the last load) as in CL13.
  3. A sequence with no sample / note trigs but locks reads e.g. `A01 07 LK`: 7 steps with a lock trig or a
     parameter lock (each step once, at most 64) -- was `LOCKS`. On the playing slot the source reads `B14 07 LK`.

- **KYOTI CL13 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL11 (its list below still applies; CL11 and CL12 were never flashed; CL12's brackets are gone) + the boxes as
  decided 2026-11-05 and the "x" for sequences only:
  1. Load a slot: a full frame (the select box) stays on it, its grid LED blinking red / yellow; on the playing slot
     (an original, a card reload, SAVED TRK) there is no select box.
  2. Arrows: the pre-select box -- the same frame, flashing slowly in step with the red / yellow LED -- moves; its
     grid LED is solid yellow. Over the select box that frame flashes; over the highlight only the bar's outline
     flashes, its inside stays solid.
  3. Any execution (a load, [PAGE], a reload, a temp save / reload, a track change): the pre-select box goes until
     the next arrow; a load still flashes the bar on its slot.
  4. A `[CUE]` group: switching between member tracks leaves the pre-select box where it is.
  5. The "x" means only that the sequence differs from its original: edit a Part (its knobs, a machine): no slot
     gets an "x". A card reload of a saved pattern (data as the original) leaves no "x".
  6. The slot text sits 1 px further right in both columns.

- **KYOTI CL12 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL11 (its list below still applies; CL11 was never flashed) + three boxes and the column text 1 px right:
  1. Open Clyps on a track playing its original: only the highlight (your pattern's slot).
  2. Arrows: corner brackets (the pre-select box) move; the grid's solid yellow follows them. On your pattern's
     slot the bar shows it (no brackets).
  3. `[YES]` / a trig: the slot loads; a full box (the selection box) stays on that slot, its grid LED blinking red /
     yellow. Move the brackets away: the full box does not move -- it shows the last load.
  4. A card reload / ORIG / a temp reload: the full box disappears (the track plays its own slot).
  5. Another track and back: the brackets go to that track's sequence (as CL10).
  6. A `[CUE]` group: move the brackets, switch between member tracks (TRACK keys): the brackets stay where they are.
  7. The slot text sits 1 px further right in both columns; boxes and bars as before.

- **KYOTI CL11 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL10 (flashed 2026-11-05) + card-reload fixes (the "x", the box, the names) and the headers:
  1. Hold `[PTN]`+`[BANK]`: the header reads `PTN LOAD: ORIG PTN+PRT`. A `[CUE]` group reads `MULTI LOAD: TRK SEQS` / `TRKS FULL` / `ORIG SEQS` / `ORIGS FULL`.
  2. SAVE PROJECT. In Clyps load slot 5 into a track of a NORMAL pattern whose length differs (the "x" appears on
     your pattern's slot, slot 5 blinks red / yellow). `[PTN]`+TRACK (card reload): the "x" goes, the box and the
     red / yellow blink are back on your pattern's slot, the pattern plays at its saved length.
  3. The same with `[BANK]`+TRACK and with `[PTN]`+`[BANK]`+your pattern's trig: no "x", the box home.
  4. Names: name your pattern's sequence on a track ([FUNC]+[BANK] on its slot), SAVE PROJECT, rename it, then reload
     the track from the card: the name as saved comes back. A sequence never saved with a name (named after the
     save): the card reload clears it (the default label) -- the card's version, not the original.

- **KYOTI CL10 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL9 (its list below still applies; CL9 was never flashed) + a box per track and new grid LEDs:
  1. Open Clyps on a track that plays its original: the box is on your pattern's slot. Load slot 5: the box is on 5,
     slot 5 blinks red / yellow (the track's sequence), your pattern's slot stays red.
  2. Move the box to slot 9 (not loaded): slot 9 is solid yellow, slot 5 still blinks red / yellow.
  3. Go to another track and back: the box is on slot 5 again (what the track plays), not on 9.
  4. Another track that plays its original (or a card reload / SAVED TRK): its box opens on your pattern's slot.
  5. Playing, load a slot: it flashes yellow (on / off) until it lands, then blinks red / yellow.
  6. `[PTN]`+`[BANK]` held, a pattern cued: it flashes yellow too.
  7. A `[CUE]` group: the box goes with the view's track; a load still loads the box's slot into every member.

- **KYOTI CL9 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL8 (its list below still applies; CL8 was never flashed) + ORIG PTN+PRT while playing is a pattern change to
  itself. Edit the playing pattern and its Part (a trig, a machine setting) first, then in Clyps hold `[PTN]`+`[BANK]`
  and press `[PAGE]` (or `[YES]`):
  1. DIRECT JUMP off: nothing changes until the pattern's CHAIN AFTER point (or the pattern end at the default);
     there it switches as a pattern change does -- every track from its first step, START SILENT tracks silent,
     conditional trigs (1:2 etc.) counting from the start, the Part as saved.
  2. DIRECT JUMP on: it jumps at the next master step, as a DIRECT JUMP to another pattern does (tracks stay
     clock-locked), with the pattern and Part as saved.
  3. Stop before it lands: nothing is restored (press again while playing, or stopped for an immediate restore).
  4. Stopped: as before -- at once.
  5. Cue another pattern after the chord, before it lands: that pattern plays; the restore is dropped.

- **KYOTI CL8 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL7 (its list below still applies; CL7 was never flashed) with leaner loads: no new behaviour, the same results
  with far less written to the battery memory and read from the card. Check that nothing changed:
  1. Loads in Clyps (a trig, `[FUNC]`+trig, `[PAGE]`, a `[CUE]` group, `[PTN]`+`[BANK]`+`[PAGE]`) play and show as
     before; switch tracks and come back: the grid and the slot labels as expected.
  2. Card reloads (`[PTN]`+TRACK, `[BANK]`+TRACK, `[PTN]`+`[BANK]`+trig, also a pattern late in the bank, e.g. 15 or
     16): the toast comes up sooner than on CL3 (they now read only the one pattern and its Part from the card), and
     the result is what you saved.
  3. Power-cycle right after some Clyps loads (no save): on boot the project comes back with those loads in place,
     as on CL3 (the battery memory still gets every change).
  4. The MEMORY page: 66 pages (about 400 KB) more free sample memory than CL7.
  5. Header: hold `[PTN]`+`[BANK]`: `MULTI LD: ORIG PTN+PRT` (it acts on every track). A `[CUE]` group: `MULTI LD: TRK
     SEQS` / `MULTI LD: TRKS FULL` ([FUNC]); on your own slot `MULTI LD: ORIG SEQS` / `MULTI LD: ORIGS FULL`. One track
     unchanged: `T6 LOAD: TRK SEQ` etc.

- **KYOTI CL7 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL6 (its list below still applies) + the `[CUE]` group's view follows the group, and two fixes (5, 6):
  1. In Clyps on T1, hold `[CUE]`, press T3 then T5: the view jumps to T3, then T5 (the grid shows that track's slots).
  2. Still holding `[CUE]`, press T5 again (out): the view goes back to T3. Press T3 (out): no audio member is left,
     the view goes back to T1 (where you were when the group began).
  3. Add a MIDI track (`[CUE]`+`[MIDI]`+TRACK): the view is on it, on the MIDI side. Back on the audio side, removing
     an audio member never jumps the view to the MIDI track: it goes to the newest audio member, else your
     pre-group track if that was an audio track, else it stays put.
  4. `[NO]` (dismiss the group) and closing Clyps leave the view where it is.
  5. DIRECT JUMP on, playing: in Clyps hold `[PTN]`+`[BANK]` and press `[PAGE]` (ORIG PTN+PART): the header flashes
     at the same quick cadence as with DIRECT JUMP off (3 quick flashes in half a second).
  6. Load (or SAVE) a project so everything is saved. In Clyps, hold `[PTN]`+`[BANK]` and press your pattern's trig
     (`PATTERN A01` / `RELOADED FROM PROJ`): no slot gets the edited "x", on any track's view (check a few tracks).
     Same for `[PTN]`+TRACK and `[BANK]`+TRACK card reloads.

- **KYOTI CL6 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL5 (its list below still applies; CL5 was never flashed) + one fix:
  1. Save the project with its Parts saved. Edit a Part that the playing pattern does NOT use (its mark shows).
     In Clyps, hold `[PTN]`+`[BANK]` and press the trig of a pattern on that Part: that Part comes back from the
     card and its edited mark goes; the Part you are hearing is not touched.

- **KYOTI CL5 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL4 (its list below still applies, CL4 was never flashed) with the user's corrections:
  1. Header order: `T6 LOAD: TRK SEQ` ... `BNK A` on the right; a group: `MULTI LOAD: TRK SEQS`.
  2. A group on your own slot: `LOAD: ORIG SEQS` / `LOAD: ORIGS FULL` ([FUNC]).
  3. TRACK + `[YES]` / `[NO]` (temp save / reload): releasing TRACK leaves the active track as it was.
  4. SAVE BANK, then edit a pattern of that bank: ORIG brings back the bank as saved.

- **KYOTI CL4 walk-through** (WIP; `out/KYOTI_WIP/KYOTI_V1.7_WITH_CLYPS/OCTATRACK_OS1.40C_KYOTI_V1.7_WITH_CLYPS.syx`)
  = CL3 + the user's 2026-11-02 changes (scope §1.11).
  1. Header: `LOAD: TRK SEQ` on the left (`[FUNC]`: `LOAD: TRK FULL`), `T6 BNK A` on the right; the MIDI side reads the
     same. `[BANK]` held alone boxes `BNK A`.
  2. No 17th ORIG slot: UP / DOWN cycle the 16 slots. The box on your own pattern's slot (where Clyps opens) reads
     `LOAD: ORIG TRK SEQ` / `ORIG TRK FULL` ([FUNC]); `[YES]` or that slot's trig brings the original back.
  3. A `[CUE]` group: `LOAD: TRK SEQS` / `LOAD: TRKS FULL`; on your own slot `ORIG SEQS` / `ORIG FULL`.
  4. Outside and inside Clyps: hold TRACK, press `[YES]` -> `TEMP TRK SAVED`; hold TRACK, press `[NO]` -> `TEMP TRK
     RELOADED` (sequence + machine / FX as saved). While playing it lands on the track's next step, and works again
     after more edits. Two TRACK keys held: both. Right after power-on / a project load / SAVE PROJECT, with no temp
     save made, a reload brings the track's original (as loaded / saved).
  5. Stock ARM / DISARM REC TRK on TRACK + `[YES]` / `[NO]`: only with the Recording Setup menu open (then no temp
     save / reload). Open Recording Setup over Clyps: arrows, trigs and `[YES]` act on the menu, Clyps stays as it was.
  6. A temp reload in Clyps: the slot reads `SAVED TRK`.
  7. SAVE PROJECT, then make edits: ORIG (and a temp reload) bring back the project as saved, not as loaded.
  8. Card reloads in Clyps: `TRK SEQ` / `RELOADED FROM PROJ` and `TRK FULL` / `RELOADED FROM PROJ`, either side.

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

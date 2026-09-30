# Safe flashing guide — OT Kyoti FW

How to flash an OT Kyoti FW image onto your Octatrack, with a full safety net.

> **Features are OFF by default.** Straight after flashing, the unit behaves like stock
> apart from the always-on bug fixes. MUTE_MODES lives in PERSONALIZE;
> QUANTIZE_LIVE_REC_TOGGLE, DIRECT_JUMP_KYOTI and RELOAD_FROM_PROJECT are front-panel
> chords that do nothing until you press them (DIRECT_JUMP_KYOTI comes up OFF on every
> power-on); SIDECHAIN_COMPRESSOR and REPITCH_REPEAT98_KYOTI only engage on a setting you
> pick.

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
| DIRECT_JUMP_KYOTI | `140C_KDJ7` |
| REPITCH_REPEAT98_KYOTI | `140C_RPK16` |
| ERASE_EMPTY_TRIGLESS_LOCKS and the BATCH_BUGFIXES builds | `1.40C` (stock string — check by behaviour) |

PERSONALIZE is reset by every flash, so features are off until you re-enable them. A
quick check for each:

- **MUTE_MODES** — PERSONALIZE → MUTE MODE → `OTFX`. Mute a track playing through a
  reverb: the dry sound cuts, the tail rings out, and unmuting picks up in time.
- **DIRECT_JUMP_KYOTI** — hold `[PTN]`, tap `[YES]` → toast `ON`. While playing, cue
  another pattern: it takes over on the next step, in time with the metronome.
- **SIDECHAIN_COMPRESSOR** — COMPRESSOR on a track, page 2 → `KEY` = another track
  playing a kick. The compressed track ducks on the kick; `MON` lets you hear the key.
- **RELOAD_FROM_PROJECT** — save the bank, change a track's trigs, then `[PTN]` +
  `[TRACK n]` while playing: the saved trigs come back without the transport stopping.
- **REPITCH_REPEAT98_KYOTI** — a STATIC track with a sample whose tempo is set (audio
  editor, ATTR), SETUP → TSTR = `RPCH`: it follows the project tempo by varispeed, and
  PTCH now reads QUAN.
- **QUANTIZE_LIVE_REC_TOGGLE** — hold `[REC]`, tap `[PLAY]` → toast; tap `[PLAY]` again
  while it is up → the setting inverts.
- **ERASE_EMPTY_TRIGLESS_LOCKS** — make a trigless lock with one p-lock, erase that lock
  in live record: the step goes dark.
- **MIDI_PLAYS_FREE_FIX** — a PLAYS FREE MIDI track, trig quantize DIRECT, SCALE MODE PER
  TRACK, notes on steps 1 and 2: a manual trig keeps it running instead of stalling.
- **EMPTY_PATTERN_LED_FIX** — a pattern whose only content is a p-lock on a MIDI track:
  its LED lights under `[PTN]`.
- **PART_CHANGE_CARRYOVER_FIX** — a track that is PICKUP on one Part and FLEX on
  another: switching patterns across the Parts plays the FLEX sample, not the old loop.

---

## 5. Reverting to the official firmware

Reflash the official one with the **same steps in §3**, sending
`downloads/extracted/OCTATRACK_OS1.40C.syx`. Your CF card and projects are not affected.
Nothing the features store survives a revert except the PERSONALIZE block, which an EMPTY
RESET clears.

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

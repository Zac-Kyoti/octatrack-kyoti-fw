# CLYPS — scope (rev 2, 2026-10-23; research only, nothing built)

Rev 1 (2026-10-22, as `TRACK_SEQ_SELECT_SCOPE.md`) was the first pass. Rev 2 adds:
- the user's name and terms;
- the 16-at-once table;
- the cue colour change;
- the non-destructive model;
- the 16 saved sequences.

## Terms (the user's, 2026-10-23 — use them everywhere)

| term | meaning |
|---|---|
| **Clyps** | the feature (was TRACK_SEQ_SELECT) |
| **Clyps mode** | any time Clyps is entered: the Clyps view and/or the Clyps grid is active |
| **Clyps view** | behaviour in, or acting on, the popup window |
| **Clyps grid** | behaviour of the trig LEDs and trig keys while in Clyps mode |
| *own sequence* | the sequence a pattern stores for a track |
| *clyp* | a sequence Clyps has put onto a track in place of its own sequence (from any bank/pattern slot, or from the track's saved sequence) |
| *saved sequence* | the per-track temporary buffer written by [FUNC]+[YES] and played back by [FUNC]+[NO] in Clyps mode (16 of them: 8 audio tracks, 8 MIDI tracks) |

## The ask, as it stands

**Opening Clyps.** Hold **[PATTERN] + [BANK]** to open the Clyps view. It shows all 16 slots of a
bank at once: the active track's sequence in each pattern. LEFT/RIGHT change the bank, UP/DOWN move
the cursor through all 16 (auto-repeat, wrapping 16→1), and empty slots read `---`. The sequence now
on the track is marked.

**Loading.** A trig or [YES] loads the chosen sequence onto the active track. It is cued like a
pattern change when DIRECT JUMP is off, and instant (DJ-style) when it is on. The Part does not
change.
- **While the chord is held**, trig taps load. The view highlights the picked entry, cued sequences
  light **yellow** and the playing one **red**, and Clyps stays up. Releasing the chord after a trig
  load closes Clyps.
- **When the chord is released with nothing loaded**, Clyps stays open. [YES] loads the cursor entry
  and closes, a trig loads and closes, and [NO] closes.
- **A load is an ordinary edit** (keep, stock-like): what is on the grid stays. Clyps also keeps
  every track's **original**, the sequence it had before Clyps first replaced it, and can always
  put it back (§1.5).

**The Clyps grid.** Full green = sample/note trigs, half green = other data only (trigless trigs,
locks, recorder trigs), off = empty, red = playing, yellow = cued.

**Saved sequences.** In Clyps mode, **[FUNC]+[YES] saves** the active track's sequence and
**[FUNC]+[NO] reloads** it. There is one saved sequence per audio track and per MIDI track. They
survive pattern and bank changes, and are destroyed by a power cycle or a project reload.

**General.** TRACK keys change the track while in Clyps mode. Stock [PTN]/[BANK] actions and
toasts are suppressed. Loads are instant. A loaded sequence keeps its own length and scale under
the destination's master length and scale. A NORMAL destination is converted to PER TRACK only when
it has to be (rev 1 D4, agreed).

**Phase 2:** named sequences. Lower priority, kept in scope (§10).

## Verdict

**Feasible.** Every load is a RAM-to-RAM copy of one track record: 2,330 B for audio, 2,224 B for
MIDI, tens of µs, with no card I/O. All 16 banks are resident (`kb/caves.md` §5c).

What it costs:
- ≈ 5 KB of ColdFire;
- **≈ 9 MiB of RAM**: the 16 saved sequences (36 KB) and a guaranteed place for every original
  (8.9 MiB).

Both go in DRAM through the loader route that KYOTI V1.5 and BLACKPYRAMIDS_303 already use,
taking ≈ 9 MiB (≈ 1,525 pages) from the ~85 MB sample pool (§6).

The modal-window risk from rev 1 remains. Every RELOAD2 bug class has a counter (§4.4), and the
stress gate in §7 checks them.

Evidence: static reads of our own `section_3_MAIN_OS.bin`, confidence **C** unless marked **L**
(from a doc) or **I** (inferred). Nothing has been run in the emulator, built or flashed.

---

## 1. Behaviour

### 1.1 Entering and leaving Clyps mode (the user's rule, 2026-10-23)

**Entering.** Pressing the second of [PTN]/[BANK] while the first is held, in either order, enters
Clyps mode: the view and the grid together. They open on the bank the track's playing sequence came
from, with the cursor on its slot. Neither key's stock action happens, and no SELECT window or toast
appears on either release.

**Two states, one Clyps mode.** The view and the grid are always up together, and **closing always
closes both**.

| state | how you get there |
|---|---|
| **held** | the chord is held |
| **latched** | the chord was released with no load made during that hold |

| event | held | latched |
|---|---|---|
| TRIG 1–16 | load that slot: cued (DJ off) or instant (DJ on). The view's cursor jumps to it. Clyps stays | load, then close |
| [PAGE] (`0x1b`) | load this track's original (§1.5) | load the original, then close |
| [YES] | DIRECT JUMP's [PTN]+[YES] toggle | load the cursor entry (a slot or `ORIG`), then close |
| [NO] | swallowed | close, no load |
| [FUNC]+[NO] | load the saved sequence, immediately | the same, then close |
| releasing the chord | if any load was made during this hold: close. Otherwise: go to latched | — |
| pressing the chord again | — | go to held |
| any window that evicts ours | close | close |

LEFT/RIGHT (bank) and UP/DOWN (cursor) work in both states.

### 1.2 The Clyps view: all 16 at once

A full-screen window, 128 × 64. It has a 7-px header row and two columns of eight 7-px rows
(7 + 8·7 = 63 px), one column per half of the bank. Each column is 64 px wide. The body font
`0x400ba876` sets ~4 px a character: RELOAD measured `RELOADED` at 32 px and `TRK SEQ + PART` at
52 px. A column therefore holds ~15 characters.

```
█ T6   BANK A ████████████████████ SAVED █   header: track, bank, saved-sequence mark (inverted)
  1 ▸12 TRIGS       │  9  ---
  2  ---            │ 10  4 TRIGS
▓▓3  LOCKS ONLY▓▓▓▓ │ 11  ---             ▓ = cursor (XOR bar)
  4  9 TRIGS        │ 12  16 TRIGS        ▸ = the sequence on this track (red on the grid)
  5  ---            │ 13  ---             » = cued (yellow on the grid; only seen if Clyps is
  6  16 TRIGS       │ 14  ---                 re-entered before the landing)
  7  ---            │ 15  2 TRIGS
  8  ---            │ 16  ---
```

- **Navigation.** UP/DOWN run 1→16 down the first column and on into the second, and wrap at both
  ends. They auto-repeat when held. LEFT/RIGHT change the bank and wrap A↔P.
- **Drawing.** It is our own: stock's text `0x40012bd8`, its XOR bar `0x40012254`, and lines
  `0x40011910`/`0x40011b94`, into our own window. No stock list widget shows 16 rows, so none is
  reused. `▸`/`»` are drawn marks unless the font has glyphs for them (stock's scroll arrows are
  chars `0x11`/`0x12`).
- **Unnamed rows** show a content summary. Phase 2 names replace it (a 10-character name plus the
  number fits the 15-character column).

### 1.3 Keys in Clyps mode (held and latched alike, except where §1.1 differs)

| key | action |
|---|---|
| UP / DOWN `0x33`/`0x20` | cursor through 1–16 (and `ORIG`, §1.5), wrapping, auto-repeat |
| LEFT / RIGHT `0x34`/`0x21` | bank −/+, wrapping A↔P; view and grid follow |
| TRIG 1–16, [PAGE], [YES], [NO] | §1.1 |
| [FUNC]+[YES] | **save** the active track's sequence; Clyps stays; the header shows `SAVED` |
| [FUNC]+[NO] | **reload** the saved sequence **immediately** (O3); nothing if none is saved; then as §1.1 |
| TRACK 1–8 | change the active track; view and grid follow; bank kept |
| [PTN] / [BANK] | their held state is the chord; no stock action |
| [FUNC] `0x2d` | our layer lists it (so stock's FUNC sub-map `0x400bfa1e`, which maps [PAGE] to SCALE and sits above any layer pushed before it, is never linked); its held flag `0x46c7dd26` is read (C: set for every press at `0x4003192c`) |
| encoders | swallowed (O10) |
| all else (PLAY, STOP, CUE, mutes, MIDI, …) | passed through |

### 1.4 The Clyps grid

These rules apply to the shown bank and the active track.

| LED | meaning |
|---|---|
| green, full (15) | the slot has sample trigs (audio) or note trigs (MIDI) |
| green, half (7, stock's dim level) | data, but no sample/note trigs: only trigless trigs, trigless locks or recorder trigs |
| off | empty |
| **red** | the sequence playing on the track; for a clyp, its source slot |
| **yellow** (red + green full; stock's own colour for a cued pattern) | cued. Seen while the chord is held: in the latched state a load closes Clyps |

When the saved sequence is what's playing, no slot is red, and the view header shows `SAVED ▸`.

Every slot shows what it holds now, the playing pattern's own slot included. A track's original
appears as the `ORIG` entry (§1.5).

### 1.5 Loads are edits, and Clyps keeps originals (decided 2026-10-23)

**Keep.** A load is an ordinary edit, as stock behaves everywhere else.
- The pattern holds what you put there, whether you leave it and come back or not.
- Edits made to a loaded sequence stay.
- The bank shows unsaved changes, the power-cycle copy holds the change, and a card save writes
  what you hear.
- There is no automatic restore mode (the user, 2026-10-23).

**Originals.** The first time Clyps replaces a track in a pattern, it keeps what that track held
just before: the RAM state, unsaved edits included, keyed by (bank, pattern, track).
- **First one wins.** Later loads and edits never replace an original, so "original" always means
  "before Clyps touched this track in this pattern".
- **Any Clyps replacement captures one**: a slot load or a saved-sequence load. Plain edits never do.
- **Restoring a track** puts its original back and drops it. It lands like any load: cued, or
  instant with DJ on.
- **Lifetime:** a power cycle or a project reload destroys originals, as it does saved sequences.

**Recovery is guaranteed (the user, 2026-10-23).** Wherever you are, every original can be
recovered. There is one reserved place for every (bank, pattern, track): 16 × 16 × 16 = 4,096,
directly indexed, so the store can never fill.
- Size: 256 patterns × (8 × 2,330 + 8 × 2,224 B) = **9,326,592 B ≈ 8.9 MiB**, about 10–11 % of the
  ~85 MB sample memory.
- With "sequence + machine/FX" loads (O18), the Part slices add to that (research running).
- Compressing would shrink typical originals (their lock arrays are mostly `0xFF`), but a guarantee
  must budget for the worst case anyway.

**Getting originals back:**

| where | how |
|---|---|
| Clyps view | a 17th entry, `ORIG`, in the cursor cycle after slot 16. It is present only when the active track has an original on the playing pattern. Select it, then [YES] in the latched state |
| Clyps grid | **[PAGE]** (`0x1b`), the key after the 16 trigs whose [FUNC] function is SCALE SETUP: this track's original (§1.1) |
| whole pattern | **[FUNC]+[PAGE]** (decided): restore every track of the playing pattern that has an original, on one landing |

An original belongs to its pattern: you play that pattern to restore it. A project-wide "restore
everything" is O17.

**Showing which tracks have originals (O16, open; the TRACK LEDs are already busy).** Candidates:
- the **4 page LEDs** beside [PAGE] (C: dies `0x48..0x4f`, red/green/yellow, LED-layer slot 7,
  painter `0x4004d1a8`). The key itself has no separate LED. In Clyps mode they would be lit when
  the active track has an original, and yellow while its restore is cued;
- a 16-dot strip in the view header, one dot per track of the playing pattern that has one;
- a `*` beside the `ORIG` entry, or on the playing pattern's own row.

### 1.5a Loading — timing, length and scale

**Timing.**
- Transport stopped: the load is immediate.
- Running, DIRECT JUMP off: cued, landing where a stock pattern change cued now would land (§3.4).
  At a master wrap that is step 1. At a CHANGE point it is phase-continuous (O9): the track lands
  where it would be had the sequence been in the pattern since its last restart.
- Running, DIRECT JUMP on (decided): it lands like a DIRECT_JUMP_KYOTI jump, at the next master
  step, at the clock-locked position, as if that sequence had been playing since START. That is
  the "great in combo with direct jump" case.
- **One cue per track, last pick wins.** Re-picking the sequence already playing cancels the cue.
  A pattern change landing first drops pending cues.

**Length and scale.**
- The loaded track keeps its own resolved length and scale: record `+0x50/+0x51` from a PER TRACK
  source, or the source pattern's `+0x8e53/+0x8e54` from a NORMAL one.
- The destination's master length and scale govern.
- A NORMAL destination is converted to PER TRACK **only when** the clyp's length or scale differ
  from the pattern's, with every other track set to the pattern's length and scale (rev 1 D4,
  agreed). The conversion is part of the edit: it is kept and saved like any other, and a restore
  undoes it (§4.6).

### 1.6 Saved sequences ([FUNC]+[YES] / [FUNC]+[NO])

- **16 buffers**, one per audio track and one per MIDI track, kept in DRAM. They are kept across
  pattern and bank changes, and **destroyed by a power cycle or a project reload** (decided
  2026-10-23).
- **[FUNC]+[YES]** copies what the active track is playing now: the clyp or the own sequence,
  including edits, plus its resolved length/scale.
- **[FUNC]+[NO]** loads the buffer onto the active track **immediately** (at its next step,
  phase-continuous), and captures an original like any Clyps load.
- **Unlike the Analog Rytm**, these are per track, independent of pattern and bank, and never saved.

---

### 1.7 "Sequence + machine/FX" loads — FULL loads (decided 2026-10-23: yes, scene locks included)

**What it would carry.** Exactly the per-track Part slice that stock's own TRACK COPY/PASTE carries
(C, `0x40029754` / `0x4002b654`; MIDI `0x40029614` / `0x4002b470`).

Audio, **136 B** per track, read from the source pattern's linked Part (working copy):

| Part offset | size | field |
|---|---|---|
| `+0x00+t` / `+0x08+t` | 1 each | FX1 / FX2 id |
| `+0x12+2t` | 2 | track level, and probably CUE level |
| `+0x22+t` | 1 | machine type |
| `+0x2a+30t` / `+0x1da+30t` | 30 each | machine page 1 / page 2, all 5 machines |
| `+0x11a+24t` | 24 | AMP / LFO / FX1 / FX2 page 1 |
| `+0x2f2+30t` | 30 | LFO PMTR/WAVE, AMP/FX page 2, MULT/TRIG |
| `+0x2ca+5t` | 5 | slot record |
| `+0x602+12t` | 12 | recorder setup |

MIDI, **68 B** per track: `+0x3e2+32m` (page values) and `+0x4e2+36m` (channel, bank, program, …).

Stock does not carry:
- **scene locks** (`+0x662+(s·8+t)·0x20`, 512 B per track) or the per-scene track bytes;
- **the LFO designer** (`+0x1702+16t`). An LFO set to a designer wave would play the destination
  Part's designer: a gap stock has too.

**How it would land on time.** A single-track apply exists: **`0x40001f18(bank, part, t)`** (C).
It publishes one track's lanes, FX ids, levels and recorder setup, and its only call is memcpy.
At the landing tick:
1. copy the slice into the playing Part's working copy;
2. call it;
3. set the voice-restart bit `0x8000184c` if the machine changed.

The SRAM copy, the dirty bits and the UI refresh are deferred to the UI task. Do not write the
slice early: machine type, slot and the recorder gate are read straight from the Part at trig time.

Risks:
- PICKUP setup (`0x40000e50` / `0x40006820`) is UI-context, not ISR-safe;
- VARISPEED's `rp` hold/forget on `0x4002b654` (KYOTI);
- features that read FX ids (SIDECHAIN).

Whole-Part re-apply `0x40009094` would also work, but it snaps in-flight slides on every track;
`0x40001f18` touches only the one track. An FX type change makes the DSP re-init only that
track's effect (its tail is cut, as stock does on a live FX change).

**⚠️ The musical consequence: a Part is shared.** The slice is written into the Part linked to
the playing pattern, and every other pattern in that bank linked to the same Part then plays that
track with the new machine/FX. That is how the Octatrack's Parts work (stock PASTE TRACK does the
same). The Part shows as edited.

**Originals for it.** Kept per (bank, part, track): 16 × 4 × 16 = 1,024 places, (8 × 136 + 8 × 68)
× 64 = **104,448 B**. That is small next to the sequence originals. A restore brings the old
machine/FX back the same way.

**Scene locks come too** (the user, 2026-10-23): the track's 16 scene rows
(`+0x662+(s·8+t)·0x20`, 512 B) and its per-scene bytes (`+0x1662+10s+t`), about 682 B per audio
track. MIDI tracks have no scene locks.

**The LFO designer wave comes too** (decided, was O20): `+0x1702+16t` + slope `+0x1782+2t`, 18 B
(MIDI: `+0x1792+16m` / `+0x1812+2m`).

**Stock TRACK COPY leaves it behind** (C, re-read 2026-10-23: `0x40029754` copies the record plus six
Part blocks of 0x1e/0x18/0x1e/5/0x1e/0xc B into clipboard `+0x91f..+0x9a1`, and nothing else). A
pasted track keeps WAVE = designer but plays the destination track's designer. It shows only when
pasting to another track, or into a pattern on another Part.
- **Probable stock bug, not yet observed.** The user's 2-minute hardware check is in NOTES.
- If confirmed, it is a BATCH_BUGFIXES candidate (working name TRACK_PASTE_DESIGNER_FIX). Copy,
  paste and the undo snapshot each carry the 18 B as well. It is ~60–100 B of code.
- In KYOTI it has to compose with VARISPEED's detour on `0x4002b654`.

Part-slice originals with scene locks and designer: 512 × 700 + 512 × 86 ≈ **393 KB**.

**How to choose it per load (decided 2026-10-23).**
- The view header has a mode field reading `SEQ`.
- **Holding [FUNC] highlights `FULL` instead; releasing [FUNC] drops back to `SEQ`.**
- A trig picked while [FUNC] is held is a FULL load. A plain trig is a SEQ load.
- [FUNC]+[YES], [FUNC]+[NO] and [FUNC]+[PAGE] keep their own meanings (save, reload saved,
  restore-all). The `FULL` label applies to trig picks.

**A restore undoes what Clyps did:** the track's sequence original, plus its Part-slice original
when a FULL load made one.

**The [MIDI/PART] key** (MKI's combined key; [FUNC]+[MIDI] opens Parts). Plain [MIDI] passes
through in Clyps mode: it switches between audio and MIDI tracks, and the view and grid follow
(`0x80000012`). [FUNC]+[MIDI] does nothing in Clyps mode, because Clyps owns [FUNC] while open.

## 2. Decisions

### Settled (2026-10-23)

- Name and terms: **Clyps**, Clyps mode / view / grid.
- All 16 slots visible at once; UP/DOWN cycle through them with wrap and auto-repeat.
- [YES] or a trig, with the chord not held, loads and closes Clyps entirely; there is no flashing
  red at all.
- With the chord held, the grid keeps picking (rev 1 D3): cued = **yellow**, playing = **red**.
- NORMAL destination: convert to PER TRACK only when needed (rev 1 D4).
- Saved sequences: [FUNC]+[YES] / [FUNC]+[NO], 16 buffers, not across power cycles.
- Naming: phase 2, kept on the radar.
- **DIRECT JUMP on (was O4):** a Clyps load lands like a DIRECT_JUMP_KYOTI jump. It lands at the
  next master step, at the clock-locked position the sequence would have if it had been playing
  since START.
- **[YES] with the chord held (was O5):** passes to DIRECT JUMP's [PTN]+[YES] toggle.
- **Saved sequences (was O7):** they last only while the unit runs its project. A power cycle or a
  project reload destroys them.
- **O9, CHANGE-point landings:** phase-continuous. The track lands where it would be had the
  sequence been in the pattern since its last restart, so it stays in step with the other tracks.
  At a master wrap that is step 1, the same as stock.
- **O3, [FUNC]+[NO]:** immediate. The saved sequence lands at the track's next step, at the
  phase-continuous position.
- **O6, full green:** sample trigs (audio) or note trigs (MIDI) only. A slot holding only
  recorder trigs, trigless trigs or locks is half green.
- **O1 / O1b / O2:** keep (a load is an edit; edits stay; card saves write what you hear), plus
  automatic originals with guaranteed recovery (§1.5). There is no automatic restore mode.
- **O8 and the two states:** held / latched (§1.1). LEFT/RIGHT change the bank throughout Clyps
  mode, and there is no grid-only state.
- **Restoring:** the `ORIG` entry on screen, [PAGE] on the grid, and **[FUNC]+[PAGE] = restore all**
  (was O14).
- **FULL loads (was O18/O19):** yes, scene locks included. Holding [FUNC] momentarily highlights
  `FULL` in the header, so [FUNC] + trig is a FULL load (§1.7).
- **Recorder trigs:** they are part of each audio track's record (REC1–3 masks), so every load,
  save and restore carries them. A pattern has 16 track records, recorder trigs included.

### Open — recommendation first

| # | question | recommendation | alternative |
|---|---|---|---|
| **O16** | The 4 page LEDs beside [PAGE] in Clyps mode (dies `0x48..0x4f`) | steady, in the grid's own colours: **red** = the active track plays its original (nothing to restore); **green** = Clyps changed it ([PAGE] restores); **yellow** = restore cued. While [FUNC] is held they show the same for the whole pattern (restore-all). Plus a 16-dot strip in the view header for all tracks | the user's idea: all 4 red = original, all 4 flashing red = not original |
| **O17** | A project-wide "restore everything" | not in v1 | a gesture that restores all originals in all patterns |
| **O10** | Encoders in the view | swallowed, as in stock lists | passed through |
| **O11** | Arranger running | Clyps does nothing (RELOAD's `ARR_ACT` gate) | works |
| **O12** | Standalone [BANK] alone | carry RELOAD's SELECT-BANK-on-release deferral | stock [BANK]; SELECT BANK flashes when the chord starts with [BANK] |

---

## 3. What stock does — the mechanisms Clyps uses

### 3.1 Data model

- **Pattern slab** = `0x400e21e0 + bank·0x9b340 + pattern·0x8ed8`.
  - 8 audio records at `t·0x91a`, 8 MIDI records at `0x48d0 + m·0x8b0`.
  - Trailer `+0x8e50..+0x8e5b`: `+0x8e50` u16 master length (−1 = INF), `+0x52` master scale,
    `+0x53/+0x54` pattern length/scale, `+0x55` SCALE_MODE, `+0x56` CHANGE, `+0x57` Part link,
    `+0x58` tempo.
  - All 16 banks are resident.
- **A track record is self-contained and position-independent.** Stock's track paste memcpys it
  anywhere (`0x40029614`/`0x40029754`). It holds:
  - masks and recorder trigs;
  - swing/slide;
  - p-locks `+0x59` (64 × 32);
  - trig words `+0x89a` (count, micro-timing, condition);
  - its own length/scale `+0x50/+0x51` (MIDI record: `+0x28/+0x29`);
  - flags `+0x53..+0x57`.

  P-locks are scene-parameter indices and the sample lock is a slot number, so a clyp plays through
  the **destination** Part's machines.
- **SRAM mirror** `0x1001614e` (+ pattern offset) = the **UI** bank `0x80000002`, the copy that
  survives a power cycle. Stock edits write both it and the slab.
- **Stock's sequence-only write.**
  - `0x4002b3b4(ctx, pat, t)` (audio undo-restore): `0x91a` B into `[0x46c82456] + pat·0x8ed8 + t·0x91a`
    and the mirror, then `0x40029b9c(t)`. MIDI twin `0x4002b2f4` (mirror `0x1001aa1e`).
  - `0x40029b9c(t)` sets `bank+0x9b332 = 1` / `0x100f8598 = 1` (dirty), then calls `0x400339d8`,
    `0x4009da20(t)` / `(t+8)` and `0x400486cc`.
  - **Clyps uses the copies and the refresh calls, but not the dirty flags** (§1.5).
- **Not PASTE TRACK** (`0x4002b988` → `0x4002b654`): it writes Part data too.

### 3.2 The chord and the keymap

- **The layer stack** (`LAYER_PUSH 0x40031494`, `LAYER_POP 0x4003146c`, head `0x460d165c`).
  - A push appends and is idempotent; the last layer listing a key wins.
  - Struct (RAM): `+0` next, `+4` 26-B key records (end `0xff`), `+8` 22-B encoder records,
    `+12` 0, `+16` tag.
  - Record fields: `+2` press, `+6` release, `+10` hold; `−1` passes down, `0` swallows;
    `+22/+24` hold delay/repeat.
- **⚠️ A key held during a rebuild keeps its old handlers** (`0x400312e2`). The [PTN]/[BANK]
  releases therefore always reach `0x4005a044`/`0x4007b3e0`, and are suppressed through state:
  - `PTN_CONSUMED 0x460d173e = 1` → [PTN] release only tears down (`0x40043418`);
  - `BANK_SEL 0x460e73c6 = 2` → either [BANK] release (stock or RELOAD's) takes the no-op dismiss.

  Our handlers stay live for any key held across a pop, so each one tests "Clyps mode".
- **[PTN] press** pushes keymap layer `0x400bf0f2` (trigs → `0x40056b2c`) and LED layer
  `0x400bebfe`. It clears `PTN_CONSUMED` (`0x4005a06e`).
- **[BANK] press** `0x4007af80` pushes `0x400cff14` (trigs → `0x4007b2fc`) and LED `0x400cff28`.
  RELOAD defers its window to release. Teardown `0x4007b408` pops both and balances
  `0x4007e760`/`0x4007e81c`.
- **Held flags** `0x46c7d8ee + code·24`, tested non-zero: [FUNC] `0x46c7dd26`, [PTN] `0x46c7dd3e`,
  [BANK] `0x46c7dd56`.
- **Chord edges.** Two are needed, one per order:
  - standalone: a [PTN] splice at `0x4005a04e` (8 B) and a [BANK] splice at `0x4007af8c` (6 B),
    beside RELOAD's guarded `0x4005a044..+8` / `0x4007af80..+8`;
  - with RELOAD: inside RELOAD's `rl3_bank_show` plus one [PTN] splice.
- **Arrows**: UP `0x33`, DOWN `0x20`, LEFT `0x34`, RIGHT `0x21` (`0x4007e55c`,
  `0x4007ec7c`/`0x4007eca4`, RELOAD's `UP_CODE`/`DOWN_CODE`).

### 3.3 Windows

- **`FUN_4005829c(w, h, dx, dy, prio, close_cb)`**: a centred window, or **0 when all 5 slots are
  busy**.
  - Opening priority P closes every slot whose priority is ≥ P, calling its close_cb (`0x400582ce`).
  - Toasts/SELECT 0xa, MLNOTIFY 4, name editor 5, menus 3, project lists 2. A **priority-3**
    Clyps view survives toasts and the name editor.
- **No timeout** unless `0x40059f8c`/`0x4005a2b8` is used.
- **⚠️ close_cb is never cleared** and may be called again later: guard it on our own handle, and
  never pass 0.
- **Template: CHOOSE PROJECT** (`0x400647a0`, draw `0x40063f14`).
  - Surface: `win+0x24`; y = 0 is the bottom row.
  - Clear: `0x400356a8` (titled) / `0x40035624` (untitled).
  - Title bar: `0x40057c84`.
  - Text: `0x40012bd8(font, surf, x, y, mode, str)`; XOR: `0x40012254(surf, x0, y0, x1, y1, −1)`.
  - Redraw: `RDRAW 0x46c7c72c = 1`.
- **Not used:** the generic menu `FUN_4006d94c` (4 rows; Octakit's patch site), the SHOW_WIN slot
  `0x460d1e5c`, and the toast slot `0x460d1e70` (DJ's `dj_ptnrel` closes toasts).
- **Track changes from anywhere** go through the setter `FUN_40083bf8` → the broadcaster
  `FUN_40083bc0` (7 callers): the hook for "Clyps mode → rebuild" (**I** that it covers every path).
  MIDI side: `0x80000012`/`0x460d1736`.

### 3.4 Landing

**The tick** (`0x400a1eea`, seq ISR, IPL 2) runs four phases, in this order:

| phase | start | what it does |
|---|---|---|
| D | `0x400a1f72` | — |
| E | — | builders, one step ahead (`0x400a2d7e` audio, `0x400a39c6` MIDI) |
| F | `0x400a3ca4` | track advance |
| G | `0x400a3f94` | master |

**The gate** (`0x400a42fa..0x400a439c`, spot-checked). At master tick 0, `s = ++0x800065b2`, and
`N = 0x400d80dc[+0x8e56, or 0x8000004e when < 0]`. A change lands:
- when `N > 0 && pending && s % N == 0`;
- else when `s ≥` the arranger point `0x8000662c`;
- else, with the arranger running, when `s % N == 0`;
- else when `mlen ≠ −1 && s ≥ mlen`.

It never reads SCALE_MODE. Clyps evaluates the same rule with `pending` = a cue of ours.

**The wrap body** `0x400a43a0`:
- purges events at or after one master step;
- commits;
- re-homes every track (`0x400a4856..0x400a4b78`).

The builder reads the **blob slab**, and captures locks at build time.

**Our copy point (I, to be proven on the oracle).**
1. On the commit tick, in phase G after stock's body, copy the record into the slab.
2. Re-home that track with its new length/scale.
3. Purge its slots at or after the landing (audio `0x80001904`/`0x46c7e998`/`0x46c7fe44` and
   `0x80001984`/`0x46c7faa4`/`0x46c7fe8c`; MIDI `0x46c76a26`/`0x46c769c0`/`0x46c77be2`).
4. Write `0x8000663e[t]`, then call `0x400a539c(t)` (A:B counter, FILL).

**Edge case:** a PER TRACK track faster than the master finishes from the outgoing slab (the HOLD
bit, cleared at `0x400a3d1c`), so its copy waits for its own late landing.

**MEASURED 2026-10-23 (emulator, stock image).** Harness: `tools/diag_clyps_landing.py` +
`tools/cmp_clyps.py`. The base is the user's real OT DEMO export. Each test pattern is built in
RAM after the load with stock-style slab and record copies, and no file is written.

| run | setup | result |
|---|---|---|
| A1 vs B1 | PER TRACK A15 (master 32): T6 from A14 (64 steps, 3 trigs) in place of its own (16 steps, 9 trigs). Copy at the **wrap-body entry `0x400a43a0` on the master-wrap tick**. Reference: a stock change to A16 = A15 with A14's T6 | **IDENTICAL at all 450 ticks**: state and live events, including the next master wrap |
| C1 vs B1 | control: no load | FAIL (never locks) |
| D1 vs B1 | control: the same copy one tick later (phase D of tick 187) | FAIL: the first new step's event (step 0 at t192) is lost, then it locks from t193. One tick late is too late |
| A2 vs B2 | NORMAL A10 (16 steps): T1 from A12 | **IDENTICAL at all 260 ticks** |
| A3 vs B3 | CHANGE = 4 on A15 | FAIL, as expected: the stock change lands at the CHANGE point (t42) and **restarts every track at step 1**. With no pending stock change, the wrap body runs only at the master wrap (t186) |

**So:**
- **At a master wrap:** a Clyps landing is one record copy at `0x400a43a0`. Stock's own wrap body
  then re-homes and purges, so no per-track code of ours is needed.
- **At a CHANGE point:** the stock reference is the wrong target, because it restarts all tracks.
  A one-track rule is needed (O9). The recommended phase-continuous rule has an exact oracle: a
  never-switched run of the pattern that holds the clyp from START. That is the same oracle as the
  DJ-on case. Mid-pattern landings need our own one-track re-home to that position (the DJ-style
  `dj_bparams`/`dj_tprime` arithmetic).

**Mid-pattern landings (O9 phase-continuous), MEASURED 2026-10-23.** The reference is a
never-switched run of an in-RAM copy of A15 holding the new T6 from START. The copy is in **phase
D (`0x400a1f72`) of the tick in which the track's next step is built** (its window start). The
parts before the landing differ by construction, so read "locked from".

| run | load | landing | locked from |
|---|---|---|---|
| A4 vs R4 | A08's 16-step T6 (same length) | step 12 (t66), copy only | before the landing (t49); identical after it |
| A5 vs R5 | A14's 64-step T6 | step 12 (t66): index unchanged, copy only | **t67**, the tick after the landing |
| A6n vs R5 | the same | step 20 (t114), copy only | t192: wrong until the master wrap (old index 4 kept) |
| A6 vs R5 | the same | step 20, copy **+ STEP = 20, STEP−1 = 19** | **t115**, the tick after the landing |

| A7 vs R7 | A14's T6 with its scale set to 2x in RAM (tps 3) onto A15's 1x T6 | t66, copy only | t192: wrong until the master wrap |
| A7f vs R7 | the same | t66, copy **+ STEP 23, STEP−1 22, TICKS 0, TRK_SCALE 0** | **t67** |
| A8 vs R8 (JAM2) | **MIDI**: pattern 1's 32-step M2 onto pattern 2's empty 16-step M2 | t66, copy only | before the landing (t55); identical after it |

**The one-track landing rule.** It is measured on every case above, and agrees with DIRECT JUMP V7's
position model.
- **When.** The landing tick L must be a window start for both the old and the new tick rate
  (t′ ≡ 0 mod lcm(tps_old, tps_new)), so that no old event is still pending and the new step is
  built on L. At a master wrap, the copy at `0x400a43a0` on the commit tick is the same thing:
  stock's re-home does the rest.
- **What, in phase D (`0x400a1f72`) of L:**
  1. copy the record (plus the length/scale fix, §4.6);
  2. STEP = (t′ / tps_new + 1) mod len_new, and STEP−1 = STEP − 1;
  3. TICKS = t′ mod tps_new (0 at L);
  4. TRK_SCALE = the new scale (`0x8000663e[t]`).

  RELOAD, CNTDN and ARMED are unchanged.
- **t′, with DJ off (phase-continuous, O9):** ticks since the master's last restart,
  t′ = (m_step − 1)·tps_M + m_tick + 1, from `0x800065b2` / `0x800065b6` (the master lags the
  tracks by one tick).
- **t′, with DJ on:** DJ's clock-locked T since START, reduced mod the master cycle
  (`dj_T`, `dj_bparams`).
- **Stock re-reads** the length at each wrap (`0x400a3d7a`) and restarts every track at the master
  wrap.

Not run yet: master length INF, a cross-bank source (pure data, low risk), DJ on, and a
CHANGE-point trigger (the arithmetic is above; the trigger is our phase-G evaluation of stock's
gate rule).

**DIRECT JUMP on** (decided). DJ re-lands the whole sequencer through phase D (`0x80006687`), which
Clyps must never write. What Clyps can reuse from DJ for a single-track clock-locked landing:
- `dj_T`, running ticks since START, counted whether DJ is on or off;
- `dj_bparams`, per-track tps/len as stock's landing loader `0x400a2124` resolves them;
- `dj_tprime`.

The position is the memory-map model `step = (⌊t′/tps_t⌋ + 1) mod len_t`.

**Cost:** the memcpy `0x40020898` is ~600 longword moves, ~15–25 µs against an 8.3 ms tick at
300 BPM, so it is safe in the ISR. The rest goes to the UI task (§4.5).

### 3.5 Trig LEDs

- **The LED buffer.** `0x460ba98c` holds 1 bit per die; trig n is red die `2n`, green `2n+1`. Bit
  set `0x400131a0`, clear `0x400131c8`, brightness `0x400135b0(id, 0..15)` (cached). Stock's dim
  level is **7**. Flush `0x400136a8`.
- **The LED layer stack.** An 8-slot table at `0x460e7628`; trig LEDs are slot 0. Push `0x4007e760`
  (append, last wins), pop `0x4007e81c`, repaint and flush `0x4007e998(0)`. Descriptor
  `{next, {id, paint, tick, period}}`, which must be in RAM.
- **Stock's cue colour is yellow.** The [PTN] grid paints a cued pattern red + green. Clyps' yellow
  is the same pair, so no blink tick is needed any more.
- **Ticks** run from `0x4007e940` inside `FUN_40052200`: LED bits only there. Never a window, draw,
  toast or layer push/pop (CLAUDE.md, Session 93).
- **Classifier** (stock's `FUN_4009a464` skips `+0x10..0x17` and reads no locks, the bug
  EMPTY_PATTERN_LED_FIX fixed).
  - **Full**: `+0x00` (sample / note trigs) non-zero, and nothing else (O6, decided).
  - Else **half**: `+0x08..0x37` non-zero (trigless layers, recorder trigs), or any lock ≠ `0xff`
    (the AND-8-longs scan from `patch_pattern_led.s`).
  - Else **empty**.
  - MIDI: masks `+0x00`/`+0x08`, locks `+0x30`.
  - Cost: ≤ ~13k instructions for 16 slots. Cache it, and re-classify on bank/track/side change and
    the playing slot per paint (Session 119's lesson).

### 3.6 The bank file writer (reference; not needed now that O2 is "write what you hear")

All 5 stock bank writes go through `0x400917c8`. Its callers are the storage-task dispatcher
`0x40084dc2`, `0x4008505c` (SAVE AS NEW), `0x400851e0` and `0x40085534`, plus `0x40091a9c`.

`0x400917c8` opens `%s/bankNN.work` with mode `"w"` and calls `0x4008b278(fh, bank)`. That function
calls the pattern writer `0x4008a6fc`, which emits each track record field by field from the slab.

A hook that switches the source pointer of an affected track to its backup covers every save path,
and never touches the slab the sequencer is reading. Which user actions post those jobs (SAVE, SYNC,
project change) is not mapped (**I**).

---

## 4. Design

### 4.1 State (in our own DRAM, never `0x80006a40+`)

| item | size | notes |
|---|---|---|
| mode flags, window handle, shown bank, cursor | ~12 B | |
| `cls[16]` | 4 B | 2-bit classes, shown bank × active track |
| per track ×16: `src` (bank, pattern \| SAVED \| OWN) | 32 B | what is playing; drives red and `▸` |
| per track ×16: `cue` (bank, pattern \| SAVED \| none) | 32 B | |
| per track ×16: `saved_valid`, `saved_len`, `saved_scale` | 48 B | |
| **originals** | 4,096 slots, **9,326,592 B**, + a 512 B valid bitmap | indexed by (bank, pattern, track) |
| **saved sequences** | **36,432 B** | [FUNC]+[YES] |
| keymap layer + records | ~24 + 34 × 26 B | trigs, arrows, YES/NO, TRACK, PTN/BANK, FUNC, end |
| encoder records, LED descriptor | ~200 B | |

### 4.2 Chord edges (UI task)

On the second key's press, when the other is held and the arranger is off:
1. If [BANK] was first, tear it down once: dismiss if a window with onClose `0x4007b408` is up,
   else call `0x4007b408`. If [PTN] was first, its layers stay harmlessly under ours.
2. Skip the second key's press entirely.
3. Set `PTN_CONSUMED = 1` and `BANK_SEL = 2` (inside RELOAD's unit: `rl3_bank_used = 1`).
4. Classify, open the view, and push our keymap layer and LED layer (last).

On each [PTN]/[BANK] release: if the view is closed and the chord is no longer complete, pop the
LED layer, then repaint.

### 4.3 The view

- **One open path and one idempotent teardown.** The teardown is also the window's close_cb. It
  closes the handle (`0x40055db4`), pops the keymap layer, clears the flag and sets RDRAW.
  Eviction, [NO], loads and track changes all funnel through it.
- **Handlers** act on event 1 only, with repeat set in our arrow records. They draw in place, and
  clamp and wrap at one choke point.
- **TRACK records** call the setter path (not the base handler `0x40040250`, which is RELOAD's
  detour) and carry no sub-map, so REC_TRIG_MUTE's `0x400d164a` is not linked over us (**I**,
  emulator check).
- **[FUNC]** is swallowed. [YES]/[NO] read its held flag.

### 4.4 RELOAD2's bug classes and the counter to each

| RELOAD2 bug | counter here |
|---|---|
| dead YES/NO, borrowed layers, YES swallowed under [BANK] | own layer pushed last with its own records; no detours on `0x4005e4c8`/`0x4005e25c` |
| [PTN] triple-booked | one decision point per order; consumed flags |
| collision with DJ's poke | never write another layer's records |
| SELECT BANK flashing | suppressed before it draws (O12); one teardown |
| arrows double-stepping, pairing wrong | event 1 only; one record per code |
| walk-away left it primed | the teardown is the close_cb |
| snapshot corruption | no saved dispatch slots |
| redraw tripped teardown | draw in place |
| unbounded selection | one clamp/wrap choke point |
| BUSY | none; last pick wins |

### 4.5 Loads and originals

A **load** onto track t from source S (a slot, SAVED or ORIG):
1. **Original.** If S is not ORIG and (playing bank, pattern, t) has no original yet, copy the
   playing pattern's record → that original slot and set its valid bit.
2. **Source.** A slot's record, `saved[t]`, or the original (ORIG). After a restore, clear the
   original's valid bit.
3. **Write it like a stock edit:**
   - stopped: in the key handler;
   - running: write `cue[t]`; the phase-G hook (or DJ's landing when DJ is on) copies on the
     landing tick (§3.4);
   - then the SRAM mirror (when the destination bank is the UI bank) and `0x40029b9c(t)` (dirty
     flags and refresh) in the UI follow-up.
4. **Restore-all** cues every track with an original on the playing pattern, onto one landing.

Originals are cleared at boot and beside project load (never in the body of `0x4000faf0`).

**The UI follow-up** runs from a UI-task tick. The candidate is the 60 Hz UI tick task `0x40056c40`
(message type 1, DTIM1 ÷2); its "always runs" property is **I**. It covers the SRAM mirror, the
dirty flags and refresh, and the LED repaint.

### 4.6 Length/scale

| source | destination | write |
|---|---|---|
| PER TRACK | PER TRACK | none (in the record) |
| NORMAL | PER TRACK | record `+0x50/+0x51` := source `+0x8e53/+0x8e54` |
| any | NORMAL, same len/scale | none |
| any | NORMAL, different | convert (below) |

**The conversion:**
- back up the 12 trailer bytes and every track's `+0x50/+0x51`;
- set `+0x8e55 = 1`, `+0x8e50 = (u16)+0x8e53`, `+0x8e52 = +0x8e54`;
- set every other track (audio `+0x50/+0x51`, MIDI record `+0x28/+0x29`) := `+0x8e53/+0x8e54`.

Keep the 12 trailer bytes with the original, so a restore can undo it. Respect the clamps (`0x4009a670`,
`0x4009aa4a`), and refresh `SCALE_IX 0x8000663d` if the master scale changes.

### 4.7 Saved sequences

- **[FUNC]+[YES]** copies the playing pattern's track-t record (what is heard) plus its resolved
  length/scale → saved[t], and sets `saved_valid`. The header flashes `SAVED`; no toast is needed.
- **[FUNC]+[NO]** is a load with S = SAVED (§4.5). It does nothing if `!saved_valid`.
- **The buffers live in the DRAM reserve.** Boot clears them, and so does a hook beside project
  load: they last only while the unit runs its project.

---

## 5. Interactions

| feature | if nothing is done | rule |
|---|---|---|
| RELOAD_FROM_PROJECT | with the chord held, TRACK triggers a TRK SEQ reload; both own [BANK]'s press/release sites; a RELOAD of a track that has an original | our layer owns TRACK; in KYOTI, recognise the chord inside `rl3_bank_show`/`rl3_bank_rel`; a RELOAD leaves the original alone (it is still "before Clyps") |
| DIRECT_JUMP_KYOTI | [PTN]+[YES] toggles DJ; a DJ jump changes the playing pattern | [YES] with the chord held goes to DJ's toggle; a jump drops cues; Clyps loads use DJ's landing when DJ is on; never write `0x80006687` |
| REC_TRIG_MUTE | holding TRACK links its YES/NO sub-map over us | our TRACK records carry no sub-map (verify) |
| EMPTY_PATTERN_LED_FIX | — | we never call `FUN_4009a464` |
| BLACKPYRAMIDS_303 | an empty trigless lock is a tie there | half green is cosmetic only |
| octabam / Octakit | `FUN_4006d94c` is Octakit's | not used |

## 6. Size and placement

| unit | estimate |
|---|---|
| chord edges, suppression | ~250 B |
| view: 2 × 8 draw, keys, teardown, track hook | ~1,000 B |
| grid: LED layer, classifier | ~400 B |
| landing hook, copy, re-home, purge, length/scale | ~800 B |
| DJ-landing variant | ~300 B |
| originals: capture, lookup, restore one, restore all, `ORIG` entry, [PAGE] | ~700 B |
| saved sequences | ~200 B |
| UI follow-up | ~150 B |
| records, strings | ~1.2 KB |
| **code** | **≈ 5 KB** |
| **buffers** | saved 36,432 B + sequence originals 9,326,592 B + Part-slice originals ≈ 393,216 B ≈ **9.3 MiB** |

The buffers need RAM, so **Clyps is a DRAM unit, standalone and in KYOTI**. It uses octabam's
loader route (`tools/dram/`, as `build_kyoti.py` already does for RELOAD). The reserve is about
1,525 pages of 6,144 B, i.e. ~9 MiB taken from the ~85 MB sample pool. It inherits the known
cosmetic FREE MEM / MEMORY-page mismatch (`kb/caves.md` §5).

⚠️ A reserve this large is new. The known DRAM units are 1 page (RELOAD) and 16 pages
(BLACKPYRAMIDS_303), so the allocator and the arena geometry need a canary run at this size.

The ROM keeps only the guarded detours:
- two chord edges (one inside RELOAD's unit in KYOTI);
- phase G;
- `FUN_40083bc0`;
- the UI tick;
- [PTN]/[BANK] release;
- project load (clearing originals and saved sequences).

## 7. Test plan

**Emulator (logic only: no UI tick, no real DSP path).**
- **The landing oracle** (`diag_reflock` + `cmp_reflock`). Run A plays pattern 1 and cues a Clyps
  load of T6 from pattern 4 at step k. Run B plays pattern 1 and cues a stock change to pattern 2,
  where pattern 2 = pattern 1 with T6 pasted from pattern 4. Events after the landing must be equal.
  - **The user builds the fixture on the device** with stock track copy/paste, then exports it.
  - Variants: NORMAL and PER TRACK; CHANGE OFF/4/master; a faster-than-master track; INF master;
    MIDI; a cross-bank source; stopped.
  - DJ-on runs are graded against a never-switched reference of pattern 2.
- **The originals oracle.** Load clyps onto several tracks, edit one, leave and come back, then
  restore one and restore all: the slab bytes equal the pre-Clyps bytes, and the landing equals a
  stock change to an in-RAM copy holding the originals.
- **The stress gate** (shape of `diag_reload3_bankdefer.py`). Both chord orders and both release
  orders, with YES / NO / trig / FUNC+YES / FUNC+NO / eviction-by-toast cycles. Every layer list,
  LED layer, window slot, `PTN_CONSUMED`, `BANK_SEL` and our state returns to baseline, and no SELECT
  window or toast appears.
- **Conflicts:** RELOAD's chords alone, DJ's toggle, REC_TRIG_MUTE outside Clyps.

**Hardware** (a FLASHING §4 entry when built). Write down what was observed, not a verdict:
- [ ] Both chord orders and both release orders: no SELECT window, no toast.
- [ ] Every key in §1.3, held and latched; PLAY/STOP/mutes pass through.
- [ ] Grid: full, half, off, red, yellow; bank and track changes.
- [ ] Landing on time by ear, NORMAL and PER TRACK, CHANGE OFF/4/master, DJ on and off.
- [ ] Leave the pattern and return: the own sequences are back; SAVE then reload project: no clyp
      was saved.
- [ ] [FUNC]+[YES] on T6 in bank A, then [FUNC]+[NO] in bank F: the saved sequence plays there.
- [ ] Power cycle: no clyp and no saved sequence survives; the own sequences are intact.
- [ ] A toast or menu over the view leaves nothing stuck.

## 8. Phases (each a separate flash)

1. **Oracles, no feature code.** The user exports the fixture; prove the copy point, the per-track
   re-home and the DJ-landing rule in the emulator.
2. **The view and the grid** with stopped-transport loads only: chord, suppression, the 2 × 8 table,
   keys, TRACK follow, colours. This is where RELOAD2 failed, so it is tested alone.
3. **Originals**: capture, `ORIG`, [PAGE], restore-all, the 9 MiB reserve canary.
4. **Cued landing** while running, then the DJ landing, then held-state picking (yellow → red).
5. **Saved sequences.**
6. **KYOTI** integration.
7. **Phase 2: names.**

## 8b. Phase 2 status (2026-10-23)

- **Built:** `tools/build_clyps.py` (WIP) → `out/OCTATRACK_OS1.40C_CLYPS.syx` (`140C_CLYP2`, sha256
  `8d6a0ef9…`), CF `.bin` `d7a458aa…`, mainos `0e163f38…`. `tools/clyps/patch_clyps.s` is
  3,606 B in the classic cave at `0x400d6500`, with detours at `0x4005a044`, `0x4007af80` and
  `0x4007b3e0`.
- **Contents:** Clyps mode, the 2 × 8 view, the grid, and the held / latched states.
  - Loads apply at once (no cued landing yet).
  - Not in it yet: originals, saved sequences, FULL loads, page LEDs, RELOAD's [BANK] deferral.
- **Emulator gate** `tools/diag_clyps_ui.py`: real key events through `set_key_state`
  `0x40031734`, 28/28 checks on OT DEMO. It covers:
  - both chord orders; held load; latched [YES] / [NO];
  - bank wrap; TRACK selection;
  - layer lists back to baseline;
  - the grid LEDs;
  - the stock [PTN]/[BANK] controls.

  Route A does not run the UI redraw, so the screen layout is **hardware-only**.
- **Two bugs the gate found, both fixed:**
  - **Key timing mismatch.** A key record's hold delay must equal the base keymap's. A key
    pressed under one layer and released under another, with a different delay, leaves its
    timer record in the repeat list `0x460d1660`. Its next press then links the record to
    itself, and the UI task loops forever.
  - **TRACK keys.** Their stock handler selects the track on **release**, so press, hold and
    release are all forwarded to `0x40040250`.
- **Hardware checklist:** FLASHING.md §4, CLYPS.
- **Hardware report on `140C_CLYP2` (2026-10-23).** Every checklist gesture works. Requests:
  - an ATTR-style window that leaves the track columns visible, with a 1-px border;
  - a dark header with exactly 1 black px above and below its text;
  - a small font;
  - slots 8/16 were blank and row 9 was 1 px left (both fixed);
  - no `>` marker;
  - a load-mode label;
  - LEFT/RIGHT at least twice as fast.
- **`140C_CLYP3`** (syx `63e92f85…`, CF `.bin` `edc18b58…`), NOT flashed:
  - a 106 × 64 window (screen columns 11–116);
  - font `0x400ba84e` (5 px), 2 × 8 rows at a 6-px pitch;
  - a header/separator layout verified pixel-exact in the emulator;
  - footer `LOAD: SEQ`. `LOAD MODE: SEQ + MACHINE/FX` measures 123 px against 104 inside, so
    the label is `LOAD: SEQ + MACHINE/FX` (98 px);
  - LEFT/RIGHT delay 20 / repeat 10 (stock 30 / 30).

  Gate 28/28.
- **Screen rendering in the emulator** (`tools/clyps_render.py`). Stock's compositor
  `0x40013abc` (the UI task runs it when RDRAW is set) is called directly. Read its double-buffered
  target `[0x400b9710]` **before** the call. It has the LCD plane's rotated layout.

## 9. KB corrections found by this scope

To be applied with the first code commit:
- `FUN_4005829c` is `(w, h, dx, dy, prio, close_cb)`, centred, and its 5th argument is an eviction
  priority, not a style. `memory-map.md` has `(x,y,w,h,…)`, and RELOAD_REDESIGN's "style 4" is that
  priority.
- Arrows: UP `0x33`, DOWN `0x20`, LEFT `0x34`, RIGHT `0x21`.
- `0x40027e00` is an undo-kind clear, not a dirty flag.
- [PTN] does push a keymap layer, `0x400bf0f2`.
- **`0x40009094` is 1,492 B and only moves parameters**: it ends at `0x40009664` with `jmp 0x40000c3c`.
  The eDMA re-arm, tempo republish and INTC unmask belong to the next function, `0x4000966c`
  (engine restart), which calls `0x40009094` last. memory-map.md merged the two.
- [FUNC] (`0x2d`) has a dispatcher record (press `0x4004e954`, sub-map `0x400bfa1e`), and its held
  flag is `0x46c7dd26`. The "not located" note is obsolete.
- MKI has no [PART] key (T1). On MKII it is `0x1d` → `0x4002e7c8`.

---

## 10. Phase 2 — named sequences (on the radar, not designed in detail)

**Not in the bank file.**
- The loader requires exact chunk lengths (−51 at `0x4008cf66`), and a 16-bit checksum covers every
  byte (−54 at `0x4008e2b4`).
- The slab tail `+0x8e5c..+0x8ed7` (124 B) and the audio `+0x899` pad are never serialised.
- `project.work` refuses an unknown `[SECTION]`.

**A sidecar in the project folder** (e.g. `clyps.work` / `clyps.strd`).
- Stock ignores it.
- Size: 16 banks × 16 patterns × 16 tracks × 10 B ≈ 40 KB in DRAM.
- Written beside the bank writer `0x400917c8` and copied to `.strd` when SAVE copies `.work → .strd`,
  so names are exactly as saved as the sequences.
- Primitives: FOPEN `0x40016864`, FREAD `0x40016564`, FWRITE `0x400166b8`, FCLOSE `0x4001677c`,
  copy `0x40016388`, PROJDIR `0x40025230`.

**Entry.** On the cursor slot, stock's editor `FUN_4007e664(maxlen, title, buf, charset, done_cb)`
(RENAME PART: `(6, "RENAME PART", buf, 1, 0x4002e944)`).
- maxlen 10, charset 1.
- Priority 5, so the Clyps view survives under it.
- Test `0x460e7612` after the call.
- The gesture is to be chosen ([FUNC]+[YES] is now save): e.g. [FUNC]+[BANK] on the cursor slot.

**What follows the data.** Names follow a slot's data. With the non-destructive model they never
move with a clyp, because a clyp is never written into a pattern. Stock copy/paste and SAVE AS NEW
would need hooks to carry names.

Its own decisions come then: name length, the gesture, paste behaviour, SAVE AS NEW, and whether
audio and MIDI tracks share one name space.

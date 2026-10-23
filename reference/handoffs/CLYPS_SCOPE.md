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

**Loading.** [YES] or a trig loads the chosen sequence onto the active track. The load follows the
pattern settings (it is cued like a pattern change), and the Part does not change.
- If the chord is no longer held, the load **closes Clyps** (view and grid).
- If the chord is still held, the view closes but the Clyps grid stays. Further trig taps keep
  picking, cued sequences light **yellow**, and a sequence turns **red** once it plays. Clyps ends
  when the chord is released.
- [NO] closes without loading.

**The Clyps grid.** Full green = sequence data, half green = only trigless trigs or locks, off =
empty, red = playing, yellow = cued.

**Saved sequences.** In Clyps mode, **[FUNC]+[YES] saves** the active track's sequence and
**[FUNC]+[NO] reloads** it. There is one saved sequence per audio track and per MIDI track. They
survive pattern and bank changes but not a power cycle.

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
- **≈ 73 KB of RAM** for the 16 saved sequences and the 16 "own sequence" backups the
  non-destructive model needs.

Both go in DRAM through the loader route that KYOTI V1.5 and BLACKPYRAMIDS_303 already use, at a
cost of about 12–14 pages (≈ 80 KB) of sample memory.

The modal-window risk from rev 1 remains. Every RELOAD2 bug class has a counter (§4.4), and the
stress gate in §7 checks them.

Evidence: static reads of our own `section_3_MAIN_OS.bin`, confidence **C** unless marked **L**
(from a doc) or **I** (inferred). Nothing has been run in the emulator, built or flashed.

---

## 1. Behaviour

### 1.1 Entering and leaving Clyps mode

- **Entering.** Pressing the second of [PTN]/[BANK] while the first is held, in either order, enters
  Clyps mode. The view and the grid open together on the bank the track's playing sequence came
  from, with the cursor on its slot. Neither key's stock action happens, and no SELECT window or
  toast appears on either release.
- **The view stays open after the chord is released**, until one of these:

| event | effect |
|---|---|
| [YES], a trig, or [FUNC]+[NO] (a load), chord **not** held | load; close the view **and** the grid |
| a trig, chord **still held** | load; close the view; the **grid stays** while the chord is held |
| [YES], chord still held | not a load: DIRECT JUMP's [PTN]+[YES] toggle |
| [NO] | close the view and, unless the chord is held, the grid; no load |
| any window that evicts ours | same teardown as [NO] |

- **The grid ends** when the view is closed and the chord is no longer complete (either key
  released).
- **Re-holding the chord while the view is open** counts: a trig pick then keeps the grid.

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

### 1.3 Keys in Clyps mode

| key | Clyps view open | Clyps grid only (chord held, view closed) |
|---|---|---|
| UP / DOWN `0x33`/`0x20` | cursor, wrapping, auto-repeat | swallowed |
| LEFT / RIGHT `0x34`/`0x21` | bank −/+, wrapping | bank −/+; a short stock toast names the bank (O8) |
| [YES] `0x31` | load the cursor slot, then close (§1.1) | DIRECT JUMP toggle |
| [NO] `0x32` | close, no load | swallowed |
| [FUNC]+[YES] | **save** the active track's sequence; view stays; header shows `SAVED` | same |
| [FUNC]+[NO] | **reload** the saved sequence **immediately** (O3, decided), then close as in §1.1; nothing if none saved | same, immediately |
| TRIG 1–16 | load that slot, close (§1.1) | load (cue), yellow → red |
| TRACK 1–8 | change active track; view and grid follow; bank kept | same |
| [PTN] / [BANK] | swallowed (their held state still counts as "chord held") | — |
| [FUNC] `0x2d` | swallowed; only its held flag `0x46c7dd26` is read | same |
| encoders | swallowed (O10) | passed through |
| all else (PLAY, STOP, CUE, mutes, MIDI, …) | passed through | passed through |

### 1.4 The Clyps grid

These rules apply to the shown bank and the active track.

| LED | meaning |
|---|---|
| green, full (15) | the slot has sample trigs (audio) or note trigs (MIDI) |
| green, half (7, stock's dim level) | data, but no sample/note trigs: only trigless trigs, trigless locks or recorder trigs |
| off | empty |
| **red** | the sequence playing on the track; for a clyp, its source slot |
| **yellow** (red + green full; stock's own colour for a cued pattern) | cued; visible only while the chord is held after a pick |

When the saved sequence is what's playing, no slot is red, and the view header shows `SAVED ▸`.

For the playing pattern's own slot, the grid and view always describe its **own** sequence (from
the backup, §1.5), not the clyp on the track.

### 1.5b Originals — an open proposal (2026-10-23)

The user sees the benefits of both models below (keep vs restore) and would use both. Proposed
way to have both:

- **The base rule is keep.** It is stock-like: a load is an edit, and the grid holds what you
  did, whether you leave the pattern or come back.
- **Clyps also keeps originals, automatically.** The first time Clyps replaces a track in a
  pattern, it keeps what that track held just before. That is the RAM state, unsaved edits
  included, keyed by (bank, pattern, track).
  - **First one wins:** later loads and edits never replace the original.
  - Plain edits made without Clyps are never captured.
  - The pool is cleared by a power cycle or a project reload.
- **Ways back:**

| gesture | does |
|---|---|
| a 17th cell `ORIG` in the view, after slot 16 in the cursor cycle (present only when this track has an original) + [YES] | restore this track's original, cued like any load |
| chord held + [NO] (O14) | restore every track of the playing pattern that has an original, on one landing |
| AUTO-RESTORE mode (O15) | leaving a pattern restores its originals: the restore model, as a toggle |

- **Restoring a track drops its original.**
- **When the pool is full**, the load still happens, with a toast that no original was kept.
- **Optional:** in Clyps mode the TRACK LEDs show which tracks differ from their originals (O16),
  and a `SAV` cell beside `ORIG` makes the saved sequence pickable from the list.
- **Cost:** ~2.3 KB per original (O13), about 600–900 B more code, and the same landing machinery
  as any load.

The text of §1.5 below describes the restore model (rev 2). It stays here as the AUTO-RESTORE
behaviour, until O1 is settled.

### 1.5 Loading — non-destructive (the restore model; O1 is open)

The user's model (2026-10-23): a clyp replaces the pattern's own sequence on the track, *and* the
original stays available by picking its own slot again.

A plain copy (rev 1) makes that true for every slot **except the playing pattern's own slot**. That
slot is the one the copy writes into, so after one load it holds the clyp and its original is gone.
Clyps therefore keeps a backup:
- **The first time a clyp replaces a track's own sequence**, Clyps copies the own sequence into
  that track's backup (one per track). The playing pattern's own slot is listed from the backup,
  and **picking it puts the original back.**
- **Leaving the pattern** (a stock pattern change, a DIRECT JUMP, a bank change) restores every
  track's own sequence from its backup to the pattern that was left, and drops the backups (O1). A
  clyp is thus a live state of the playing pattern: Clyps never permanently changes a pattern. To
  carry a clyp (edited or not) to another pattern, use [FUNC]+[YES] / [FUNC]+[NO].
- **What reaches the card and the power-cycle copy is always the own sequences** (O2).
  - A bank written to the card while clyps play writes the backups for those tracks.
  - A Clyps load writes neither the SRAM mirror nor the bank's unsaved flag.
- **Edits to a clyp** (GRID/LIVE REC) are part of the clyp and go when the pattern is left (O1b).
  Capture them with [FUNC]+[YES] first.

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
  agreed). The conversion is part of the live state too: it is undone when the pattern is left, and
  never saved (§4.6).

### 1.6 Saved sequences ([FUNC]+[YES] / [FUNC]+[NO])

- **16 buffers**, one per audio track and one per MIDI track, kept in DRAM. They are kept across
  pattern and bank changes, and **destroyed by a power cycle or a project reload** (decided
  2026-10-23).
- **[FUNC]+[YES]** copies what the active track is playing now: the clyp or the own sequence,
  including edits, plus its resolved length/scale.
- **[FUNC]+[NO]** loads the buffer onto the active track as a clyp. It follows the same timing,
  backup and restore rules as any Clyps load.
- **Unlike the Analog Rytm**, these are per track, independent of pattern and bank, and never saved.

---

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
- **Recorder trigs:** they are part of each audio track's record (REC1–3 masks), so every load,
  save and restore carries them. A pattern has 16 track records, recorder trigs included.

### Open — recommendation first

| # | question | recommendation | alternative |
|---|---|---|---|
| **O1** | Leaving a pattern after Clyps loads (the user is torn and uses both) | **keep** (stock-like: what is on the grid stays) **plus automatic originals** (§1.5b), restored on demand | restore on leave; or an AUTO-RESTORE mode toggle over the same originals |
| **O1b** | Edits made to a loaded sequence | stay, as stock edits do; the original still means "before Clyps touched it" | lost on leave (restore model) |
| **O2** | A bank written to the card while clyps play | with keep: what is heard, as stock | with restore: the own sequences (bank-writer hook) |
| **O8** | LEFT/RIGHT in the grid-only state: the chord still held after a trig pick closed the view (the user's 2026-10-22 spec: the LED view "will remain open, until the user releases Pattern + Bank") | change the bank the grid shows, with a short stock toast `BANK B` | swallowed |
| **O13** | Originals pool size (§1.5b) | 128 (~290 KB) | 256 (~590 KB) |
| **O14** | Restore-all gesture | chord held + [NO] | another gesture |
| **O15** | AUTO-RESTORE mode toggle | offer it (same storage, different trigger) | manual restores only |
| **O16** | TRACK LEDs show which tracks differ from their originals | yes, in Clyps mode | no |
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

Not run yet: MIDI tracks (OT DEMO has no MIDI trigs), a track faster than the master, master
length INF, a cross-bank source, DJ on.

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

### 3.6 The bank file writer (for O2)

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
| per track ×16: `home_valid`, `home_bp` (bank, pattern) | 48 B | the backup belongs to this playing pattern |
| per track ×16: `src` (bank, pattern \| SAVED \| OWN) | 32 B | what is playing; drives red and `▸` |
| per track ×16: `cue` (bank, pattern \| SAVED \| none) | 32 B | |
| per track ×16: `saved_valid`, `saved_len`, `saved_scale` | 48 B | |
| **backups** | 8 × 0x91a + 8 × 0x8b0 = **36,432 B** | own sequences of the playing pattern |
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

### 4.5 Loads, backups and restores

A **load** onto track t from source S (a slot, or SAVED) does the following:
1. **Backup.** If `home_valid[t]` is clear, or `home_bp[t]` is not the playing pattern, copy the
   playing pattern's record → backup[t] and set `home_*`.
2. **Source.** If S is the playing pattern's own slot, the source is backup[t], and afterwards
   `home_valid[t]` is cleared (the own sequence is back). If S is SAVED, the source is saved[t].
3. **Then:**
   - stopped: copy in the key handler;
   - running: write `cue[t]`; the phase-G hook (or DJ's landing when DJ is on) copies, re-homes, purges and
     resets on the landing tick (§3.4);
   - either way: set `src[t]`, then run the UI follow-up.

A **restore** happens when the playing (bank, pattern) changes, whether by a stock commit, a DJ
jump, a bank change or a project load. For every t with `home_valid` and `home_bp` = the pattern
left behind:
- copy backup[t] → that slab, and → the SRAM mirror (cleaning any bytes an edit wrote there);
- undo a NORMAL→PER TRACK conversion (§4.6);
- clear `home_valid`.

This runs in the UI task after the landing, and after any HOLD track has finished reading the
outgoing slab. Pending cues are dropped.

**Invalidation without a restore.** Stock rewrites the pattern (RELOAD_FROM_PROJECT on that track,
a project or bank reload, a pattern paste/clear onto it) → drop that backup without restoring it.
The sites are to be listed: RELOAD's worker `rl_job`, the type-0x14 doneFn, project load (beside
`0x4000faf0`, never in its body), and paste `0x4002b654`.

**The UI follow-up.**
- Runs `0x400339d8`, `0x4009da20(t)` / `(t+8)` and `0x400486cc`, but no dirty flags and no SRAM
  write on a load.
- Then the LED repaint and the D2-style teardown.
- It runs from a UI-task tick. Candidate: the 60 Hz UI tick task `0x40056c40` (message type 1,
  DTIM1 ÷2). Its "always runs" property is **I**.

**The bank-save hook** (§3.6): a track with a live backup is written from the backup.

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

It is restored with the backups when the pattern is left. Respect the clamps (`0x4009a670`,
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
| RELOAD_FROM_PROJECT | with the chord held, TRACK triggers a TRK SEQ reload; both own [BANK]'s press/release sites; a RELOAD of a track with a backup | our layer owns TRACK; in KYOTI, recognise the chord inside `rl3_bank_show`/`rl3_bank_rel`; RELOAD drops that track's backup |
| DIRECT_JUMP_KYOTI | [PTN]+[YES] toggles DJ; a DJ jump changes the playing pattern | [YES] with the chord held goes to DJ's toggle; a jump drops cues (and restores, under AUTO-RESTORE); Clyps loads use DJ's landing when DJ is on; never write `0x80006687` |
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
| backups and restore, invalidation hooks, bank-save hook | ~700 B |
| saved sequences | ~200 B |
| UI follow-up | ~150 B |
| records, strings | ~1.2 KB |
| **code** | **≈ 5 KB** |
| **buffers** | **72,864 B** |

The buffers need RAM, so **Clyps is a DRAM unit, standalone and in KYOTI**. It uses octabam's
loader route (`tools/dram/`, as `build_kyoti.py` already does for RELOAD), with a reserve of about
13–14 pages of 6,144 B. That takes ~85 KB from the sample pool, and inherits the known cosmetic
FREE MEM / MEMORY-page mismatch (`kb/caves.md` §5).

The ROM keeps only the guarded detours:
- two chord edges (one inside RELOAD's unit in KYOTI);
- phase G;
- `FUN_40083bc0`;
- the UI tick;
- [PTN]/[BANK] release;
- the bank writer;
- the invalidation sites.

## 7. Test plan

**Emulator (logic only: no UI tick, no real DSP path).**
- **The landing oracle** (`diag_reflock` + `cmp_reflock`). Run A plays pattern 1 and cues a Clyps
  load of T6 from pattern 4 at step k. Run B plays pattern 1 and cues a stock change to pattern 2,
  where pattern 2 = pattern 1 with T6 pasted from pattern 4. Events after the landing must be equal.
  - **The user builds the fixture on the device** with stock track copy/paste, then exports it.
  - Variants: NORMAL and PER TRACK; CHANGE OFF/4/master; a faster-than-master track; INF master;
    MIDI; a cross-bank source; stopped.
  - DJ-on runs are graded against a never-switched reference of pattern 2.
- **The restore oracle.** Load clyps, edit one, change pattern, come back: pattern 1's slab, its
  SRAM mirror and a card save all equal the pre-Clyps bytes. Also a bank save while clyps play, and
  SAVE AS NEW.
- **The stress gate** (shape of `diag_reload3_bankdefer.py`). Both chord orders and both release
  orders, with YES / NO / trig / FUNC+YES / FUNC+NO / eviction-by-toast cycles. Every layer list,
  LED layer, window slot, `PTN_CONSUMED`, `BANK_SEL` and our state returns to baseline, and no SELECT
  window or toast appears.
- **Conflicts:** RELOAD's chords alone, DJ's toggle, REC_TRIG_MUTE outside Clyps.

**Hardware** (a FLASHING §4 entry when built). Write down what was observed, not a verdict:
- [ ] Both chord orders and both release orders: no SELECT window, no toast.
- [ ] Every key in §1.3, view and grid-only; PLAY/STOP/mutes pass through.
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
3. **Backups and restore**, the bank-save hook, invalidation.
4. **Cued landing** while running, then the DJ landing, then grid-only picking (yellow → red).
5. **Saved sequences.**
6. **KYOTI** integration.
7. **Phase 2: names.**

## 9. KB corrections found by this scope

To be applied with the first code commit:
- `FUN_4005829c` is `(w, h, dx, dy, prio, close_cb)`, centred, and its 5th argument is an eviction
  priority, not a style. `memory-map.md` has `(x,y,w,h,…)`, and RELOAD_REDESIGN's "style 4" is that
  priority.
- Arrows: UP `0x33`, DOWN `0x20`, LEFT `0x34`, RIGHT `0x21`.
- `0x40027e00` is an undo-kind clear, not a dirty flag.
- [PTN] does push a keymap layer, `0x400bf0f2`.

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

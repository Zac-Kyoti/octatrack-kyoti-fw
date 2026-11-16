# Clyps user manual — handoff (2026-11-15)

Start here if you are the session writing the Clyps manual. Read this whole file first, then
`CLAUDE.md` (repo rules), then the sources in §5. Everything below is current as of **Clyps CL38**
(trkseq commit `cfe1a54`, flashed by the author as the full image "KY+CL DJC9", 2026-11-15).

## 1. The task (the author's words, 2026-11-15)

> "A concise, conversational user manual for Clyps. It will need to describe the conceptual
> organization of the suite, the conceptual organization of the front panel controls, the different
> types of loads and reloads, how they differ, and what their constraints are. We'll need to describe
> what the user can expect, and maybe some best practices for using the system. I do not want a lot of
> hyper-technical details — no code-speak, or Claude-speak. Diagrams are welcome and may be helpful.
> Don't leave anything out, but do focus on the high level organizational strategy and logic of the
> system, and the playable features."

**Scope rule (the author, 2026-11-15): "Don't need history. Just current features, what they do, and how
to use them."** No changelog, no "previously", no version numbers in the manual.

**Standing rule (the author):** the manual is updated whenever a Clyps change affects its (approved)
content. Note it in the Clyps change's NOTES entry when you do.

### Audience and voice
- An Octatrack MKI player who knows stock patterns, Parts, banks, tracks, CHAIN AFTER, scenes and the
  parameter pages, but nothing about this firmware's internals.
- Conversational, second person, short paragraphs. Explain *why* the system is organised as it is
  (the mental model) before *what each key does*.
- **No:** addresses, function names, register/byte talk, "detour", "hook", "DRAM", build/commit ids,
  emulator talk, session history ("CL34 changed..."). **Yes:** Octatrack terms as printed on the unit
  and in Elektron's manual ([PTN], [BANK], [FUNC], [CUE], [YES], [NO], trig keys, TRACK keys,
  PLAYBACK/AMP/LFO/FX1/FX2, SETUP page, Part, CHAIN AFTER, SILENCE TRACKS).
- Terms to use consistently (the author's): **Clyps**, the **Clyps view** (the screen), the **Clyps
  grid** (the trig LEDs while Clyps is open), **slot** (one of the 16 patterns of a bank shown in the
  view), **original**, **SEQ** / **FULL** load (the UI says `TRK SEQ` / `TRK FULL`; older notes say
  "ALL"), **temp save / temp reload**, **group** (multi-track), **peek**.

### Deliverable (propose to the author; adjust to their answer)
- `docs/clyps/MANUAL.md` in the repo (Markdown, renders on GitHub), diagrams beside it in
  `docs/clyps/` (SVG or PNG). Keep it one file, ~8–15 screens of reading.
- Diagrams that would help most: (1) the mental model — banks × 16 slots, the tracks, "your pattern",
  a sequence coming from a slot; (2) the Clyps view annotated (header, two columns, highlight bar,
  select box, arrows, "x", labels); (3) the grid LED legend; (4) a front-panel map of what each key
  does in Clyps; (5) a timeline: cued vs instant landing, and FULL's sound arriving with the first
  sounding trig; (6) the "where does [YES] go" cursor logic (box vs arrows).
- Real screen images: `tools/clyps_render.py` renders the view from the emulator (composes windows),
  `tools/clyps_view_html.py` puts renders in a browser page. Use them for the annotated view; never
  invent pixel layouts. (Renders need the emulator — see `CLAUDE.md` and NOTES for setup; a render
  takes minutes.)
- Get the outline approved before writing prose; then the draft; record the approval (date + what) in
  NOTES and at the top of the manual.

## 2. Proposed outline (confirm with the author)

1. What Clyps is — one paragraph and the mental model diagram ("every pattern's track sequences are a
   library of clips you can play on the pattern you are on").
2. The big ideas — your pattern vs the library; the active track; SEQ vs FULL; originals; cued vs
   instant (DIRECT JUMP); groups.
3. Opening and closing Clyps; the view (annotated); the grid LEDs.
4. The front panel in Clyps (map + table).
5. Loading a sequence: by trig, by the arrows + [YES]; SEQ vs FULL; when it lands and what you hear.
6. Going back: ORIG (SEQ / FULL), ORIG PTN+PRT, what an "original" is, SAVE PART, the "x" mark.
7. Temp save / temp reload.
8. Reloading from the project on the card (track SEQ, track FULL, the pattern).
9. Groups (several tracks at once).
10. Banks, patterns and DIRECT JUMP from inside Clyps.
11. Peek at a parameter page.
12. Naming sequences.
13. What is kept and what is lost (saving, power cycles, project loads); memory; compatibility.
14. Best practices.
15. Quick reference card (one table).

## 3. Current behaviour — the digest (CL38). Verify each item marked ⚑ before writing it.

### Opening, closing, the view
- **Open:** hold [PTN] and [BANK] together (either order). Releasing them changes nothing; Clyps stays.
- **Close:** [NO] (with a group: the first [NO] dismisses the group, the next closes). A LOAD PROJECT
  also closes it. Stock pattern / bank picks inside Clyps do NOT close it.
- **The view:** a header and the 16 slots of one bank in two columns (1–8, 9–16). Each slot shows the
  active track's sequence in that pattern: its **name** if named, else a summary (`A01 15 TR` = 15 trigs,
  `... LK` = locks only, `---` = empty).
- **Header:** `T6 LOAD: <label> BNK A` — the track, what [YES] would load, the shown bank. With a group:
  `MULTI LOAD: ...`. While [BANK] is held the bank gets a box. ORIG loads show `ORIG TRK SEQ` / `ORIG
  TRK FULL` during their flash.
- **Marks in the view:**
  - **highlight bar** (inverted) = the pattern you are on (only in its bank);
  - **select box** (thin frame) = where the active track's playing sequence came from (not drawn
    when that is your own pattern's slot — the highlight stands for it);
  - **pre-select arrows** (two arrowheads) = where [YES] will load from (your aim; see §3 "cursor");
  - **"x"** = that slot's sequence differs from its original (sequence only, never the Part);
  - your pattern's slot reads the **source** of what plays (e.g. `B14 6 TRG`, `SAVED`) until edited.
- **The grid LEDs** (shown bank, active track): red = your pattern; red/yellow flash = the slot the
  track's sequence came from; flashing yellow = a cued load; solid yellow = the arrows' slot (never on
  your own pattern's LED, which stays red); green bright = has sample/note trigs, green dim = other data
  only (locks, trigless), off = empty. Page LEDs are stock's.

### The cursor: "[YES] loads what you see"
- The **arrows** are your aim. Once you move them they stay — no load moves or hides them by itself.
- After the slot under the arrows **lands**, the arrows **tuck** under the box (or under the highlight,
  for your own pattern) and their yellow LED goes. When the box **goes away** (ORIG, temp reload, card
  reload, pattern change) or **moves** (a trig load elsewhere), the arrows **reappear** where they were.
  So you can flip between an original and a slot with [YES] and your pattern's trig, never re-aiming.
- If nothing is on screen (no box, no arrows: the track plays its own sequence and you never aimed),
  [YES] does nothing. Trigs always load.
- Arrows are per track, remembered for the session; a project load clears them.
- **Arrows follow the shown bank:** paging banks shows them on the same slot number; going back shows
  them as they were there.
- UP/DOWN move through 1–16 with wrap and auto-repeat. LEFT/RIGHT jump between the columns (1↔9 ...),
  **no wrap** at the edges.
- **A cued load blinks:** arrows on the cued slot blink (fixed 120 BPM, 2/3 on) until it lands.

### Loads (the active track, or every group member)
- **Trig** = load that slot of the shown bank. **[YES]** = load the arrows' slot.
- **SEQ** (plain) = the sequence only. **FULL** = hold [FUNC]: the sequence plus that track's sound
  from the source's Part — machine, FX, page settings, scene locks, LFO designer.
- **When it lands:**
  - DIRECT JUMP **off**: cued, landing where a stock pattern change would (CHAIN AFTER). The slot's LED
    flashes yellow meanwhile.
  - DIRECT JUMP **on**: instant — on the track's next step, in time, as if the sequence had been
    playing all along.
  - Stopped: at once.
- **FULL's sound** never lands on the outgoing sound: it reaches the track with the incoming sequence's
  first trig that actually sounds (a sequence without sample trigs: at the boundary).
- **Length and scale:** a loaded sequence keeps its own length and scale. A NORMAL-scale pattern is
  switched to PER TRACK only when a load needs it; going back to the original undoes only that.
- **Trig conditions:** a cued load starts them fresh (as a pattern change); an instant load continues
  them as if the sequence had always been there (A:B counts from PLAY / the last pattern start; PRE
  starts at "true"; a held FILL carries over).
- Loading the data that already plays does nothing. ⚑ Re-cueing / cancelling a cued load (check the
  current rule in scope §1.20 / RELOAD notes before describing it).
- Loads are edits of the pattern in memory, like any stock edit: SAVE to keep them.
- **Shared Parts:** a FULL load writes into the Part of the pattern you are on. Patterns sharing that
  Part hear it too (stock's Part model). ORIG FULL brings each track's original sound back correctly.

### Going back
- **ORIG (SEQ):** the trig of the pattern you are on → the track's original sequence. **ORIG FULL:**
  [FUNC] + that trig → original sequence + original sound. With arrows aimed at your own slot, [YES]
  does the same.
- **ORIG PTN+PRT:** [PTN] + [BANK] + [YES] → the whole pattern and its Part as originally loaded, in
  place (playing: on the next shared step, in time).
- **What "original" means:** the state when the bank was loaded — power-on, LOAD / RELOAD PROJECT, SAVE
  PROJECT, SAVE BANK, a new project. **SAVE PART** (stock Parts menu) makes the saved Part that Part's
  original (ORIG FULL / ORIG PTN+PRT bring it back as saved; sequences' originals unchanged).
- [PAGE] does nothing in Clyps.

### Temp save / temp reload
- Hold a TRACK key + [YES] = temp save that track; TRACK + [NO] = temp reload it (FULL: sequence and
  sound as saved), inside and outside Clyps. Toasts `TEMP TRK SAVED` / `TEMP TRK RELOADED` (`SAVE
  FIRST!` if none). One per track (8 audio + 8 MIDI). Each track's temp save is preloaded with what it
  plays at every originals retake. Lost at power-off and project load. Slot label after a reload:
  `SAVED TRK`.

### Reload from the project on the card (inside Clyps)
- [PTN] + TRACK = that track's **sequence** as saved on the card (`TRK SEQ` / `RELOADED FROM PROJ`).
- [BANK] + TRACK = the track's sequence **and its sound** (its Part slice) as saved (`TRK FULL`).
- [PTN] + [BANK] + trig = that **pattern** from the card: your own pattern reloads in place (in time);
  another pattern = a pattern change to it (CHAIN AFTER, or DIRECT JUMP when on).
- Landing as above (next step, in time; stopped: at once). ⚑ Confirm the toasts on the unit.
- These are Clyps' own; the standalone RELOAD_FROM_PROJECT feature is a separate firmware option and is
  never combined with Clyps.

### Groups (multi-track)
- Hold [CUE] + TRACK keys to add / remove tracks (audio and MIDI). The header reads `MULTI ...`; members'
  tabs and LEDs mark them.
- With a group: a trig or [YES] loads every member, each its own track of the chosen slot; [FUNC] = FULL
  for all; ORIG restores each member's own original.
- [CUE] held + a trig = every member that slot. [CUE] held + arrows + [YES] = every member, the arrows'
  slot.
- [NO] dismisses the group (Clyps stays). [FUNC]+[CUE] (stock's Part reload) does nothing in Clyps.

### Banks, patterns, DIRECT JUMP from inside Clyps
- [BANK] + arrows = page the shown bank (wraps). A [BANK] tap = stock's SELECT BANK; [BANK] + trig =
  pick a bank; [PTN] + trig = a real pattern change (Clyps stays open, the view follows).
- [PTN] + [YES] = DIRECT JUMP on / off.
- TRACK keys = change the active track (the view follows; arrows per track). [MIDI] switches sides.

### Peek at a parameter page
- Hold PLAYBACK / AMP / LFO / FX1 / FX2: that page shows — page 1 or SETUP, as you left it — and the
  knobs work. Release: back to the Clyps view, exactly as it was.
- A quick double tap, or [FUNC] + the page key, flips that page between page 1 and SETUP (as stock); the
  choice sticks. Clyps does not flash up between the two taps of a double tap.
- Holding two page keys: the page follows the latest; Clyps returns when both are released.
- The grid LEDs stay Clyps' during a peek. Outside a peek the knobs do nothing in Clyps.

### Names
- [FUNC] + [BANK] = name the sequence under the arrows (⚑ arrows vs box — check `cl_rename`), stock's
  name editor, 9 characters. Names follow the sequence through loads, temp saves, ORIG.
- Saved with the project (SAVE / SAVE BANK; restored by RELOAD; deleted with the project).

### What is kept, costs, compatibility
- Loads, ORIGs, groups are edits in memory until you save (as stock). Originals are retaken at every
  save / load (above). Temp saves and arrows: session only.
- Memory: Clyps reserves about 10 MB of the sample memory pool for its originals and buffers (⚑ state
  the user-facing figure; check NOTES / `build_clyps.py` output "reserve ... pages").
- Clyps ships in "KYOTI with Clyps" (with DIRECT JUMP built in) and as a standalone image. Never combined
  with the standalone DIRECT JUMP or RELOAD_FROM_PROJECT builds.
- Known, not a bug: a FULL load's new settings can be heard for a few milliseconds on the outgoing
  sound's fade (the Octatrack has one sound path per track) — describe only if the author wants it.

## 4. Which parts of `CLYPS_SCOPE.md` are history (for YOUR research only — none of this goes in the manual)

The scope grew in layers; later sections override earlier ones. For the manual:
- **Current:** §1.26 – §1.38 (persistent arrows onward), §1.27 (combinations), §1.20 (executions, groups),
  §1.9 (groups, base rules), §10.0 / §10.2 (names), and the FLASHING.md "KYOTI CL25" … "KYOTI CL38"
  walk-throughs (each is the delta the author tested on the unit — the most reliable statement of
  current behaviour, newest first).
- **Superseded (do not describe):** §1.1 / §1.3 held / latched states and close-on-load; [PAGE] as ORIG;
  [FUNC]+[YES] / [FUNC]+[NO] as temp save / reload (now TRACK + [YES] / [NO]); the `ORIG` 17th entry;
  "red / green cued LED"; arrows hiding after loads (CL29–CL31); LEFT/RIGHT wrap; the
  tempo-locked blink; anything named CLYPA…CLYPZ / CL1…CL24 unless a later section repeats it.
- When in doubt: the code (`tools/clyps/patch_clyps.s`, comments are plain enough) and the emulator
  gates (`tools/diag_clyps_ui.py`, its check messages read like behaviour statements) are the truth.

## 5. Sources
- `reference/handoffs/CLYPS_SCOPE.md` (see §4 above), `FLASHING.md` §4 (the Clyps walk-throughs),
  `NOTES.md` (search "Clyps", "CL3"), `tools/diag_clyps_ui.py` (behaviour as checks),
  `tools/clyps/patch_clyps.s` (key tables near the end: `cl_keys`, `cl_ckeys`, `cl_fkeys`).
- Memory topic `ot-clyps-scope` (author decisions, dated).

## 6. Questions to ask the author before drafting
1. Where it lives and its format (repo Markdown + images, a shareable web page, or both).
2. Whether to cover the standalone Clyps image or only "KYOTI with Clyps".
3. How much of the timing logic to explain (cued vs instant, first-sounding-trig) — a short "what you
   hear" paragraph, or a diagram too.
4. Whether to mention the known limits (FULL's few-ms overlap on a fading sound; SILENCE TRACKS pops are
   fixed in DIRECT JUMP).
5. Tone sample: show one section in draft and get a yes before writing the rest.

## 7. How to work
- Own worktree: `tools/worktree.sh new clyps-manual` (or continue in `trkseq` if the author prefers;
  register the manual's paths under `Thread: trkseq` in `tools/githooks/threads.txt`).
- Commit explicit paths; email = the Zac-Kyoti noreply (check `git config user.email`); end commit
  messages with the Co-Authored-By line from the session's attribution reminder. No push without asking.
- No firmware changes in this task. If you find behaviour that looks wrong while writing, list it for the
  author instead of fixing it.

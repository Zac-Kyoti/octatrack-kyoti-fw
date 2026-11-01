# CLYPS — scope and build record (WIP; latest test image `140C_CLYPY`)

## §0 Start here (handoff, 2026-10-25) — read this first, then §1–§4

**Where it stands.**
- **Worktree / branch:** `../octatrack-kyoti-fw-trkseq`, branch `trkseq`. Commits are local, not
  pushed. Clyps is WIP, nothing is promoted, and there is no README entry.
- **Latest image:** `140C_CLYPM` (see "2026-10-29" below); before it `140C_CLYPH` (`tools/build_clyps.py`), a standalone image: stock + Clyps only.
  **BUILT 2026-10-28, NOT flashed** (the user flashes it next round): CLYPG (step 0 below: stock
  [PTN] / [BANK] inside Clyps, the BANK box, [MIDI] follows, no MIDI load modes) + step 1, FULL
  loads (§1.7 "Built"). Walk-through: FLASHING §4 "CLYPH walk-through" (it includes CLYPG's).
  CLYPG itself was never flashed.
- **On the unit:** `140C_CLYPF`, syx `b3eacd36…`. FLASHED 2026-10-28: the user ran the CLYPF
  walk-through (FLASHING §4: layout, names across SAVE / RELOAD project and bank, power cycle,
  LOAD another project, EXPORT TO SET, DELETE PROJECT on a throwaway project): all passed.
- **How the user tests now (2026-10-26):** a few changes at a time, a short list per image, not
  the whole FLASHING checklist.
- **On the user's unit:** CLYP6 (FLASHING §4 steps 1–10 passed; MIDI tracks not seen, fixed in
  CLYP7). CLYP7 was never flashed: CLYP9 replaces it.
- **Pending on hardware (CLYP9):** FLASHING §4 CLYPS step 0 (boot with the 9.6 MB reserve), steps
  11–15 (cued landings), step 5 on the MIDI side, and the new F/G/H (saved sequences, originals,
  lifetime).
- **Built and gated:**
  - Clyps mode; the 2×8 view (v5 layout, user-approved); the grid; held/latched states;
  - stopped and cued loads (master wrap, CHAIN AFTER points, phase-continuous);
  - **the DRAM move** (step 1 below, done);
  - **saved sequences** (step 2, done): [FUNC]+[YES] / [FUNC]+[NO];
  - **originals** (step 3, done): capture on the first replacement, the `ORIG` cursor entry,
    [PAGE], [FUNC]+[PAGE], the NORMAL→PER TRACK undo, cleared on a project load;
  - [YES] with the chord held does nothing; [PTN]+[YES] in Clyps mode = DJ toggle hook (user,
    2026-10-25).
- **Gates:**
  - UI: `diag_clyps_ui.py --only ABCDYENP` on OT DEMO, plus `--only M` on JAM2.
  - Landing: real key presses, exact against the oracles (§3.4, §8b): C1w/C2c/C3s, plus C4v
    (saved, immediate), C5o / C6o (restore at a wrap / a CHAIN AFTER point), against C1 (no load).
- **Code:** `tools/clyps/patch_clyps.s`, one source, two sections:
  - `.text` (ROM, classic cave `0x400d6500`, ~2.1 KB, ~3.8 KB left): the tick path (`cl_land`,
    `cl_wrap`, `cl_landone`, `cl_apply`, `cl_srcrec`, `cl_oidx`, `cl_capture`, `cl_release`,
    `cl_convert`, `cl_newrate`, `cl_tps`, the drop/count helpers) and the cue state;
  - `.dram` (linked at the arena reserve `0x40a955e0`, ~5.5 KB): everything else;
  - buffers `CL_BSS_SIZE` = 9,591,200 B after `.dram` (4,096 originals, 16 saved, 256 pattern
    snapshots); their valid marks live inside `.dram`, so every boot's depack zeroes them;
  - reserve 1,563 pages (9.6 MB) of the 14,602-page sample arena.
  - Seven detours: `0x4005a044` [PTN], `0x4007af80` / `0x4007b3e0` [BANK] press / release,
    `0x400a1f72` phase D, `0x400a43a0` wrap body, `0x40062d1c` UI tail, `0x400905d4` the masked
    bank loader (project load).

**HANDOFF 2026-10-30 (start here; supersedes the older handoff notes below).**
- **Update 2026-10-31 (4): CLYPX FLASHED, all good.** `140C_CLYPY` (built, not flashed) = temp toasts `TRACK n
  TEMP SAVED` (one line) / `TRACK n` + `TEMP RELOADED`, MIDI two lines (the user). Next: DIRECT JUMP integration.
- **Update 2026-10-31 (3): `140C_CLYPX`** (built, not flashed). Hardware on CLYPW: whole tabs right, but a stray
  `!` beside the glyph wherever the shown tab and the real active track differ (the active track with [CUE]
  held; every member that is not the active track). Source: a THIRD drawer of `0x40052200`, `FUN_40044804`
  (KB): a per-track status mark coloured from its own active test `0x4004482a` -> `jsr cl_act4` (nine splice
  sites now). Reproduced and checked by rendering with `call:40052200` (the real per-pass function), not the
  painters alone -- do that for any sidebar change. Card reload toast: [BANK]+TRACK `TRACK n ALL` / `MIDI
  TRACK n ALL` + `RELOADED FROM PROJ` (the user).
- **Update 2026-10-31 (2): `140C_CLYPW`** (built, not flashed; replaces the unflashed CLYPV): the user dropped
  ALL from the save / reload toasts and wants one line wherever it fits. Measured with the TOAST font
  `0x400ba862` (widths `0x400c205c`, 1 px gap; digits 5 px, `1` 2 px; a line holds 113 px) -- NOT the header
  font `0x400ba876`, which reads ~30% narrower and would have said everything fits: `TRACK n SAVED` 75,
  `MIDI TRACK n SAVED` 96, `TRACK n RELOADED` 93 (one line each); `MIDI TRACK n RELOADED` 114 (two lines),
  `MIDI TRACK n: SAVE FIRST!` 125 (two, unchanged); card reloads `TRACK n SEQ` / `TRACK n` + `RELOADED FROM
  PROJ` 151+ (two), `PATTERN A06` + it (two).
- **Update 2026-10-31: CLYPT FLASHED** (track LEDs correct; tab only half right) -> **`140C_CLYPV`** (built,
  not flashed): the tab's lower half too (§1.9 "CLYPV"), and the UI word FULL -> **ALL** everywhere (the
  user: labels and toasts; "FULL load" in this document = an ALL load on the unit).
  Gates (CLYPV): full ABCDYETGRSNPK 128, F+Q 27, L 8, M+U on JAM2 26, U alone 17. **Run U in its own
  run, not with K:** ...U then K in one run faults in K (`_pop`: unmapped exception-frame read), while
  each passes alone -- the same emulator accumulation as S with tail posts (traps below).
- **Update (later 2026-10-30): §1.9 built as `140C_CLYPT`** (CLYPR + the [CUE] group; "CLYPS" skipped:
  it is the builder's default name). NOT flashed; CLYPR was not flashed either (the unit has CLYPQ), so
  CLYPT's walk-through (FLASHING §4) comes after CLYPR's. The sidebar RE item is solved (§1.9 "RE").
  New gate scenario U (run it with M on JAM2). Next: the user's CLYPR + CLYPT walk-throughs, the
  group label wording (§1.9 "Built", my proposal), then item 2 below.
- **State:** latest image `140C_CLYPR` (syx `25174496…`, commit `01c789c`, branch `trkseq`, all
  unpushed), NOT flashed yet; on the unit: `140C_CLYPQ`. Gates all green: `diag_clyps_ui.py --only
  ABCDYETGRSNPK` (OT DEMO, 128) + `--only FQ` (27) + `--only L` (8, card reloads) + `--only M` on JAM2
  (9). Run L / F / M / full in parallel with distinct `--name`s (each stages its own card tree), and
  absolute `--shots` paths (the script chdirs into refs/octabam).
- **What exists** (details in §1.0-§1.9 and the CLYPx walk-throughs in FLASHING §4): the view / grid /
  labels as the user finalised them (dark header boxes, `T6 BNK A`, `LOAD: TRK SEQ|FULL`, `MIDI TRK
  SEQ|FULL`, `ORIG ...`, `ORIG PTN+PART`), FULL loads (§1.7, MIDI too via [FUNC]), originals ([PAGE],
  ORIG, chord + [PAGE]/[YES] = ORIG PTN+PART), temp save / reload (FULL), names on the card (§10),
  stock [PTN]/[BANK] inside Clyps with [BANK] on release everywhere, mutes and the Parts menu inside
  Clyps (window prio 0), the load-confirmation flash (detour on the 1/60 s UI tick `0x40056c28`),
  card reloads (§1.8, `tools/clyps/clyps_reload.s`).
- **Next, in order (agreed with the user):**
  1. **DONE (`140C_CLYPT`): Multi-track loads with a [CUE] group, §1.9** (decisions recorded there). RE done: [CUE] = key
     `0x2a` (its held sub-map `0x400bf2a0`); track LEDs = LED slot 6 painter `0x40083eb0` (tick
     `0x40083fdc`, period 2), which picks "active" by `0x80000000`: replace with a group test in our own
     slot-6 record. **Open RE:** where the main screen draws the sidebar's active-track tab -- not via
     RECT `0x40012254` / TEXT `0x40012bd8` (an emulator trace of a track change showed no edge draws;
     probe script idea: hook every call during a TRACK change and filter x <= 8 / >= 120); probably the
     compositor `0x40013abc`'s own chrome or a bitmap blit.
  2. **DIRECT JUMP / KYOTI integration** (§0 step 3 below; Clyps replaces RELOAD_FROM_PROJECT in KYOTI).
  3. **The standalone RELOAD_FROM_PROJECT update** (§1.8: FULL track slice from the card, new toasts,
     the pattern reload; all build forms + octabam PR) -- after Clyps.
- **New traps (2026-10-29/30):** route A runs no UI tick: call `0x40056c28` from the gate to drive
  the flash; the gate posts a type-0 SYS message after keys only in K/M (`posttail`) and via
  `tailmsg()` before held-flag checks (posting everywhere made S fault); `diag_clyps_landing.py` stages
  one fixed tree (no parallel runs); a wait loop `pgrep -f <name>` matches itself (use `[n]ame`);
  `clyps_render.py` needs a leading `32` (the boot SET DATE dialog); card copies differ from RAM only
  in bytes the bank file never holds (`+0x899` per audio record, slab tail); a toast line holds 113 px
  (`0x400ba862`, box = text + 15, screen 128); header labels end at x 107, `LOAD: ` = 21 px, `T6 BNK A`
  ends at x 31; `0x40033970` is not a readable mute state; `WIN_NEW(prio p)` evicts every window with
  prio >= p; the user tests a few changes per image and wants measurements before wording / layout
  choices, renders only for layout changes and only if they ask.

**2026-10-29: CLYPH FLASHED; the user's changes → `140C_CLYPI`, then `140C_CLYPJ` (FLASHED), then
`140C_CLYPK` (built, not flashed): rounding and header outlines undone (dark inverted boxes again,
on BANK while [BANK] alone is held and on every right-hand label after `LOAD: `);
` + ` → `/` (`SEQ/MCH/FX`, `ORIG SEQ/MCH/FX`, `ORIG PTN/PART`); the select box LED and the "changed"
page LEDs use stock's p-locked-trig flash (`0x40013784(green die, 3)` each period 30, as stock's
trig tick `0x400340e4` does for a locked trig: red with a short yellow flash); unnamed slots read
`-NN TRGS-` (`-%02d TRGS-`, 34 px). CLYPK FLASHED (all points passed); `140C_CLYPL` (built, not
flashed): labels `TRK SEQ`, `TRK SEQ/MCH/FX` (left side `T6` only beside it: 54 px), `ORIG TRK SEQ`,
`ORIG TRK SEQ/MCH/FX` (73 px), MIDI `MIDI TRK` (boxed; MIDI ORIG stays `ORIG`). `140C_CLYPM`: the audio
temp reload ([NO]+TRACK) is FULL too (the user: a temp save keeps the sound; `SAVEPART` already
held the Part); source labels `%c%02d %02d TR` (`B14 06 TR`), `B04 LOCKS`, `B04 ---`; an empty
slot's `---` centred (places 4-6, `EMP_DX` 12); unnamed slots `A01 15 TR` (`%c%02d %02d TR`, the slot's own
bank / pattern); the load confirmation: the select box (or the ORIG header box) flashes inverted
for 45 UI ticks (0.75 s), phase every 4 ticks, from a new detour on stock's 1/60 s UI tick
`0x40056c28` (the toast countdown, task `0x40056c40`; ROM stub `cl_uitick` guarded by `cl_magic`);
arrows / paging / TRACK / close stop it. Route A runs no UI tick: gate B calls `0x40056c28`
directly. [FUNC]+TRACK = stock's mute in Clyps (the TRACK keys left out of `cl_fsub`; they had
shadowed stock's FUNC sub-map `0x40083dfc`); [FUNC]+[MIDI] = stock's Parts menu over Clyps: `0x35`
left out of `cl_fsub` too, and the Clyps window at **priority 0** (was 3): `WIN_NEW(prio p)`
`0x4005829c` evicts every window with prio >= p, and the Parts menu opens at 1 (`0x4002e730`), so
at 3 it closed Clyps. Every stock window now opens over Clyps (gate Q). Earlier CLYPI/J
notes below.**
- **Rounded boxes:** the highlight bar and the select box lose one pixel at each corner.
- **Header outlines** (1 px, dark on the lit band, rounded): round `BANK A` while [BANK] alone is held
  (no longer when the chord is held, so entering Clyps shows none); round the right label, after
  an unboxed `LOAD: `: `SEQ` / `SEQ/MCH/FX` ([FUNC]); box on ORIG: `ORIG SEQ` / `ORIG SEQ/MCH/FX`
  ([FUNC]) / `ORIG` (MIDI); the [PTN]+[BANK] chord held: `ORIG PTN/PART`. Beside the two long
  ones the left reads only `T6` (the user's choice). MIDI: no label except on ORIG.
- **[BANK] outside Clyps acts on release** (RELOAD_FROM_PROJECT's inversion, `cl_bankp` →
  `cl_bkdefer` / `cl_bankr` → `cl_bkrel`): the press pushes only the trig overlay; a plain tap's
  release opens SELECT BANK; a chord begun with [BANK] flashes nothing.
- **Grid LEDs:** red = your pattern, **solid** yellow = cued, **flashing red** = the select box
  (`cl_blink`); priority red > yellow > box.
- **[PAGE] (SCALE)** = ORIG SEQ of the active track; **[FUNC]+[PAGE]** = ORIG SEQ/MCH/FX (MIDI always
  both). **Chord + [PAGE]** = **ORIG PTN/PART** (`cl_restorepat`): all 16 tracks' original
  sequences + slices, plus the Part bytes in no slice (`cl_slR`: `+0x10` 2 B, per-scene bytes 8–9,
  the 144 B tail) at the first landing, the pattern's length / scale / mode with the last track:
  the pattern and its whole Part as loaded. Chord begun outside Clyps (it opened Clyps) → Clyps
  closes after; begun inside → stays (the user). The Part source is the load snapshot, not stock's
  saved Part (the user's choice): it equals stock RELOAD PART only if the Part had no unsaved edits
  at load and was not saved since. Not restored: the pattern's Part assignment if it was changed.
- **Page LEDs** (slot 7, `cl_ppaint`): stock's step indicator, except while the box is on ORIG or the
  chord is held: then all four LEDs (dies `0x48..0x4f`) show the same: red = original, yellow =
  restore cued, flashing red = changed (track; with the chord: the whole pattern incl. the Part).
  (CLYPI used only the 4th; the user wants all four alike: CLYPJ.)
- **Wording:** `SEQ/MCH/FX`, `ORIG PTN/PART` (the user).
- **"SAVED" (the user, 2026-10-29):** the slot label after a temp reload reads `SAVED SEQ`; no SAVED in
  the header any more (CLYPJ).

**Handoff 2026-10-28 (start here).** Read §1.0 (the 2026-10-27 model), §10.0/§10.2 (names), the
traps below (incl. the harness lesson in §10.2), then continue with step 0 below. The user tests a
few changes per image with a short walk-through (FLASHING §4 "CLYPx walk-through"), not the full
list; give renders in the browser for any layout change (tools/clyps_render.py + clyps_view_html.py).
Gate: `CLYPS_SYMS=… python3 tools/diag_clyps_ui.py --image … --only ABCDYETGRSNPK` on OT DEMO
+ `--only M` on JAM2; landing runs C1w/C6o (§8b) for tick-path changes. Since CLYPG, scenarios K
and M (and clyps_render.py) post a type-0 SYS message after every key: on hardware each key is a
message of that loop and Clyps' UI tail runs after it; the loop's range check sends type 0 straight
to the tail. Without it, what Clyps does from the tail (the BANK box, closing on a pattern pick,
following the [MIDI] key) only happened when stock posted a message of its own. Only K and M:
with the posts in every scenario, S faulted at its first key (`rte … not a 4-word frame` /
unmapped frame read) once enough had run before it (A..E+G+T; every shorter prefix passed, and
the full run passes without them): an emulator accumulation effect, like the card-poster lesson
(§10.2). `CLYPS_NOTAIL=1` turns them off in K and M too.

**Next, in this order** (decisions are all in §1.0–§1.7 and §2):
0. **DONE (CLYPG, not flashed): §1.0 step 2, stock [PTN] / [BANK] inside Clyps**, and the BANK box.
   How it works: §1.0 "Step 2 as built". Next after the user's CLYPG walk-through: step 1.
1. **DONE (CLYPH, not flashed): FULL loads** (§1.7 "Built"). The rest of this item is the plan as
   it stood; the built route differs (single-track applies, no Part hand-off).
   - [FUNC] held = `LOAD: SEQ/MCH/FX`, and a trig picked then is a FULL load (our FUNC sub-map
     `cl_fsub` does not list the trigs, so trig records stay ours).
   - The Part slice is stock TRACK PASTE's 136 B (audio) / 68 B (MIDI), plus scene locks
     (`+0x662+(s·8+t)·0x20`, `+0x1662+10s+t`) and the LFO designer (`+0x1702+16t`, `+0x1782+2t`).
   - Apply at the landing with the single-track apply `0x40001f18(bank, part, t)`; set
     `0x8000184c` bit t if the machine changed.
   - Part-slice originals are keyed per (bank, part, track): add them to the bss (~393 KB) and
     to `cl_release`'s restore.
2. **Page LEDs** (O16): dies `0x48..0x4f`, slot 7, painter `0x4004d1a8`. Red = playing its
   original, green = changed, yellow = restore cued; with [FUNC] held, the same for the whole
   pattern.
3. **KYOTI integration:**
   - DIRECT JUMP-timed landings: the next master step, clock-locked; reuse `dj_T`/`dj_bparams`.
   - [PTN]+[YES] in Clyps mode: link DJ's toggle (`--defsym DJ_TOGGLE=…`); the chord held: nothing.
   - Share the [BANK] sites with RELOAD's deferral (`rl3_bank_show` / `rl3_bank_rel`).
   - The TRACK keys' `TRK_BASE` must go to a stub, not RELOAD's detour at `0x40040250`.
   - DRAM: Clyps must be the LAST DRAM unit (its bss follows its `.dram`), or `dram.build` needs
     per-unit bss.
4. **Later:** an octabam module; names follow stock copy / paste (§10.3); the TRACK_PASTE_DESIGNER_FIX Bugfix candidate
   (NOTES Session 131 cont. (3); the user still has to observe it on stock).
5. **Decided (the user, 2026-10-25):** after a load onto the playing pattern, its own slot shows
   the loaded copy (the keep rule, as built). Picking that slot is a no-op; `ORIG` / [PAGE] is the
   way back to what it held before.

**Traps already paid for.** Read them before writing code.
- **Key records must copy T1's hold delay/repeat for every key they override** (T1 `0x400bfc10`).
  A key pressed under one layer and released under another, with a differing delay, leaves its
  timer record in the repeat list `0x460d1660`. The next press links it to itself, and the UI
  task hangs.
- **A key's sub-maps CHAIN across layers; they are not overridden.** The rebuild `0x4003125c`
  appends each layer's sub-map for a key after the lower ones, and the press links the chain at the
  end of the layer list. Stock's FUNC sub-map `0x400bfa1e` therefore always links above our layer
  while [FUNC] is held; [FUNC]+[YES] reached stock's `0x4005e3d8` (CLYP9 first cut). Fix: our own
  sub-map `cl_fsub` on our [FUNC] record: it links after stock's and wins.
- **TRACK double tap.** Stock's TRACK press reads a second press of the same key as a double tap
  while its timer `0x460d5de0` ≤ 14 (event 3). Route A never advances that timer: the gate ages it
  before each TRACK press. On hardware a real double tap opens stock's window and evicts Clyps.
- **The project load is the masked bank loader `0x400905d4(ctx, mask, …)`** (bit n = bank n), not
  `0x40090504` (it never ran in a LOAD PROJECT). Measured masks: `0xffff` on a first load,
  `0xfffe` on a reload of the same project.
- **TRACK keys select on RELEASE.** Forward press, hold and release to the base handler.
  Forward [FUNC]'s press/release to stock (`0x4004e954` / `0x400568e4`).
- **A key's held flag is set only AFTER its press handler**; track [FUNC] by its own events.
- **`0x80000012` (MIDI tracks showing) is a LONG.** `0x80000000` is the active track of the
  current side (stock swaps `0x80000000`/`0x80000001` on the toggle).
- **Landing tick.** In phase D the master counters are already advanced by the previous tick's
  phase G. A landing happens on `TICK_CTR == 0`, with
  t0 = (MASTER_STEP − 1)·tps_M + TICK_CTR, STEP = (t0/tps + 1) mod len, STEP−1 = (STEP+len−1)
  mod len, TICKS = t0 mod tps. Land only on a window start of both the old and the new rate. A
  master wrap uses the wrap-body hook (copy only; stock re-homes).
- **Tick hooks sit mid-function:** save **all** registers (d0–d7/a0–a6) and replay the displaced
  instruction last (stock branches on its flags).
- **ColdFire (as `-mcpu=5407`) lacks** cmpi to memory, `not.b`, `exg`, `cmpa.w`, movem with
  `-(sp)` / `(sp)+`, and d16 offsets beyond 32767 (use a trailer register: slab + `0x8e50`).
  Watch for `.b` branches out of range, and **duplicate `.equ`s: the last one wins silently**
  (cost one hardware round).
- **The UI is drawn into our own window** (`0x4005829c(w,h,dx,dy,prio,cb)`, prio 0 since CLYPM (stock windows open over it; was 3), close_cb =
  the one idempotent teardown). Never draw from tick context. Follow-ups go through the UI-tail
  hook.
- **Font:** `0x400ba876` (3×5 glyphs, 4 px advance). Measure widths from its table at
  `0x400c246a` (+1 px spacing).
- **Window geometry:** 112×64, `dx = −1` (screen columns 8–119). Header band 9 rows; rows at a
  6 px pitch from `ROW0_Y` 46; columns at x 4 / 59, highlights 2–54 and 57–109.
- **Renders:** the user wants every render **opened in the web browser** (`tools/clyps_view_html.py`).
  The emulator does not compose the screen by itself: `tools/clyps_render.py` calls the
  compositor `0x40013abc`, reading its double-buffered target `[0x400b9710]` **before** the call.
  The emulator boots with a SET DATE/TIME window up; send [NO] (`32`) first.
- **Emulator fixtures:** never ask the user for a project. Use the real exports in
  `~/Desktop/OT Backup/KYOTI/` (OT DEMO: varied lengths, no MIDI trigs; JAM2: MIDI trigs, loads
  with the MIDI tracks showing). Build cases in RAM with stock-style copies
  (`--copypat`/`--copytrk`/`--setb`).
- **Builds:** `KYOTI_ALLOW_WIP=1 python3 tools/build_clyps.py 140C_CLYPn`. Then run the UI gate
  (OT DEMO, plus `--only M` on JAM2) and, for any landing change, the landing runs C1w/C2c/C3s
  (§8b). Before handing over a build, give its sha256 and say it is not yet flashed.
- **Terms:** Clyps mode / view / grid; CHAIN AFTER (never "CHANGE").

**Tools.**
- `tools/build_clyps.py`: the builder.
- `tools/diag_clyps_ui.py`: the UI gate; `--only ABCDM`.
- `tools/diag_clyps_landing.py` (`--keys-at` for real-code runs, `--clyp` for harness copies)
  and `tools/cmp_clyps.py`: the landing oracle.
- `tools/clyps_render.py` and `tools/clyps_view_html.py`: renders.
- Reference outputs in `out/clyps/`: B1, R5, R7 (references), C1w/C2c/C3s (real-code runs).

---


Rev 1 (2026-10-22, as `TRACK_SEQ_SELECT_SCOPE.md`) was the first pass. Rev 2 adds:
- the user's name and terms;
- the 16-at-once table;
- the cue colour change;
- the non-destructive model;
- the 16 saved sequences.

## Terms (the user's, 2026-10-23 — use them everywhere)

> **Octatrack term (2026-10-24):** the pattern-change quantisation setting is **CHAIN AFTER**.
> The firmware names it so (`0x400b5f37`, under PATTERN CHANGE in the project's sequencer
> settings, next to SILENCE TRACKS and LFO AUTO CHANGE). The project value is at `0x8000004e`;
> each pattern also stores its own at slab `+0x8e56` (< 0 = use the project's), indexing the step
> table `0x400d80dc`. Earlier revisions of this doc called it "CHANGE" (other RE projects' label).
> That is not an Octatrack term, so do not use it.

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

### 1.0 The 2026-10-27 model (the user) — supersedes §1.1 / §1.3 where they differ

**What the user must always see:** (a) the pattern they are on, (b) the sequence they are about to
load into that pattern's track.
- **Slots = patterns.** Bank A slot 1 = pattern A1.
- **Highlight** (inverted bar) = the pattern you are on. It moves only when the pattern changes, and
  is shown only while viewing that pattern's bank.
- **Select box** (1 px frame) = what a load takes. The arrows move it; shown only in its own bank.
  A move made in another bank brings the box into it (same slot number). `ORIG` stays the cursor
  entry after slot 16 (header box).
- **A trig** moves the box to that slot and loads it (cued while running). **[YES]** loads the box.
- **After a load** your pattern's slot reads its source, `A14 6 TRG` / `A14 LOCKS` / `A14 ---` /
  `SAVED`, until the track is edited or restored; then the plain summary. Names (§10) replace this.
- **Grid LEDs:** red = your pattern (**red wins**); flashing yellow = the cued sequence (solid once
  it plays); solid yellow = the select box; green full / half = data; off = empty.
- **Only [NO] closes Clyps**, or (step 2) a real pattern / bank + pattern selection. No held /
  latched states; releasing the chord does nothing.
- **[BANK] held + arrows** page the shown bank (L/R and U/D, ±1, wrapping); the slot selector rests.
- **Step 2 — stock [PTN] / [BANK] inside Clyps** (the user's answers, 2026-10-27):
  - [PTN] and [BANK] behave as in stock; a pattern selection made that way is a real pattern
    change (all tracks), or bank + pattern; it closes Clyps;
  - selecting a bank on the trig grid ([BANK] + trig) does NOT leave Clyps, and never changes the
    bank by itself: as in stock, a real bank change needs a pattern selection with it;
  - SELECT BANK on [BANK]'s release, not its press (RELOAD_FROM_PROJECT's inversion; the user
    remembered it as DIRECT JUMP's).
- **Removed:** the held / latched states, close-on-load, the [BANK]-alone Clyps bank pick (CLYPA).
- **[BANK] held = the BANK box** (the user, 2026-10-28; built CLYPG): while [BANK] is held (the
  arrows page the shown bank), the header's `BANK A` gets a dark box with lit letters, the way
  `ORIG` looks when the box is on it (x 12..37, 2 dark columns each side of the text). It follows
  [BANK]'s real held flag, redrawn from the UI tail (the flag changes after the key's handler).
- **[MIDI] inside Clyps** (the user's report, 2026-10-28; fixed CLYPG): the [MIDI] key is not ours,
  so switching sides left the view and grid on the old side. The UI tail now compares the active
  track (0..15, MIDI 8..15) with the one `cl_refresh` last drew (`cl_lastt`) and refreshes.

**Step 2 as built (CLYPG, RE 2026-10-28, C on our image).** Stock's two keys:
- [BANK] press (`0x4007af80` → tail `0x4007af30`): state `0x460e73c6` := 0, tap-eligible
  `0x460e73c2` := !latched, latched `0x460e73bc` := 0, SHOW_WIN(`SELECT BANK`, 0xf0, 0, teardown
  `0x4007b408`), push keymap layer `0x400cff14` (trigs → `0x4007b2fc` / `0x4007b434`, [NO] →
  `0x4007b25c`, [YES] swallowed) and LED layer `0x400cff28`. Hold `0x4007af24`: tap-eligible := 1.
- [BANK]-layer trig, state 0: bank n picked (`BANK UNAVAILABLE` toast if `[0x4017d516 + n·0x9b340]`
  ≠ 0), `0x460e73b8` := n, state 1, SHOW_WIN(`BANK %c: SELECT PTN`). State 1: the pattern pick
  `0x400a1030(bank, pattern)` (or the chain add `0x4009c634` while another trig is held), state 2.
- [BANK] release `0x4007b3e0`: state 2 or not tap-eligible → DISMISS; else latched := 1 and
  `0x40031200` (`0x460d1e4c` = 1: SHOW_WIN without countdown).
- [PTN] (`0x4005a044`, all three events): press = DISMISS, state `0x460d1742` 1, consumed
  `0x460d173e` 0, push `0x400bf0f2` (trigs → pick `0x40056b2c`, which sets consumed −1) + LED
  `0x400bebfe`. Release: consumed or not eligible → teardown `0x40043418`; else state 2 +
  SHOW_WIN(`SELECT PATTERN`, 0xf0, sticky, `0x40043418`).
- SHOW_WIN = `0x40059f8c(title, ticks, sticky, onClose)`: a priority-10 window (WIN_NEW), over the
  prio-3 Clyps view, which stays (measured).

Clyps (`cl_k_chord`; keys pressed under our layer return to our record for hold and release, also
after Clyps closed):
- [PTN] pressed in Clyps → stock's handler for every event. [PTN] with [BANK] held → swallowed.
- [BANK] pressed in Clyps → stock's press minus SHOW_WIN (DISMISS any SELECT window first, as
  SHOW_WIN would); release: something picked → stock's release; the arrows paged → teardown only;
  a plain tap → SHOW_WIN(`SELECT BANK`) + latched; the tap on a latched window → it closed at the
  press, teardown. [BANK] with [PTN] held → swallowed (consumed := 1).
- Closing on a pick (UI tail): consumed = −1 (only stock's pick writes it; Clyps' entry writes 1),
  or state 2 after a [BANK] pressed in Clyps (Clyps' entry writes 2 itself, so it is armed per
  gesture).
- Gate K (emulator, 21 checks): box on / off, SELECT BANK on a tap's release and [NO], paging
  without a window, held and latched bank + pattern picks (close, layer lists at baseline, the
  pattern changed), [PTN] tap + [NO], [PTN] + trig, the chord again.
- **KYOTI note:** with a [PTN] pressed in Clyps, stock's [PTN] layer owns [YES] (a null record), so
  `cl_k_yes`'s [PTN]+[YES] → DJ_TOGGLE only sees a [PTN] pressed before Clyps opened. DJ's own
  [PTN]+[YES] route decides it there; check it at KYOTI integration.


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
| [YES] | nothing (DIRECT JUMP must not toggle while the chord is held) | load the cursor entry (a slot or `ORIG`), then close |
| [PTN]+[YES] ([PTN] held, [BANK] not) | — | DIRECT JUMP on/off; Clyps stays; never a load |
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
| LEFT / RIGHT `0x34`/`0x21` | the same row of the other column (1↔9 … 8↔16); nothing on `ORIG` (the user, 2026-10-26: no bank change on the arrows) |
| TRIG 1–16, [PAGE], [YES], [NO] | §1.1 |
| [FUNC]+[YES] | **save** the active track's sequence; Clyps stays; the header shows `SAVED` |
| [FUNC]+[NO] | **reload** the saved sequence **immediately** (O3); nothing if none is saved; then as §1.1 |
| TRACK 1–8 | change the active track; view and grid follow; bank kept |
| [PTN] / [BANK] | their held state is the chord; no stock action |
| [BANK] alone (held) + trig | **bank picking** (the user, 2026-10-26), as in stock: the trigs show the banks (shown bank red, banks with data green, empty off); a trig picks the shown bank, the view follows and the Clyps grid comes back, Clyps mode stays; further trigs wait for [BANK]'s release |
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

### 1.5′ Originals, redefined (the user, 2026-10-26) — supersedes the capture model below

- **A track's original is the state it had when its bank was loaded**: at power-on, at LOAD
  PROJECT, at a project reload. It is always available, not only after a Clyps switch.
- **Any change makes a track not original**: a trig edit on the grid, a Clyps load, a saved
  sequence put back. `ORIG` (cursor entry, latched [YES]) / [PAGE] bring it back; [FUNC]+[PAGE]
  brings back every changed track of the playing pattern.
- The original includes the track's machines/FX (its Part slice). Restoring those arrives with
  FULL loads (§1.7); the snapshot already holds the Parts.
- **Saved sequences** (§1.6) are for the in-between states: neither the original nor another slot
  (edit the grid, like it, [FUNC]+[YES]; [FUNC]+[NO] puts it back on that track at any time).
- **Mechanism (CLYPA):** Clyps snapshots every bank (16 slabs + its Parts, `0x9b340` B each, 9.7 MB)
  right after it is written by a load: at the return of the masked bank loader `0x400905d4`, and
  after stock's power-on SRAM restore `0x4000fbb4` (call site `0x40025808`). A track is original
  when its record equals the snapshot. When a restore makes every track of a pattern original
  again (length/scale bytes aside), the pattern's length/scale/mode and every track's length/scale
  come back too, so a NORMAL→PER TRACK conversion is undone.

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

**`ORIG` on screen (decided 2026-10-25, option a).**
- **The cursor cycle.** It is 1 → 16 → `ORIG` → 1. `ORIG` is present only when the active track
  has an original on the playing pattern.
- **On screen.** On `ORIG` no slot is highlighted, and the header's right side shows `ORIG` as a
  dark box with lit letters, in place of `LOAD: SEQ`.
- **Restoring.** Latched: [YES] restores and closes. Held: [PAGE]. It is cued like any load.
- **What comes back.** A restore always puts the track back to its pre-Clyps state: the sequence,
  plus machine/FX/scene locks/designer if a FULL load had changed them. There is no SEQ / FULL
  choice, because [FUNC] near `ORIG` is already save ([FUNC]+[YES]) and restore-all ([FUNC]+[PAGE]).

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
  At a master wrap that is step 1. At a CHAIN AFTER point it is phase-continuous (O9): the track lands
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

**Built (CLYPH, 2026-10-28; emulator-gated, not flashed).**
- **Choosing:** audio: [FUNC] + trig and [FUNC]+[YES] (the box: a slot, or `ORIG` = `ORIG
  SEQ/MCH/FX`) are FULL; a plain trig / [YES] is the sequence only. MIDI: every load is FULL (slot,
  `ORIG`, [PAGE], [FUNC]+[PAGE], the temp reload). [PAGE] / [FUNC]+[PAGE] on audio: sequence only.
  Stock's FUNC sub-map does not list the trigs, so [FUNC] + trig reaches `cl_k_trig` (C).
- **The slice** (`cl_slA` / `cl_slM`, table-driven `cl_slice`): audio = FX1/FX2, levels, machine,
  machine pages 1/2, AMP/LFO/FX page 1, page 2 block, slot record, recorder setup, 16 scene-lock
  rows, 16 per-scene bytes, LFO designer + slope (682 B); MIDI = page values 32 B, setup 36 B,
  designer + slope. Part tail `+0x1822` (16 B) is Part-level (a newer bank-file field read only by
  the file reader/writer `0x4008cc7e` / `0x4008a67e`), not copied.
- **Sources** (`cl_fullone`): a slot = its pattern's Part (`slab + 0x8e57`); `ORIG` = the playing
  pattern's Part as loaded (the snapshot, its own Part byte); a saved sequence = the whole Part
  saved with it (`SAVEPART`, 16 × 0x18b2 B, written by `cl_savet`).
- **At the landing** (tick, or at once when stopped), in `cl_apply` after the record: the slice
  into the playing pattern's Part, then that track only is published: audio `0x40001f18(bank,
  part, t)` (stock's own, engine state + memcpy), with the restart bit `0x8000184c` set first when
  the machine changed (as stock's machine edit, `0x400973b4`); MIDI `cl_mapply` = stock's
  whole-Part apply's per-track MIDI body (`0x400094b0..0x400095e0`: engine record `0x46c76dc0 +
  68m` ← pages + setup, designers `0x46c7738c` / slopes `0x46c7750c` for LFOs on a designer wave,
  `0x8000666e[m]` / `[8+m]` = bank / part, `0x8000664e[m]` := 0). No kernel call, no Part hand-off.
- **The UI tail owes** (`cl_postpart`, as stock's TRACK PASTE `0x4002b554..0x4002b59a`): the Part
  in the SRAM mirror (UI bank), Part-edited bit (bank `+0x95048`, SRAM `0x100b145e`, `bset`), bank
  changed (`+0x9b332`), `0x100f8598`; a new audio machine → stock's PICKUP setup `0x40097290`
  (UI-context, reads the UI bank); then stock's Part-reload page redraw (`0x4005e0a8`'s calls).
- **Gates:** F (OT DEMO, 14 checks: plain trig keeps the slice; [FUNC]+trig = sequence + slice, no
  other track touched, Part marked edited, Clyps stays; `ORIG SEQ` sequence only; `ORIG
  SEQ/MCH/FX` both back; playing with CHAIN AFTER = 1 step: the cue lands from the tick with its
  slice, no other track touched), M (JAM2: a plain MIDI trig brings M2's slice), full 109 + K.
  Landings: C1wH (plain) and C1wF (FULL, A14 T6 → A15 at the wrap) = B1 at all 450 ticks; C1wP
  (FULL, A14 set to Part 2 first) = B1 too: the sequencer state is undisturbed. A running UI-gate
  case needs `internal_clock()` + `frame = True` + `exact_clock()` before the transport starts
  (as diag_clyps_landing.py does), or the master step never moves.
- **Not done:** the "edited" x / `cl_diff` still compare the sequence only (a FULL load from a slot
  with an identical sequence shows no x); stock's paste/undo of names (§10.3).

**ORIG SEQ / ORIG SEQ/MCH/FX (the user, 2026-10-28; built CLYPH).**
- With the select box on `ORIG`, its header box reads **`ORIG SEQ`** (was `ORIG`).
- With [FUNC] held while the box is on `ORIG`, it reads **`ORIG SEQ/MCH/FX`**.
- `ORIG SEQ` loads the original sequence only (what `ORIG` / [PAGE] do now). `ORIG SEQ/MCH/FX`
  loads the original sequence plus the track's original machine and effects: the Part slice
  below, taken from the load snapshot (§1.5′: it already holds every bank's Parts), the same FULL
  load as from a slot. So [FUNC] on `ORIG` works like [FUNC] on any other slot.
- Widths (font table `0x400c246a`): `ORIG SEQ` 30 px, `ORIG SEQ/MCH/FX` 58 px; right-aligned to
  `BOX_R` (text ends at x 107) the long one starts at x 50, clear of `T6 BANK A` (ends x 35).
- [PAGE] / [FUNC]+[PAGE] keep their meaning (this track / every changed track, sequence only)
  unless the user decides otherwise when FULL loads are built.

**Superseded 2026-10-30 (the user): the MIDI side gets SEQ / FULL like the audio side** -- a user may
want to keep the destination's channel / program and change only the sequence. Plain load = SEQ,
[FUNC] = FULL; header `LOAD: MIDI TRK SEQ` / `LOAD: MIDI TRK FULL`; on ORIG `LOAD: ORIG MIDI SEQ` /
`LOAD: ORIG MIDI FULL` (`ORIG MIDI TRK SEQ` does not fit beside `BNK A`). [PAGE] / [FUNC]+[PAGE] the same
rule. The temp reload and ORIG PTN+PART stay FULL. Built `140C_CLYPQ`. The paragraph below is history.

**The MIDI side has no load modes (the user, 2026-10-28).** MIDI tracks have no machines or FX, and
a MIDI sequence depends on its track's settings, so every MIDI load takes everything.
- Header: no `LOAD: SEQ` label on the MIDI side, and [FUNC] changes nothing there (no
  `LOAD: SEQ/MCH/FX`). **Built in CLYPG.** The `ORIG` and `SAVED` boxes stay.
- Loads: a MIDI load (slot, `ORIG`, saved sequence) = the track record + the MIDI Part slice,
  68 B (`+0x3e2+32m` page values, `+0x4e2+36m` channel / bank / program / …), always. **Not built
  yet:** today a MIDI load copies the track record only. It arrives with step 1 (FULL loads), as the
  MIDI side's only kind of load. Check then whether MIDI tracks have scene locks / arp settings
  outside those 68 B that should travel too.
- `ORIG` on the MIDI side: stays `ORIG` (no `SEQ`, there is no choice); built so, to confirm.
- **Built in CLYPH** (see "Built" above): every MIDI load carries the slice.

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

**Measured 2026-10-25 (static, our image) — where the slice must be applied.**
- **Part base** = bank base + `0x8ed80` + part·`0x18b2` (right after the 16 pattern slabs; bank base
  `0x400e21e0` + bank·`0x9b340`, so every bank's 4 Parts are resident). Every offset in the table
  above is relative to it: stock TRACK COPY `0x40029754` reads FX1 `+0x00+t`, FX2 `+0x08+t`, machine
  `+0x22+t`, levels `+0x12+2t`, then the six blocks (C). A pattern's Part = slab `+0x8e57`.
- **How stock and our features apply a Part (corrected 2026-10-26).** When a pattern change lands,
  stock's wrap body posts `{0x15, bank}` and `{0x14, part}` (`0x400d8167` / `0x400d8169`) to the
  **sequencer→UI** queue `0x460d17ae` (not an engine queue), and hands the audio engine "apply
  Part X at time T" through its own variables (`ENG_APART` `0x46c7ff62`, flags, time; the engine's
  light Part apply `0x40009e00` from `0x4000b1dc` then runs on time). Stock does this on every real
  switch, even into a pattern on the same Part.
  - **DIRECT_JUMP_KYOTI** replays that hand-off at its landing (`dj_handoff`,
    `patch_directjump_v7.s`): the whole Part of the incoming pattern. HW-confirmed in V7.0.1.
  - **RELOAD_FROM_PROJECT** calls stock's PART RELOAD (`TRK SEQ + PART`) or `0x40009094(bank,
    part)` (`PART + PTN SEQ`) from the key handler, at once: the whole current Part.
- **Clyps differs:** a FULL load changes ONE track's slice of the playing pattern's Part (the other
  seven tracks keep theirs), copied from another pattern's Part, at a cued landing that does not
  restart the other tracks.
- **`0x40001f18(bank, part, t)`**, the single-track apply, touches only engine state
  (`0x80000110…`, `0x80000c50…`, `0x80000ec4/ecc`, `0x80001828…`, `0x800010d5`) and memcpy, no kernel
  call. Callers `0x40043d1a`, `0x40094096`, `0x40094158`, `0x40096c3e`, `0x40096d9a`, `0x400973da`,
  all with (`0x100b14ce`, `0x100b14cf`, t); `0x400973da` sets `0x8000184c` bit t first. Their task
  is not mapped.
- **Plan (recommendation):** reuse DIRECT JUMP's route. At the landing tick, copy the slice into
  the playing Part (a RAM copy, like the sequence), then run the same engine hand-off for the
  playing Part, so the engine applies it on time. **To check first:** whether the light Part apply
  `0x40009e00` disturbs the other seven tracks mid-pattern (slides, LFO phase), which a pattern
  change hides because it restarts every track. Only if it does: the single-track `0x40001f18`
  (from the tick, or deferred to the UI tail).

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

### 1.8 Reloads from the card inside Clyps (the user, 2026-10-30; scoped, not built)

**Pattern reload.** With the [PTN]+[BANK] chord held (begun outside Clyps: it opens Clyps), a trig N
reloads pattern N **of the playing bank** from the card: its whole sequence data (the slab, all
16 tracks + its settings) and its Part's saved state. Toast **`PTN A05 RELOADED`** (bank + 2-digit
pattern). Chord begun outside → Clyps closes after; begun inside → stays. The transport keeps
running (RELOAD_FROM_PROJECT's way).

**Track reloads (RELOAD_FROM_PROJECT) move into Clyps.** Same chords, only inside Clyps: [PTN] held +
TRACK n = that track's sequence from the card; [BANK] held + TRACK n = the same plus its Part's saved
state. Same toasts. In KYOTI, Clyps then **replaces** the RELOAD_FROM_PROJECT module (its chords
outside Clyps go away); the standalone RELOAD_FROM_PROJECT build stays as it is.

**Plan.** Fork `octabam-modules/reload-from-project/patch_reload3.s` into `tools/clyps/` (Clyps'
thread; KYOTI drops the module, so no two copies run together): keep its card job (the
type-0x14 worker detour `0x40085864`, `rl_done` `0x40023c62`, the `.strd` reader, BUSY guards,
toasts, the S119/S120/S98 lessons), drop its four outside-Clyps chord detours (`0x40083dc4`,
`0x40040250`, `0x4007af42`, `0x4007b3e0` -- the last is Clyps' own), call it from Clyps' handlers,
and add a pattern kind: `PART_RELOAD(the pattern's Part)` first (as RELOAD's [BANK] chord does), then
the job: kind 2 (slab incl. its Part link + Part apply) for the playing pattern, kind 1 (slab, link
kept) for another pattern; message `PTN A05 RELOADED` on success. Its `PTN_CONSUMED = -1` must not
look like a pattern pick to Clyps' UI tail (which closes Clyps on -1).

**Revised by the user, 2026-10-30 (supersedes the track-reload part above).**
- [BANK]+TRACK must **not** reload the whole Part (that touches unrelated tracks): it is Clyps' own
  FULL track load (sequence + that track's Part slice: machine, FX, pages, scene locks, designer),
  with the data **from the card**. [PTN]+TRACK stays sequence-only from the card.
- **Exclusive modifiers (the user, 2026-10-30):** a card reload on TRACK n only with [PTN] alone held
  (sequence) or [BANK] alone held (FULL) -- never with both: with the [PTN]+[BANK] chord held, a
  TRACK key reloads nothing (it changes the track, as today). Gate it on the live held flags of both.
- Toasts: sequence only **`TRK X CF SEQ RELOAD`**; sequence + machine/FX **`TRK X CF FULL RELOAD`**;
  the pattern reload **`PTN A05 CF RELOAD`**. (MIDI tracks: proposed `MIDI TRK X CF ...`, as the temp
  save toasts do; to confirm.)
- **The card's Part (RE 2026-10-30, C):** stock's bank reader `0x4008e0c0..0x4008e2c0` reads 16 PTRN
  chunks (`0x4008cebc(fh, slab, ver)`) into the slabs, then 4 PART chunks (`0x4008be2c(fh, dst, i,
  ver)`) into the **working** Parts (bank `+0x8ed80`), then 4 more into the **SAVE PART** copies
  (`+0x9504a`), then the 4 "Part saved" flags (`+0x9b312`), the version-3 extra word and the
  Part-edited byte (`+0x95048`). So the `.strd` holds both, and they differ whenever a Part was edited
  after its SAVE PART. "From the card" = the **working** Part chunk of the `.strd` (what a project
  reload restores). The job parses on past the 16 patterns to that Part chunk into a scratch Part
  buffer (bss, `0x18b2` B): a track FULL reload copies that track's slice from it (Clyps' FULL
  machinery: `cl_slice` + `TRK_APPLY` / `cl_mapply`); the pattern reload copies the whole Part.
- **Toasts (the user, 2026-10-30; built CLYPQ), two lines:** `TRACK n SEQ` / `RELOADED FROM PROJ`,
  `TRACK n FULL` / ..., `MIDI TRACK n SEQ|FULL` / ..., `PATTERN A06` / `RELOADED FROM PROJ`
  ("RELOADED FROM PROJECT" is 123 px, a toast line holds 113). Temp save / reload (they ARE full:
  the save keeps the record + the whole Part, the reload applies the record + the track's slice):
  `TRACK n FULL SAVED` (one line), `MIDI TRACK n FULL` / `SAVED`, `TRACK n FULL` / `RELOADED` (122 px
  in one line), `MIDI TRACK n FULL` / `RELOADED`.
- **For the standalone RELOAD_FROM_PROJECT (after Clyps):** the [BANK]+TRACK FULL-from-the-card
  behaviour (track slice, not the whole Part), the toasts above, AND the pattern reload from the card
  (`PATTERN A06` / `RELOADED FROM PROJ`) -- its gesture outside Clyps is to be decided then (Clyps uses
  [PTN]+[BANK] + trig, which in the standalone image is stock's chord).
- **The standalone RELOAD_FROM_PROJECT gets the same change** (track FULL from the card instead of
  the whole Part, and toasts 1 and 2), rebuilt in all its forms (standalone, KYOTI, Bugbuild,
  octabam) with an octabam PR drafted. **Order: after Clyps** (the user).

**Built `140C_CLYPP` (2026-10-30, not flashed):** `tools/clyps/clyps_reload.s` (forked from
`patch_reload3.s`, `.include`d into the DRAM part): `cl_rlreq` (UI: message first, then the job post),
`cl_rljob` (detour on the type-0x14 case `0x40085864`, 8 B), `cl_rldone` (doneFn success `0x40023c62`,
6 B: verify + toast, skips stock's bank reload), `cl_toast2` (2-line block toast). Kinds: 1 track SEQ,
2 track FULL (the slice from the card's working Part: parses on past the 16 PTRN chunks to that PART
chunk with stock's `0x4008be2c` into `RQ_PART`), 3 PTN (slab + whole Part; Part apply when it is the
sounding Part). Gate L (OT DEMO; SAVE PROJECT, edit, reload): SEQ keeps the slice, FULL restores
T1's slice and not T2's, the chord + TRACK reloads nothing, chord + trig restores slab + Part; the only
differences from RAM are bytes the bank file never holds (`+0x899` per audio record, slab tail).
Toasts: track ones are 2 lines ("TRK 8 CF FULL RELOAD" is 130 px: wider than the 128 px screen);
the pattern one is 1 line.

**The chord's grid** (built CLYPN): with both keys held, in either order, the pattern view of the
playing bank (your pattern red, cued yellow, data green); the bank view only for [BANK] alone.

### 1.8b CLYPR fixes (the user, 2026-10-30; built)
- A load with the box on your own pattern (the highlight) flashes the highlight bar itself.
- Stock's Part-edited flag (bank `+0x95048`, SRAM `0x100b145e`) after a FULL load follows "differs
  from its SAVE PART copy" (bank `+0x9504a + part*0x18b2`, valid when `+0x9b312 + part` != 0, the
  test stock's PART RELOAD makes): identical again → cleared, as after stock's PART RELOAD.
- The chord + [PAGE] / [YES] begun inside Clyps flashes the `ORIG PTN+PART` box (`cl_ftgt` = 1: the
  header label is the flash target; 0: the select box / highlight).

### 1.9 Multi-track loads (the user, 2026-10-30; built `140C_CLYPT`, not flashed)

- **[CUE] in Clyps** does not do stock's cue. Hold [CUE]: the header's left reads **`MULTI BNK A`**
  (the user's choice: the bank stays); the stock sidebar's active-track tab disappears from the active
  track; the track LEDs show plain mute / cue states (solid green, flashing green, off).
- **[CUE] held + TRACK n** toggles track n in the multi group (press again: out, again: in). Members get
  the sidebar's active-track tab and the active track's LED colours (solid red / yellow / flashing).
  Any of the 8 audio and 8 MIDI tracks. After [CUE] is released the group is fixed; only [CUE] held
  changes it.
- **Loads with a group:** [YES] / a trig loads, into **every member**, that member's own sequence from
  the chosen slot number (the box's bank / slot); [FUNC] = FULL for all, as for one track. The select
  box flashes as usual. **ORIG / [PAGE] / [FUNC]+[PAGE]: every member restores its own original**
  (the user's choice).
- **A plain TRACK press** (no [CUE]) with a group: changes the view's track (which track's sequences the
  slots show); the group stays (the user's choice).
- **[NO]** with a group: dismisses the group; everything back to how it was before (Clyps stays).
  [NO] without a group closes Clyps as before.
- To RE: [CUE]'s key code / records (its held sub-map lists the TRACK keys: `0x400bf122`), the track
  LED painter (an LED slot of the base layer `0x400c0932`), and how the main screen's sidebars draw the
  active-track tab (from `0x80000000`), to draw it on every member. **Done, below.**

**RE (2026-10-30, C).** The sidebars ARE drawn with RECT / TEXT: `FUN_4003fed8` (KB memory-map "Mute /
solo / cue"), called on every pass of `FUN_40052200` (the function that ages the TRACK double-tap timer
`0x460d5de0`) and from `0x4004d870`. The earlier trace saw nothing because route A never runs
`0x40052200`, so a track change is never repainted there. Found by a write watch on the main window's
edge columns (`0x46c7e0ea`, rows 0-7 / 120-127 of the rotated plane) during a project load
(`tools/clyps_probe_sidebar.py`). Both of its loops (MIDI `0x4003ff06`, audio `0x4004008c`, track in `d4`)
and the four colour picks of the track LED painter `0x40083eb0` (`0x40083ef4/f04/f24/f36`, track in
`d5`) open with the same 6-byte `mvzb 0x80000000,%d0`; it is the only "active" input of either.
[CUE] = `0x2a`, press `0x4004e978` / release `0x4004e968` (they only set / clear `0x460d168c` and
redraw), delay 0; its sub-map `0x400bf2a0` = TRACK cue toggle `0x40083dc4`, [YES] `0x400402ec`, the
scene keys `0x2b`/`0x2c`, [TEMPO] `0x18` = METRONOME ON / OFF.

**Built `140C_CLYPT` (2026-10-30, not flashed).**
- The six `mvzb 0x80000000,%d0` → `jsr cl_act4` / `cl_act5` (ROM, `cl_magic`-guarded): with a group
  (`cl_gmask` = `0x10000` | members, bit t, MIDI 8..15; set while Clyps is open and [CUE] is held or
  the group has members) d0 = the track when a member, -1 otherwise. So stock itself draws the tab on
  every member and none elsewhere, and gives members the active colours (red; yellow muted; cue
  flashing) and everyone else the plain ones. No painter is reimplemented; the LEDs are repainted
  (`LED_PAINT(6)`) on every group change, and the sidebar follows on stock's next pass.
- Our [CUE] record (`cl_k_cue`, press + release, delay 0 as T1's; stock's cue never runs in Clyps) with
  its own sub-map `cl_csub` (chained after stock's, wins): TRACK = `cl_k_cuet` (toggle; the MIDI side
  when [MIDI] shows it), [YES] = nothing. [TEMPO] (metronome) and the scene keys stay stock's.
- Loads (`cl_load` → `cl_each`) and restores (`cl_restore`: ORIG, [PAGE], [FUNC]+[PAGE]) act on
  `cl_targets`: the members, or the active track without a group; each member = `cl_cueload(t, …)`
  as a one-track load (stopped: at once; running: cued, each at its own window start). With [CUE]
  held and no member picked, a load does nothing. Chord + [PAGE] / [YES] (ORIG PTN+PART) is unchanged.
- [NO] with members: the group goes (Clyps stays); without: closes Clyps. The group also ends when Clyps
  closes, and starts empty at every open.
- Header (measured: font table `0x400c246a`): left `MULTI BNK A` (41 px, x 3..43) while there is a group
  (not while the [PTN]+[BANK] chord is held: its ORIG PTN+PART is the pattern's). The right label
  with a group drops `TRK` / `MIDI TRK` (members can be on both sides): `LOAD: SEQ` / `LOAD: FULL`,
  on ORIG `LOAD: ORIG SEQ` / `LOAD: ORIG FULL` (its `LOAD:` at x 53, 9 px clear). The per-track
  labels would not fit: `LOAD:` starts at x 34-42 for `ORIG MIDI FULL`, `ORIG PTN+PART`,
  `MIDI TRK ...`, `ORIG TRK ...`. **This wording is my proposal (to confirm).** The BANK box moves 12 px
  right (`MULTI_DX`).
- Not changed: the grid's yellow (cued) and the page LEDs still describe the view's track only.
- Gate U (`diag_clyps_ui.py --only U`, OT DEMO; also on JAM2 with M): tabs (stock's painter called
  directly, edge cells counted) and LED colours against stock's own colours for "active" / "none";
  [CUE] held with no member loads nothing; loads / [PAGE] / FULL / [FUNC]+[PAGE] per member, byte
  for byte; a non-member untouched; plain TRACK keeps the group; [MIDI] + TRACK adds a MIDI member;
  [NO] dismisses, [NO] again closes at baseline.

**CLYPV (2026-10-31, not flashed).** CLYPT on hardware: LEDs right, but the tab followed the group only in
its upper half (machine glyph); the lower half (play-status glyph) stayed on the active track, and the
mismatched halves showed a stray `!` beside the glyph. The lower half is a second painter, `FUN_4004bd48`
(called by `0x40052200` just before `0x4003fed8`), with its own two active tests: `0x4004bd64` (MIDI, track
in `d4`) and `0x4004be9c` (audio, track in `d3`; `a0` = its voice record, live across the site) -> `jsr
cl_act4` / `cl_act3`. Emulator renders calling both painters in stock's order: a member's tab is now
pixel-identical to stock's active tab; none while [CUE] is held; back on the active track after [NO].
Also: FULL -> ALL in every label and toast (widths re-measured: all narrower; group `ORIG ALL` puts
`LOAD:` at x 57).

### 1.10 DIRECT JUMP / KYOTI integration (2026-10-31; steps 1-5 built as `KYOTI CL1`, not flashed)

**Target:** KYOTI with Clyps in place of RELOAD_FROM_PROJECT (decided 2026-10-30; Clyps carries the card
reloads). DIRECT JUMP stays as it is (FINAL, ROM, HW-proven); Clyps adapts to it.

**What collides (measured: every Clyps site against every KYOTI feature's sources):**
- `0x400a1f72` phase D: DIRECT JUMP's `dj_land` (jsr) and Clyps' `cl_land` (jmp) -- the same 6 bytes.
- `0x4005e4c8` stock [YES]: Clyps' `cl_yes`; DJ's builder only asserts it is stock (each KYOTI feature
  builds in its own sandbox from stock, so that check still holds there); DJ writes the [PTN]-layer
  YES record `0x400bf0be`, which Clyps does not touch.
- RELOAD_FROM_PROJECT's sites (`0x4005a044`, `0x4007af80`, `0x4007b3e0`, `0x40085864`, `0x40023c62`,
  `0x4005e25c`, ...): RELOAD leaves KYOTI.
- `0x40056c28` (QLREC only names it), `0x40062d1c` (VARISPEED_EMUS, not in KYOTI): no clash.
- REC_TRIG_MUTE patches the lower-tab painter at `0x4004bee2` / `0x4004c00c`, not Clyps' `0x4004be9c`.
- **Placement:** KYOTI V1.6's ROM zones are full (CAVE 42 B, SAFE 8 B, ENC 40 B free; SPRING 400 B,
  PERS1 128 B, PERS2 64 B reclaimable). Clyps' ROM part is 3,544 B.

**Plan.**
1. **Clyps' ROM part -> DRAM.** Only guarded stubs stay in ROM (the painter tests `cl_act3/4/5`, the
   tick / wrap / UI-tick entries, `cl_rstall`): each checks `cl_magic`, then jumps into the DRAM body.
   About 200 B, in SPRING. Tick code in DRAM is HW-proven (OBKYOTI6-12 ran DJ's phase-D hook and
   REPITCH's frame-ISR half from DRAM; KB caves.md §5); `build_kyoti.py`'s "ISR code: CAVE/SAFE only"
   line is a choice, and this changes it for Clyps. Clyps is KYOTI's only DRAM unit once RELOAD leaves,
   so its bss can stay after its `.dram`.
2. **Phase D shared:** Clyps owns `0x400a1f72`; its stub calls DJ's `dj_land` first (it saves every
   register and replays the displaced `move.b 0x80006687,%d0`), then Clyps' landing, then replays and
   resumes. DJ's symbols come in as pass-2 flags (as VARISPEED gets `sw9_draw`); `build_kyoti.py` learns
   that this one site is Clyps' and that DJ's 6 bytes there are superseded (asserted, not silently).
3. **DJ on (`DJ_MODE` != 0):** a Clyps load lands at the next master step (Clyps' landing gate reads
   CHAIN AFTER = 1 step), at the phase-continuous position within the playing pattern's master cycle.
   That IS the clock-locked "as if since START" position whenever DJ landed the playing pattern (V7
   lands START-aligned); only a pattern entered by a stock change before DJ was turned on differs,
   and there the track stays in step with its own pattern.
4. **A DJ jump drops Clyps cues:** on DJ's landing tick (`dj_state` = LANDING after `dj_land`) Clyps
   drops every pending cue (stock re-lands the whole sequencer). Clyps never writes `0x80006687`.
5. **[PTN]+[YES] in Clyps = DJ's toggle** (`cl_k_yes`, `DJ_TOGGLE` = `dj_toggle`, called with the key's
   own two arguments). A [PTN] pressed inside Clyps gets stock's [PTN] layer, whose YES record DJ
   already points at `dj_toggle`.
6. **Then, in the same image, check:** VARISPEED (an ALL load changes TSTR without stock's paste /
   PART RELOAD, where VARISPEED's hold / forget hooks sit: S119's bug class), SIDE-CHAIN (ALL loads
   change FX ids under its tap), REC_TRIG_MUTE ([TRACK]+[YES]/[NO] vs the temp save's [YES]/[NO]+TRACK,
   order-dependent), MUTE_MODES (FUNC+TRACK mutes inside Clyps).

**Built: `KYOTI CL1`** (`KYOTI_ALLOW_WIP=1 KYOTI_VERSTR="KYOTI CL1" python3 tools/build_kyoti.py --with CLYPS`;
out/KYOTI_WIP/KYOTI_V1.6_WITH_CLYPS/). Steps 1-5 as planned, with one change to step 1: NO ROM stubs at all.
The loader runs from the boot site `0x4000050c`, before `0x40001e50` (boot continue) starts the tasks, the
UI and the sequencer, so every hook finds the DRAM unit in place; the whole unit is `.dram`
(`--defsym CLYPS_ALLDRAM`, the source's five ROM blocks are `ROMSEC`), 17,204 B + 10,434,796 B buffers =
1,704 arena pages (10.2 MB). The standalone build is byte-identical to CLYPY (`111d6103...`).
- `build_clyps.py`: a KYOTI mode (KYOTI_PLACE set): all DRAM, linked at `patch_clyps_dram`, DJ's
  `dj_land` / `dj_toggle` / `dj_state` / `DJ_MODE` as defsyms, no append, no wrap.
- `build_kyoti.py` (thread kyoti-v1): `WIP_FEATURES["CLYPS"]`; `--with CLYPS` drops RELOAD_FROM_PROJECT;
  `SUPERSEDE` (Clyps owns `0x400a1f72`, asserted: DJ's bytes there = `jsr dj_land`, Clyps built with
  that `DJ_LAND`); B2 accepts Clyps' [PTN] / [BANK] handler detours only as jmps into its DRAM unit; the
  DRAM image takes Clyps' buffers (`dram.build(bss=)`, Clyps last); `KYOTI_VERSTR`. The default build
  still matches the promoted KYOTI V1.6 (`c2692220...`).
- Gates on the KYOTI image (`CLYPS_SYMS` from the map's `patch_clyps_dram` symbols): full 128, F+Q 27,
  L 8, M+U on JAM2 26, and the new **J** (10): [PTN]+[YES] in Clyps toggles DJ (no load, Clyps stays, no
  SELECT on [PTN]'s release); DJ on, CHAIN AFTER off, master length 64: a cue made at master step 3
  lands at step 4 (75 ms); a DJ jump (PEND written as stock's pick writes it) lands and drops the
  pending Clyps cue, neither T1 touched.
- Step 6 is NOT done: VARISPEED / SIDE-CHAIN / REC_TRIG_MUTE / MUTE_MODES with Clyps are hardware
  walk-through items (FLASHING §4 "KYOTI CL1").
- Found on the way, not Clyps': KYOTI's SAFE zone (`0x400d24d0..0x400d2cdc`, ~2 KB of V1.6 code) is
  entries 508-1023 of a live 1,024-long curve table at `0x400d1ce0` (stock 0 there; the per-voice engine
  `0x40003522` indexes it with a u16 >> 6, so inputs >= 32,512 read code). caves.md §5 / NOTES S124 said
  so; build_kyoti.py's zone list was never updated. Told the user.

**Cost to KYOTI users:** Clyps' buffers (the originals = every bank as loaded, the saved sequences,
the pattern snapshots) take ~10 MB of the sample pool, as in the standalone Clyps images.

## 2. Decisions

### Settled (2026-10-26, the user)

- Originals = the state as loaded (power-on / LOAD PROJECT / reload), always available (§1.5′).
- LEFT/RIGHT jump to the same row of the other column; no bank change on the arrows.
- The bank is picked as in stock: [BANK] alone + a trig, without leaving Clyps mode.
- No 17th `ORIG` row: `ORIG` stays the cursor entry with the header box (ROW17 proposal dropped).
- The playing pattern's own slot shows the loaded copy after a load (2026-10-25).

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
- **Temp save / reload (the user, 2026-10-27):** outside Clyps only: hold [YES] + TRACK = save,
  hold [NO] + TRACK = reload; stock ARM / DISARM on a quick tap only (a long hold does nothing).
- **[YES] and DIRECT JUMP (was O5; changed by the user 2026-10-25):** with the [PTN]+[BANK] chord
  held, [YES] does nothing: DIRECT JUMP must not toggle there. In Clyps mode with only [PTN] held,
  [PTN]+[YES] is DIRECT JUMP's toggle, and it never loads.
- **Saved sequences (was O7):** they last only while the unit runs its project. A power cycle or a
  project reload destroys them.
- **O9, CHAIN AFTER point landings:** phase-continuous. The track lands where it would be had the
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
    `+0x53/+0x54` pattern length/scale, `+0x55` SCALE_MODE, `+0x56` CHAIN AFTER, `+0x57` Part link,
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
| A3 vs B3 | CHAIN AFTER = 4 on A15 | FAIL, as expected: the stock change lands at the CHAIN AFTER point (t42) and **restarts every track at step 1**. With no pending stock change, the wrap body runs only at the master wrap (t186) |

**So:**
- **At a master wrap:** a Clyps landing is one record copy at `0x400a43a0`. Stock's own wrap body
  then re-homes and purges, so no per-track code of ours is needed.
- **At a CHAIN AFTER point:** the stock reference is the wrong target, because it restarts all tracks.
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
CHAIN AFTER point trigger (the arithmetic is above; the trigger is our phase-G evaluation of stock's
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
| DIRECT_JUMP_KYOTI | [PTN]+[YES] toggles DJ; a DJ jump changes the playing pattern | with the chord held [YES] does nothing; [PTN]+[YES] in Clyps mode is DJ's toggle; a jump drops cues; Clyps loads use DJ's landing when DJ is on; never write `0x80006687` |
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
  - Variants: NORMAL and PER TRACK; CHAIN AFTER default/4/master; a faster-than-master track; INF master;
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
- [ ] Landing on time by ear, NORMAL and PER TRACK, CHAIN AFTER default/4/master, DJ on and off.
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
- **Hardware report on `140C_CLYP3` (2026-10-23):** text too big (not the interface font), window
  too narrow, header not lit, footer unwanted.
- **`140C_CLYP4`:**
  - font `0x400ba876`: the interface font, 3-px glyphs 1 px apart, 5 rows tall, used at 506 stock
    sites;
  - a 112 × 64 window on stock's border lines (screen columns 8–119);
  - a lit header band with inverted text, exactly one lit row above and below it;
  - `LOAD: SEQ` right-aligned in the header (32 px). [FUNC] held shows `LOAD: SEQ/MCH/FX` (60 px).
    The full `SEQ+MACHINE/FX` (76 px) collides with `T8 BANK A`;
  - gate 28/28.
- **CLYP4 flashed (2026-10-23); the user's notes:** header 2 px taller, rounded top corners
  (card), rows centred, and symmetric columns. Column 2's highlight had overlapped column 1's:
  a stale duplicate `.equ COL1_X, 55` silently won.
- **`140C_CLYP5`**, pixel-checked in the emulator:
  - header band 9 rows (2 lit rows above and below the text, border included);
  - corners rounded (3 px cleared each);
  - rows 4 above / 3 below in the odd 54-row field;
  - highlights 2–54 and 57–109 (1 px to the frame both sides, 2 px between);
  - render `CLYPS_view.png`. Gate 28/28.
- **CLYP5 flashed: "looks good".**
- **`140C_CLYP6`: cued landings while playing.** Detours at `0x400a1f72` (phase D),
  `0x400a43a0` (wrap body) and `0x40062d1c` (the UI loop tail, the follow-up).
  - **Exact against the oracles, driven by real key presses:**
    - a master wrap equals a stock pattern change (C1w vs B1, 450/450 ticks);
    - a CHAIN AFTER = 4 landing of a 64-step sequence (C2c vs R5) and of a 2x one (C3s vs R7) is
      locked from the tick right after the landing.
  - **First cut one tick early (corrected).** It treated the tick *before* the boundary as the
    landing tick. Phase G advances the master counters, so phase D sees TICK_CTR == 0 on the first
    tick of step s, and t0 = (MASTER_STEP − 1)·tps_M + TICK_CTR.
  - **DIRECT JUMP timing:** with the KYOTI integration (this image has no DJ).
- **CLYP6 flashed (2026-10-25).**
  - Hardware steps 1–10 pass, except that **MIDI tracks were not detected**. Clyps read the long
    flag `0x80000012` with a **byte** read (its high byte, always 0), so on the MIDI side it
    showed and loaded audio tracks.
  - **RELOAD_FROM_PROJECT has the same byte read** (`patch_reload3.s` `rl3_arm_n`,
    `move.b MIDI_MODE`). Reported to the user, not fixed in this thread.
- **`140C_CLYP7`:** the flag is read as a long; bank repeat is delay 15 / repeat 6.
  - New gate scenario M on JAM2 (which loads with the MIDI tracks showing): M2 loads byte-exact.
  - OT DEMO gate 28/28; MIDI render `M2 BANK A` correct.
- **`140C_CLYP8` (2026-10-25), the DRAM move, not flashed.** One source, two sections: the tick
  path in the cave (1,512 B), the rest in DRAM (3,584 B) through the boot loader (`tools/dram/`,
  `dram.build(bss=)` added; KYOTI V1.6 rebuilds sealed). Behaviour-identical to CLYP7: C1w/C2c/C3s
  equal the stored CLYP7 runs tick for tick (state, fires, commits, builder calls); UI gate 28/28;
  JAM2 M passes. Superseded by CLYP9 before any flash.
- **`140C_CLYP9` (2026-10-25), NOT flashed.** Syx `9bd97e27cce2a61341f552eb1a9e3c448d8a752459a81b449e76154cfdcd3ada`,
  CF `.bin` `4ac0cdc0…`, mainos `1fc43991…`. Saved sequences, originals, the project-load clear,
  the [YES] / DIRECT JUMP rule. Cave 2,130 B (3,818 left); DRAM 5,472 B + 9,591,200 B buffers =
  1,563 pages.
  - **Gates:** UI `--only ABCDYENP` on OT DEMO, 61/61. E: save byte for byte; the first load keeps
    the original, later loads and a saved load do not replace it; `ORIG` in the UP/DOWN cycle;
    [PAGE] / [FUNC]+[PAGE] restore byte for byte. N: a NORMAL pattern converted by a 64-step load
    and restored: the whole slab is back, 0 bytes differ. P: a second LOAD PROJECT drops every
    original and saved sequence. Y: the chord + [YES] does nothing; [PTN]+[YES] latched never
    loads. JAM2 `--only M` passes.
  - **Landings with transport running** (against C1, the never-switched A15):
    - C4v (A14's T6 at the wrap, then [FUNC]+[NO] at t252, immediate): identical from t247 to
      t451. Without it (C1w8) T6 diverges from t282.
    - C6o (CHAIN AFTER = 4, [PAGE] at t130): locked from t139, the tick after its landing.
    - C5o ([PAGE] cued to the wrap t378): identical from t384; for the first step after the wrap
      only T6's STEP−1 differs (31 vs 15). Stock's re-home after a pattern change leaves it the
      same way, so it is left as stock does it.
  - **Bugs found and fixed in the gate before handing over:** stock's FUNC sub-map took [FUNC]+[YES]
    / [NO] / [PAGE] (sub-maps chain, §0 traps; fixed with our `cl_fsub`); the project-load hook sat
    on `0x40090504`, which a LOAD PROJECT never runs (moved to `0x400905d4`).
  - **Renders:** `out/clyps/v9/` (SAVED box, ORIG box, `SAVED` while the saved sequence plays).
- **`140C_CLYPA` (2026-10-27), NOT flashed.** Syx `44176784addb11e9a616242b8982bbea7e414e7b1fd6e64717717f61001206fc`,
  CF `.bin` `1e7524f8…`. The user's 2026-10-26 changes (§1.5′, §1.3):
  - originals = every bank as loaded: snapshots (10.2 MB, 1,664 pages) at the masked loader's
    return, after the power-on SRAM restore (`0x40025808`), and after each `0x4000fd34` reset
    (four call sites, ROM stub `cl_rstall` guarded by `cl_magic`: `0x4001fb1e` may run before the
    DRAM part exists); `ORIG` always in the cycle; [PAGE] undoes a load or a grid edit;
  - LEFT/RIGHT = the other column; [BANK] alone + trig picks the shown bank in Clyps mode.
  - Gates: UI `--only ABCDYEKNP` 71/71 (OT DEMO), M on JAM2; C1w = B1 exactly; C6o (ORIG from
    the snapshot) locks at t139.
  - Found: a reload runs as "loader pass → `reset_all_banks` → maybe another pass"; in one
    emulator flow the reset came last and left the banks at defaults. Hence the re-snapshot after
    every reset. The snapshot copy (10 MB per pass) adds an estimated 0.1–0.2 s per pass to a
    project load on hardware (not measured).
- **`140C_CLYPB` (2026-10-27), NOT flashed.** Syx `4a708dacb23e60309d84482aba8fc30ea6bdb8f4973e99b6bec2a4a2edb2422b`,
  CF `.bin` `81cd0139…`. §1.0 step 1: highlight = your pattern, 1 px select box, trig = select +
  load, source label, red-wins LEDs with a flashing cue (ROM tick `cl_blink`, hardware-only: route
  A runs no LED ticks), only [NO] closes, [BANK] held + arrows page. Gate A B C D Y E G N P 60/60,
  M on JAM2. Renders `out/clyps/vB/`: with 1 px gaps the box lines sit in the gap rows, touching
  the neighbours' text.
- **`140C_CLYPC` (2026-10-27), NOT flashed.** Syx `6868f7ed5497b64697dbda9995704acab2c714e293de37c0224f15460907f30d`,
  CF `.bin` `d73d0c9c…`. The user's 2026-10-27 changes:
  - temp save / reload moved OUT of Clyps: hold [YES] + TRACK = save, hold [NO] + TRACK = reload
    (cue path, armed at once); toasts `TRK n SAVED` / `TRK n RELOADED` / `TRK n: SAVE FIRST`
    (`MIDI TRK n …`; window ≤ 126 px). Detours on stock [YES] `0x4005e4c8` / [NO] `0x4005e25c`;
    our TRACK layer `cl_tlayer` while one is held.
  - Stock ARM / DISARM only on a QUICK TAP (< ~300 ms of SCLK `0x4610757c`, 127,008,000 / s,
    measured running with the transport stopped), replayed as stock's press + release. Stock
    untouched with the arranger running and in LIVE REC (`0x460d172a`: stock [NO] + TRACK / knob
    erase live through its NO sub-map `0x400bfbfc`).
  - [FUNC]+[YES] / [FUNC]+[NO] inside Clyps do nothing; no frame when the box is on the highlight.
  - Gates: A B C D Y E T G N P 71/71 (OT DEMO), M on JAM2. The gate now dismisses the emulator's
    boot SET DATE/TIME dialog (layer `0x400d0ed6`) before its baseline.
  - Not verified: the quick [NO] tap's disarm against a stock run (it replays stock's handler).
- **`140C_CLYPD` (2026-10-27), NOT flashed.** Syx `8eb80153765279d97e8887e8e8c1c0654775ff0b2c638b599ff47b8c659d7180`,
  CF `.bin` `3a7e3912…`. Sequence names (§10.0): [FUNC]+[BANK] in Clyps opens stock's editor
  `0x4007e664` on the box's sequence (9 characters; its first argument is the character count:
  the cursor stops at count − 1, and [YES] copies count + 1 bytes back from its space-padded
  working copy `0x460e743c`). Names follow loads, temp saves and ORIG; DRAM only for now
  (+82 KB, 1,677 pages). Gates: A B C D Y E T G R N P 81/81, M on JAM2. Renders `out/clyps/vD/`.
- **`140C_CLYPE` (2026-10-27), NOT flashed.** Syx `8830a239212372d1855433995ea4176377a81b9abad5dd5dbc93adb27798d22c`,
  CF `.bin` `5cdf1ff0…`. The "edited" mark (the user, revised): a 3 × 3 "x" (corners + centre) at
  rows y + 1..3, left of the number at col − 4..−2 in both columns; the columns re-laid out so
  column 2's mark is 2 px clear of column 1's bar / box (bars 2–54 and 56–108, number → label
  5 px, labels ≤ 35 px: 9-character names; source label `A14 64TRG`), on a slot whose sequence (active track)
  differs from its load snapshot: the record with its length / scale bytes aside, plus its
  effective length / scale (`cl_edited` / `cl_efflen`). So: none after power-on / a load; on after
  a swap or a trig edit; off when the original is back by any route. Gate 81/81; renders
  `out/clyps/vE/`.
- **`140C_CLYPF` (2026-10-27), FLASHED 2026-10-28, the user's walk-through all passed.** Syx `b3eacd36a5357a9f6886c5cb4b901717ec45f8db15c5cf624d3688c06178ccd8`,
  CF `.bin` `220560c1…`. Names on the card (§10.2) and the user's layout: per column (`cl_colx`)
  the x at 3..5 / 55..57, bar / box 8..52 / 60..108, numbers at 10 / 62..68, labels at 16 / 72
  (3 px from the number: the only fit for 9-character names with 2 px to the right frame); the
  select box drawn SET after every bar (a full box, also next to the highlight); rows at 6 px
  (7 px tried, dropped). Gates: A B C D Y E T G R S N P 88/88, M on JAM2. A "fault" chased for a
  while was the harness (§10.2 harness lesson), not Clyps.
- **Decided (the user, 2026-10-25):** after a load onto the playing pattern, its own slot shows the
  loaded copy (the keep rule, as built). What it held before is reached through `ORIG` / [PAGE].
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
- A key's sub-maps chain across layers in the rebuild `0x4003125c` (they are appended, never
  overridden), and a press links the chain at the end of the layer list (`0x40031766`).
- Stock's TRACK press `0x40040250`: a second press of the same key while `0x460d5de0` ≤ 14 is a
  double tap (event 3 to `0x40083ab4`).
- LOAD PROJECT reads banks through the masked loader `0x400905d4(ctx, mask, …)` (bit n = bank n;
  callers `0x400853d8`, `0x40084d60`, `0x40085452`); `0x40090504` (kb/octabam-index L92's "project
  load") did not run in an emulator LOAD PROJECT.

---

## 10. Phase 2 — named sequences

### 10.0 Decided (the user, 2026-10-27) and built (CLYPD)

- **Entry:** [FUNC]+[BANK] (EDIT), only inside Clyps. It names the sequence under the select box
  (nothing on `ORIG`).
- **Editor:** stock's own, as project naming: `0x4007e664(size, title, buf, layout 0, done_cb)`,
  title `RENAME SEQUENCE`. Its window is priority 5, so the Clyps view (priority 3) stays under it.
  [YES] stores the name and drops back to Clyps; [NO] keeps the old one.
- **Shown:** a named slot shows its name in place of its trig summary.
- **Length:** 9 characters. Every letter and digit of the slot font is 3 px (+1): 35 px of the
  37 a slot has after its number. Only `# $ @ ~` are wider.
- **Names follow the sequence** (built, not yet asked of the user): a load copies the source's
  name onto your pattern's slot (none = cleared), a temp save / reload carries it, `ORIG`
  restores the name the slot had at load time.
- **Persistence: none yet.** Names live in DRAM and are cleared by a project load and lost at
  power-off. Next: a sidecar file in the project folder (below), read at load and written with
  SAVE PROJECT, so names are exactly as saved as the sequences.

### 10.2 Names on the card (CLYPF, 2026-10-27)

- **Files:** per bank, `<project>/clypsNN.work` and `clypsNN.strd` (NN 01–16): 2,568 B each, the
  header `CLYP` + u16 1 + u16 256, then 256 names × 10 B (16 patterns × 16 tracks). Per bank
  because SAVE BANK / RELOAD BANK touch one bank.
- **Kept in step with stock's own bank files**, all in the project worker task (`0x4008445c`,
  prio 1, 16 KB stack; it peaks at 2.85 KB during a SAVE that creates them, measured):
  - written at the bank writer's exit `0x400919d6` for its mask (every `.work` write: SAVE, CARD
    SYNC, SAVE AS NEW, flushes);
  - copied `.work → .strd` at SAVE PROJECT (`0x4008f0a2`) and SAVE BANK (`0x4008ee66`, mask d6);
  - restored `.strd → .work` at RELOAD PROJECT (`0x4008f3ae`) and RELOAD BANK (`0x4008f172`);
    a missing source removes the destination, so the two stay mirrors;
  - read at the loader's return (`cl_ldexit`, before the snapshot: names are part of the
    original), all 16 on a project load (the power-on resume too), else the reloaded banks;
  - deleted with DELETE PROJECT (`0x4008ed5e`, stock's own `0x4008ec08`, before the folder goes);
    exported with EXPORT TO SET (`0x400914de`, stock's own `0x4009115c`, not required).
  - Every error of ours is swallowed: never stock's result. A file of the wrong size or header
    reads as no names.
- **Gate S (emulator):** name → SAVE PROJECT → rename + CARD SYNC → LOAD reads the rename (the
  `.work` write) → RELOAD PROJECT restores the saved name (`.strd`) → LOAD reads it; SAVE BANK →
  rename + sync → RELOAD BANK restores the bank's saved name. DELETE PROJECT and EXPORT TO SET
  are NOT run in the emulator (their stock code does card FAT work on the main task, which this
  harness cannot drive): hardware test with a throwaway project.
- **Harness lesson:** never `call_as_main` a poster that touches the card first (CARD SYNC's
  `0x40022cd4` runs `0x400255ec`): it corrupts the emulator's task frames. Enter it past the
  check (`0x40022cfc`, arg 0). SAVE PROJECT / RELOAD PROJECT / SAVE BANK / RELOAD BANK posters only
  post; SAVE BANK's and RELOAD BANK's argument is the bank mask.
- **Limitation (accepted by the user):** names typed after the last `.work` write are lost at
  power-off (stock restores the current bank's unsaved edits from SRAM; Clyps cannot).

### 10.3 Names follow stock copy / paste (the user, 2026-10-28; scoped, not built)

Stock's TRACK COPY / PASTE and PATTERN COPY / PASTE must carry sequence names, exactly as they carry
the sequences: a paste puts the copied name(s) on the destination, so a name always describes the
sequence under it.
- **Track:** COPY remembers the source's name (bank, pattern, track) in a clipboard of ours, beside
  stock's clipboard; PASTE writes it to the destination's (bank, pattern, track) name, or clears it
  if the source had none. Audio: COPY `0x40029754` / PASTE `0x4002b654`; MIDI: `0x40029614` /
  `0x4002b470` (C, §1.7). Hook each at its success path, after stock's own copy.
- **Pattern:** COPY remembers all 16 names of the source pattern (8 audio + 8 MIDI tracks, 160 B);
  PASTE writes all 16. Pattern COPY / PASTE entry points: not yet located (RE).
- **To check during the RE:** stock's paste UNDO (a second paste press / the undo slot) must bring
  the old name(s) back as well; CLEAR TRACK / CLEAR PATTERN probably clear the names (to ask the
  user); a paste into another bank and after a bank change (the clipboard outlives them); the
  clipboard is invalid after a project load (stock's too?); a paste onto the playing pattern while
  a Clyps cue is pending on that track.
- The "edited" x and `ORIG` need nothing new: they compare against the load snapshot, which holds
  the names as loaded.
- Names are written to the card with the bank as now (§10.2), so a paste is saved exactly when the
  pasted sequence is.

### 10.1 Earlier notes


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

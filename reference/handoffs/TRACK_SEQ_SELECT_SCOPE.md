# TRACK_SEQ_SELECT — scope (2026-10-22, research only, nothing built)

*Working name. It is renamed everywhere once the user picks one (§2, D12).*

**Ask (the user's, 2026-10-22).** Hold **[PATTERN] + [BANK]** together and a window opens. It lists
the **active track's sequence in each of the 16 patterns** of a bank: header `BANK A`..`BANK P`,
LEFT/RIGHT change the bank, UP/DOWN move the selection, empty slots read `2 ---`, and the
sequence now on the track is highlighted. [YES] loads the selected sequence onto the active track
and closes the window; [NO] closes it without loading. Other tracks are untouched, and the Part
does not change.
- **Trig LEDs** show the same list while the chord is held: full green = sequence data, half green =
  only trigless trigs or trigless locks, off = empty, solid red = the sequence playing on the
  track, flashing red = cued. They follow the arrows and the TRACK keys.
- **Tapping trig N** picks pattern N's sequence and closes the window at once. The flashing/solid
  red view stays only while [PTN]+[BANK] are still held.
- **Timing.** The load is cued and lands where a pattern change would, per the pattern's settings.
  It must be instant (no stall), like RELOAD_FROM_PROJECT.
- **Length and scale.** The loaded sequence keeps its own length and scale, under the destination
  pattern's master length and master scale.
- **Suppression.** Stock [PTN] and [BANK] actions and toasts are suppressed when the two are
  pressed together.
- **TRACK keys** change the track, and the list and LEDs follow.
- **Phase 2** (to scope, not build): user-named track sequences, shown in the list.

**Verdict: feasible, with no card I/O at all.** All 16 banks are resident in RAM
(`0x400e21e0 + 16 × 0x9b340` is exactly the sample-heap base `0x40a955e0`, `kb/caves.md` §5c). A
load is therefore one memcpy of a 2,330-byte audio record or a 2,224-byte MIDI record: about
600 longword moves, tens of µs. Stock already has every piece we need:
- a sequence-only track write with its SRAM mirror (`0x4002b3b4` / `0x4002b2f4`);
- the dirty-flag helper (`0x40029b9c`);
- the change gate (`0x400a4352..`);
- a track re-home loop (`0x400a4856..`);
- an LED layer stack;
- the list-state helpers;
- the name editor (`0x4007e664`).

The size is the hard part, not the mechanics: an estimated **3.3–4 KB** of ColdFire. It fits the
standalone image's classic cave. In KYOTI it has to go to DRAM, as RELOAD_FROM_PROJECT did in V1.5
(§6).

The real risk is that this **is a modal picker**: the thing RELOAD2 died of (~13 bugs, all in its
picker; `reference/RELOAD_REDESIGN.md`). The difference this time is that the failure modes are now
measured and each has a specific counter (§4.3, §4.4). It still needs a dedicated stress gate.

**Evidence.** Static reads only, made this session against our own `section_3_MAIN_OS.bin`.
Confidence is **C** (read in our image) unless marked **L** (from a doc) or **I** (inferred). Nothing
was run in the emulator, built or flashed.

---

## 1. Behaviour, as proposed (the decisions in §2 pick between variants)

### 1.1 Opening the window

- **The chord, in either order.** Pressing the second of [PTN]/[BANK] while the first is held
  opens the window.
- **The first key's own pending action is cancelled.** [PTN] shows SELECT PATTERN only on
  release, so nothing is visible yet. [BANK] needs SELECT BANK deferred to its release; that is
  RELOAD_FROM_PROJECT's shipped behaviour (D9).
- **The second key does nothing of its own.**
- **Releasing either key never opens SELECT PATTERN or SELECT BANK**, and shows no toast.
- **Starting position.** The window opens on the bank the track's playing sequence came from, with
  its row selected.

### 1.2 The window

Our own window, 128 × 64. It has a title bar and 7 rows at the stock 7-px pitch, and it scrolls
through 16 rows. Draft:

```
┌───────── T6  BANK A ─────────┐
│ ▶ 1  12 TRIGS                │   ▶ = playing on this track (red on the grid)
│   2  ---                     │   --- = empty (LEDs off)
│███3  LOCKS ONLY███████████████│   inverted bar = cursor (UP/DOWN)
│   4  9 TRIGS        CUED     │   CUED = waiting for its landing (flashing red)
│   5  ---                     │
│   6  16 TRIGS                │
│   7  ---                    ▼│   scroll glyph (stock chars 0x11 / 0x12)
└──────────────────────────────┘
```

- **Rows.** Unnamed rows show a content summary; empty rows show `---`. With Phase 2, a name
  replaces the summary (D10).
- **The title names the track** (`T6`, or `M6` for MIDI), because TRACK keys change it while the
  window is open (D11).
- **Keys inside the window:**

| key | action |
|---|---|
| UP / DOWN (`0x33` / `0x20`) | move the cursor, clamped 1..16, auto-repeat |
| LEFT / RIGHT (`0x34` / `0x21`) | bank −/+ (A..P, clamped); the rows, title and LEDs are rebuilt |
| [YES] (`0x31`) | load the cursor row and close the window |
| [NO] (`0x32`) | close the window, load nothing |
| TRIG 1–16 (`0x00..0x0f`) | load pattern N's sequence from the shown bank and close the window |
| TRACK 1–8 (`0x10..0x17`) | change the active track; rows, title and LEDs follow; the bank stays |
| [PTN] / [BANK] (`0x2e` / `0x2f`) | swallowed while the window is open |
| encoders | swallowed, as every stock list does (D13) |
| everything else (PLAY, STOP, CUE, mutes, FUNC, …) | passes through, so performance continues |

### 1.3 The trig-LED view

- **When it shows.** It is on while the window is open **or** the chord is held. D2 decides whether
  a [YES] load also keeps it on until the load lands.
- **Colours**, for the shown bank and the active track:
  - full green (level 15) = the slot has sequence data;
  - half green (level 7, stock's own dim level) = only trigless trigs or trigless locks;
  - off = empty;
  - solid red = the sequence playing on the track;
  - flashing red = cued.
- **Updates.** The view follows the arrows, TRACK keys and landings. It hands back to whatever was
  underneath: the [PTN]/[BANK] grid, the GRID REC view or the normal view.
- **While the chord is still held after the window closed** (a trig pick), the trigs keep picking
  sequences, so a second tap re-cues (D3).

### 1.4 Loading

- **Target.** The source record, at slab `0x400e21e0 + srcBank·0x9b340 + srcPat·0x8ed8 + t·0x91a`
  (MIDI: `+0x48d0 + m·0x8b0`), is copied into the **playing** pattern's track. The playing pattern
  is `PLAY_BANK 0x800065bd` / `ACT_PAT 0x800065be`, the pair RELOAD learned to trust in Session 92.
  Part and other tracks are untouched.
- **Transport stopped:** the load is immediate, and the LED goes straight to solid red.
- **Transport running:** the load is cued, and lands where a stock pattern change cued now would
  land (§3.4). The track restarts at step 1 at that landing, exactly as it would on a pattern
  change (D6).
- **One cue per track, last pick wins.** Cues on several tracks land together. Picking the slot
  that is already playing cancels that track's cue (D7).
- **A stock pattern change or a DIRECT JUMP drops pending cues.** The destination they were aimed at
  is no longer playing (D8).
- **Length and scale.**
  - The loaded track gets its **own** resolved length and scale. That is its record's
    `+0x50`/`+0x51` when the source is PER TRACK, or the source pattern's `+0x8e53`/`+0x8e54`
    when the source is NORMAL.
  - The destination's master length and scale (trailer) are kept, so a 64-step sequence loaded into
    a 16-step-master pattern restarts with the master every 16 steps, as in stock PER TRACK.
  - A NORMAL destination cannot hold a per-track length; D4 decides what happens there.

---

## 2. Decisions for the user

The recommendation is listed first in each.

| # | question | recommendation | alternative(s) |
|---|---|---|---|
| **D1** | **What becomes of the playing pattern's own sequence on that track?** | **It is overwritten**, like stock PASTE TRACK. The bank shows unsaved changes. RELOAD_FROM_PROJECT `[PTN]+[TRACK]` brings back the card-saved version. In the list, the playing pattern's own slot then holds the loaded copy. | (b) Keep the original in RAM per track until the pattern changes, so the playing pattern's slot still lists and reloads its original. That costs ~36 KB of DRAM and more code. (c) A non-destructive "play from" mode that restores the original on pattern change. Rejected: it fights edits made after the load, and saving while overridden. |
| **D2** | After **[YES]**, when the chord is no longer held, do the LEDs stay in the view until the cued load lands? | **Yes** (my reading of your text: [YES] shows flashing then solid red, a trig pick does not). The view ends at the landing, or at once when stopped. | Same rule as a trig pick: after [YES] the view ends unless the chord is held. |
| **D3** | With the window closed but the chord still held, do trigs keep picking? | **Yes**: the grid stays a sequence picker until the chord is released. | The window closes, and trigs revert to stock under the held keys (PTN would then change pattern). |
| **D4** | **Destination pattern in NORMAL mode** (no per-track length exists) | **Convert it to PER TRACK only when the loaded length/scale differ from the pattern's.** Every other track gets `+0x50/+0x51` = the pattern length/scale, and master = pattern length/scale, so they behave as before (to be proven on the oracle). | (b) The loaded track follows the pattern length, so its own length is ignored. (c) Always convert. Either way the SCALE page then shows PER TRACK, and saving keeps it. |
| **D5** | What counts as **full green**: note trigs only, or recorder trigs too? | Note trigs, plus recorder trigs (REC1–3 are real events) | Note trigs only, with recorder-only tracks half green |
| **D6** | At a CHANGE point **before** the master end, does the track restart at step 1 or keep its position? | **Restart at step 1**, as a stock pattern change would do for every track. With CHANGE = master length (the common case) the two are identical. | Keep its step, phase-continuous with the other tracks |
| **D7** | Cancelling a cue | Picking the playing slot again cancels; [NO] only closes the window | [NO] also cancels pending cues on the track |
| **D8** | A stock pattern cue or DIRECT JUMP lands first | Drop our cues (their destination is gone) | Re-aim them at the new pattern |
| **D9** | Standalone builds: [BANK] alone | **Carry RELOAD's SELECT-BANK-on-release deferral** (same code; one copy in KYOTI) | Keep [BANK] stock and close SELECT BANK when [PTN] joins. SELECT BANK then flashes on press. |
| **D10** | Row text for unnamed slots | `12 TRIGS` / `LOCKS ONLY` / `---` | the slot number alone; a 16-step mini-map |
| **D11** | Title | `T6  BANK A` (track, then bank) | `BANK A` only, as specified |
| **D12** | Feature name | your call (`TRACK_SEQ_SELECT` is a placeholder) | |
| **D13** | Encoders while the window is open | Swallowed (stock list behaviour) | Passed through to the page underneath |
| **D14** | Arranger mode active | Chord does nothing (RELOAD's `ARR_ACT 0x460d1aec` gate) | Works; the arranger may re-cue over it |

---

## 3. What stock does — the mechanisms this uses

### 3.1 Data model

- **Pattern slab** = `0x400e21e0 + bank·0x9b340 + pattern·0x8ed8`.
  - It holds 8 audio records (`t·0x91a`), 8 MIDI records (`0x48d0 + m·0x8b0`) and the trailer
    `+0x8e50..+0x8e5b`.
  - Trailer fields: `+0x8e50` u16 master length (−1 = INF), `+0x52` master scale, `+0x53/+0x54`
    pattern length/scale, `+0x55` SCALE_MODE, `+0x56` CHANGE quant, `+0x57` Part link, `+0x58`
    tempo.
  - All 16 banks are resident in RAM at all times.
- **A track record is self-contained and position-independent.** Stock's track paste memcpys it
  into any pattern of any bank (`0x40029614` / `0x40029754`). It contains:
  - trig masks;
  - recorder trigs;
  - swing/slide;
  - p-locks (`+0x59`, 64 × 32);
  - trig words (`+0x89a`: trig count, micro-timing, condition);
  - its own length/scale (`+0x50/+0x51`);
  - the START SILENT flag and `+0x54/+0x57`.

  The Part link lives in the trailer, so the copy never touches it.
- **P-locks are scene-parameter indices and the sample lock is a slot number.** So a loaded
  sequence drives the **destination** Part's machines. That is what "the Part does not change"
  means, and the user should expect it.
- **The SRAM mirror** `0x1001614e` (+ pattern offset) holds the **UI** bank `0x80000002` and is
  what survives a power cycle. Write it only when the destination bank equals `0x80000002`.
- **Stock's sequence-only write**, which is exactly ours:
  - `0x4002b3b4(ctx, pat, t)` is the audio undo-restore. It copies `0x91a` bytes into
    `[0x46c82456] + pat·0x8ed8 + t·0x91a`, the same into the SRAM mirror, then calls `0x40029b9c(t)`.
  - The MIDI twin is `0x4002b2f4` (mirror `0x1001aa1e`).
  - `0x40029b9c(t)` sets `bank+0x9b332 = 1` and `0x100f8598 = 1` (the dirty flags), then calls
    `0x400339d8` (p-lock presence masks), `0x4009da20(t)`, `0x4009da20(t+8)` and `0x400486cc` (UI).
- **Do not call stock PASTE TRACK** (`0x4002b988` → `0x4002b654`): it also writes the Part's
  per-track machine data, sets the Part dirty bits and calls `0x40009094`.

### 3.2 The chord and the keymap

- **The layer stack** (`LAYER_PUSH 0x40031494` / `LAYER_POP 0x4003146c`, head `0x460d165c`).
  - A push appends and is idempotent. A re-push never moves a layer to the top.
  - The rebuild `0x4003125c` walks first to last, and the **last layer that lists a key wins**.
  - Struct (in RAM): `+0` next, `+4` key records (26 B, ended by `0xff`), `+8` encoder records
    (22 B), `+12` sub-map (0), `+16` tag. Record fields: `+2` press, `+6` release, `+10` hold;
    `−1` passes the key down, `0` swallows it; `+22/+24` hold delay/repeat.
- **⚠️ A key held during a rebuild keeps its old handlers** (`0x400312e2` marks its held flag 2
  and skips it). [PTN] and [BANK] are both held when our layer goes up, so **their releases always
  reach stock's `0x4005a044` / `0x4007b3e0`**. Releases are suppressed through state, never through
  the layer. Every handler of ours must also test "window open", because it stays live for any key
  still held after a pop.
- **[PTN]** (`0x2e`):
  - The base record sends press, release and hold to `0x4005a044`.
  - Press pushes the [PTN] layer `0x400bf0f2` (trigs → pattern select `0x40056b2c`) and LED layer
    `0x400bebfe`.
  - Release shows SELECT PATTERN, unless `PTN_CONSUMED 0x460d173e` is set; then it only tears down
    (`0x40043418`). The press clears that flag (`0x4005a06e`).
- **[BANK]** (`0x2f`):
  - Press `0x4007af80`, release `0x4007b3e0`, hold `0x4007af24`.
  - Press pushes the [BANK] layer `0x400cff14` (trigs → bank/pattern select `0x4007b2fc`) and LED
    layer `0x400cff28`. Under RELOAD the window is deferred to release.
  - `BANK_SEL 0x460e73c6 = 2` sends either release handler (stock or RELOAD's `rl3_bank_rel`)
    down the dismiss path, which is a no-op when no window is up.
- **Detecting the chord.**
  - Use the dispatcher's held flags `0x46c7d8ee + code·24` (PTN `0x46c7dd3e`, BANK `0x46c7dd56`),
    tested non-zero, inside the second key's press handler.
  - The panel rows `0x46100b18` (PR #3's choice) run ahead of dispatch; the held flags are in step
    with event order, which is what we need here.
  - Two edges are needed, one per order. Inside RELOAD's unit that is RELOAD's existing
    `rl3_bank_show` press branch plus one new [PTN] splice. Standalone it is a [PTN] splice at
    `0x4005a04e` (8 B) and a [BANK] splice at `0x4007af8c` (6 B), beside RELOAD's guarded ranges
    `0x4005a044..+8` / `0x4007af80..+8`.
- **Arrow codes**: UP `0x33`, DOWN `0x20`, LEFT `0x34`, RIGHT `0x21`.
  - The editor cursor `0x4007e55c` and the list steppers `0x4007ec7c`/`0x4007eca4` settle them, as
    does RELOAD's own `UP_CODE`/`DOWN_CODE`.
  - **`kb/memory-map.md`'s key table is wrong** (§9).

### 3.3 Windows and lists

- **`FUN_4005829c(w, h, dx, dy, prio, close_cb)`** builds a centred window (shifted by dx/dy) and
  returns it, or **0 when all 5 slots are busy** (check it).
  - The 5th argument is an **eviction priority**: opening priority P closes every slot whose
    priority is ≥ P, running its close_cb first (`0x400582ce`).
  - Priorities: toasts/SELECT 0xa, MLNOTIFY 4, name editor 5, menus 3, project lists 2. A
    **priority-3** list therefore survives toasts and the name editor.
  - **`kb/memory-map.md` reads this as `(x,y,w,h,…)` with a "style"; that is wrong** (§9).
- **No timeout unless you ask** (only `0x40059f8c` / `0x4005a2b8` count down). So a plain window
  lives until it is closed.
- **⚠️ close_cb is not cleared on a normal close** and can be called again later. Ours must be
  idempotent and guarded on our own handle. Never pass 0 (the slot would keep a previous owner's
  callback).
- **The template is CHOOSE PROJECT.**
  - Opener `0x400647a0`: `FUN_4005829c(100,64,0,−1,2,0x40063ee4)`, title `0x40057c84(win,title,0)`,
    layer `0x400cba98`.
  - Draw `0x40063f14`: clear `0x400356a8(win+0x24)`, rows at 7 px with font `0x400ba876`
    (`0x40012bd8(font,surf,x,y,mode,str)`), XOR bar `0x40012254(surf,x0,y0,x1,y1,−1)`.
  - y = 0 is the bottom row.
  - Redraw = draw into the window's own surface, then `RDRAW 0x46c7c72c = 1`.
- **List-state helpers.**
  - `0x4007ec60(st,vis,total)` init, `0x4007ec7c` up, `0x4007eca4` down, `0x4007edb0(st,sel)`
    set (clamped).
  - State is `{top, row, sel, vis, total}`.
- **Not reusable:**
  - the generic callback menu `FUN_4006d94c`: 4 rows, no title, LEFT/RIGHT swallowed. octakit
    patched it, so we would collide with an OCTAKIT build;
  - the SHOW_WIN slot `0x460d1e5c` RELOAD's card used: shared with SELECT BANK/PTN, evicted by
    every toast;
  - the toast slot `0x460d1e70`: DIRECT JUMP's `dj_ptnrel` closes toasts on [PTN] release.
- **Track-change redraw.** The setter is `FUN_40083bf8` (writes `0x80000000`). It calls the
  refresh broadcaster `FUN_40083bc0`, which has 7 callers including pattern select and track swap.
  That broadcaster's entry is the hook for "window open → rebuild rows" (**I** that it covers every
  path). MIDI side: `0x80000012` / `0x460d1736`.

### 3.4 Where a pattern change lands, and where a one-track load must land

The tick handler `0x400a1eea` (seq ISR, IPL 2) runs four phases, in this order:

| phase | start | what it does |
|---|---|---|
| D | `0x400a1f72` | — |
| E | — | event builders, one track step ahead: audio `0x4009d1e8` at `0x400a2d7e`, MIDI `0x400a39c6` |
| F | `0x400a3ca4` | track advance |
| G | `0x400a3f94` | master |

**The gate** (`0x400a42fa..0x400a439c`, spot-checked). At master tick 0, `s = ++0x800065b2`.
`N = 0x400d80dc[q]`, where `q = +0x8e56`, or the project default `0x8000004e` when `q < 0`. A change
lands:
- when `N > 0 && pending && s % N == 0`;
- else when `s ≥ ca`, the arranger point `0x8000662c` (≠ −1);
- else, with the arranger running, when `s % N == 0`;
- else when `mlen ≠ −1 && s ≥ mlen`.

The gate never looks at SCALE_MODE. An INF master with no CHANGE never lands.

**Our gate.** The same arithmetic with `pending = "a track cue of ours is armed"`, evaluated at the
same point, without stock's PEND≠ACT test. It needs no code of its own if we hook right after
stock's evaluation.

**The landing.**
- The wrap body `0x400a43a0`:
  - purges pending events at or after one master step;
  - commits;
  - re-homes every track (`0x400a4856..0x400a4b78`): per-track tps/len, the HOLD bit `0x80006626`,
    countdowns, `0x800064d0[t]`.
- The audible landing is one master step after the commit tick.
- The event builder reads the **blob slab**, not the SRAM mirror, and captures locks at build
  time.

**Our copy point (I, must be proven on the oracle, §7).**
1. Copy on the commit tick, in phase G after stock's body. The track's last old step was built on
   or before that tick; its first new step is built after it.
2. Re-home that one track ourselves with its **new** length/scale (stock's re-home used the old
   ones).
3. Purge its slots at or after the landing time:
   - audio `0x80001904`/`0x46c7e998`/`0x46c7fe44` and `0x80001984`/`0x46c7faa4`/`0x46c7fe8c`;
   - MIDI `0x46c76a26`/`0x46c769c0`/`0x46c77be2`.
4. Write `0x8000663e[t]` (the per-track scale cache).
5. Call `0x400a539c(t)`: it resets that track's A:B counter and FILL; 0..15 = one track.

**Edge case.** In PER TRACK mode a track faster than the master finishes its last steps from the
outgoing slab (stock's deferred landing, the HOLD bit cleared at `0x400a3d1c`). Here that is the
same slab, so the copy must wait for that track's own late landing.

**Cost.**
- The blob memcpy (`0x40020898`, unrolled longwords) is ~600 moves, about 15–25 µs, against an
  8.3 ms tick at 300 BPM. It is safe in the ISR.
- **Not in the ISR:**
  - the SRAM mirror write (wait states unknown);
  - `0x40029b9c`'s calls (UI code, and `0x4009da20` posts to a queue).

  These run in the UI task right after the landing (§4.5).

### 3.5 Trig LEDs

- **Hardware.** `0x460ba98c` is 17 bytes, 1 bit per die; trig n is red die `2n`, green `2n+1`.
  - Bits: `0x400131a0` set / `0x400131c8` clear.
  - Brightness: `0x400135b0(id, 0..15)`, cached, so a repeat call is free. Stock's dim level is
    **7**.
  - Flush: `0x400136a8` sends changed rows only.
- **The LED layer stack.** An 8-slot table at `0x460e7628`; trig LEDs are slot 0.
  - `0x4007e760(desc)` push (append, idempotent, last wins), `0x4007e81c(desc)` pop,
    `0x4007e998(0)` repaint slot 0 + flush.
  - Descriptor `{next, records}`, records `{id, paint, tick, period}`. It must live in RAM.
- **Tick context.** Ticks run from `0x4007e940`, inside `FUN_40052200`.
  - Stock's [BANK] layer does LED work there (period 15).
  - ⚠️ Nothing else may run from that context: **no window, draw, toast or layer push/pop**. It is
    the path where QLREC's toast crashed a unit (CLAUDE.md, Session 93).
- **Stock never flashes a cued pattern.** The [PTN] grid shows it steady red+green. Our flashing red
  is our own tick toggling the red bit.
- **Stock's content test** `FUN_4009a464` ORs `+0x00..0x0f` and `+0x18..0x37` and skips `+0x10..0x17`
  (and reads no locks). That is EMPTY_PATTERN_LED_FIX's bug. Our classifier is our own:
  - **full**: any of `+0x00` (note trigs), plus `+0x20..0x37` if D5 says so;
  - else **half**: `+0x08..0x1f` non-zero or any lock byte ≠ `0xff`, using the AND-8-longs scan
    from `patch_pattern_led.s`;
  - else **empty**;
  - MIDI: masks `+0x00`/`+0x08`, locks at `+0x30` (`0x800`).
- **Cost and Session 119's lesson.** Worst case ~800 instructions per empty slot, 16 slots ≈ 13k per
  classification, ~1000× under the Session 119 stall. Even so, **cache** the 16 classes and
  re-classify only:
  - on entry and on a bank/track/MIDI-side change;
  - the playing slot, on each paint (live recording).

---

## 4. Design

### 4.1 State (in our own code space, never `0x80006a40+`)

| item | size | notes |
|---|---|---|
| `ts_open` | 1 | window open |
| `ts_view` | 1 | LED layer linked |
| `ts_bank`, `ts_cur` | 2 | shown bank, cursor |
| `ts_win` | 4 | our window handle (never a stock slot) |
| `ts_cls[16]` | 4 | 2-bit classes for the shown (bank, track) |
| `ts_src[16]` | 32 | per track: the (bank, pattern) its sequence was loaded from; valid while `ts_home[t]` == the playing (bank, pattern) |
| `ts_home[16]` | 32 | per track: the playing (bank, pattern) at load time, so provenance invalidates itself lazily |
| `ts_cue[16]` | 32 | per track: pending (bank, pattern) or −1 |
| `ts_post` | 1 | landing happened, so the UI-side follow-up is owed |
| layer struct + key records | ~24 + 33 × 26 | trigs 16, arrows 4, YES/NO, TRACK 8, PTN/BANK, terminator; RAM-resident |
| encoder records | 8 × 22 | seven nulls + terminator |
| LED descriptor | ~24 | |

The "playing" (red) slot of track t:
- if `ts_home[t]` is still the playing pattern, it is `ts_src[t]`;
- otherwise it is the playing pattern itself.

So no hook on pattern commit is needed.

### 4.2 Chord edges (UI task, key handlers)

On the second key's press, with the other's held flag non-zero, and outside the arranger:
1. **Undo the first key.**
   - If [BANK] was first: call its teardown once. Use RELOAD's `r3r_notours` rule: dismiss if a
     window with onClose `0x4007b408` is up, else call `0x4007b408`. This pops both of [BANK]'s
     layers and balances `0x4007e760`/`0x4007e81c`.
   - If [PTN] was first: nothing; its layers sit harmlessly under ours.
2. **Skip the second key's own press entirely.**
3. Set `PTN_CONSUMED = 1` and `BANK_SEL = 2` (inside RELOAD's unit: `rl3_bank_used = 1`). Both
   releases then tear down silently.
4. Build the class cache, open the window, push our keymap layer, push our LED layer, repaint.

On each release of [PTN]/[BANK]: if neither is held any more, the window is closed, and D2 has
nothing pending, pop the LED layer.

### 4.3 The window and its keys

One open path and **one teardown** (`ts_close`), used as the window's close_cb *and* by YES, NO
and trig picks. This is CHOOSE PROJECT's shape (`0x4006d754`). The teardown:
- closes the handle (`0x40055db4(&ts_win)`) if set;
- pops our keymap layer;
- clears `ts_open`;
- sets RDRAW;
- is idempotent and guarded on `ts_win`.

Eviction by any later window (priority ≤ 3) therefore lands in the same teardown: the
"walk-away" bug class cannot leave state behind.

The handlers:
- They act on **event 1 only**; the stock list records set the arrows' auto-repeat.
- They draw **in place** into `ts_win`, never re-create it.
- They clamp at the single draw choke point.

The TRACK records:
- call the stock setter path, **not** the base handler `0x40040250` (RELOAD's detour lives there,
  and would read PTN+BANK as a reload chord);
- carry **no sub-map**, so REC_TRIG_MUTE's TRACK sub-map (`0x400d164a`, YES/NO → `rtm_*`) is not
  linked above us (**I**, emulator check).

The track-change redraw hook on `FUN_40083bc0` covers track changes from anywhere.

### 4.4 RELOAD2's bug classes and the counter to each

| RELOAD2 bug | counter here |
|---|---|
| dead YES/NO under [PTN]; borrowing other layers; YES swallowed under [BANK] | own layer, pushed last, own YES/NO records; never detour `0x4005e4c8`/`0x4005e25c` |
| [PTN] triple-booked | one decision point per order; claim the gesture with the consumed flags |
| collision with DIRECT JUMP's poke | never write another layer's records (`0x400bf0be` is DJ's) |
| SELECT BANK flashing | suppress before it draws (D9); exactly one teardown |
| arrows double-stepping / pairing wrong twice | event 1 only; one record per code, codes from §3.2 |
| walk-away left it primed | one idempotent teardown, also the close_cb |
| snapshot corruption | never save/restore dispatch slots; push/pop rebuild |
| redraw tripped its own teardown | draw in place, never re-create |
| unbounded `G_SEL` | stock clamped helpers |
| BUSY inconsistency | no BUSY state; last pick wins |

### 4.5 Loading

**Stopped**, from the key handler (UI task):
1. memcpy source → destination record.
2. Fix the length/scale (§1.4, D4).
3. Write the SRAM mirror if the destination bank is the UI bank.
4. Call `0x40029b9c(t)`.
5. Update provenance and repaint.

**Running.** The key handler only writes `ts_cue[t]`. A hook in phase G, right after stock's gate
and wrap body (or at the faster-than-master late landing, §3.4), does the following for every armed
track whose destination is still the playing pattern:
1. Copy into the blob slab.
2. Fix the length/scale.
3. Re-home that track.
4. Purge its later slots.
5. Write `0x8000663e[t]` and call `0x400a539c(t)`.
6. Set provenance, clear the cue, set `ts_post`.

**The follow-up** (SRAM mirror, `0x40029b9c`, the LED repaint and the D2 teardown) runs from a
**UI-task** tick.
- The candidate is the 60 Hz UI tick task `0x40056c40` (message type 1, posted by DTIM1 via the
  ÷2 prescaler; it counts toasts down).
- Its rate and its "always runs" property are **I** until measured.
- The LED layer's own tick is **not** that place.

### 4.6 Length/scale on landing

| source | destination | write |
|---|---|---|
| PER TRACK | PER TRACK | nothing; `+0x50/+0x51` travel in the record |
| NORMAL | PER TRACK | record `+0x50/+0x51` := source `+0x8e53/+0x8e54` |
| any | NORMAL, same len/scale | nothing |
| any | NORMAL, different len/scale | D4: convert the destination. `+0x8e55 = 1`, `+0x8e50 = (u16)+0x8e53`, `+0x8e52 = +0x8e54`, every other track's (audio `+0x50/+0x51`, MIDI record `+0x28/+0x29`) := `+0x8e53/+0x8e54`. Then the loaded track's own values. |

The validator's ranges are respected (track length 2..64, scale 0..6; `0x4009a670`, `0x4009aa4a`).
The master scale cache `SCALE_IX 0x8000663d` must be refreshed if a conversion changes it (RELOAD
Session 89's scar).

---

## 5. Interactions with the other features

| feature | conflict if nothing is done | rule |
|---|---|---|
| RELOAD_FROM_PROJECT | with both held, TRACK hits `rl3_bank_trk` → a TRK SEQ reload; both own the [BANK] press/release sites | our layer owns TRACK while open; in KYOTI, recognise the chord inside RELOAD's `rl3_bank_show`/`rl3_bank_rel` instead of splicing beside them |
| DIRECT_JUMP_KYOTI | [PTN]+[YES] toggles DJ when [PTN] is on top; a DJ jump changes the playing pattern under a pending cue | YES belongs to our window while it is open; drop cues when the playing pattern changes (D8); never write `0x80006687`; DJ's hooks (`0x400a1f72`, `0x400a221c`, `0x40043418`) are disjoint from ours |
| REC_TRIG_MUTE | holding TRACK links its sub-map above us, so TRACK+YES would mute recorder trigs | our TRACK records carry no sub-map (verify) |
| EMPTY_PATTERN_LED_FIX | none: we never call `FUN_4009a464` | — |
| MUTE_MODES, SIDECHAIN, VARISPEED, BLACKPYRAMIDS_303 | none known: no shared site | BLACKPYRAMIDS_303 tracks: an "empty trigless lock is a tie" there, so the half-green rule is cosmetic only |
| OCTAKIT / octabam | the generic menu `FUN_4006d94c` is Octakit's patch site | we do not use it |

---

## 6. Size and placement

| unit | estimate |
|---|---|
| chord edges + suppression | ~250 B |
| window, draw, list, teardown, track hook | ~800 B |
| LED layer: paint, tick, classifier | ~450 B |
| cue gate hook, copy, re-home, purge, length/scale | ~800 B |
| UI follow-up | ~150 B |
| layer struct, key/encoder records, strings | ~1.1 KB |
| **total** | **≈ 3.3–4 KB** |

- **Standalone**: the classic cave `0x400d64da..0x400d7c3c` (5,986 B in stock) holds it. Read
  `kb/caves.md` before naming addresses.
- **KYOTI**: no ROM is left (`reference/MERGE.md`), so the feature goes in as a DRAM unit through
  octabam's loader, as V1.5 did with RELOAD.
- **The ROM detours stay small**:
  - two chord edges, or one inside RELOAD's unit;
  - the phase-G hook;
  - the `FUN_40083bc0` hook;
  - the UI-tick hook;
  - the release hooks, shared with RELOAD's in KYOTI.
- Each splice asserts its stock bytes, as every builder does.

## 7. Test plan

**Emulator (logic only: the harness has no UI tick and no real DSP path).**
- **The landing oracle** (`tools/diag_reflock.py` + `cmp_reflock.py`, DIRECT JUMP's equality
  method). Run A plays pattern 1 and cues our load of T6 from pattern 4 at step k. Run B plays
  pattern 1 and cues a stock change to pattern 2, where pattern 2 = pattern 1 with T6 replaced by
  pattern 4's T6. Every event after the landing must be equal.
  - **The fixture is made on the device** with stock track copy/paste, then exported by the user.
    We never fabricate one.
  - Variants:
    - NORMAL and PER TRACK;
    - CHANGE = OFF / 4 / master;
    - a track faster than the master;
    - INF master;
    - a MIDI track;
    - a cross-bank source;
    - transport stopped.
- **The stress gate** in the shape of `tools/diag_reload3_bankdefer.py`, run in both chord orders
  and with releases in both orders:
  - repeated chord / YES / NO / trig-pick / eviction-by-toast cycles;
  - asserting that the layer list, LED layer list, window slots, `PTN_CONSUMED`, `BANK_SEL` and our
    state all return to baseline every time;
  - asserting that no SELECT window or toast ever appears.
- **Conflict runs**: RELOAD `[BANK]+[TRACK]` and `[PTN]+[TRACK]` still work alone, DJ `[PTN]+[YES]`
  still toggles, REC_TRIG_MUTE still works outside the window.

**Hardware** (FLASHING §4 entry when built). Check each of these and record what was observed, not
a verdict:
- [ ] Both chord orders, both release orders: no SELECT PATTERN, no SELECT BANK, no toast.
- [ ] Each key in §1.2's table does what it says, including PLAY/STOP and mutes passing through.
- [ ] LEDs: full, half and off on known patterns; solid and flashing red; bank/track changes.
- [ ] Landing on time by ear against a metronome, in NORMAL and PER TRACK, CHANGE OFF/4/master.
- [ ] Power-cycle after a load: the sequence survives (SRAM mirror) when the UI bank was the
      destination.
- [ ] A toast or menu opening over the window leaves nothing stuck.

## 8. Phases (each one is a separate flash)

1. **Oracle first, no feature code.** Build the fixture with the user and prove the copy point and
   per-track re-home rule in the emulator (§3.4).
2. **The window**: chord, suppression, list, keys, TRACK follow, with the **stopped-transport load
   only**. Hardware-test the modal behaviour alone, since that is where RELOAD2 failed.
3. **The LED view.**
4. **Cued landing while running**, then trig picks and D2/D3.
5. **KYOTI integration** (DRAM unit, shared RELOAD sites).
6. **Phase 2: names** (§10).

## 9. KB corrections found by this scope

These are to be applied when this thread commits code:
- **Window constructor.** `kb/memory-map.md` gives `FUN_4005829c` as `(x,y,w,h,…)` with a style
  argument. It is **`(w, h, dx, dy, prio, close_cb)`**: centred, and the 5th argument is an
  eviction priority. RELOAD_REDESIGN's "style 4 = card" is that priority.
- **Arrow codes.** The key table's arrows: **UP `0x33`, DOWN `0x20`, LEFT `0x34`, RIGHT `0x21`**.
- **`0x40027e00`** is an undo-kind clear, not a dirty flag (the p-lock store row).
- **"[PTN] does not use a layer"** is wrong: [PTN] pushes `0x400bf0f2`.

---

## 10. Phase 2 — named track sequences (scoped, not designed in detail)

**Where names cannot go.** Nowhere in the bank file.
- The pattern loader requires exact chunk lengths (−51 at `0x4008cf66`), and a 16-bit checksum
  covers every byte (−54 at `0x4008e2b4`).
- The writer `0x4008b278` emits a fixed layout.
- The two candidate gaps are not persisted:
  - the slab tail `+0x8e5c..+0x8ed7` (124 B) is **never serialised**; it is mirrored to SRAM for
    the current bank only, and is stale after a card load;
  - the audio record's `+0x899` pad byte is never written either.
- `project.work` refuses an unknown `[SECTION]` (−51), and stock drops comment lines on save.

**Where they go: a sidecar file in the project folder**, e.g. `tsnames.work` / `tsnames.strd`.
- Stock opens only its fixed names, so stock firmware ignores the file.
- Size: 16 banks × 16 patterns × 16 tracks × 10 B ≈ 40 KB, held in RAM (DRAM reserve).
- Primitives:
  - FOPEN `0x40016864` (modes `"r"` `0x400b3289` / `"w"` `0x400b328b`);
  - FREAD `0x40016564`, **FWRITE `0x400166b8`**, FCLOSE `0x4001677c`;
  - copy `0x40016388`, PROJDIR `0x40025230`.
- **Recommended save semantics: mirror stock's own.** Write `.work` when stock writes the bank
  (hook beside the bank writer `0x4008b278`), and copy to `.strd` when SAVE PROJECT copies
  `.work → .strd`. Names are then exactly as saved as the sequences are, and RELOAD's card reload
  can restore them too.
- **Load**: at project load, beside stock's own bank loads.

**Entry.** In the window, a key on the cursor row (proposal: [FUNC]+[YES]) opens stock's editor
**`FUN_4007e664(maxlen, title, buf, charset, done_cb)`**.
- RENAME PART uses it as `(6, "RENAME PART", buf, 1, 0x4002e944)`.
- Proposal: maxlen 10, charset 1 (upper case + symbols), title `NAME T6 SEQ 4`.
- The editor is priority 5, so our priority-3 list survives under it.
- YES copies into our buffer and calls `done_cb(1)`; NO calls `done_cb(0)`.
- Test `0x460e7612` after the call: the editor returns silently if one is already open.

**What follows the data and what does not.**
- Our own loads copy the name with the sequence (D1: the destination slot becomes a copy).
- Stock pattern copy/paste, track copy/paste, bank operations and SAVE AS NEW (which re-serialises
  from RAM into a new folder) do **not** carry sidecar names unless each is hooked.

**Decisions to take then:**
- name length;
- whether stock track/pattern paste should carry names (more hooks);
- whether SAVE AS NEW copies the sidecar;
- whether MIDI and audio tracks share one name space.

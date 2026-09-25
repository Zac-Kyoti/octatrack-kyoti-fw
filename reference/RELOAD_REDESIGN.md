# RELOAD — redesign spec (Session 85)

**Status: SPEC ONLY, nothing built yet.** Supersedes the RELOAD2 picker design.

## Why redesign

Hardware report #8 (Session 85): "Very inconsistent. hard to understand what is
happening where and when… I think this design has gotten way too convoluted."

That judgement is supported by where the bugs have actually been. Tallying this
thread:

| where | bugs |
|---|---|
| picker / keymap / popup machinery | dead YES/NO hooks while `[PTN]` held; `[PTN]` triple-booked; our poke colliding with DIRECT JUMP's; SELECT BANK flashing under the picker (fixed, then reverted); arrows double-stepping; arrow pairing wrong **twice**; `[YES]` swallowed while `[BANK]` held; picker borrowing other layers → own layer; walk-away leaving the reload primed; `rl_bank_press` snapshot corruption; `rl_draw`'s redraw tripping its own walk-away hook; unbounded `G_SEL`; inconsistent BUSY/arrow behaviour |
| the worker that does the actual reload | **essentially none** — `--trk` has passed consistently throughout |

~13 bugs, all in the modal picker; none in the reload itself. A modal window on
this hardware costs its own keymap layer, a share of stock's single popup slot,
walk-away detection, and redraw-vs-teardown interaction. Every one of those has
bitten us. So: **delete the picker**, execute directly on a chord.

## Two operations (user spec, verbatim intent)

### 1. `[PTN]` + `[TRACK n]` — reload the CF-saved TRACK sequence
- Audio or MIDI track.
- **The Part does not change.**
- Toast: **`TRK SEQ RELOADED`**, 0.5 s or less (OT standard duration).
- **Release of `[PTN]` after this must NOT open the SELECT PATTERN window or its
  countdown.**

### 2. `[BANK]` + `[TRACK n]` — reload the CF-saved TRACK sequence **plus the Part**
- Audio or MIDI track.
- The Part comes **from RAM, not the card**: the saved Part currently associated
  with the active pattern. So if the user opens a project, tweaks the Part, saves
  it (`FUNC`+`PART`, `FUNC`+`EDIT`, SAVE), this restores **the Part they just
  saved**, not the project's card copy — as long as that is still the Part
  associated with the pattern.
- Toast: **`TRK SEQ + PART RELOADED`**, 0.5 s or less.
- Requires reinstating the earlier change: **SELECT BANK executes on `[BANK]`
  RELEASE instead of press.**
- **Release of `[BANK]` after this must NOT open the SELECT BANK window or its
  countdown.**

Deferred, explicitly: all-tracks (whole pattern) and whole-bank reloads. "Let's
start with just this."

## What carries over

- **The whole-bank suppression — the main win, keep it.** `rl_done` @ `0x40023c62`
  plus the `FUN_4000faf0` live-cache refresh cut a reload from **6852 buffered
  card reads to 354** (parses 17 → 1). Hardware-confirmed: the ~1 s stall is
  better and stock `[BANK]` single-press survives.
- `rl_job` — the worker and its per-track slice logic. `--trk` has always passed.
- `rl_arm_trk` — already the per-track arm entry point, and the handoff had
  already flagged it as the entry for exactly this `+[TRACK]` power move.

## What gets deleted

`rl_draw`, `rl_menu_tbl`, the three item strings, `G_MENU`, `G_SEL`, `rl_arr_a`,
`rl_arr_b`, the picker's own keymap layer and all its records, `rl_push_layer`,
`rl_pop_layer`, `rl_lay_*`, `rl_closecb_hook`, `rl_redraw`, `rl_busy_seen`, the
`rl_bank_press` snapshot/delegate guard, and the whole "sticky popup shares
stock's single slot" problem. ~10 detours → ~4.

## Mechanism notes (measured, do not re-derive)

- **Per-key is-held array**: `0x46c7d8ee`, 24-byte stride. `patch_reload2.s`
  already pins this — `BANK_HELD_FLAG 0x46c7dd56 = 0x46c7d8ee + 0x2f*24`. So
  PTN (`0x2e`) held-flag = **`0x46c7dd3e`**. Both chords are a byte test.
- **Dispatch table**: `0x46c7d8de`, 24-byte stride, handler at +0. Button families
  share one handler (all 16 trigs → `0x40060ce0`), which is how the TRACK family
  is identified rather than guessed. See `tools/diag_keymap_dump.py`.
- **The Part primitive for #2 is `FUN_40009094(part, pattern)`** — measured to read
  the **per-Part SAVED copy** (`0x40170f70 + part*0x9b340 + pattern*0x18b2`), not
  the live one. That is exactly "the Part as last saved, from RAM", which is what
  the spec asks for. Already called on the old PART+PTN path.
- `[PTN]` opens SELECT PATTERN on **release**; `[BANK]` opens SELECT BANK on
  **press**. Asymmetric — the suppressions in #1 and #2 are therefore different
  problems, not one shared one.

## Chord availability — MEASURED (tools/diag_keymap_dump.py, Session 85)

Live dispatch table `0x46c7d8de`, 24-B stride; button families share a handler.

- **TRACK buttons = keycodes `0x10..0x17`**, family of 8, handler `0x40040250`.
- **Trigs = `0x00..0x0f`**, family of 16, handler `0x40060ce0`.
- Held-flag array `0x46c7d8ee` (24-B stride) validated: BANK computes to
  `0x46c7dd56`, exactly what `patch_reload2.s` already pins. **PTN held-flag =
  `0x46c7dd3e`.**

**`[BANK]`+`[TRACK]` is FREE.** The `[BANK]` overlay (`0x400cff34`) overrides only
trigs `0x00..0x0f` (bank select), NO (`0x32`), and YES (`0x31`, press = NULL — the
dead slot). Track keys are not in it, so they fall through to the base handler.

**`[PTN]`+`[TRACK]` is overridden in stock** — the `[PTN]` overlay maps all eight
track keys to `0x40083dc4`, which converts keycode → track index (`addil #-16`)
and calls `0x4007d5f8(track)` behind two gates. **But the user confirms on
hardware that `[PTN]`+`[TRACK]` does nothing observable**, so overriding it is
agreed. (Releasing `[PTN]` afterwards still raises SELECT PATTERN, as stock does
— that is the part spec #1 must suppress.)

## The Part half of #2 — STOCK ALREADY DOES ALL OF IT (measured, Session 85)

The user described stock's behaviour exactly: a never-saved Part toasts
**`SAVE PART FIRST!`** on a reload attempt; once saved, that never reappears —
dirty reloads to the saved version with a `PART %d RELOADED` toast, clean does
nothing at all. So do not reimplement any of it. Stock's Part RELOAD lives at
`0x4005e042` and decodes as:

```
4005e042:  movel #0x95048,%d0          ; DIRTY_BLOB_OFF (same constant patch_partreapply.s pins)
4005e048:  moveal 0x46c82456,%a0       ; BLOB_PTR
4005e04e:  mvzb  %a0@(0,%d0:l),%d0     ; the PERSISTED per-Part dirty bitmask
4005e052:  btst  %d1,%d0               ; d1 = part index
4005e054:  beqw  0x4005e0e2            ; bit CLEAR -> bail, do nothing, no toast
4005e058:  movel %d1,%sp@-
4005e05a:  jsr   0x4004aab4            ; <-- THE PART RELOAD
4005e070:  tstl  %d0                   ; its RETURN VALUE
4005e072:  beqs  0x4005e090            ;   0  -> "SAVE PART FIRST!"  (never saved)
4005e080:  pea   0x400b41aa            ;  !0  -> "PART %d RELOADED"
4005e0a4:  jsr   0x4005a2b8            ; TOAST(buf, 0x18)
```

**Three things fall out of this, all of which the redesign should use:**

1. **`FUN_40049aab4`… i.e. `0x4004aab4(part)` is the whole operation**, and it
   **returns the never-saved answer itself**: `0` = never saved (stock then says
   `SAVE PART FIRST!`), non-zero = reloaded. So the "handle it gracefully" case
   needs no detection logic of ours at all — call it and branch on `d0`.
   Note `PARTRELD_FN = 0x4004aab4` is ALREADY pinned in `tools/emu_reload.py`, and
   the RELOAD2 suite asserts it is called **zero** times. The redesign inverts
   that expectation: #2 must call it exactly once.
2. **Stock gates the whole thing on the persisted dirty bit** (`blob + 0x95048`,
   bit = part index): clear → do nothing, no toast. That is the user's "clean
   (nothing happens, no toast)". Mirror it, or simply let `0x4004aab4` be the
   single source of truth.
3. **Toast duration is `0x18` (24)**, not the `0x44` (68) the RELOAD2 code uses.
   That answers "0.5 s or less / whatever is OT standard" — `0x18` IS the OT
   standard for this family of messages. Use it.

Relevant strings, for toasts that should read like stock:
`0x400b4190` `PARTS SAVED` · `0x400b419c` `PART %d SAVED` ·
`0x400b41aa` `PART %d RELOADED` · `0x400b41bb` `SAVE PART FIRST!`

## Unsaved-Part handling — RESOLVED by the above

If `[BANK]`+`[TRACK]` runs while the pattern's Part has **unsaved edits**,
applying the saved Part silently discards them — and Part edits are not covered
by the sequencer's UNDO.

**Detection is already solved**: the PARTREAPPLY thread (hardware-confirmed,
closed) pins `PART_DIRTY_RAM = 0x100b145e`, a per-Part edited/unsaved bitmask
(persisted copy at `blob + 0x95048`). A single bit test.

**My first recommendation here was WRONG and the user corrected it.** I had
conflated "dirty" with "never saved" and proposed skipping the Part when dirty.
The user's actual requirement: **a saved Part SHOULD replace a dirty Part** —
that is the entire point of the operation. The only special case is a Part that
has **never been saved**, which must execute gracefully: no change to the Part,
slightly different toast.

**Resolved policy**, using stock's own semantics via `0x4004aab4`:
- Part never saved → it returns 0 → leave the Part alone, toast that says so
  (stock's own wording is `SAVE PART FIRST!`).
- Part dirty → it reloads to the saved version → toast `TRK SEQ + PART RELOADED`.
- Part clean → nothing to do (stock's own gate on the persisted dirty bit).

No dirty-flag logic of our own, no two-press confirm, no new detection. The
sequence reload happens either way; only the Part half varies.

## ⚠️ Known-hard piece: deferring SELECT BANK to release

Spec item #2 needs this, and **it has been tried once and failed on hardware.**
Session 80 continued (3) implemented it (`rl_bank_press` suppressing the
`jsr FUN_40059f8c` and reserving the 4 arg slots the tail's `lea 28(sp),sp`
reclaims, plus `rl_bank_rel` picking one of three routes). Session 80 continued
(7) **reverted it**: on hardware `[BANK]` "stuck on (overlay never torn down) and
off (window never drawn)".

What was measured and still stands: `0x4007b408` is the **window's** `onClose`,
and **the window owns the keymap layer** — press shows the window *then* pushes
the layer; release calls nothing and leaves it live; calling `0x4007b408` directly
pops it and restores the YES slot. So the window cannot merely be suppressed:
**exactly one teardown must run on every path.** That is what the earlier attempt
got wrong.

**User's position (Session 85), and it is reasonable**: that failure happened in
a build that also carried the picker, its own keymap layer, the YES-slot pokes
and the snapshot guard — far more machinery to interact with. In a build with
none of that, the change should be tractable.

Plan: implement it minimally, keep everything else on `[BANK]` stock, and gate it
with a test of the `tools/diag_bank_window.py --stress` shape — repeated `[BANK]`
taps AND reload chords, asserting layer depth, the BANK dispatch slot and the
window handle all return to baseline every time.

**Fallback if it misbehaves again**: leave `[BANK]` press fully stock, let SELECT
BANK open, and *dismiss* it from the reload path by calling its own `onClose`
`0x4007b408` (measured to pop the layer it owns and restore the YES slot), plus
`clr.l BANK_COMMIT` to route release down the dismiss path (hardware-confirmed in
Session 80 continued (3)). Cosmetically worse — the window flashes on press — but
far less invasive.

## Open question carried forward

**The root cause of the stuck `G_KIND` is still unknown.** Killed by measurement:
playback clobber, `RELOAD_NOW`, storage-task contention as a sole explanation
(suppression cut reads 95% and BUSY persisted), and trig-sequence editing
(`tools/diag_seq_edit_io.py`, with a real edit-liveness gate). Still untested: a
post lost in `FUN_40022778`'s single scratch message buffer (`0x460bd912`), edit
types the harness cannot yet drive, and the storage task under real CF streaming
(which no harness here can model).

With the picker gone there is no modal state to wedge, and the intended policy is
**last-request-wins** rather than a BUSY refusal: overwrite the request and
re-post. Both posts are the same job type and bank mask, so a double post is
benign, the user never sees BUSY, and a second press always retries instead of
being refused. This does not fix a lost post — it makes one harmless.

## Implementation plan — both detour sites measured (Session 85)

**Calling convention, confirmed at both sites**: `handler(keycode @ sp+4,
event @ sp+8)`. Both handlers open with `movel %d2,%sp@-`, after which the
keycode is at `sp@(8)` and the event at `sp@(12)` — which is how each derives its
own track index. Event `1` = press. Track index = keycode − `0x10`.

### Detour A — `[PTN]` + `[TRACK]` → `0x40083dc4`

**Reachable ONLY via this chord.** All 8 references to `0x40083dc4` are exactly
the 8 `[PTN]`-overlay track slots (`0x400bf124` … `0x400bf1da`), so arriving here
*is* the gesture — **no held-flag test needed at all.**

Displaced prologue is exactly 6 bytes, so a 6-byte `jmp` fits with no padding:

```
40083dc4:  2f02            movel %d2,%sp@-        ; 2 B
40083dc6:  242f 0008       movel %sp@(8),%d2      ; 4 B   -> resume at 0x40083dca
```

Behaviour: on press, arm a TRK SEQ reload for `keycode-0x10`, mark PTN-release
suppression, toast `TRK SEQ RELOADED` (duration `0x18`), and swallow. On any
other event, replay the two displaced instructions and `jmp 0x40083dca`.

### Detour B — `[BANK]` + `[TRACK]` → `0x40040250`

`[BANK]` does **not** override track keys, so the chord lands on the ordinary base
track handler. Same 6-byte prologue shape, same fit:

```
40040250:  2f02            movel %d2,%sp@-        ; 2 B
40040252:  222f 0008       movel %sp@(8),%d1      ; 4 B   -> resume at 0x40040256
```

Behaviour: test the BANK held-flag `0x46c7dd56`. Not held → replay displaced and
`jmp 0x40040256` (ordinary track select, untouched). Held + press → arm TRK SEQ
for `keycode-0x10`, then `jsr 0x4004aab4(part)` for the Part half and branch on
its return (`0` → `SAVE PART FIRST!`, else `TRK SEQ + PART RELOADED`), mark
BANK-release suppression, swallow.

**Note the asymmetry and why it is good**: A needs no held test because the PTN
overlay routes the chord to a private handler; B needs one because BANK leaves
track keys on the base handler. Neither requires poking a keymap layer record —
the mechanism that caused the DIRECT JUMP collision and several routing bugs in
the picker era.

### Still to design

- **PTN-release suppression** (stock opens SELECT PATTERN on *release*).
- **BANK press→release deferral + suppression** — the known-hard piece, built last
  and separately, behind the `--stress`-shaped gate.
- Reuse unchanged: `rl_job`'s TRK SEQ slice path, `rl_arm_trk`, and the whole-bank
  suppression (`rl_done` + the `FUN_4000faf0` live refresh).
- Toast duration `0x18`, not RELOAD2's `0x44`.

---

# Session 86 — hardware report #9, and the clock finding

First RELOAD3 flash: **both chords execute, no conflicts.** The chord design is
confirmed on hardware. Three follow-ups, all now built.

## Item 3 (the real bug) — a reload must not re-home the transport

`rl_job` armed `RELOAD_NOW` (`0x46c8028a`) whenever the reloaded pattern was the
active one and the transport was running. That flag is polled once per step at
`0x400a2530`, and **the block it gates is stock's whole-bank re-home, which is
positional, not a cache refresh**:

| site | write | effect |
|---|---|---|
| `0x400a26fe` | `0x800065b4 = 0` | previous master step |
| `0x400a2704` | **`0x800065b2 = 0`** | **master playhead → the sequence restarts** |
| `0x400a2658` | `0x800065b6 = LEN_TBL[..]-1` | ticks-within-step → wraps next tick |
| `0x400a27e2` | `0x800065b8 = 1` | `RUNNING` — the old "reload while stopped starts playback" bug, same block |

`0x800065b2` is DIRECT JUMP's `MASTER_STEP` / `BAR_CTR`, measured there as the
bounded master playhead; the metronome's beat flags are derived from it by masking
against `0x400abae4` / `0x400abacc` (`0x400a4264..0x400a42a0`). **One write, both
reported symptoms.**

Dropping the arm costs nothing, measured rather than assumed:

- **trig data** — the worker writes the cold blob and `LIVE_REFRESH` copies
  blob → live cache, so both consumers see the new bytes already.
- **per-track scale/length** — stock re-reads it from the blob on *every wrap*
  (`0x400a3d08  moveb %a2@(1),%a3@` → `TRK_SCALE_IX[t]`), so a changed step count
  self-heals within one cycle, in time.

`RELOAD_NOW` is therefore armed on **no path**, and the `ACT_PAT`/`RUNNING` gates go
with it. Harness: `tools/diag_reload3_timing.py`.

> **Naming trap.** `diag_reload2_transport.py` called `0x800065b6` "MASTER_STEP".
> Wrong, and corrected there in Session 86: `0x800065b6` is ticks-within-step,
> `0x800065b2` is the playhead. A timing test on `0x800065b6` measures the wrong word.

## Item 2 — the known-hard piece, now attempted with the state machine decoded

The section above ("⚠️ Known-hard piece") can be read alongside this. What made the
retry tractable is that the whole machine is now measured:

- `0x4007af80` **press** — `BANK_COMMIT = (0x460e73bc == 0)`, i.e. a **toggle**, then
  `bras 0x4007af30`.
- `0x4007af30` — a **shared tail**, reached from that `bras` and **nothing else in the
  image**. Clears `BANK_SEL`/`0x460e73b8`/`0x460e73bc`, `SHOW_WIN` (dur `0xf0`,
  onClose `0x4007b408`), `LAYER_PUSH`, two more UI calls, then `lea 28(sp),sp ; rts`.
- `0x4007b3e0` **release** — `BANK_SEL==2` or `BANK_COMMIT==0` → dismiss
  (`0x40056a70`); else commit (`0x460e73bc=1`, then `0x40031200`, which is merely
  `0x460d1e4c=1` — a popup **confirm** flag, *not* a bank change). That commit is what
  makes the window sticky after release.

So: press shows, release sticks, next tap dismisses. **Time-shifting only the show
preserves that exactly**, and two measured facts make it safe rather than hopeful:

- `LAYER_PUSH` (`0x40031494`) is **idempotent** — `rts` if the struct is already the
  head (`0x400314b4`) or anywhere in the list (`0x400314b8`). Replay cannot double-link.
- `LAYER_POP` (`0x4003146c`) finds nothing if the struct was never linked, so a
  teardown for a window that never opened is harmless.

Implementation: a **one-shot gate** spliced into the tail at `0x4007af42` (a press
returns without showing) plus the release handler at `0x4007b3e0`, which opens the
gate for one pass and calls **stock's own tail** — so the window, its duration and its
teardown are all stock's, one event later. The gate is what makes replay possible:
without it, calling the tail would hit our own detour and short-circuit.

The chord claims the release outright (`rl3_bank_used`), so `[BANK]`+`[TRACK]` shows
nothing on either event, and `BANK_WIN_CLOSE` is now **conditional** on a popup being
up (normally there is none; MLNOTIFY bails while `0x460e5cd0` is non-zero).

### The trap: the overlay layer, not just the window

Deferring the show by skipping stock's whole press tail is **wrong**. `LAYER_PUSH`
lives in that tail, and the `[BANK]` overlay is what remaps the 16 TRIG keys to
bank-select while `[BANK]` is held — the "hold `[BANK]`, tap a trig" gesture. Skip it
and the trigs stay on base handler `0x40060ce0`, so that gesture would **edit the
sequence instead of changing bank**. Silent and destructive, and invisible to any
"did the window appear?" test. Very likely why Session 80's attempt was rejected.

Correct shape (and it is stock `[PTN]`'s own): **push the layer on the press, defer
only `SHOW_WIN`.** Teardown then has to be accounted for on every release path, since
stock's layer is owned by the window's onClose:

| release path | teardown |
|---|---|
| chord consumed (`rl3_bank_used`) | `BANK_WIN_CLOSE` (no window ever existed) |
| opening tap (`BANK_COMMIT != 0`) | show the window; it owns the layer from there |
| toggle-off, popup up | stock's dismiss runs onClose |
| toggle-off, no popup | `BANK_WIN_CLOSE` |

`BANK_WIN_CLOSE` is the right teardown rather than a bare `LAYER_POP` because it also
balances the press tail's `0x4007e760` with its own `0x4007e81c`.

### It is stock `[PTN]`'s own release, transplanted

Stock's `[PTN]` release (`0x4005a084..0x4005a0ca`) already does both things this needs:

```
tstl 0x460d173e      ; consumed?
bnes -> 0x4005a0be   ;   yes: clrl PTN_MODE ; jsr 0x40043418  <- teardown called
                     ;        DIRECTLY, and no window is shown
pea  0x40043418      ;   no:  teardown as the window's onClose
jsr  0x40059f8c      ;        SHOW_WIN -- the window opens on the RELEASE
```

The show lives on the release, and the consumed path calls the teardown itself rather
than relying on a window that was never opened. Every `rl3_bank_rel` branch is that
same structure with `BANK_WIN_CLOSE` substituted — which is why "like PTN does" was
the right instinct: the mechanism was already in the firmware.

**This still deserves suspicion**: Session 80 continued (3)/(7) tried a deferral and
hardware rejected it. The difference is that that build also carried the picker, its
own keymap layer and a poked YES slot; here the only moving part is the show. That is
a reason to retry, not evidence of success. Harness:
`tools/diag_reload3_bankdefer.py` — press shows zero, release shows exactly once (its
own positive control), the layer list never grows across repeated taps, the toggle
still toggles, the chord is silent.

## Item 1 — two-line box

`MLNOTIFY` was already wired for the never-saved case, so the saved case joins it:
`TRK SEQ + PART` / `RELOADED`, which also restores the spaces around the `+` that the
21-char single-line budget had forced out.

## Status

Six detours (was four), `patch_reload3` 1454 B @ `0x400d6500` of a 2044 B ceiling.
Session 85's deferred boundary checks closed green: tracks 1 and 8 each revert only
themselves, so `subi.l #0x10` is right at both ends of the range.

> **Harness note.** `er.stage_project` stages into one shared
> `out/_emu_rtos_tree/<set>/<project>`, so parallel RELOAD3 diags race and one dies in
> `mkdir`. Run the suite sequentially.

---

# Session 88 — the message box: titled card, centred, self-dismissing, no dots

Hardware report #10, after the Session 86 flash confirmed reloads happen "quick and
on-time" (item 3 verified on hardware). Four asks, all about presentation:

1. title `RELOAD FROM PROJ`, not `RELOAD`
2. the second line **centred**, not left-justified
3. **no "OK" prompt** — a ~0.5 s self-dismiss is enough
4. the plain `TRK SEQ` message should use the same card, not the big block toast

…then, on seeing the first cut: **no countdown dots anywhere** — "these are instantly
executed functions", so a progress indicator is semantically wrong.

## MLNOTIFY cannot do any of it, and one of my own notes was wrong

`FUN_4006d57c` is a **blocking dialog by construction**:

- it **pushes keymap layer `0x400cdff8`** (`0x4006d722`). That push *is* the OK prompt —
  the box waits for a key because it installed a key handler.
- it has **no duration argument at all**.
- its body renderer `0x4006d128` draws every line with **x hardcoded to 4**
  (`0x4006d170`) — exactly the left-justification reported.

> ⚠️ **A prior comment in `patch_reload3.s` claimed `0x460e5e20` was "a 40-frame
> countdown at 0x460e5e20, so it goes away on its own". That was WRONG**, and the
> hardware report is what exposed it. `0x460e5e20` is the box **WIDTH** accumulator:
> seeded to 40 at `0x4006d596`, max'd against each measured line width + 9, capped at
> 128. `0x460e5e24` is the height, `7*nlines + 27` clamped to `[34,64]`. The box never
> self-dismissed; nobody had tested it without pressing OK.

## The build: our own card on the other popup slot

`rl3_card(title, nlines, lines[])` uses the same primitives MLNOTIFY does, but on the
popup slot `SHOW_WIN` owns (`0x460d1e5c`) — that slot already has stock's countdown and
**never pushes a keymap layer**, so there is no OK prompt to answer by construction.

| piece | call | note |
|---|---|---|
| create | `0x4005829c(w,h,0,0,**4**,0x40056a70)` | style **4** = the card look; `0xa` is the block toast |
| clear | `0x400356a8(winptr)` | as MLNOTIFY does |
| title | `0x40057c84(handle, text, 0)` | the title bar |
| lines | `0x40012bd8(font, winptr, **x**, y, -1, text)` | **x = (boxwidth − textwidth)/2** instead of 4 → centred |
| dismiss | `CD_CUR`/`CD_RELOAD` = `0x18`, `CD_SEGS` = **1**, `CD_FLAG` = **1** | stock's own timer |

Width/height formulas, body font (`0x400ba876`) and the 7-pixel line pitch are copied
from MLNOTIFY so the box keeps proportions already approved on hardware. y counts **up**
from the bottom, so `lines[0]` (higher y) lands on top, matching MLNOTIFY's ordering.

## No dots — and why CD_SEGS = 1 is the mechanism

The dots come only from `0x40037cc8`, which has exactly two reachable callers: SHOW_WIN's
tail (unused here) and the tick at `0x40056aea`. That tick reaches it **only while
`CD_SEGS` is still non-zero after being decremented** (`0x40056ae2 bne`). So with
`CD_SEGS = 1` the single segment expires straight into the dismiss at `0x40056ae4` and
the dot routine is never entered. `CD_CUR` therefore carries the whole duration rather
than a quarter. Verified: **zero references to `0x40037cc8` in the blob.**

## ⚠️ The bug the emulator could not have caught

The tick is **gated on `CD_FLAG`**:

```
40056ab8  tstl 0x460d1e4c      ; CD_FLAG
40056abe  beqs 0x40056afc      ; ZERO -> return; the countdown NEVER runs
40056ac0  ...tick body...
```

An earlier version of `rl3_card` **cleared** `CD_FLAG`. On hardware that card would have
sat there forever needing a keypress — reproducing the exact stuck box this change
exists to remove. Static reading of the gate found it; the emulator could not, because
**it does not drive the popup tick at all.**

## Harness honesty: the self-dismiss is UNMEASURABLE here

`diag_reload3_card.py` first reported "the card NEVER dismissed on its own". That was a
**false failure**. A stock control settles it: tapping `[BANK]` opens stock's own
SELECT BANK countdown window, and **it does not count down in this harness either** —
`CD_TICK` fires zero times for both. So the tool now runs that control and reports
UNMEASURABLE rather than failing, and says explicitly that this is **not evidence of
success either**.

Two further traps this tool hit, recorded so they are not repeated:
- hook the gate `0x40056ab8`, **not** `0x40056ac0` — the latter is past the gate, so it
  cannot distinguish "tick never ran" from "gate sent it home".
- the `DRAWTEXT` hook is global: it also sees the status bar (y=1) and stock's title
  draw (x=4). Filter to the **cave address range**; `min/max` over all ELF symbols spans
  the whole address map (they include absolute equates like `0x80006a55`) and filters
  nothing.
- do not assume line 1 is the longer line. It is for `TRK SEQ + PART`/`RELOADED` but not
  for `TRK SEQ`/`RELOADED`, and hardcoding it produced a false centring failure.

## Verified in the emulator (both chords)

Measured from the real draw calls:

```
BANK: 'TRK SEQ + PART' (x=9)   'RELOADED' (x=19)    box width 70
PTN:  'TRK SEQ' (x=22)         'RELOADED' (x=19)    box width 70
```

The longer line sits further left in **both** directions — which is what makes it real
centring rather than a coincidence of one card's line lengths. Also: MLNOTIFY never
called, OK layer never pushed, dot routine never entered, block toast gone from the PTN
path, `CD_FLAG` non-zero, and a **second reload draws immediately** (the old dialog
blocked that until OK was pressed).

**Needs hardware:** the self-dismiss actually firing, and the visual layout (spacing,
title rendering, whether `TRK SEQ` / `RELOADED` reads better than one line). Cave is at
1870 B of the 2044 B ceiling — 174 B headroom.

# Session 92 — hardware report #14: the pattern-pick toast, and a mismatched bank

Two items, both from one flash of `f497786`.

## Item 1 — a pick during the hold must cancel the release show

> "when holding bank > select a bank trig > select a pattern trig > release bank, the
> 'select bank' toast with countdown appears. I don't want this — selecting a pattern
> should disable the on-release bank behavior."

**Root cause: we inverted stock's own test order.** Stock's `[BANK]` release
(`0x4007b3e0`) opens with `cmpl 0x460e73c6,#2 ; beq -> DISMISS` *before* it looks at
`BANK_COMMIT`. Session 86's release handler tested `BANK_COMMIT` first, so it never
reached the question "was something already picked?".

`0x460e73c6` (`BANK_SEL`) is that gesture's progress counter, measured at the
`[BANK]`-overlay trig handler `0x4007b2fc`:

| value | meaning | set at |
|---|---|---|
| 0 | nothing picked yet | the show tail `0x4007af30` clears it on every press |
| 1 | a BANK was picked | `0x4007b276`, with `BANK_COMMIT=1` at `0x4007b33c` and a "SELECT PATTERN IN BANK x" window of its own (`SHOW_WIN` at `0x4007b2b0`, onClose `0x4007b408`) |
| 2 | a PATTERN was picked | `0x4007b3d2`, end of the pattern branch |

`BANK_SEL == 2` cannot be reached without passing through 1 (`0x4007b304` gates the
pattern branch on `BANK_SEL != 0`), so a pick always means a window is up.

**The fix is one test, and both non-zero values then want stock's own tail:**

* `2` → our displaced compare succeeds, `BANK_REL_RES`'s `beq` takes DISMISS
  (`0x40056a70`), which closes the pick's window and runs *its* onClose `0x4007b408` —
  the same teardown, so the overlay pops exactly once.
* `1` → falls past the compare to stock's `BANK_COMMIT` test, which sets the sticky flag
  and keeps the overlay live so a pattern can still be picked after release. Stock's
  untimed window, unchanged.

This also closes an **un-reported** half: releasing after picking only a bank would have
drawn SELECT BANK over "SELECT PATTERN IN BANK x".

Layer arithmetic is undisturbed: our silent press pushes `0x400cff14` once, the trig
handler pushes it again (`LAYER_PUSH` is idempotent — stock itself double-pushes here),
and one teardown pops. Same for `BANK_UI_A` / `0x4007e81c`.

## Item 2 — the reload was aimed with a MISMATCHED (bank, pattern) pair

> "parts always reload well. However, the sequence data does not always reload reliably.
> Most of the time it does. Occasionally the toast will show 'reloaded', but the sequence
> is not actually restored."

**There are two "current bank" variables and we used the wrong one.** The worker took the
PATTERN from `ACT_PAT` (`0x800065be`) but the BANK from `CUR_BANK` (`0x80000002`), in four
places: the `.strd` filename (`rl_openstrd`), the cold-blob slab pointer (`rlj_ours`), the
Part apply (`rlj_faithful`) and `LIVE_REFRESH` (`rlj_setflag`).

`ACT_PAT`'s actual partner is `0x800065bd`. **All three of its writers set it in the same
breath as `ACT_PAT`:**

```
0x400a05f6   the direct goto        65bd=bank, 65be=pattern, + the queued mirrors
0x400a40aa   the boundary latch     gated on BOTH queued values being != -1
0x400a44dc   the second latch site  identically gated
```

So `(0x800065bd, 0x800065be)` always describes **one** pattern — the one being played —
and both move only when the sequencer says so. `CUR_BANK` has no such pairing: it is
written at `0x400622b8` (a UI path, alongside `LIVE_REFRESH` and the cached blob base
`0x46c82456`) and at `0x40087d26` (clamped 0..15, project load). Neither writer is in the
performance bank-change path (`0x4007b37c → 0x400a1030`).

Pair them wrongly and the worker reads one bank's `.strd`, rewrites that bank's slab,
refreshes that bank's live cache, sets `rl_own`, and our toast says RELOADED — while the
sequencer keeps reading a slab nobody touched. **Intermittent exactly as reported:
harmless while you stay in one bank, wrong right after you leave it.** The user's own
report #14 item 1 shows they were performing bank+pattern picks in the same session.

Fix: `PLAY_BANK = 0x800065bd` at all four targeting sites. `CUR_BANK` is left defined but
unused, with the reasoning in a comment, so a future site cannot reach for it by habit.

### MEASURED, and the fix verified by A/B

`tools/diag_reload3_bankvar.py` settles the mechanism. It creates divergence directly
(CUR_BANK poked to 2, PLAY_BANK left at 0) and reports which slab the worker writes:

| build | BLOB writes | verdict |
|---|---|---|
| before the fix | `((2,0), 2332)` | follows **CUR_BANK** -- a slab the sequencer is NOT reading |
| after the fix  | `((0,0), 2330)` | follows **PLAY_BANK** -- the slab the sequencer reads |

Same test, same divergence, opposite result -- and it still wrote ~2.3 KB either way, so
the fix cannot have passed by breaking the reload. That is report #14 item 1's symptom
reproduced on demand: the `.strd` is read, a slab is rewritten, LIVE_REFRESH runs, the
toast says RELOADED, and not one byte of what the user hears changed.

** What is NOT proven: that hardware ever reaches the divergent state. ** The divergence
here is POKED, because reaching it honestly needs a queued bank change to survive to a
pattern boundary, and at 121-143x slower than realtime that is ~30 min of wall clock per
run. `tools/diag_reload3_whichbank.py` does it the honest way -- drives a real bank change
through the per-key dispatcher and waits for the latch -- and has never completed; it is
kept because its gates are right, including the one that caught its own first version
concluding "CUR_BANK tracked the change" while blind.

So this is a real defect that produces exactly the reported symptom, NOT yet a proof that
it is THE cause of the intermittent failures. If hardware rarely diverges, the fix is
harmless and the next suspect is storage-task contention while audio streams off the card
-- the standing unsolved question in this thread, which no harness here can model.

The fix stands on its own regardless: taking the bank from CUR_BANK and the pattern from
ACT_PAT is incoherent by construction, and the worker already trusts ACT_PAT, so trusting
ACT_PAT's own partner is strictly more correct.

Regression-checked on the fixed build: `diag_reload3_toast.py` (the `[BANK]`+`[TRACK]`
chord, the path carrying the changed `PARTAPPLY` site) and `diag_reload3_bankpick.py`
(item 2) both pass.

## A latent hazard found on the way, NOT yet fixed

`SCRATCH` (`0x460aff60`) is `OPEN_BUF + 0x7000`, and `OPEN_BUF` (`0x460a8f60`) is a
**stock** buffer. All 14 stock users of it pass size `0x10000` (e.g. `0x4008fbde`,
`0x400916d4`), so our 0x8ed8-byte pattern scratch sits 28 KB **inside** stock's own 64 KB
read window. Our source asserts it is "idle while we hold the task"; that is an
assumption, not a measurement, and this session did not settle it — the diag reports which
PCs write there during the job but cannot prove absence under real card contention. Worth
resolving before the next feature leans on that region.


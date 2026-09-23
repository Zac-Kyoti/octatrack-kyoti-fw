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

**Correction worth recording**: the live arrow handlers in the default context
are `0x40081610` (UP `0x33` + DOWN `0x20`) and `0x40081798` (L/R `0x21`/`0x34`) —
NOT the `0x4004b970` / `0x400491a0` that `patch_reload2.s` detours. Those belong
to some other layer/context. This mismatch is a plausible contributor to the
inconsistent arrow behaviour in hardware report #8, and it is moot in the
redesign (no arrows involved).

## Unsaved-Part handling (spec gap, user invited suggestions)

If `[BANK]`+`[TRACK]` runs while the pattern's Part has **unsaved edits**,
applying the saved Part silently discards them — and Part edits are not covered
by the sequencer's UNDO.

**Detection is already solved**: the PARTREAPPLY thread (hardware-confirmed,
closed) pins `PART_DIRTY_RAM = 0x100b145e`, a per-Part edited/unsaved bitmask
(persisted copy at `blob + 0x95048`). A single bit test.

**Recommended policy**: if the active Part is dirty, **reload the sequence and
SKIP the Part**, with a distinct toast (`TRK SEQ RELOADED / PART UNSAVED`).
Rationale: one predictable behaviour per state, clearly announced, and never
destroys unsaved work. Explicitly NOT a two-press confirm idiom — conditional
multi-press behaviour is what made the old design "hard to understand what is
happening where and when" (hardware report #8). A force-override can be added
later if wanted.

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

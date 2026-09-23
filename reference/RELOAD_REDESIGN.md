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

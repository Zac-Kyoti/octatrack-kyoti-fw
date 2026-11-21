# BATCH_BUGFIXES

Three fixes to **stock** Octatrack OS 1.40C behaviour, as one module. Nothing here
adds a feature, changes a menu, or touches a setting — each one only makes the stock
instrument do what it already meant to do.

| # | fix | size | sites |
|---|---|---|---|
| 1 | MIDI Plays-Free trig (`MIDI_PLAYS_FREE_FIX`) | 62 B | `0x4009b6f2` (18-byte splice) |
| 2 | Empty-pattern LED (`EMPTY_PATTERN_LED_FIX`) | 318 B | `0x4009a464` |
| 3 | Part-change carryover (`PART_CHANGE_CARRYOVER_FIX`) | 402 B | `0x40062216` + `0x400621da` |

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the declaration — three independent caves |
| `patch_trigscale.s` | bug 1 |
| `patch_pattern_led.s` | bug 2 |
| `patch_partreapply.s` | bug 3 |

In this repo the three ship together: `tools/build_batch_bugfixes.py` builds them alone, and
`tools/feature_image.py` composes all three onto every feature image, asserting on every run that the composite's changes are the
disjoint union of the feature's and the fixes' own.

## The three fixes

**Bug 1 — MIDI Plays-Free trig.** A Plays-Free MIDI track with trig quantize *Direct*
and pattern scale *Per Track* stalled after its first step on a manual trig.
Hardware-confirmed 2026-08-28.

**Bug 2 — Empty-pattern LED.** A pattern whose only content is parameter locks — on a
MIDI track, or trigless locks on an audio track, with no trig anywhere — showed as an
unused slot, its grid LED unlit under `[PTN]`. The fix runs stock's own trig test first.
When that says "empty":

- under `[PTN]` (and the chain view) it scans the lock arrays for any locked value;
- under `[BANK]` — whose grid asks about the patterns of all 16 banks on every LED refresh,
  where a full scan starved the CPU (2026-09-30) — it reads only the trigless-lock step masks
  stock skips (audio and MIDI `+0x10`) and, for each step set there, that step's 32 lock
  bytes: a bank holding a pattern with a trigless lock that carries a locked parameter lights.
  At most 16 such steps are checked per pattern; past that the pattern reads as stock reads it.

A trigless lock with nothing locked lights neither grid. Lock values on a step with no trig
and no trigless-lock flag (a project edited off the unit can hold them) light `[PTN]` only. Measured in the
emulator with the sequencer playing and `[BANK]` held: ~0.5 % more ColdFire work than the
`[BANK]` grid without this check on a real project; ~2.3 % in a contrived worst case where
every pattern of every bank is nothing but empty trigless locks (less than holding `[PTN]` on
that same project costs today).

**Bug 3 — Part-change carryover.** After a pattern-triggered Part change, stale
per-track state from the old Part leaked into the new one. Reported on Elektronauts
("Playback gets carried over…"). Two reproducible cases are fixed: a track leaving
PICKUP for FLEX kept playing the old Part's pickup loop, and a pattern switch into a
PICKUP track marked that Part edited/unsaved when nothing had changed.

### Bug 3's root cause

The `sys` task's "select Part P" handler at `0x400621a6` — the site a real
pattern→Part change reaches — calls `FUN_400972fc(newPart, track, oldType)` once per
track. For `oldType==4` (PICKUP) and `newType!=4` that function takes a fast-path
branch that does **nothing**: no slot rebind, no voice re-trigger.

Because PICKUP and FLEX share one sample arena (`0x100b14f0+id*1096`), the voice's
stale SETTINGS pointer still reads as valid and the FLEX track sounds the old pickup
loop. A STATIC machine on the same switch works — but only by accident, because
STATIC's arena is a different one, forcing an incidental rebind. Separately, nothing
in the pattern-change path ever republishes the recorder UI cache.

The fix detours the handler's tail, after its existing `FUN_400972fc` ×8 loop, and:

1. republishes all 8 tracks' recorder records in one 96-byte copy;
2. sets the voice-kill bit for the PICKUP→notPICKUP transition — stock's own *reverse*
   arm already does exactly this;
3. calls `FUN_40001f18` to re-seed the sample slot, which stock calls on the way
   *into* PICKUP and never on the way out.

Step 3 is the actual fix for the reported case: an earlier version set the kill bit
but omitted the re-seed.

Verified with `tools/emu_partswitch.py --repro`, watching `FUN_400972fc` and the
voice/slot state across a real pattern-driven switch.

## ⚠️ If your remix includes DIRECT_JUMP_KYOTI, take this module with it

This is about this repo's DIRECT_JUMP_KYOTI module, not octabam's `direct-jump`. It
changes the Part by posting stock's own `{0x14, part}` message, so it reaches the very
handler bug 3 fixes — stock path, stock bug included.

The two are **independent**, and were measured as such: with and without this module,
DIRECT JUMP's Part-change trace, its Program Changes on fast re-cues and its whole
timing matrix are identical, including a run where *every* jump changes Part. So
neither needs the other. But DIRECT JUMP gives you many more Part changes to meet the
carryover with, which makes the pairing the sensible default.

## With OCTAKIT, bug 3's fix stays idle

Em's Octakit replaces the "select Part" handler that bug 3 hooks with her own Kit-change
code. It takes over at the handler's entry (`0x400621a6`) and rejoins stock only at its
end, so the two hooks inside (`0x400621da`, `0x40062216`) are never reached. In a remix
with OCTAKIT, bug 3's fix is present but does nothing: no effect and no crash. Bugs 1
and 2 are unaffected.

Whether the carryover bugs also occur on an Octakit Kit change has not been tested.

## What the bundle costs

A remix takes all three or none, and a site conflict on any one of them keeps all
three out. The three caves are otherwise independent — splitting them into three
modules later is a small change if it ever matters.

Bugs 1 and 2 are position-independent. Bug 3's cave is not (4 longwords hold absolute
addresses inside it), so its `reference(addr)` rebases exactly those — verified against
real `m68k-elf-ld` output at `0x400d7300` and `0x400d6d00`.

## Measured

Bugs 1 and 3 are hardware-confirmed on the author's Octatrack **MKI**. Bug 2: the
original fix was hardware-confirmed; the version before this one (stock's test first, the
`[BANK]` grid left to stock) ended the `[BANK]`-held stall on hardware, and in the emulator
gives the same `[PTN]` answer as the original for all 256 patterns and finds a planted lock
at the first and last byte of both lock arrays. This version (318 B, the `[BANK]`
trigless-lock check) on the author's MKI, 20 Nov 2026, in KYOTI V1.8BC / V1.8C release
candidates and the VARISPEED_EMUS image (the same bytes): audio and MIDI trigless locks with
and without a locked value light (or not) as specified under `[PTN]` and `[BANK]`, and
`[BANK]` held with the sequencer running stays responsive. Gates:
`tools/led_trigless_matrix.py`, `tools/led_bank_stall.py`. Nothing tested
on an MKII.

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.

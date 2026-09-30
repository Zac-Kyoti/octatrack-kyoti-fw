# ERASE_EMPTY_TRIGLESS_LOCKS

A stock bug fix. A **trigless lock** — a step holding parameter locks but no audible
trig — used to stay lit on the trig row forever once you erased its last remaining
lock, even though the step was now inert. It now disappears.

A deliberately empty trigless lock placed with `FUNC` + `TRIG` is left alone.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — one cave, one `jsr` hook |
| `patch_triglock.s` | the m68k source; the only truth for the cave's bytes |

Standalone image: `tools/build_erase_empty_trigless_locks.py`. It deliberately does **not** bump the
version string — one bug fix, stock-transparent.

## Root cause

`FUN_40038874` is the **live erase worker**, reached through opcode 8's case and
`FUN_40041af4`. It was identified by tracing the gesture on real hardware, not by
static guesswork. It already works out that the step's p-lock row has gone empty
and clears the track's bit from the per-step bitmap — but it never clears the
trig-type-layer flag `TRAC+0x10`, which is what keeps the LED lit. This module adds
only that clear.

| site | displaces | kind |
|---|---|---|
| `0x40038a5c` | `moveb %d1,%a0@(0x59,%d2:l)` + `addl %d4,%d0` | `jsr`; the cave replays both, then `rts` onto `0x40038afe` |

**Why that site and not the obvious one.** An earlier attempt detoured `0x40038af8`,
whose second instruction is the enclosing loop's `addql #1,%d7` — and `0x40038afc`
is a branch target from two places, so a six-byte splice would have been jumped
into halfway. The standalone builder keeps an `assert_no_branch_into` check for
exactly this; here the site is pinned by its stock bytes.

The cave is **position-independent** (verified byte-identical linked at `0x400d7500`
and `0x400d6f00`), so it may land wherever the allocator puts it.

## Measured

Hardware-confirmed on the author's Octatrack **MKI** — the gesture was traced on
the unit, which is how the real worker was found. Nothing tested on an MKII.

296 bytes, sha256 `5656b2da0a61719a…` linked at `0x400d7200`.

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed.

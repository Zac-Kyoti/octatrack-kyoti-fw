"""ERASE_EMPTY_TRIGLESS_LOCKS -- a stock bug fix.

A trigless lock (a step holding parameter locks but no audible trig) used to stay
lit on the trig row forever once you erased its last remaining lock, even though
the step was now inert. It now disappears, on audio and MIDI tracks. A deliberately
empty trigless lock placed with FUNC + TRIG is left alone.

ROOT CAUSE (static RE + a hardware gesture trace, NOTES.md section 13).
FUN_40038874 is the LIVE erase worker -- reached through opcode 8's case and
FUN_40041af4, and identified by tracing the gesture on the unit rather than by
static guesswork. It already works out that the step's p-lock row has gone empty
and clears the track's bit from the per-step bitmap, but it never clears the
trig-type-layer flag TRAC+0x10, which is what keeps the LED lit. On the MIDI side
FUN_40041af4 calls the twin FUN_40038668, which leaves MTRA+0x10 set the same way
(2026-11-20). This module adds only that clear.

Two jsr detours, one per worker, on its per-param erase store; each entry replays
the store + increment it displaced and returns:
  0x40038a5c  AUDIO  `moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0`  -> cave
  0x400387b8  MIDI   `moveb %d1,%a0@(0x4900)     ; addl %d4,%d0`  -> cave_midi
An earlier attempt detoured 0x40038af8 instead, whose second instruction is the
enclosing loop's `addql #1,%d7` -- and 0x40038afc is a branch target from two
places, so the six-byte splice would have been jumped into halfway. The standalone
builder keeps an `assert_no_branch_into` check on both sites; here they are pinned
by their stock bytes.

The unit is position-independent (both entries reach the shared rule with bsr.w;
byte-identical linked at 0x400d7200, 0x400d7500, 0x400d6f00 and 0x400c45b0).

MEASURED: the AUDIO side is hardware-confirmed on the author's MKI (the 296-byte
form before the 2026-11-20 refactor; the same rule, re-run in the emulator on the
new bytes). The MIDI side is emulator-verified only (tools/erase_trigless_test.py),
not yet on hardware. The standalone image is tools/build_erase_empty_trigless_locks.py,
which deliberately does NOT bump the version string -- one bug fix, stock-transparent;
it refuses to build when REFERENCE below is not its source linked at 0x400d7200.
"""

import os

from remix.schema import Detour, Kind, Linked, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

AUDIO = 0x40038a5c
AUDIO_STOCK = bytes.fromhex("11812859d084")
MIDI = 0x400387b8
MIDI_STOCK = bytes.fromhex("11414900d084")

# patch_triglock.s, m68k-elf-as -mcpu=5407, linked at 0x400d7200: 240 bytes.
REFERENCE = (0x400d7200, "0fa04f4dad79809cdf7d6c9ef174e76424f49c3f5128697380fd86a2356c6571")


MODULE = Module(
    name="erase-empty-trigless-locks",
    key="ERASE_EMPTY_TRIGLESS_LOCKS",
    kind=Kind.CF_PATCH,
    doc="Bug fix: a trigless lock whose last parameter lock is erased stops "
        "staying lit on the trig row (audio and MIDI tracks).",
    linked=(
        Linked("tl", os.path.join(_HERE, "patch_triglock.s"), reference=REFERENCE),
    ),
    detours=(
        Detour(AUDIO, AUDIO_STOCK, "tl", "cave",
               "FUN_40038874's erase store: clear TRAC+0x10 when the last lock goes",
               kind="jsr"),
        Detour(MIDI, MIDI_STOCK, "tl", "cave_midi",
               "FUN_40038668's erase store: clear MTRA+0x10 when the last lock goes",
               kind="jsr"),
    ),
)

# DIRECT_JUMP_KYOTI

An optional immediate pattern change for the Octatrack, toggled from the front
panel with **`[PTN]` + `[YES]`**. A cued pattern takes over on the **next step**
instead of waiting for the current one to finish, and the landing is **locked to
the master clock**: the new pattern plays exactly where it would be had it been
running since START, whatever its track lengths, scales or master settings —
never shifted by a step, never a fraction of a step off, and its first trig
always wins.

Off by default, and it comes up OFF at every power-on: a unit that never enables
it behaves exactly as stock.

- The Part, START SILENT and trig conditions change as on a stock pattern change.
- The last MIDI Program Change sent always names the pattern that plays.
- The arranger and pattern chains are untouched.

The Analog Rytm's own DIRECT JUMP lands shifted or fractional whenever lengths or
scales differ. Matching that behaviour was frozen as V6.4 (the OT↔AR parity
build); V7 is the clock-locked landing that this module ships.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — one DRAM unit, three detours, the keymap slot |
| `patch_directjump_v7.s` | the m68k source; the only truth for the unit's bytes |

The standalone image (this repo's own build, outside octabam) is
`tools/build_direct_jump_kyoti.py` → version string `140C_KDJ7`.

## How it works

OT already has a synchronous re-landing as **stock** code, behind the countdown
byte `0x80006687` in phase D of its tick handler. V7 adds no new sequencer
mechanism — it arms that countdown and prepares the snapshot on the landing tick
(ACT←PEND, master step, per-track step and counter), suppresses the MIDI START
(`0xFA`) that a jump must not send, and owns the `[PTN]`-held `[YES]` key. The
pattern-boundary body, the rebuild loops and every per-track counter are stock.

Three detours, six bytes each, plus one function pointer:

| site | symbol | what it displaces |
|---|---|---|
| `0x400a1f72` | `dj_land` | `move.b (0x80006687).l,%d0` — the phase-D countdown read |
| `0x400a221c` | `dj_nofa` | `tst.b (0x8000002a).l` — the MIDI START gate |
| `0x40043418` | `dj_ptnrel` | `pea 0x400bf0f2` — `[PTN]` release, so the chooser stays shut |
| `0x400bf0c0` | `dj_toggle` | the `[PTN]`-layer YES press slot, all-NULL in stock |

**State:** one word, `DJ_MODE` (0 = OFF/stock, 1 = ON), kept **inside the code unit**
(the source's default; only the standalone builder passes `DJ_MODE_IN_RAM=1` for the old
`0x800000d8` word). DIRECT JUMP must come up **OFF at every power-on**: in octabam the
unit lives in DRAM and octabam's loader unpacks it at every boot, so the word starts at 0
by construction and no battery restore can reach it.

That is what lets it share an image with MUTE MODE, which widens the boot `ANDY` restore
(`pea 0x64` → `pea 0x70` at `0x4001f322`, `0x4001f3be`, `0x4001fb24`) so its own word
`0x800000dc` survives power-off. The widened span `0x80000070..0x800000df` sweeps
`0x800000d8`, where `DJ_MODE` lived before this module switched, and where the
standalone build still keeps it (`reference/MERGE.md`, blocker B1).

**In DRAM.** In octabam the code is a `Linked(dram=True)` unit in the platform reserve
at the bottom of the audio page arena, not a ROM cave: octabam's floating ROM run cannot
hold every KYOTI module. The reserve is the same cached SDRAM the OS image runs from, so
the tick-path code runs at the same speed. The `[PTN]`-layer YES record around the press
slot is declared `Keep`, so a module writing into it is refused.

**Not with octabam's `DIRECT JUMP`** (Tim Hastie's CHAIN AFTER = DIRECT). The two share
no address, but both change when a cued pattern takes over and have never been tried in
one image, so the module declares them a conflict and the ledger refuses the pair.

## Measured vs inferred

**Hardware-confirmed** (the author's Octatrack MKI): the clock-locked timing, and the
Part change on a jump, first from the ROM cave (2026-09-27/28), then from DRAM in an
octabam-built image with all six KYOTI modules (2026-10-01). That image also confirmed
OFF at power-on, the `[PTN]`+`[YES]` toggle, and OFF again after a power cycle.

**Emulator only** (`ot_emu`, Unicorn on real image bytes): Program Change on fast
re-cues, MIDI tracks, and START SILENT and the trig-condition reset (both behave exactly
as on a stock pattern change in the emulator, but were not exercised on the unit).

Everything the emulators prove is control flow and image bytes, not how the unit
sounds. Nothing here has been tested on an MKII.

Reproduction: assembled with `m68k-elf-as -mcpu=5407` or `54455` (identical) and no
symbols, linked at `0x400d6d38` → 1980 bytes, sha256 `b86e3c3255674cef…`: byte for byte
the DIRECT JUMP code of the KYOTI V1.0 image flashed on the author's MKI. octabam
re-links it there on every build and compares.

## Recommended pairing: the bugfix bundle

**If you are composing a remix with DIRECT JUMP, take the KYOTI bugfix bundle with
it.** Not because this module needs it — it does not — but because a jump reaches
the Part machinery by posting stock's own `{0x14, part}` message, which is the
stock path, stock bug family included. Without the bundle's PART_CHANGE_CARRYOVER_FIX fix, a
jump into a pattern on a different Part shows exactly what a *stock* pattern
change shows: a track going PICKUP→FLEX plays the old Part's pickup loop, and the
recorder's SRC/RLEN cache goes stale. DIRECT JUMP neither causes nor worsens that,
but it does give you more Part changes to run into it with.

The two are independent and were measured as such: PART_CHANGE_CARRYOVER_FIX hooks the head and
tail of the very handler this module's hand-off posts to (`0x400621da` /
`0x40062216`), and on the composite the Part-change trace, the Program Changes on
fast re-cues and the whole timing matrix are identical to this module standalone —
including a 16↔7 run where *every* jump changes Part, tick-for-tick identical.
Either can be selected without the other; the sites are disjoint.

## What is open

- MKII is untested.
- Hardware confirmation of Program Change on fast re-cues, MIDI tracks, START SILENT
  and the trig-condition reset.

## Design notes

- `reference/handoffs/DIRECTJUMP_V7_DESIGN.md` — the V7 design
- `reference/OT_SEQUENCER_BUGS.md` — sequencer bugs found on the way
- `reference/AR_SEQUENCER_ENGINE.md` — the Analog Rytm decompilation that
  retracted the V1–V5 approach

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed: the build
reads *your own* copy of OS 1.40C and produces a modified image from it.

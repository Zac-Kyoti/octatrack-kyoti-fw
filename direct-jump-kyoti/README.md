# DIRECT JUMP (KYOTI)

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
| `manifest.py` | the octabam module declaration — cave, three detours, the keymap slot |
| `patch_directjump_v7.s` | the m68k source; the only truth for the cave's bytes |

The standalone image (this repo's own build, outside octabam) is
`tools/build_directjump_v7.py` → version string `140C_KDJ7`.

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

**State:** one word, `DJ_MODE = 0x800000d8` (0 = OFF/stock, 1 = ON). DIRECT JUMP must
come up **OFF at every power-on**, and that rests on two *stock* facts rather than on
this module's code: the boot `ANDY` battery restore (`pea 0x64` at `0x4001f322`,
`0x4001f3be`, `0x4001fb24`) covers `0x80000070..0x800000d3` and never reaches
`0x800000d8`; and the boot re-image seeds `0x800000d8` from `0x401087cc`, which is 0.

### ⚠️ Not safe with MUTE MODE yet — and the ledger will refuse it

MUTE MODE widens that restore to `pea 0x70` so its own word `0x800000dc` survives
power-off — and the widened span `0x80000070..0x800000df` **sweeps `0x800000d8`**. With
both in one image, `DJ_MODE` would be restored from a battery word nothing maintains,
and **DIRECT JUMP could come up ON**. (`reference/MERGE.md`, blocker B1.)

> **Correction.** An earlier revision of this README said the two modules "do not
> collide on SRAM." That compared the two words — `d8` and `dc` differ — and missed that
> MUTE MODE restores a *range*. It was wrong.

So this module **claims** those four sites as assert-only pokes (each writes back
exactly the stock bytes it expects). A remix pairing it with anything that rewrites them
is refused at octabam's ledger rather than shipping a unit that can power on with DIRECT
JUMP enabled. Measured against the real ledger: refused whether a MUTE MODE port declares
its widening as `Module.pokes` or through `emit()`; DIRECT JUMP alone, and all five ported
modules together, still pass.

The claims live in `emit()`, not `Module.pokes`, on purpose: the ledger checks plain pokes
against caves, hooks and `emit()` pokes, but not against another module's plain pokes.

**The real fix** is the source option `DJ_MODE_IN_CAVE` (branch `kyoti-v1`, `4ed4720`),
which moves the word into the cave — re-loaded from flash at every boot, so OFF by
construction. Once that is on `main`, this module will be rebuilt with it and the claims
can go.

**The cave floats.** It is not position-independent: 17 longwords hold absolute
addresses of its own state block. `reference(addr)` in the manifest rebases
exactly those, and was verified against real `m68k-elf-ld` output at `0x400d7300`
and `0x400d6500` — byte-identical at both.

## Measured vs inferred

**Hardware-confirmed** (the author's Octatrack MKI, 2026-09-27/28): the
clock-locked timing, and the Part change on a jump.

**Emulator only** (`ot_emu`, Unicorn on real image bytes): Program Change on fast
re-cues, START SILENT, trig-condition reset, MIDI tracks.

Everything the emulators prove is control flow and image bytes, not how the unit
sounds. Nothing here has been tested on an MKII.

Reproduction: assembled with `m68k-elf-as -mcpu=5407 --defsym DJ_TOAST_DUR=0x44`,
linked at `0x400d7000` → 1980 bytes, sha256 `34635ad57f25f733…`. The standalone
image is `fac16421de73c3aa…`.

## Recommended pairing: the bugfix bundle

**If you are composing a remix with DIRECT JUMP, take the KYOTI bugfix bundle with
it.** Not because this module needs it — it does not — but because a jump reaches
the Part machinery by posting stock's own `{0x14, part}` message, which is the
stock path, stock bug family included. Without the bundle's PARTREAPPLY fix, a
jump into a pattern on a different Part shows exactly what a *stock* pattern
change shows: a track going PICKUP→FLEX plays the old Part's pickup loop, and the
recorder's SRC/RLEN cache goes stale. DIRECT JUMP neither causes nor worsens that,
but it does give you more Part changes to run into it with.

The two are independent and were measured as such: PARTREAPPLY hooks the head and
tail of the very handler this module's hand-off posts to (`0x400621da` /
`0x40062216`), and on the composite the Part-change trace, the Program Changes on
fast re-cues and the whole timing matrix are identical to this module standalone —
including a 16↔7 run where *every* jump changes Part, tick-for-tick identical.
Either can be selected without the other; the sites are disjoint.

## What is open

- MKII is untested.
- The four emulator-only behaviours above want hardware confirmation.
- **PLAYSFREEFIX is deliberately not part of this module.** The standalone
  builder folds the manual-trig fix (`patch_trigscale`) into its own image, but
  as a module that fix is its own contribution — five KYOTI feature builders each
  carry a copy and all write the same site `0x4009b6f2`, which octabam's ledger
  would refuse. It belongs to the bugfix bundle module.

## Design notes

- `reference/handoffs/DIRECTJUMP_V7_DESIGN.md` — the V7 design
- `reference/OT_SEQUENCER_BUGS.md` — sequencer bugs found on the way
- `reference/AR_SEQUENCER_ENGINE.md` — the Analog Rytm decompilation that
  retracted the V1–V5 approach

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed: the build
reads *your own* copy of OS 1.40C and produces a modified image from it.

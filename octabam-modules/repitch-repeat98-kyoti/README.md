# REPITCH_REPEAT98_KYOTI

Tempo-locked varispeed for STATIC and FLEX tracks, as three extra TSTR positions after the
four stock ones:

| TSTR | what it does |
|---|---|
| **RPCH** | follows the project tempo by playback speed, without grains (the basic Repitch) |
| **RPS9** | the same, with an S900/S950-style repitch emulation |
| **RPSP** | the same, with an SP-1200-style repitch emulation (channels 1/2) |

On a repitch track the PTCH knob becomes **QUAN**: one detent per ratio.

**Credit:** Jannik Aßfalg ([repeat98](https://github.com/repeat98)) wrote the basic Repitch
(octabam's `modules/repitch`). Zac Kyoti wrote the S900/S950 and SP-1200 repitch emulations
and the Quantizer.

## ⚠️ Work in progress

This folder holds the **ColdFire half only**. RPS9 and RPSP are rendered by a DSP kernel
(`tools/patch_repitch_dsp.asm` in this repository) that the manifest does not place yet. It
needs per-payload DSP hook sites and a home for its tables, both open with octabam. Do not
use this module in a remix until the DSP half is here.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration: three DRAM units, 14 `jmp` detours, 7 symbol refs, 5 pokes |
| `patch_repitch_kyoti.s` | the ColdFire logic (unit `rpk_logic`) |
| `rpk_glyphs.s` | the seven TSTR position glyphs (unit `rpk_glyphs`) |
| `patch_repitch_reload.s` | stock RELOAD PART treated as a Part apply (unit `rpk_reload`) |

Standalone image: `tools/build_repitch_repeat98_kyoti.py`.

## How it works

The detours are Jannik's seven (rate gate, pitch gate, rate hook, TSTR resolve, three
audio-editor ATTR hooks), the four page-1 dial renderers (the QUAN widget), the two Part
applies, and stock RELOAD PART. TSTR's count goes from 4 to 7 on the STATIC and FLEX
descriptors, with this module's formatter. PTCH gets the QUAN widget and encoder step.

**The 7-position selector.** Stock 1.40C has a 5-position select widget at `0x40046ab4`
that nothing in stock references: no pointer, no `jsr`, no PC-relative call. Jannik's
REPITCH uses it unmodified. This module patches it in place: its bound `moveq #4` becomes
`#6`, and its icon-table operand points at this module's glyphs. TSTR then points at it.
The standalone builder makes the same two changes to a copy in its cave; here no stock
byte is copied.

**Not with octabam's `REPITCH`.** Both grow the same Repitch: the same detour sites and
TSTR words. The module declares the conflict, and the ledger refuses the pair.

**In DRAM.** About 2.6 KB, more than octabam's floating ROM run has left beside the other
KYOTI modules. A remix with this module carries the platform loader and its 10 MiB reserve
unless another DRAM module already does.

## Measured

Hardware-confirmed on the author's MKI: the standalone image (rev 16) and the KYOTI V1.0
combined image. `rpk_logic` and `rpk_glyphs`, linked at the standalone image's own
addresses, are byte for byte that image, for `-mcpu=5407` and `54455` alike. Built by
octabam (`make bus`, a stock-effects remix with this module): it changes every stock site
the standalone image changes on the ColdFire side, and passes `verify_dram_boot`. The
octabam form has not been run on hardware.

## Licence

MIT, © 2026 Zac-Kyoti, for this repository's code. It builds on Jannik Aßfalg's Repitch
from octabam (see octabam's `THIRD_PARTY.md` and this repository's `CREDITS.md`). No Elektron
bytes are included or distributed.

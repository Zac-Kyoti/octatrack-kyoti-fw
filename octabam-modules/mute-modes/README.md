# MUTE_MODES

Choose what muting an audio track does, in **PERSONALIZE → MUTE MODE**:

| mode | what a muted (or soloed-out) track does |
|---|---|
| **OT** | stock: an instant cut after the FX |
| **OTFX** | the dry sound cuts, the track's delay/reverb tails ring out, and the sequencer keeps running underneath, so unmuting picks up where the pattern would have been |
| **OTFX-T** | as OTFX, and new trigs are suppressed |
| **DT-T** | a Digitakt-style mute: the sounding note plays out on its own amp envelope, only new trigs are suppressed |

Default **OT**, so a freshly flashed unit behaves as stock. The setting survives
power-off; an OS upgrade resets it with the rest of PERSONALIZE.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — two linked units, six `jmp` detours, three grown tables, four pokes |
| `patch_softmute.s` | the mute behaviour (unit `mm_softmute`) |
| `patch_mutemode.s` | the PERSONALIZE row: label, getter, setter (unit `mm_menu`) |

Standalone image: `tools/build_mute_modes.py`. Both sources assemble to that image's bytes
with no symbols defined (`DT_MODE`, the four-mode build, is the source default).

## How it works

| site | displaces | symbol |
|---|---|---|
| `0x40004dc6` | `move.l (0x80000008).l,%d5` — the frame builder's mute word | `pre` |
| `0x40006844` | `move.w %sr,%d2; move.w #0x2700,%sr` | `mt_trig` |
| `0x4000f4dc` | two `move.l` into the voice record (8 B) | `mt_rebind` |
| `0x4000d498` | `move.l %d0,-(%sp); move.l %d3,-(%sp); jsr (%a0)` — trig dispatch | `dt_trig` |
| `0x40006820` | the fresh-voice bind's prologue (8 B) | `fresh_bind` |
| `0x40004c72` | `moveq #3,%d0; and.l %d1,%d0; beq` — per-trig flag bits | `trigflag` |

**State:** `0x800000dc` (0 = OT), a free PERSONALIZE word. To survive power-off, the boot
`ANDY` battery restore is widened from `pea 0x64` to `pea 0x70` at `0x4001f322`,
`0x4001f3be` and `0x4001fb24`, and the setter writes the shadow at `0x100fff6c`.

**The menu row.** The three stock PERSONALIZE pointer arrays (`0x400b2a34` labels,
`0x400b2a74` getters, `0x400b2ac0` setters) are relocated with MUTE MODE inserted at row 2,
after PREVIEW WITHOUT FX (`TableGrow(count=16, insert_at=2)`), and the row count at
`0x40068fb2` goes from 15 to 16. LED BRIGHTNESS stays the last row, which the stock count
shows on an MKII only. Nothing in the firmware keys off a PERSONALIZE row's position.

**With SIDECHAIN_COMPRESSOR** (not a module yet): the combined KYOTI image assembles
`patch_softmute.s` with `SC_KEY` so a muted KEY track keeps feeding the compressor, as on
stock. The source tests it with `.ifdef`, so it must be absent otherwise. octabam can
express that per remix; it is added when SIDECHAIN_COMPRESSOR becomes a module.

## Measured vs inferred

**Hardware-confirmed** (the author's Octatrack MKI): all four modes, from the standalone
image and the KYOTI V1.0 combined image.

**This module** has been built by octabam (`make bus`, upstream `363861e3`, alone and with
DIRECT_JUMP_KYOTI): both units re-linked at their octabam addresses match the author's
build at `0x400d7400` / `0x400d7800`, and the image changes the same stock sites as the
standalone build. It has not been flashed in an octabam image.

# REC_TRIG_MUTE

Mute a track's recorder trigs without deleting them. Hold **`[TRACK]`** and press
**`[NO]`**: the held tracks' recorder trigs stop firing — a recording already running
finishes — toast `REC TRIGS MUTED`. **`[TRACK]`** + **`[YES]`** brings them back
(`REC TRIGS UNMUTED`). Any screen, grid recording or not; it holds across pattern changes
until you unmute, and every track starts unmuted at power-on. A muted track shows two dots
beside its play/stop icon at the screen edge (`..■` / `..▶`).

MIDI **CC 80**: 0 unmutes, 1–127 mutes, on a track's channel (AUTO channel = the active
track), with AUDIO CC IN on. The keys send CC 80 (1 / 0) on each held track's channel, with
AUDIO CC OUT on. `[FUNC]` + `[YES]` / `[NO]` still arm and disarm one-shot trigs as on
stock; `[TRACK]` + `[YES]` / `[NO]` no longer do.

## Status

The same source builds the standalone image (`tools/build_rec_trig_mute.py`) and goes into
KYOTI V1.0; both are **hardware-confirmed** on the author's MKI (keys, toasts, the edge icons,
a running recording finishing and nothing new starting). MIDI CC 80 has not been tried on
hardware. This octabam form — the `OCTABAM_UNIT` variant of the source — has not been flashed.
Its `reference` is the author's build of that form (linked alone at `0x40000000`, 8698 B,
sha256 `dbb5d5f6…`), made by `tools/build_rec_trig_mute.py` with octabam's own DRAM-unit
oracle recipe on every run.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the module: one DRAM `Linked` unit, four `Detour`s, four `SymbolRef`s |
| `patch_rec_trig_mute.s` | the m68k source for every layout; octabam builds it with `--defsym OCTABAM_UNIT` |

## Sites

| site | stock | kind | what |
|---|---|---|---|
| `0x4009d9a4` | `tst.l %d3 ; beq.s ; move.l #0x91a,%d2` | `jmp`, padded to 10 B | step handler: a muted track's step has no recorder trig |
| `0x4004bee2` | `lea 0x400c0cb8,%a0` | `jsr` | edge renderer: the mute folded into its state cache |
| `0x4004c00c` | `moveq #3,%d0 ; cmpl %a4,%d0 ; bnes` | `jmp` | edge renderer: `..■` / `..▶` |
| `0x4000f210` | `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge` | `jmp` | CC handler fall-through: CC 80 |
| `0x400d15e4` / `e8` | `0x400834d8` | data | `[TRK]`-layer YES record → `rtm_yes` |
| `0x400d15fe` / `0x400d1602` | `0x40083488` | data | `[TRK]`-layer NO record → `rtm_no` |

Compatible by construction with octabam's `cc-map` and with Octakit's CC wrapper: both
hook the CC handler's **entry** (`0x4000e79c`) and pass CCs they don't own to stock, which
is where CC 80 is caught. Untested together.

Mechanism and every proof: `reference/handoffs/REC_TRIG_MUTE_SCOPE.md` in OT Kyoti FW.

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed.

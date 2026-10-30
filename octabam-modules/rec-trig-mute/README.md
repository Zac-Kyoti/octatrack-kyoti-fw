# REC_TRIG_MUTE

Mute a track's recorder trigs without deleting them. Hold **`[TRACK]`** and press
**`[REC]`**: that track's recorder trigs stop firing — a recording already running
finishes — toast `REC TRIGS MUTED`. Press it again to bring them back (`REC TRIGS UNMUTED`).
Each track keeps its own state: with several track keys held, each one flips
(`REC TRIGS TOGGLED` when they end up mixed). The toast stays up while the track key is
held, up to 1 s (QUANTIZE_LIVE_REC_TOGGLE's length), and closes when it is let go. While a
track key is held, `[REC]` does not switch grid recording; on its own `[REC]` is stock. Any screen; it holds across pattern
changes until you unmute, and every track starts unmuted at power-on. A muted track shows
two dots beside its play/stop icon at the screen edge (`..■` / `..▶`).

MIDI **CC 80**: 0 unmutes, 1–127 mutes, on a track's channel (AUTO channel = the active
track), with AUDIO CC IN on. The keys send CC 80 (1 muted / 0 unmuted) on each held track's
channel, with AUDIO CC OUT on. `[TRACK]` + `[YES]` / `[NO]` and `[FUNC]` + `[YES]` / `[NO]`
arm and disarm one-shot trigs as on stock.

## Status

The same source builds the standalone image (`tools/build_rec_trig_mute.py`) and goes into
KYOTI. The earlier form (`[TRACK]` + `[NO]` / `[YES]`) is **hardware-confirmed** on the
author's MKI as the standalone image and in KYOTI (keys, toasts, the edge icons, a running
recording finishing and nothing new starting). The `[TRACK]` + `[REC]` form — the per-track
toggle, and the 1 s toast that closes on release — ran on the same MKI inside KYOTI V1.6 on
29 Oct 2026 ("all good"). MIDI CC 80 has not been tried on hardware. This octabam
form — the `OCTABAM_UNIT` variant of the source — has not been flashed. Its `reference` is the
author's build of that form (linked alone at `0x40000000`, 556 B, sha256 `aa2d1ae3…`), made by
`tools/build_rec_trig_mute.py` with octabam's own DRAM-unit oracle recipe on every run.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the module: one DRAM `Linked` unit, five `Detour`s, four `SymbolRef`s |
| `patch_rec_trig_mute.s` | the m68k source for every layout; octabam builds it with `--defsym OCTABAM_UNIT` |

## Sites

| site | stock | kind | what |
|---|---|---|---|
| `0x4009d9a4` | `tst.l %d3 ; beq.s ; move.l #0x91a,%d2` | `jmp`, padded to 10 B | step handler: a muted track's step has no recorder trig |
| `0x4004bee2` | `lea 0x400c0cb8,%a0` | `jsr` | edge renderer: the mute folded into its state cache |
| `0x4004c00c` | `moveq #3,%d0 ; cmpl %a4,%d0 ; bnes` | `jmp` | edge renderer: `..■` / `..▶` |
| `0x4000f210` | `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge` | `jmp` | CC handler fall-through: CC 80 |
| `0x40083e84` | `and.l %d0,0x460fab40` | `jsr` | track-key release: our toast closes once no track key is held |
| `0x400c003c` / `0x400c0040` | `0x40048774` | data | T1 keymap `[REC]` record, press / release → `rtm_rec` |
| `0x400c0620` / `0x400c0624` | `0x40048774` | data | T2 keymap `[REC]` record, press / release → `rtm_rec` |

`rtm_rec` hands every event except a press with a track key held back to `0x40048774`, so a
module that detours the REC handler itself (STEM REC's `UP` + `REC`) still runs behind it.
One exception: a `[REC]` release while a track key is held and our toast is up does stock's
release (`clr.l 0x460d1726`) itself, so a release hook (QUANTIZE_LIVE_REC_TOGGLE closes every
toast there) cannot close the toast while the track key is held.

Compatible by construction with octabam's `cc-map` and with Octakit's CC wrapper: both
hook the CC handler's **entry** (`0x4000e79c`) and pass CCs they don't own to stock, which
is where CC 80 is caught. Untested together.

Mechanism and every proof: `reference/handoffs/REC_TRIG_MUTE_SCOPE.md` in OT Kyoti FW.

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.

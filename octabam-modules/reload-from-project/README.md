# RELOAD_FROM_PROJECT

Reload **one track's** sequence from the CF card **without stopping the transport**.

Stock can only reload a whole bank, and doing so stops the sequencer. Two direct
chords, no modal window and no timeout:

- **`[PTN]` + `[TRACK n]`** — reload that track's card-saved sequence, Part untouched
- **`[BANK]` + `[TRACK n]`** — the same, and re-apply the saved Part

It reloads the pattern that is *playing*, on an audio or a MIDI track, and never
restarts the sequence or the internal metronome. A stock-style toast confirms when
the reload has **finished** — and says so if the trigs did not land.

Deferred by the author's own scoping: all-tracks and whole-bank reload.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — one DRAM unit, six `jmp` detours |
| `patch_reload3.s` | the m68k source; the only truth for the unit's bytes |

Standalone image: `tools/build_reload_from_project.py` → `RELOAD_FROM_PROJECT`.

## How it works

| site | symbol | what it is |
|---|---|---|
| `0x40083dc4` | `rl3_ptn_trk` | `[PTN]` + `[TRACK n]` |
| `0x40040250` | `rl3_bank_trk` | `[BANK]` + `[TRACK n]` |
| `0x4007af42` | `rl3_bank_show` | `[BANK]` display |
| `0x4007b3e0` | `rl3_bank_rel` | `[BANK]` release (8-byte span) |
| `0x40023c62` | `rl_done` | the FINISHED toast |
| `0x40085864` | `rl_job` | stock's own message case `0x14` worker |

All six are `jmp`. Two displace eight bytes, so the six-byte jump is followed by a
nop — otherwise the span would be left half-rewritten.

The worker is **stock's own**; this module hooks it rather than reimplementing it.

After a successful `[BANK]` + `[TRACK n]` Part reload it runs the tail of stock's own
Part-reload shortcut (`0x4005e0a8`: the redraw flag plus stock's UI refresh), so the knobs
show the reloaded Part's values at once instead of after a page press. Confirmed on
hardware.

**In DRAM.** In octabam the code is a `Linked(dram=True)` unit: octabam's loader
unpacks it into the platform reserve at the bottom of the audio page arena at every
boot, and the six detours jump there. It left the ROM cave so that every KYOTI module
fits one remix, and it is the one that moved because it runs from key chords and the
message worker, never on the per-step tick. The standalone image keeps it in the ROM
cave at `0x400d6500`; the bytes are the same, linked at a different address.

## Why two plain chords and not a picker

An earlier design (RELOAD2) put a modal picker window on a `[PTN]`-hold with arrow
navigation. It needed **ten** detours and a keymap-layer poke — and that poke was
the mechanism behind a keymap slot collision with DIRECT JUMP and several routing
bugs. This is the Session 85 redesign: six detours, two chords, and **neither chord
site pokes a keymap layer record.**

Full RE and design rationale: `patch_reload3.s`'s own header comment. The dynamic proof
against the real stock layer-push code is `NOTES.md` Session 85 (its harness is in the
repo's history).

## ⚠️ No private state in the DSP window

RELOAD_FROM_PROJECT's request bytes used to live at `0x80006a54-55`, inside the `0x80006a40+`
scratch block. On hardware they were **overwritten between the chord and the
worker**: it reloaded MIDI track 6 instead of audio track 1 and cheerfully reported
`RELOADED` (Session 98). That block sits in the DSP shared-RAM window, and a static
"no references" scan says nothing about runtime writes.

Everything now lives in the unit itself, and the standalone builder refuses any
reference into `0x80006a40..0x80006abf`.

## Measured

Hardware-confirmed on the author's Octatrack **MKI**, including that the sequencer and the
internal metronome keep their phase (`RELOAD_NOW` is not armed on any path). This was
confirmed from the ROM cave (the standalone image and KYOTI V1.0), and from DRAM in an
octabam-built image with all six KYOTI modules (2026-10-01): both chords, the FINISHED
toast, the transport kept running, and the knob repaint. Nothing tested on an MKII.

2088 bytes, sha256 `ef22237d38c24966…` linked at `0x400d6500` (`-mcpu=5407` or `54455`, identical); octabam re-links it there on every build and compares.

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed.

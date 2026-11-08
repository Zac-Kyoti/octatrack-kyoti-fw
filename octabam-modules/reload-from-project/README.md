# RELOAD_FROM_PROJECT

Reload **one track**, or **one pattern**, from the CF card **without stopping the transport**.

Stock can only reload a whole bank, and doing so stops the sequencer. Two direct
chords, no modal window and no timeout:

- **`[PTN]` + `[TRACK n]`** — reload that track's card-saved sequence, Part untouched
- **`[BANK]` + `[TRACK n]`** — the same, and that track's slice of the Part as the
  project was saved: machine, FX, levels, every page, scene locks and LFO designer.
  Every other track, and the rest of the Part, is left alone.
- **`[PTN]` + `[BANK]` + trig N** — pattern N of the playing bank, all its tracks and its
  Part, as the project was saved; then the OT goes to it (at once when stopped; while
  playing, where stock's own pattern change would land). Hold the two keys in either order.
  With both held, a `[TRACK]` key reloads nothing.

`[CUE]` + `[TRACK n]` is stock cue behaviour, not a reload. The eight stock refs to
the `0x40083dc4` detour are CUE's held-modifier TRACK slots (`0x400bf122`); without a
panel PTN held gate that path toasted `TRK SEQ RELOADED` (16 Oct 2026, MKII).

It reloads the pattern that is *playing*, on an audio or a MIDI track, and never
restarts the sequence or the internal metronome. A stock-style toast confirms when
the reload has **finished** — and says so if the trigs did not land.

Deferred by the author's own scoping: whole-bank reload.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — one DRAM unit, eight `jmp` detours |
| `patch_reload3.s` | the m68k source; the only truth for the unit's bytes |

Standalone image: `tools/build_reload_from_project.py` → `RELOAD_FROM_PROJECT`.

## How it works

| site | symbol | what it is |
|---|---|---|
| `0x40083dc4` | `rl3_ptn_trk` | `[CUE]`'s held sub-map TRACK handler: reloads only with `[PTN]` held, else stock |
| `0x40040250` | `rl3_bank_trk` | `[PTN]` / `[BANK]` + `[TRACK n]` (the base TRACK handler) |
| `0x4007af42` | `rl3_bank_show` | `[BANK]` display |
| `0x4007b3e0` | `rl3_bank_rel` | `[BANK]` release (8-byte span) |
| `0x40023c62` | `rl_done` | the FINISHED toast |
| `0x40085864` | `rl_job` | stock's own message case `0x14` worker |
| `0x4005a044` | `rl3_ptn_key` | `[PTN]` press with `[BANK]` held: stock's press, then `[BANK]`'s layer on top |
| `0x4007b2fc` | `rl3_bank_trig` | `[BANK]`-layer trig press: with `[PTN]` held, the pattern reload (8-byte span) |

All eight are `jmp`. Three displace eight bytes, so the six-byte jump is followed by a
nop — otherwise the span would be left half-rewritten.

The worker is **stock's own**; this module hooks it rather than reimplementing it.

**`[BANK]` + `[TRACK n]`, the Part slice.** Until 8 Nov 2026 this chord ran stock's PART
RELOAD: the *whole* Part, from its SAVE PART copy in RAM, so every other track on that Part
reverted too. It now does what the author's CLYPS card reload does. The worker reads the
bank file's **working** PART chunk (the Part as the project was saved; a direct seek, then
chunk by chunk if anything is unexpected) and copies track n's slice into the Part the
pattern links to now. It publishes that slice for track n alone: stock's per-track apply
`0x40001f18` for audio, one track of stock's Part apply for MIDI. A new audio machine
restarts the voice, as stock's machine edit does. The Part-edited mark follows "differs
from its SAVE PART copy". The UI half runs in the job's doneFn, which stock calls on the UI
task (message `0x2b`): the PICKUP setup after a new machine, then the tail of stock's own
Part-reload shortcut (`0x4005e0a8`), so the knobs show the reloaded values at once.
Toasts: `TRK SEQ` / `RELOADED FROM PROJ` and `TRK FULL` / `RELOADED FROM PROJ`.

**`[PTN]` + `[BANK]` + trig N, the pattern reload** (8 Nov 2026, CLYPS' as well). Neither the
`[PTN]` nor the `[BANK]` keymap layer has a record for the other key, so the chord's second key
pushes its own layer on top and a trig goes to whichever came last. Two more detours make the
chord one state in either order: `[PTN]`'s press with `[BANK]` held (`0x4005a044`) runs stock's
press, then puts `[BANK]`'s keymap layer back on top; `[BANK]`'s trig press (`0x4007b2fc`) is ours
while both keys are held. The `[PTN]` layer's own trig handler is left alone (KITS detours it).
Both releases are silent: no SELECT PATTERN, no SELECT BANK. The grid shows `[PTN]`'s LED layer.
The worker lands the whole slab with its saved Part link and the whole working Part it links to,
and applies that Part when it is sounding. doneFn then cues the pattern as stock's `[PTN]` +
trig does (`0x4009a404`, `0x400a1030`). Toast: `PATTERN A05` / `RELOADED FROM PROJ`.

**In DRAM.** In octabam the code is a `Linked(dram=True)` unit: octabam's loader
unpacks it into the platform reserve at the bottom of the audio page arena at every
boot, and the eight detours jump there. It left the ROM cave so that every KYOTI module
fits one remix, and it is the one that moved because it runs from key chords and the
message worker, never on the per-step tick. The standalone image keeps it in the ROM
cave at `0x400d6500`; the bytes are the same, linked at a different address.

**Not with `OCTAKIT`** (Em's Octakit), for now. Until 8 Nov 2026 `[BANK]+[TRACK n]`
called stock's own Part RELOAD, which Octakit replaces with a routine that halts the unit
for any caller but the menu's and FUNC+CUE's. That call is gone. The slice reload now
calls stock's per-track apply, which Octakit's runtime also uses, and the two have never
been run together. The ledger keeps refusing the pair
(`reference/handoffs/DIRECTJUMP_OCTAKIT_SCOPE.md` in octatrack-kyoti-fw).

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

4124 bytes, sha256 `6e2e80f4283ae69e…` linked at `0x400d6500` (`-mcpu=5407` or `54455`, identical); octabam re-links it there on every build and compares.

The `[BANK]` + `[TRACK n]` Part-slice reload and the `[PTN]` + `[BANK]` + trig pattern reload (8 Nov 2026) are emulator-checked; they are not yet hardware-confirmed.

## Licence

MIT, © 2026 Zac Kyoti. No Elektron bytes are included or distributed.

# QUANTIZE_LIVE_REC_TOGGLE

Reach the **QUANTIZE LIVE REC** setting from the front panel instead of digging
through PERSONALIZE.

Hold **`[REC]`** and tap **`[PLAY]`**: a toast shows the current setting. Tap
`[PLAY]` again **while that toast is up** to invert it; tap again to invert it back.
Once the toast has gone (1 s), the next tap just shows the setting again. The first
`[REC]` + `[PLAY]` still starts live recording exactly as on stock.

This is the all-or-nothing live-record quantize, not the per-track TRIG QUANT.

## Contents

| file | what it is |
|---|---|
| `manifest.py` | the octabam module declaration — one cave, two `jmp` detours |
| `patch_qlrec.s` | the m68k source; the only truth for the cave's bytes |

Standalone image: `tools/build_quantize_live_rec_toggle.py`.

## How it works

No PERSONALIZE menu surgery. The variable, its getter/setter and its power-cycle
persistence are all **stock**; this module only adds a front-panel gesture that
writes the same word plus its `ANDY` battery shadow, and re-checksums.

| site | displaces | symbol |
|---|---|---|
| `0x40061778` | `jsr 0x4009b5c0` | `qlr_play` |
| `0x4004883a` | `clr.l (0x460d1726).l` — `[REC]` release | `qlr_recrel` |

Both are `jmp`, not `jsr`, so they are planted through the manifest's `emit()`
rather than the generic installer's hook.

The cave is **position-independent** (verified at `0x400d7700` and `0x400d7100`).

## ⚠️ Do not hook `0x400522ca`

Timing here comes from **the OS, not from us**: "is the toast still up" is read from
the OS's own toast state (handle `0x460d1e70`, countdown `0x460d1e6c`). This module
ticks nothing of its own.

That is deliberate. A third detour,
`qlr_tick` at `0x400522ca`, used to drive the toast from inside the **engine frame
handler**. `FUN_4005a2b8` (NOTIFY) and `FUN_40056bec` (close) both bottom out in
`FUN_40000c3c`, the kernel post/wake — legal from a key handler, not from the engine
frame path. It **hard-crashed a real MKI** on 2026-09-25: dead controls and a loud
persistent HF crackle. It also fired far too rarely to time anything with.

The site is retired, and the standalone builder asserts it is left byte-for-byte
stock on every build. It is not declared as a module claim, because the site is only
lethal to hook *from the engine frame path* — another module may have a legitimate
reason to take it.

Nothing is kept in the `0x80006a40+` scratch block either: that sits in the DSP
shared-RAM window and does not survive live audio on hardware.

## Measured

Hardware-confirmed on the author's **MKI**: the show-then-invert gesture works on this
version, with the tick hook removed (2026-09-25), and a setting changed with it survives
a power cycle (2026-09-30).
Nothing tested on an MKII.

176 bytes, sha256 `52c26af67443e470…` linked at `0x400d7400`.

## Licence

MIT, © 2026 Zac-Kyoti. No Elektron bytes are included or distributed.

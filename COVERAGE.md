# RE coverage vs. firmware features (OS 1.40 manual)

Cross-reference between what we have mapped/decompiled and the complete set of features
per the official manual (146 pp.). Legend: ✅ done · 🟡 partial (structure found, not fully
decompiled) · ⬜ untouched.

## Key discovery that reframes the remaining work

**The Octatrack's audio algorithms are NOT in the ColdFire binary.** The MAIN OS is the
*control*: UI, sequencer, files, and the assembly of voice parameters. The *signal
processing* — sample playback, **timestretch**, and the **17 effects** (filters, reverbs,
delays, phaser…) — runs on the **DSP56xxx**, whose program is a **separate binary** that the
ColdFire uploads at startup (`FUN_40001d4c`, 24-bit words).

→ **That blob has since been located, extracted and worked on.** It is `out/dsp_region.bin`
(DSP56300, ~188 KB), it carries **two payloads** — A for tracks 5–8, B for tracks 1–4 — and
the project now has a working DSP56300 toolchain (`vendor/dsp56300/`), a module map, an
emulator (dsp56kEmu) and a dual-core harness (`tools/dsp56300_xcore/`). One effect, the
**DynamiX COMPRESSOR**, is fully reversed and has been *extended* on hardware (the side-chain
`KEY` input). So "the audio is a separate project" is no longer the right framing: it is a
second front in this one, opened but far from finished — 16 of the 17 effects and all of
timestretch are still untouched.

## Coverage matrix by subsystem

| Subsystem (manual ch.) | Status | What we have / what's missing |
|---|---|---|
| Hardware & boot | ✅ | ColdFire CPU, DSP boot, memory map. Missing: codec/DAC-ADC init, panel (encoders/buttons/LEDs), display driver |
| OS format & update (8.5.2, ch.18) | ✅ | ELUP/ELEK/aPLib, checksum, validation, ATA write, MIDI upgrade. Complete |
| Kernel / RTOS / scheduler | ✅ | Context switch, priority queues, PIT, TRAP #0. Missing: task list, allocator |
| ATA/CF storage | ✅ | ATA stack (PIO/DMA), driver+vtable, registers. Missing: FAT layer (vtable `_DAT_46c82xxx`) |
| File hierarchy: Sets/Projects/Audio Pool (ch.4,7,8) | 🟡 | Project settings serialization found; the rest missing (banks/parts/samples on disk) |
| Audio engine (voices) | 🟡 | Data model (voice `0x800049d8`, mailboxes), frame builder, handoff to the DSP. Missing: voice parameter computation, envelopes, amp modulator |
| Sample playback: FLEX vs STATIC | ⬜ | FLEX=RAM, STATIC=stream from CF. Not decompiled |
| **Timestretch** (NORMAL/BEAT) | ⬜ | On the DSP (separate binary) |
| **Effects — Appendix B (17 FX)** | 🟡 | All on the DSP. **DynamiX COMPRESSOR fully reversed** (param map `r6+$0..5` = ATK/REL/THRS/RAT/GAIN/MIX, `+$c` = RMS; detector tap at `x:(r0)+`) and extended with a side-chain `KEY` input, hardware-confirmed. SPRING REVERB's module bounds mapped (it is the donor). The DSP module/dispatch table is mapped. The other 15 FX and timestretch: untouched |
| Machines — Appendix A (FLEX/STATIC/THRU/NEIGHBOR/PICKUP) | 🟡 | Dispatch by type found (`FUN_40097168`→0-4). **The FLEX/PICKUP sample-slot binding is mapped**: the per-track pre-image at `0x8000082f + track*0x48` byte 0 feeds the resolver, FLEX and PICKUP share one arena and one table and differ only by slot number — that is the Part-change carryover fix. Machine *logic* still not decompiled |
| Track recorders / Pickup / sampling (ch.9) | 🟡 | The recorder **record/cache** in the Part is mapped and re-applied by the carryover fix; the PICKUP machine's slot ownership is mapped. The actual recording path into buffers is still only a passing glimpse ("ROTATING AUDIO") |
| Sequencer: clock/tick | ✅ | **Sample-accurate**: clocked by the audio frame ISR (`0x4000aad0`), `2³¹/tempo` phase accumulator; wakes the seq task via a kernel queue |
| Sequencer: trig → voice | 🟡 | `FUN_400977cc` maps trig→voice command. The per-tick step engine is mapped (ISR `0x400a1e0c` → per-clock-tick body; the commit at `0x400a44d0` and its per-track rebuild tail), as is the voice/trig dispatch region `0x400a2xxx` and the per-track step/prev-step arrays it reads |
| Trig types / p-locks / sample locks (12.4-12.6) | 🟡 | **Substantially mapped.** The 16 per-pattern p-lock arrays (8 audio + 8 MIDI) and the trig-type layer are both read and written by this project's fixes: the content predicate `FUN_4009a464` (Bug 2), the stored-p-lock writer `FUN_40042158`, and the erase path `opcode 8` → `FUN_40041af4` → `FUN_40038874` (trigless-lock auto-remove). Sample locks still untouched |
| Conditional locks / micro timing / fill / scales (12.12-12.15) | 🟡 | **Scales are mapped in depth** (DIRECT JUMP): `LEN_TBL` is ticks-per-step, `0x800065b6` is master ticks-within-step, `0x800065b2` the master step, per-track `TRK_SCALE_IX`/length/countdown arrays located, MASTER LENGTH found, and the tick-vs-step domain distinction is the open problem there. Trig conditions and micro-timing are located as per-track serialized fields (RELOAD copies them per track) but their *evaluation* is not decompiled; probability/fill untouched |
| **Scenes & crossfader** (10.3) | ⬜ | Morphing of locked parameters. The OT's flagship feature. Essentially untouched — only the scene-morph *retrigger* entry point is used (by the carryover fix), not the morph itself |
| **LFO designer** / LFOs (11.4) | ⬜ | 3 LFOs per track, custom shapes. Untouched |
| Arranger / song mode (ch.14) | ⬜ | Pattern chaining. Format in OctaLib; code not decompiled |
| MIDI sequencer (ch.15) | ⬜ | 8 MIDI tracks, notes/CC, MIDI LFOs. MIDI state found; engine not |
| MIDI I/O & sync (8.7) | ⬜ | MIDI parser, clock sync, transport, Turbo MIDI, CC control. Config found; UART/parser not |
| Audio editor (ch.13) | ⬜ | Trim/slice/loop points/timestretch setup. Untouched |
| Mixer / routing / audio crossfader (8.8, 11.6) | 🟡 | **The per-frame mute/solo/cue gate `FUN_40004db8` is fully mapped and hardware-confirmed as *the* gate** (that is MUTE MODE), along with the voice rebind/retrigger paths around it. Main/Cue levels, thru and the audio crossfader: untouched |
| UI framework (menus, display, LEDs, encoders) | 🟡 | Considerably more than before: the dialog builder `FUN_4006d57c`, the self-timing notification `FUN_4005a2b8`, the modal window/overlay **stack** (`FUN_40031494` push / `0x4003146c` pop, both idempotent) and its single popup slot, the **keymap layer** system with per-key held-flags (`0x46c7d8ee`, 24-B stride) and per-overlay dispatch records, the PERSONALIZE menu arrays, and the `[PTN]`/`[BANK]` press/release window gestures. Display driver and encoder input: still untouched |
| USB disk mode (8.5.1) | ⬜ | Untouched |
| System/service: Test mode, Card tools, Personalize, Empty reset (18.1-18.5) | ⬜ | Untouched |
| Metronome (8.6.6) | ⬜ | Click track. Untouched |

## Newly-mapped territory from the 2026-09-24 ingest

Two subsystems this matrix had no entry for now have an address-level starting point
(see `reference/kb/memory-map.md`):

- **The ARRANGER** — previously unmapped entirely. The arrangement lives in battery
  NVRAM at `0x10000004` (pointer at `0x10000000`): header `+18` = row count, rows at
  `+20`, **22 B each, 48 cap**, with row type / pattern byte / repeat / scene A,B /
  OF / Ln attributed. `arranger_goto 0x4004a5c0` calls **the same
  `seq_goto_pattern 0x400a0570`** the pattern-change path uses, so it inherits that
  path's light part-apply. On-card as `arr01..arr08.work`/`.strd`, 11,336 B,
  `FORM`/`DPS1`/`ARRA`.
- **Trig conditions / FILL** — the A:B cycle counters are 16 × u32 at `0x46107918`
  (audio 0-7, MIDI 8-15), advanced by `0x400a536c` on a track step wrap; per-track
  pending FILL is 16 × u8 at `0x46107969`, promoted at the next pattern boundary.

Also now covered at address level: **scene locks + crossfader morph** (store geometry via
`scene_param_get 0x40031f44`, the frame-ISR morph pair `0x4000c202`/`0x4000cc60`, endpoints
`0x80000ed4`), **input-map registration as a layer stack** (`0x40031494`), the **FS vtable**
(`0x46c823fa`) and its recursive walker (`0x40090a14`), and the **RTOS's callable
primitives** (queue post/receive, mutex, task create) — the last of which makes "hand work
to the engine task" a supported option for a feature rather than a guess.

## Summary

- **Done thoroughly (✅)**: ~5 subsystems — the system "plumbing" (boot, kernel, storage,
  update, HW map) plus the sequencer clock. The scaffolding: we understand *how the machine
  works*.
- **Partial (🟡)**: ~11 — and the partial column is where the last year of work went. The
  audio data model, the sequencer bridge and its per-tick step engine, p-locks and the
  trig-type layer, pattern scales, the machine/sample-slot binding, the mute/solo gate, the
  recorder record, the UI's window/keymap/popup machinery, the project format, and one DSP
  effect. Most of these were opened *because a bug fix or a feature needed them*, which is
  why the coverage is deep and narrow rather than broad.
- **Untouched (⬜)**: ~8 — timestretch, 16 of the 17 effects, the playback engine, scenes and
  the crossfader, LFOs and the LFO designer, the arranger, the MIDI subsystem, the audio
  editor, USB disk mode.

**The honest shape of it:** this project understands the Octatrack's *control plane* well and
its *signal plane* barely. Every behaviour mod here works by intercepting control-side
decisions — which voice gets which sample, whether a trig fires, when a pattern commits, what
the mute gate does — and none of them synthesize or process audio, with the single exception
of the side-chain compressor's DSP work.

## Suggested priorities (highest value first)

1. ~~Close out the sequencer clock~~ ✅ **DONE** — sample-accurate, frame ISR + phase
   accumulator; the per-clock-tick step engine and the commit path are mapped too.
2. ~~Locate and extract the DSP56xxx program~~ ✅ **DONE** — `out/dsp_region.bin`, DSP56300,
   ~188 KB, two payloads (A = tracks 5–8, B = tracks 1–4). ~~Disassemble it~~ ✅ **DONE** —
   toolchain in `vendor/dsp56300/`, module map distilled, dsp56kEmu + a dual-core harness in
   `tools/dsp56300_xcore/`, and one effect (DynamiX COMPRESSOR) fully reversed and extended
   on hardware. **Still open: the other 16 effects and timestretch.**
3. **Sample playback engine** (ColdFire side): FLEX vs STATIC, how voices are fed to the DSP.
   Partly opened by the machine/slot-binding work — the resolver and the per-track pre-image
   are mapped, the playback itself is not.
4. **Sequencer depth** — the remaining half: conditional-lock *evaluation*, micro-timing
   *application*, sample locks, and scenes/crossfader morphing. P-locks, the trig-type layer
   and pattern scales are already mapped.
5. **MIDI subsystem** (parser, sync, MIDI seq) and the **display/encoder** half of the UI —
   the menu/window/keymap half is now mapped.

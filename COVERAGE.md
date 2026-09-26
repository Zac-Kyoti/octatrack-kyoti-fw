# RE coverage — what THIS project has mapped

**What this file is:** a map of **OT Kyoti FW's own** reverse-engineering coverage —
which parts of OS 1.40C this project understands well enough to modify, and which are
still dark — cross-referenced against the feature set in the official manual (146 pp.).

**What it is not:** a survey of Octatrack RE as a whole. Other projects have mapped
things this one has not. Their findings, with per-fact attribution, live in
[`reference/kb/`](reference/kb/), and the projects themselves are indexed in
[`reference/EXTERNAL_RESEARCH.md`](reference/EXTERNAL_RESEARCH.md) and credited in
[`CREDITS.md`](CREDITS.md). Where this project has absorbed such a finding without
exercising it in a build, the row below says so — that distinction is the point.

**Scope:** the **ColdFire** control plane *and* the **DSP56300** signal plane, on OS
1.40C, hardware **MKI**. (The scope rule the research-ingest tooling triages against
now lives in [`CLAUDE.md`](CLAUDE.md), not here.)

Legend:
**✅ mapped and exercised** — substantially understood *and* relied on by a build
here, with no major gap left ·
**🟡 partial** — key addresses found and often exercised, but a named part is still
missing ·
**📖 borrowed** — known only from another project's work, distilled into `kb/`, never
exercised here · **⬜ untouched**

## Two planes, both in scope

The MAIN OS is the **control plane**: UI, sequencer, files, and the assembly of voice
parameters. The **signal processing** — sample playback, timestretch and the 17
effects — runs on the **DSP56300**, whose program is a separate ~188 KB binary the
ColdFire uploads at startup (`FUN_40001d4c`, 24-bit words).

Both are in scope for this project. The DSP blob is extracted (`out/dsp_region.bin`),
carries two payloads (A = tracks 5–8, B = tracks 1–4), and this repo has a working
DSP56300 toolchain, a module map, an emulator and a dual-core harness. One effect, the
**DynamiX COMPRESSOR**, is fully reversed and has been *extended on hardware* — the
side-chain `KEY` input, which is shipped DSP56300 assembly. So the signal plane is a
second front here, opened and load-bearing but far from finished: **16 of the 17
effects and all of timestretch remain untouched.**

The honest asymmetry: this project understands the control plane well and the signal
plane narrowly. Every behaviour mod except the side-chain compressor works by
intercepting a control-side decision — which voice gets which sample, whether a trig
fires, when a pattern commits, what the mute gate does — not by processing audio.

## Coverage matrix

| Subsystem (manual ch.) | Status | What this project has / what is missing |
|---|---|---|
| Hardware & boot | ✅ | ColdFire CPU, DSP boot, memory map, the `'ANDY'` battery-SRAM block and its checksum (MUTE MODE persists a word there; the boot restore path `0x4001fb24` is mapped). Missing: codec/DAC-ADC init, panel scan, display driver |
| OS format & update (8.5.2, ch.18) | ✅ | ELUP/ELEK/aPLib, checksums, validation, ATA write, MIDI upgrade. Complete — every build here round-trips through it |
| Kernel / RTOS / scheduler | ✅ | Context switch, priority queues, PIT, `TRAP #0`, and the callable primitives (queue post/receive, mutex, task create). ⚠️ `FUN_40000c3c`, the post/wake, is why a UI call from a frame hook crashed a unit — see `CLAUDE.md`. Missing: full task list, allocator |
| ATA/CF storage | ✅ | ATA stack (PIO/DMA), driver + vtable, registers; the FS vtable (`0x46c823fa`) and its recursive walker (`0x40090a14`) |
| File hierarchy: Sets/Projects/Audio Pool (ch.4,7,8) | 🟡 | **RELOAD FROM PROJECT reads real pattern slabs off the card**: the bank `.work`/`.strd` pair, per-track sequence extents, and the Part copy associated with a pattern. Project settings serialization mapped. Missing: sample-pool bookkeeping, and writing (this project only reads) |
| Audio engine (voices) | 🟡 | Voice data model (`0x800049d8`, stride `0xA8`), mailboxes, the control-rate frame builder and the DSP handoff — enough to gate and rebind voices. Missing: voice parameter computation, envelopes, amp modulator |
| Sample playback: FLEX vs STATIC | 🟡 | The **sample-slot resolution** path is mapped and fixed (below); the playback engine itself is not decompiled. FLEX = RAM, STATIC = streamed from CF |
| **Timestretch** (NORMAL/BEAT) | ⬜ | On the DSP. Untouched |
| **Effects — Appendix B (17 FX)** | 🟡 | **DynamiX COMPRESSOR fully reversed and extended on hardware** (param map `r6+$0..5` = ATK/REL/THRS/RAT/GAIN/MIX, `+$c` = RMS, detector tap `x:(r0)+`; plus a cross-core key path). SPRING REVERB's module bounds mapped — it is the donor. The DSP module/dispatch table is mapped. **The FX UI tables are mapped too**: per bus, `LIST` (chooser rows), `ID2POS` (cursor) and `ID2E` (id → parameter-page descriptor, FX1 `0x400d5f58` / FX2 `0x400d5fdc`) — stock's own "unavailable on this bus" convention. The other 15 effects: untouched |
| Machines — Appendix A (FLEX/STATIC/THRU/NEIGHBOR/PICKUP) | 🟡 | Dispatch by type (`FUN_40097168` → 0-4). **The FLEX/PICKUP slot binding is mapped and fixed**: the per-track pre-image `0x8000082f + track*0x48`, re-seeded by `FUN_40001f18(bank, part, track)`, which stock pairs with a kill bit only when a track *enters* PICKUP — that asymmetry was the Part-change carryover bug. Machine *logic* not decompiled |
| Track recorders / Pickup / sampling (ch.9) | 🟡 | The recorder **record/cache** in the Part is mapped and re-applied by the carryover fix; PICKUP slot ownership mapped. The recording path into buffers is still only glimpsed |
| Sequencer: clock / tick | ✅ | **Sample-accurate**: clocked by the audio frame ISR (`0x4000aad0`) via a `2³¹/tempo` phase accumulator, waking the seq task through a kernel queue |
| Sequencer: trig → voice | 🟡 | `FUN_400977cc` maps trig → voice command; the per-tick step engine (ISR `0x400a1e0c`), the pattern commit (`0x400a44d0`) and its per-track rebuild tail, the dispatch region `0x400a2xxx`, and the per-track step/prev-step arrays are all mapped — this is DIRECT JUMP's territory |
| Trig types / p-locks / sample locks (12.4-12.6) | 🟡 | **Substantially mapped and exercised from both sides.** The 16 per-pattern p-lock arrays (8 audio + 8 MIDI) and the trig-type layer are read *and written* by shipped fixes: the content predicate `FUN_4009a464` (empty-pattern LED), the stored-p-lock writer `FUN_40042158`, and the erase path `opcode 8` → `FUN_40041af4` → `FUN_40038874` (trigless-lock auto-remove). Sample locks untouched |
| Pattern scales / conditional locks / micro timing / fill (12.12-12.15) | 🟡 | **Scales mapped in depth** (DIRECT JUMP): `LEN_TBL` ticks-per-step, master ticks-within-step `0x800065b6`, master step `0x800065b2`, per-track scale-index/length/countdown arrays, MASTER LENGTH, and the tick-vs-step domain distinction that is the open problem there. **Trig conditions / FILL** are located: the A:B cycle counters are 16 × u32 at `0x46107918`, advanced by `0x400a536c` on a track step wrap, and per-track pending FILL is 16 × u8 at `0x46107969`, promoted at the next pattern boundary (📖 borrowed, not exercised). Condition *evaluation* and micro-timing *application* are not decompiled |
| **Scenes & crossfader** (10.3) | 🟡 | The scene-morph **retrigger entry point** is used by the carryover fix. Store geometry (`scene_param_get 0x40031f44`), the frame-ISR morph pair (`0x4000c202`/`0x4000cc60`) and the endpoint buffers (`0x80000ed4`) are mapped at address level (📖 borrowed). The morph *itself* — the OT's flagship feature — is not decompiled |
| **LFO designer** / LFOs (11.4) | ⬜ | 3 LFOs per track, custom shapes. Untouched here; `kb/octakit-abi.md` carries borrowed LFO-designer addresses |
| Arranger / song mode (ch.14) | 📖 | Not touched by any build here, but mapped at address level: the arrangement lives in battery NVRAM at `0x10000004` (pointer `0x10000000`), header `+18` = row count, rows at `+20`, **22 B each, 48 cap** (row type / pattern / repeat / scene A,B / OF / Ln); on-card as `arr01..arr08.work`/`.strd`, 11,336 B, `FORM`/`DPS1`/`ARRA`. `arranger_goto 0x4004a5c0` calls **the same `seq_goto_pattern 0x400a0570`** the pattern-change path uses, so it inherits that path's light part-apply |
| MIDI sequencer (ch.15) | 🟡 | The 8 MIDI tracks' **stored** state is mapped and exercised — MIDI p-lock arrays (empty-pattern LED fix), per-track MIDI sequence reload (RELOAD), and the MIDI-vs-audio track distinction that caused a real bug. The MIDI *engine* (note/CC generation, MIDI LFOs) is not decompiled. ⚠️ the MIDI twin of the sequencer commit tail (`0x400a4cb0` area) is **unpatched** where DIRECT JUMP patches the audio one |
| MIDI I/O & sync (8.7) | ⬜ | Parser, clock sync, transport, Turbo MIDI, CC control. Config found; UART/parser not |
| Audio editor (ch.13) | ⬜ | Trim/slice/loop points, timestretch setup. Untouched |
| Mixer / routing / audio crossfader (8.8, 11.6) | 🟡 | **The per-frame mute/solo/cue gate `FUN_40004db8` is fully mapped and hardware-confirmed as *the* gate** (MUTE MODE), with the voice rebind/retrigger paths around it and the per-track DSP frame words that carry level and trig state. Main/Cue levels, thru and the audio crossfader: untouched |
| UI framework (menus, display, LEDs, encoders) | 🟡 | The dialog builder (`FUN_4006d57c`), the self-timing notification and its live handle (`FUN_4005a2b8`, handle `0x460d1e70`, countdown `0x460d1e6c` — this is QUANTIZE LIVE REC's gate), the modal window/overlay **stack** (`FUN_40031494` push / `0x4003146c` pop, idempotent) and its single popup slot, the **keymap layer** system with per-key held flags (`0x46c7d8ee`, 24-B stride) and per-overlay dispatch records, the PERSONALIZE menu arrays, and the `[PTN]`/`[BANK]` press/release window gestures. Display driver and encoder input: untouched |
| USB disk mode (8.5.1) | ⬜ | Untouched here. `octemu` implements USB-MIDI and a USB-Audio tap (📖, `kb/`) |
| System/service: Test mode, Card tools, Personalize, Empty reset (18.1-18.5) | 🟡 | PERSONALIZE's menu arrays and one of its settings (QUANTIZE LIVE REC) are mapped and driven from the front panel. Test mode, Card tools and Empty reset: untouched |
| Metronome (8.6.6) | ⬜ | Untouched. The one datum: RELOAD is hardware-confirmed not to restart it, so whatever drives it is independent of the sequence reload path |

## Verification coverage

Distinct from firmware coverage, and worth stating because it bounds every claim above:

- **Route A** (octabam's Unicorn ColdFire harness) boots our real patched images, mounts
  a card, loads a project and runs the sequencer. It proves **control flow and logic**.
- **`ot_emu`** (octabam's C++ ColdFire + DSP56300 port) renders real audio and runs
  ~11x faster; `--steps` drives multi-phase diagnostics natively.
- **dsp56kEmu** via `dsp_host` plus `tools/dsp56300_xcore/` covers the DSP side.
- **Neither proves hardware behaviour.** Three separate bugs here were invisible to both
  and only fell to an on-screen diagnostic build on the unit: scratch RAM at
  `0x80006a40+` not surviving under live audio, a frame-hook UI call crashing the unit,
  and DIRECT JUMP's non-1x phase error. "Emulator green" is evidence about the logic,
  never about the machine.

## Where the remaining value is (highest first)

1. **DIRECT JUMP's non-1x scales** — the one unfinished feature, and the only open
   thread. V5.7 awaits a flash; see `reference/handoffs/DIRECTJUMP_PHASE_HANDOFF.md`.
2. **Sample playback engine** — the resolver and per-track pre-image are mapped; the
   playback itself is not. The natural next depth on the control side.
3. **Scenes & crossfader morph** — address-level starting points exist (borrowed); this
   is the OT's flagship feature and the largest untouched control-plane subsystem.
4. **The other 16 DSP effects and timestretch** — the toolchain, the module map and one
   worked example (COMPRESSOR) all exist, so the cost here is now effort, not access.
5. **Sequencer depth** — conditional-lock *evaluation*, micro-timing *application*,
   sample locks; and the **MIDI twin** of the commit tail that DIRECT JUMP leaves unpatched.
6. **MIDI I/O** (parser, sync) and the **display/encoder** half of the UI.

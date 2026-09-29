```
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▐░░  O T   K Y O T I   F W   ·   custom Octatrack firmware  ░░▌
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
```

# OT Kyoti FW

> Welcome Elektron fans. I'm Zac Kyoti, a musician and music tech hacker located
> on the US west coast. This repo contains knowledge and tools that may be used
> to research and explore modifications to the Octatrack stock firmware.
>
> **Design Philosophy:** KYOTI firmware is designed as a set of new or extended features, QOL
> improvements, and bugfixes, not available in the factory firmware, which can be
> applied individually, in combination, or as a comprehensive build. All mods are
> designed to cleanly interlock. The KYOTI firmware design perspective comes
> foremost from a place of deep respect and appreciation for the architecture of
> these instruments before any mod is applied. As such, my approach is to make the
> modded instrument "feel" like stock — customizations appearing seamless,
> respecting existing UX/UI conventions, and (ideally) stage-ready and bug-free.
> KYOTI firmware is not about complete overhaul of the instrument's plumbing (there
> are plenty of other projects that do that, which you may consider combining with
> KYOTI); it's more about making the stock instrument the best version of
> itself it can be. Read on and enjoy!
>
> The features list on the `main` branch will be updated as new builds roll out.

Influenced by the concepts of [`mxldyn/octamax`](https://github.com/mxldyn/octamax)
by Maxolydian and other Octatrack RE projects — full credits in [`CREDITS.md`](CREDITS.md).

---

## Builds

You bring your own copy of the official **OS 1.40C**; the tools analyze it and
produce a modified image, byte-for-byte reproducibly from *your* copy. No Elektron
binary is included or distributed. Every mod is **off by default** — a freshly
flashed unit is indistinguishable from stock until you opt in.

Which builds have run on real hardware is tracked in
[Hardware-test status](#hardware-test-status) — **read it before you flash.**

**One branch.** `main` carries everything — the finished features, anything unfinished,
the research notes and the diagnostics. There is no separate work-in-progress branch to
hunt through. Instead, **each builder tells you what tier it is in before it runs**:

| tier | what it means | what the builder does |
|---|---|---|
| **FINAL** | flashed on the author's MKI and working | builds |
| **PREVIEW** | incomplete, but safe to try and useful as far as it goes | says what is unfinished, then builds |
| **WIP** | the author's own flash-and-measure loop; expected to be wrong | **refuses** unless you set `KYOTI_ALLOW_WIP=1` |
| **SUPERSEDED** | a dead end or an intermediate stage, kept so its reasoning stays readable | **refuses** unless you set `KYOTI_ALLOW_SUPERSEDED=1`, and names what replaced it |

Everything below is FINAL. `tools/` also holds fourteen SUPERSEDED builders — earlier
stages of MUTE MODE, the side-chain, RELOAD and DIRECT JUMP, three of which never worked on
hardware at all — and any work-in-progress builder refuses to run without
`KYOTI_ALLOW_WIP=1`. The superseded ones stay because the reasoning and the measurements in
them are worth reading, and they are gated so that browsing `tools/` cannot turn into
flashing a dead end. The gates are a
courtesy, not a lock; `tools/kyoti_status.py` is all of it.

### Extended Features

- **MUTE MODE** — choose how an audio track's mute behaves, in PERSONALIZE:
  - `OT` — stock, byte-for-byte
  - `OTFX` — hard dry cut, but FX inserts ring their tails and the sequencer keeps
    running underneath, so unmuting picks up where the pattern would have been
  - `OTFX-T` — the same cut and ringing tails, and new trigs stay suppressed until
    you unmute
  - `DT-T` — Digitakt-style: a sounding voice rides out its own amp envelope and FX
    ring, and only new trigs are suppressed

  SOLO follows the same rule as a manual mute; `CUE MUTES TRK` stays a hard cut in
  every mode. Your choice is held in battery-backed SRAM, so it survives a power
  cycle.
  → [`tools/build_mutemode_dt.py`](tools/build_mutemode_dt.py)

- **DIRECT JUMP** — an optional immediate pattern change, toggled with **`[PTN]` +
  `[YES]`** (a toast confirms; it comes up OFF at every power-on). A cued pattern takes
  over on the next step instead of waiting for the current one to finish, **locked to the
  master clock**: it plays exactly where it would be had it been running since START,
  whatever its track lengths, scales or master settings — never shifted by a step, never a
  fraction of a step off, and its first trig always wins. The Part, START SILENT and trig
  conditions change as on a stock pattern change, and the last MIDI Program Change sent
  always names the pattern that plays. The arranger and chains are untouched, and with
  DIRECT JUMP OFF pattern changes are stock. The Analog Rytm's DIRECT JUMP, by contrast,
  lands shifted or fractional whenever lengths or scales differ. Design:
  [`reference/handoffs/DIRECTJUMP_V7_DESIGN.md`](reference/handoffs/DIRECTJUMP_V7_DESIGN.md);
  sequencer bugs found on the way:
  [`reference/OT_SEQUENCER_BUGS.md`](reference/OT_SEQUENCER_BUGS.md).
  → [`tools/build_directjump_v7.py`](tools/build_directjump_v7.py)

- **SIDE-CHAIN COMPRESSOR** — an external key input for the stock DynamiX
  COMPRESSOR, on the effect's **page 2**:
  - `KEY` — which of the eight audio tracks drives the compression; it keys even
    when that track is muted, and reaches any of the 8, not just the four sharing
    the compressor's own DSP core
  - `KGN` — trims the key signal
  - `KFLT` — filters the key: below centre low-pass, above centre high-pass,
    centre off
  - `MON` — auditions the filtered key

  The DSP code space comes from **SPRING REVERB**, which is removed from the FX2
  effect list. A project that still has it in a slot loads as **NONE** — NONE's
  page, no knobs, `NONE` in the name field.
  → [`tools/build_sidechain3.py`](tools/build_sidechain3.py) →
  `OCTATRACK_SIDECHAIN3_CROSS`

- **RELOAD FROM PROJECT** — reload one track's sequence from the CF card **without
  stopping the transport**. Stock can only reload a whole bank, and doing so stops
  the sequencer. Two direct chords, no modal window and no timeout:
  - **`[PTN]` + `[TRACK n]`** — reload that track's card-saved sequence, Part
    untouched
  - **`[BANK]` + `[TRACK n]`** — the same, and re-apply the saved Part

  It reloads the pattern that is *playing*, on an audio or a MIDI track, and never
  restarts the sequence or the internal metronome. A stock-style toast confirms when
  the reload has **finished** — and says so if the trigs did not land.
  → [`tools/build_reload3.py`](tools/build_reload3.py) ·
  spec [`reference/RELOAD_REDESIGN.md`](reference/RELOAD_REDESIGN.md)

- **REPITCH KYOTI** — three new **TSTR** settings on a STATIC or FLEX track's SETUP page
  (`[FUNC]` + `[SRC]`): the sample follows the project tempo by **varispeed**, the way a
  classic sampler or a turntable would — speed and pitch move together, nothing is
  stretched. The tempo comes from the sample's own tempo attribute (audio editor, ATTR),
  so check it is right; a sample whose tempo is outside 30–300 BPM plays as stock. Each
  setting has its own character:
  - `RPCH` — the Octatrack's own playback, clean
  - `RPS9` — an Akai S900/S950: a virtual 40 kHz, 12-bit sampler
  - `RPSP` — an E-mu SP-1200: 26.04 kHz, 12-bit, drop-sample, heard through its
    channel 1/2 low-pass filter. The track's AMP envelope opens the filter the way DECAY
    did on the SP: a short envelope closes it with the note, a long HOLD keeps it open.

  On a repitch track the **PTCH** knob becomes **QUAN**, a ratio against the tempo:
  `1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1`, exact, so a loop at 3/4 lines back up with the
  pattern instead of drifting. A turn moves one ratio every 3 detents, press + turn every 2.
  QUAN takes p-locks and scene locks like PTCH, and PTCH and QUAN are kept separately:
  switch TSTR back and PTCH is where you left it. In the audio editor, TIMESTRETCH gains `REPITCH`, `RPS9`
  and `RPSP`, so under SETUP `AUTO` each sample plays in its own mode. PICKUP tracks and
  every other TSTR setting are stock.

  The DSP code space comes from **SPRING REVERB**, removed exactly as SIDE-CHAIN removes
  it (a project that still has it loads it as NONE). RPSP costs the DSP about one and a
  half FX1 FILTERs per track; a full core of RPSP tracks under heavy effects has not been
  tried on hardware. Starts from Jannik Aßfalg's Repitch module for octabam
  ([`CREDITS.md`](CREDITS.md)).
  Design: [`reference/handoffs/REPITCH_KYOTI_SCOPE.md`](reference/handoffs/REPITCH_KYOTI_SCOPE.md),
  [`REPITCH_SP_CH12_SCOPE.md`](reference/handoffs/REPITCH_SP_CH12_SCOPE.md).
  → [`tools/build_repitch_kyoti.py`](tools/build_repitch_kyoti.py) →
  `OCTATRACK_OS1.40C_REPITCH_KYOTI`

### QOL Enhancements

- **QUANTIZE LIVE REC toggle** — reach the QUANTIZE LIVE REC setting from the front
  panel instead of PERSONALIZE. Hold **`[REC]`** and tap **`[PLAY]`**: a toast shows
  the current setting. Tap `[PLAY]` again **while that toast is up** to invert it;
  tap again to invert it back. Once the toast has gone (1 s), the next tap just shows
  the setting again. The first `[REC]` + `[PLAY]` still starts live recording exactly
  as on stock.
  → [`tools/build_qlrec.py`](tools/build_qlrec.py)

- **Erase empty trigless locks** — a trigless lock (a step with parameter locks but
  no audible trig) used to stay lit on the trig row forever once you erased its last
  remaining lock, even though it was now inert. It now disappears. A deliberately
  empty trigless lock placed with `FUNC` + `TRIG` is left alone.
  → [`tools/build_triglock.py`](tools/build_triglock.py)

### Bugfixes

- **Bug 1 — MIDI Plays-Free trig fix** — a Plays-Free MIDI track with trig quantize *Direct*
  and pattern scale *Per Track* stalled after its first step on a manual trig.
  → [`tools/build_trigscale_only.py`](tools/build_trigscale_only.py)

  *Until 2026-09-28 the five feature builders each folded this fix into their own image;
  they no longer do.* It is one contribution, and every copy wrote the same patch site —
  which meant that as octabam modules no two of those features could ever be selected
  into the same remix. Flash it on its own, or take a **Bugbuild**, which carries all three.

- **Bug 2 — Empty-pattern LED fix** — a pattern whose only content is parameter locks (on a
  MIDI track, or trigless locks on an audio track, with no trig anywhere) showed as
  an unused slot, its grid LED unlit under `[PTN]`.
  → [`tools/build_pattern_led.py`](tools/build_pattern_led.py)

- **Bug 3 — Part-change carryover** — after a pattern-triggered Part change, stale
  per-track state from the old Part could leak into the new one. Two reproducible
  cases are fixed: a track leaving PICKUP for FLEX kept playing the old Part's
  pickup loop, and a pattern switch into a PICKUP track marked that Part
  edited/unsaved when nothing had changed.
  → [`tools/build_partreapply.py`](tools/build_partreapply.py)

### Comprehensive KYOTI Octatrack Firmware build

- **Bugbuilds** — one image per finished feature, with all three bug fixes folded
  in: MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK, RELOAD3, DIRECTJUMP_V7 and
  REPITCH_KYOTI, each
  as *that feature* + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX. Written to
  `out/Bugbuilds/`, so the standalone per-feature images are left alone. The features
  are never combined with each other, which is why there are seven images and not one.
  Every run rebuilds each feature from its current FINAL builder (and refuses one that
  has been superseded), then asserts the composite's changes are exactly the disjoint
  union of the feature's and the bug fixes' own, with every bug fix byte-equal to its
  current source.
  → [`tools/build_bugbuilds.py`](tools/build_bugbuilds.py)

- **Octatrack KYOTI FW v1.0** *(PREVIEW — flashed and under test on the MKI since
  2026-09-29; the bugs the first flash exposed are fixed and confirmed; one DIRECT JUMP crash
  is still unexplained)* — **every finished feature in one image**: MUTE MODE, SIDE-CHAIN, QUANTIZE
  LIVE REC, TRIGLESS-LOCK AUTO-REMOVE, RELOAD3, DIRECT JUMP V7.0.1, REPITCH KYOTI and the
  three bug fixes. Boot splash and SYSTEM STATUS → OS VERSION read **`KYOTI V1.0`**.
  The caves need ~9.6 KB against the classic cave's 5.9 KB, so the builder spreads them
  over zones with a hardware record elsewhere (midisc's shipping pads) and over stock
  data this image itself makes unreachable (SPRING REVERB's descriptor, the relocated
  PERSONALIZE arrays). Each feature is built by its own FINAL builder in a sandbox at
  the allocated addresses, and the composite is proven to be their disjoint union; the
  two old merge blockers (DIRECT JUMP's power-on default vs MUTE MODE's restore, and the
  `[PTN]` keymap overlay) are resolved and asserted.
  → [`tools/build_kyoti.py`](tools/build_kyoti.py), layout and reasoning in
  [`reference/MERGE.md`](reference/MERGE.md)

See **[`BUILD_KYOTI.md`](BUILD_KYOTI.md)** for prerequisites, the one-time setup,
every build variant, and the version strings.

---

## ⚠️ Before you flash

**This is for personal study.** Updating an Elektron unit with anything other than
official firmware is risky: it puts the warranty in question and can leave the
unit needing the bootloader recovery path. Static analysis of the public OS is
harmless; *writing* a non-official OS to real hardware is not. Nothing here is
endorsed by, supported by, or affiliated with Elektron. If in doubt, don't flash
— just read, disassemble, and learn.

Elektron ships **one OS 1.40C image for the Octatrack MKI and MKII**, and the boot
probe adapts the unit-specific details. All hardware testing in this project is on
an Octatrack **MKI** the author owns; nothing here has been tested on an MKII.

The emulators (Unicorn for the ColdFire, on real image bytes; dsp56kEmu for the
DSP) prove control-flow and the frame-word edits, not how anything *sounds* on the
unit. Keep the official `.syx` on hand — **`[FUNC]` + power on → `[TRIG 3]`**
recovers the unit even from a bad OS, because an OS update never touches the
bootloader. Never cut power during `UPDATING FLASH`. Full procedure and recovery
net: **[`FLASHING.md`](FLASHING.md)**.

### Hardware-test status

All on an Octatrack **MKI**. "Confirmed" means flashed and exercised on the unit.

| element | build | status |
|---|---|---|
| Bug 1 — MIDI Plays-Free trig fix | `build_trigscale_only.py` + every Bugbuild | **confirmed** 2026-08-28 |
| MUTE MODE — all four modes, menu, SOLO | `build_mutemode_dt.py` | **confirmed, final** 2026-09-21 |
| ↳ mode survives a power cycle | `build_mutemode_dt.py` | **confirmed** |
| ↳ OTFX-T: muting a track must not shorten OTHER tracks' notes — broken in every build until 2026-09-29 (a scratch register lost across the note-off call, so the mute edge released an extra track), fixed | `build_mutemode_dt.py` | **confirmed** 2026-09-29 in KYOTI V1.0 (`74459c01…`); same code in the standalone |
| ↳ in KYOTI (with SIDE-CHAIN): a muted SIDE-CHAIN KEY track mutes like OT in every mode, so it keeps driving the COMPRESSOR and SC LISTEN (MON) — broken in every soft mode until 2026-09-29 (the key went silent) | `build_kyoti.py` (`--defsym SC_KEY=1`) | **confirmed** 2026-09-29 (KYOTI V1.0 `74459c01…`) |
| ↳ OTFX-T / DT-T: the trig hook `fresh_bind` no longer overwrites a register stock's callers keep live (`%d3`: a saved status register in one caller, a track index before a jump through a function table in another) — present in every build with those modes until 2026-09-29; a leading suspect for the DIRECT JUMP crash **if** the unit was in OTFX-T or DT-T | `build_mutemode_dt.py` + KYOTI | emulator: renders byte-identical to before in all four modes; **not yet on hardware** |
| DIRECT JUMP V7 — clock-locked jumps: 16 ↔ 7-step NORMAL switches vs the metronome, master 1x ↔ 2x, swing/microtiming, rapid switching | `build_directjump_v7.py` | **confirmed, final** 2026-09-27 |
| ↳ PER-TRACK patterns with mixed lengths and 2x…1/4x track scales | `build_directjump_v7.py` | **confirmed** 2026-09-28 |
| ↳ MASTER LENGTH `INF` | `build_directjump_v7.py` | **confirmed** 2026-09-28 |
| ↳ MIDI tracks | `build_directjump_v7.py` | emulator-locked (every run); **not yet on hardware** |
| ↳ V7.0.1: the Part changes on a jump (V7.0 never changed it); the V7.0 checks re-run on V7.0.1 | `build_directjump_v7.py` | **confirmed** 2026-09-28 |
| ↳ V7.0.1: START SILENT and trig-condition (1:2, A:B) reset on a jump | `build_directjump_v7.py` | emulator-verified against stock value for value; not separately exercised on hardware |
| ↳ V7.0.1: Program Change on fast re-cues (always ends on the pattern that plays) | `build_directjump_v7.py` | emulator-verified; **not yet tested on hardware** |
| ↳ V6.4 — the OT↔AR parity build (AR's own behaviour, shifts included) | `build_directjump_v6.py` (SUPERSEDED) | **confirmed** 2026-09-27 |
| SIDE-CHAIN COMPRESSOR (`KEY`/`KFLT`/`KGN`/`MON`, cross-core) — the KEY/KFLT/KGN/MON behaviour | `build_sidechain3.py` | **confirmed** 2026-09-20 |
| ↳ leaves reverbs on the same DSP core alone — broken until 2026-09-29: the cross-core buffer sat inside the FX2 reverb memory of T3 (and T7), so every track's audio leaked into a DARK/PLATE REVERB there (a muted track audible through it, distorted); moved to memory no stock effect uses | `build_sidechain3.py` | **confirmed** 2026-09-29 in KYOTI V1.0 (`74459c01…`); same code in the standalone |
| ↳ a project still using the donated effect loads as NONE | `build_sidechain3.py` | **confirmed, final** 2026-09-25 |
| RELOAD FROM PROJECT — both chords | `build_reload3.py` | **confirmed, final** 2026-09-25 |
| REPITCH KYOTI — RPCH/RPS9/RPSP follow the project tempo; the 9 QUAN ratios; both DSP cores | `build_repitch_kyoti.py` | **confirmed, final** 2026-09-29 (rev 16; tempo lock since rev 10, 2026-09-27) |
| ↳ RPSP through channel 1/2's filter, opened by the AMP envelope | `build_repitch_kyoti.py` | **confirmed** 2026-09-28 (rev 14) |
| ↳ no crack at the start of a trig in RPS9/RPSP, incl. trigs on a frame boundary | `build_repitch_kyoti.py` | **confirmed** 2026-09-29 (rev 15) |
| ↳ switching TSTR keeps PTCH and QUAN apart, no knob turn needed; QUAN turn speeds | `build_repitch_kyoti.py` | **confirmed** 2026-09-29 (rev 16) |
| ↳ DARK REVERB alongside the engine (broken on rev 10–13) | `build_repitch_kyoti.py` | emulator-verified; not specifically tested on hardware |
| ↳ QUAN p-locks and scene locks | `build_repitch_kyoti.py` | **confirmed** 2026-09-27 (rev 5.1) |
| ↳ RTRG retrigs on a repitch track | `build_repitch_kyoti.py` | not specifically tested |
| Bug 2 — Empty-pattern LED fix | `build_pattern_led.py` | **confirmed** 2026-09-13 |
| Erase empty trigless locks | `build_triglock.py` | **confirmed, final** 2026-09-21 |
| Bug 3 — Part-change carryover: PICKUP→FLEX stuck loop | `build_partreapply.py` | **confirmed** 2026-09-22 |
| ↳ spurious Part-edited flag on entering PICKUP | `build_partreapply.py` | **confirmed** 2026-09-23 |
| ↳ recorder SRC/RLEN and REC SETUP carryover | `build_partreapply.py` | unconfirmed — never reproducible on stock |
| QUANTIZE LIVE REC toggle | `build_qlrec.py` | **confirmed** 2026-09-25 |
| KYOTI V1.0 — every feature in one image | `build_kyoti.py` | **flashed** 2026-09-29, three images: `bf1fff8c…` (trig fix OK; reverb cross-talk, OTFX-T note cut, muted-key silence and one DIRECT JUMP crash found), `74459c01…` (all three fixed, confirmed). Current `597a6db9…` adds the `fresh_bind` register fix — **not flashed**. DIRECT JUMP crash cause not confirmed |
| Bugbuild composites | `build_bugbuilds.py` | **not flashed** — every ingredient above is confirmed, no composite has been on hardware |

Exactly what was tested on each flash, and the failures along the way, are in
[`BUILD_KYOTI.md`](BUILD_KYOTI.md)'s own hardware-test table and
[`NOTES.md`](NOTES.md).

---

## What has been investigated

Verified against the official **OS 1.40C** — from the firmware's own checksums,
byte-exact decompilation, or direct disassembly. This is the reverse-engineering
foundation the mods are built on. Consolidated write-ups:
[`ARCHITECTURE.md`](ARCHITECTURE.md) · address-keyed knowledge base
[`reference/kb/`](reference/kb/) · chronological log [`NOTES.md`](NOTES.md) ·
mapped-vs-untouched [`COVERAGE.md`](COVERAGE.md).

**Hardware.** The CPU is a Freescale/NXP **ColdFire** (likely MCF5445x, 32-bit,
big-endian, ~266 MHz) — a 68000-family core, *not* ARM. Audio is a Freescale
**DSP56721**, two cores, tracks 1–4 and 5–8. Storage is **CompactFlash**
(FAT16/32) over the ColdFire's on-chip ATA controller, reached through the FlexBus.

**Firmware format and update chain.** Elektron ships a ZIP with two transports of
the same OS, both wrapping the same compressed container:

```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK( aPLib( MAIN OS ) ) ) + checksum
.syx  = SysEx 7-bit(              ELEK( aPLib( MAIN OS ) )              )
```

The ELUP layer (`.bin` only) is XOR obfuscation with feedback plus an additive
checksum, reimplemented in `tools/make_bin.py` and validated by regenerating
Elektron's own official `.bin` byte-for-byte. The ELEK layer is a proprietary
container whose aPLib-compressed payload decompresses to the **MAIN OS**
(1,112,560 bytes, base `0x40000400`). There is **no cryptographic signature** on
any layer, which is *why* the format can be repacked with recalculated checksums —
it is not a security bypass.

**Operating system.** A proprietary preemptive microkernel (banner
`ElektronOctatrack DPS-1` — not MQX/ThreadX/VxWorks): Task Control Blocks,
per-priority ready queues, context switch via `TRAP #0`, blocking message queues,
and a time slice driven by the ColdFire PIT timer. The same message-queue pattern
unifies the firmware — the ATA "async queues" and the audio "voice mailboxes" *are*
kernel message queues.

**Audio engine and sequencer.** Eight track voices sit in the `0x80000000`
shared-RAM window. A sequencer trig writes a voice mailbox; a control-rate frame
builder assembles a parameter frame into a **double buffer** and hands it to the
DSP56721 over MMIO, which does the real-time synthesis. The split is **ColdFire =
control** (RTOS, sequencer, parameter assembly) and **DSP = signal** (playback,
time-stretch, filters, FX).

---

## Repository layout

```
START_HERE.md        onboarding + current frontier (read first)
README.md            this file
BUILD_KYOTI.md       build guide: every build_*.py, prerequisites, version strings
FLASHING.md          safe-flashing guide + bootloader recovery (read before flashing)
CREDITS.md           lineage and acknowledgements
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map, container)
COVERAGE.md          what firmware subsystems are mapped vs untouched
NOTES.md             the full chronological reverse-engineering log

reference/kb/        distilled knowledge base (addresses, formats, DSP, code caves)
reference/           MERGE.md allocation map, per-feature specs, external-RE index
reference/handoffs/  per-thread handoffs for the work still open
tools/               build scripts, ColdFire patch sources, emulators, packers
tools/kyoti_status.py  the FINAL / PREVIEW / WIP tier each builder declares
tools/attic/         third-party reference patch sources — RE cross-reference, not built
sysex/               the MIDI Plays-Free fix as JSON hunks + a no-assembler applier
refs/                external-RE repo manifest; the clone cache under it is git-ignored
fetch-os.sh          download + extract the official OS
analyze.sh           entropy + binwalk + strings + container unpack -> out/
setup.sh             clone/patch/build elektron-firmware-tool into vendor/
disasm.sh            radare2 disassembly (m68k BE, base wired)
```

Downloaded Elektron binaries and generated images (`downloads/`, `out/`,
`vendor/*.bin`, `*.syx`, `*.bin`) are **git-ignored on purpose**. The reference
sources in [`tools/attic/`](tools/attic/) are **not** part of any KYOTI build (see
[`CREDITS.md`](CREDITS.md)).

---

## Building

```sh
./fetch-os.sh && ./analyze.sh && ./setup.sh   # one-time: bring your own OS 1.40C + tools
python3 tools/build_mutemode_dt.py            # one feature -> out/OCTATRACK_*MUTEMODE_DT.{syx,bin}
python3 tools/build_bugbuilds.py              # each finished feature + all 3 bug fixes -> out/Bugbuilds/
```

Every build is a **guarded binary patch**: it asserts the stock bytes at each
splice site, checks the code caves are free and non-overlapping, derives every
detour target from the linker symbol table (never hardcoded), and round-trips the
result through `elektron-firmware-tool`. It aborts before writing if the stock
file is wrong, already patched, or a checksum is off. Full walkthrough:
[`BUILD_KYOTI.md`](BUILD_KYOTI.md).

For the MIDI Plays-Free fix there is also a **no-assembler** path —
`sysex/apply_patch.py` applies it from a JSON hunk list (load address + expected
original bytes + replacement bytes); see [`sysex/README.md`](sysex/README.md).

---

## Legality (not legal advice)

- Static analysis of the publicly distributed OS carries **zero risk to the
  hardware** and is the point of this project.
- EU: Directive 2009/24/EC Art. 5 (observe/study/test a program you lawfully use)
  and Art. 6 (decompilation for interoperability). Elektron's EULA may contain
  anti-RE clauses — a contractual matter separate from copyright.
- Private and educational use is low-risk. Redistributing modified binaries is a
  different question; this repo deliberately redistributes **no** Elektron binary.

## License

Original work in this repository (notes, scripts, patch sources, build tooling)
is released under the **[MIT License](LICENSE)**. The exclusions are spelled out
in the LICENSE file. In short: no Elektron firmware or manual is included or
licensed, `tools/attic/` holds third-party reference sources that keep their own status (see `CREDITS.md`), and
third-party code fetched at build time keeps its own license. Code under
GPL-family licenses is used as reference only, never copied in.

---

*OT Kyoti FW is an independent, unofficial, educational project. "Elektron" and "Octatrack" are trademarks of Elektron Music
Machines MAV AB, used here only to identify the hardware under study. Not
affiliated with or endorsed by Elektron.*

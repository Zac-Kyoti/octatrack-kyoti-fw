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
> **Design Philosophy:** KYOTI firmware is designed as a set of features, QOL
> improvements, and bugfixes, not available in the factory firmware, which can be
> applied individually, in combination, or as a comprehensive build. All mods are
> designed to cleanly interlock. The KYOTI firmware design perspective comes
> foremost from a place of deep respect and appreciation for the architecture of
> these instruments before any mod is applied. As such, my approach is to make the
> modded instrument "feel" like stock — customizations appearing seamless,
> respecting existing UX/UI conventions, and (ideally) stage-ready and bug-free.
> KYOTI firmware is not about complete overhaul of the instrument's plumbing (there
> are plenty of other projects that do that, which you may consider combining with
> KYOTI); it's more about making the stock instrument be the best version of
> itself it can be. Read on and enjoy!
>
> The features list on the `main` branch will be updated as new builds roll out.

Built on the method and infrastructure of
[`mxldyn/octamax`](https://github.com/mxldyn/octamax) by Maxolydian — the
container and update-chain analysis, the guarded binary-patch pipeline, the
code-cave detour technique, and the flashing procedure. Full lineage and
acknowledgements: [`CREDITS.md`](CREDITS.md).

---

## Builds

You bring your own copy of the official **OS 1.40C**; the tools analyze it and
produce a modified image, byte-for-byte reproducibly from *your* copy. No Elektron
binary is included or distributed. Every mod is **off by default** — a freshly
flashed unit is indistinguishable from stock until you opt in.

Which builds have run on real hardware is tracked in
[Hardware-test status](#hardware-test-status) — **read it before you flash.**

**Branches.** `main` is the published line and carries everything finished. `wip`
is the active frontier: the DIRECT JUMP thread and the external-RE knowledge-base
ingest are there only. Each branch's own `START_HERE.md` §6 describes that branch.

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
  `[YES]`**. A manually cued pattern switches on the next step tick instead of
  waiting out the current one, and **keeps playing in master time** rather than
  restarting at step 1. It loads the new Part at once and sends the MIDI Program
  Change ~1 step early. The arranger and pattern chains are untouched, and the
  toggle deliberately does not persist — a performance feature comes up OFF on
  every power-on.
  **Still in development — the one unfinished feature.** Confirmed on hardware at
  1x scales. Under a master scale other than 1x a switch can land on a fractional
  step; that work continues on the `wip` branch.
  → [`tools/build_directjump_v4.py`](tools/build_directjump_v4.py) ·
  handoff [`reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md`](reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md)

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

- **MIDI Plays-Free trig fix** — a Plays-Free MIDI track with trig quantize *Direct*
  and pattern scale *Per Track* stalled after its first step on a manual trig.
  → [`tools/build_trigscale_only.py`](tools/build_trigscale_only.py)

- **Empty-pattern LED fix** — a pattern whose only content is parameter locks (on a
  MIDI track, or trigless locks on an audio track, with no trig anywhere) showed as
  an unused slot, its grid LED unlit under `[PTN]`.
  → [`tools/build_pattern_led.py`](tools/build_pattern_led.py)

- **Part-change carryover fix** — after a pattern-triggered Part change, stale
  per-track state from the old Part could leak into the new one. Two reproducible
  cases are fixed: a track leaving PICKUP for FLEX kept playing the old Part's
  pickup loop, and a pattern switch into a PICKUP track marked that Part
  edited/unsaved when nothing had changed.
  → [`tools/build_partreapply.py`](tools/build_partreapply.py)

### Comprehensive KYOTI Octatrack Firmware build

- **Bugbuilds** — one image per finished feature, with all three bug fixes folded
  in: MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK and RELOAD3, each as *that
  feature* + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX. Written to `out/Bugbuilds/`,
  so the standalone per-feature images are left alone. The features are never
  combined with each other, which is why there are five images and not one. Every
  run asserts the composite's changes are exactly the disjoint union of the
  feature's and the bug fixes' own.
  → [`tools/build_bugbuilds.py`](tools/build_bugbuilds.py)

- **Octatrack KYOTI FW v1.0 / v1.1** *(staged; the single all-in-one image is
  deliberately not buildable yet, so a combined image cannot quietly ship an
  unfinished feature)* — **`KYOTI_V1.0`** is the seven finished, hardware-confirmed
  mods; **`KYOTI_V1.1`** adds DIRECT JUMP and RELOAD3 and is held behind two
  builder-assertion conflicts. [`reference/MERGE.md`](reference/MERGE.md) is the
  allocation map it will be built from.

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
| MIDI Plays-Free trig fix | all | **confirmed** 2026-08-28 |
| MUTE MODE — all four modes, menu, SOLO | `build_mutemode_dt.py` | **confirmed, final** 2026-09-21 |
| ↳ mode survives a power cycle | `build_mutemode_dt.py` | **confirmed** |
| DIRECT JUMP — 1x scales | `build_directjump_v4.py` | **confirmed** 2026-09-23 |
| ↳ master scales other than 1x | `build_directjump_v4.py` | **open** — in progress on `wip` |
| SIDE-CHAIN COMPRESSOR (`KEY`/`KFLT`/`KGN`/`MON`, cross-core) | `build_sidechain3.py` | **confirmed, final** 2026-09-20 |
| ↳ a project still using the donated effect loads as NONE | `build_sidechain3.py` | **confirmed, final** 2026-09-25 |
| RELOAD FROM PROJECT — both chords | `build_reload3.py` | **confirmed, final** 2026-09-25 |
| Empty-pattern LED fix | `build_pattern_led.py` | **confirmed** 2026-09-13 |
| Erase empty trigless locks | `build_triglock.py` | **confirmed, final** 2026-09-21 |
| Part-change carryover — PICKUP→FLEX stuck loop | `build_partreapply.py` | **confirmed** 2026-09-22 |
| ↳ spurious Part-edited flag on entering PICKUP | `build_partreapply.py` | **confirmed** 2026-09-23 |
| ↳ recorder SRC/RLEN and REC SETUP carryover | `build_partreapply.py` | unconfirmed — never reproducible on stock |
| QUANTIZE LIVE REC toggle | `build_qlrec.py` | **confirmed** 2026-09-25 |
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
tools/attic/         inherited octamax patch sources — RE cross-reference, not built
sysex/               the MIDI Plays-Free fix as JSON hunks + a no-assembler applier
refs/                external-RE repo manifest; the clone cache under it is git-ignored
fetch-os.sh          download + extract the official OS
analyze.sh           entropy + binwalk + strings + container unpack -> out/
setup.sh             clone/patch/build elektron-firmware-tool into vendor/
disasm.sh            radare2 disassembly (m68k BE, base wired)
```

Downloaded Elektron binaries and generated images (`downloads/`, `out/`,
`vendor/*.bin`, `*.syx`, `*.bin`) are **git-ignored on purpose**. Maxolydian's own
octamax behaviour mods are **not** part of any KYOTI build; their patch sources are
kept in [`tools/attic/`](tools/attic/) for reverse-engineering cross-reference (see
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

---

*OT Kyoti FW is an independent, unofficial, educational project derived from
`mxldyn/octamax`. "Elektron" and "Octatrack" are trademarks of Elektron Music
Machines MAV AB, used here only to identify the hardware under study. Not
affiliated with or endorsed by Elektron.*

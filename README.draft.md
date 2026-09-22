<!--
  DRAFT — not live. Do not merge into README.md yet.

  Assumes everything on wip has been merged into main.
  Before this goes live: run the queued hardware passes (FLASHING.md), then
  update the "Hardware-test status" table and any "emulator only" wording to
  match, and replace README.md with this file.

  Consolidation pass vs the current README:
    - "no Elektron binary distributed" : 5 mentions -> 2 (Builds intro, Legality)
    - "off by default"                 : 3 -> 1 (Builds intro)
    - MKI/MKII one-image fact           : 3 -> 1 (Before you flash)
    - "guarded binary patch" method     : 2 -> 1 (Building)
    - flash status                      : scattered + per-feature -> one table
    - the long per-feature H3 sections were folded into the Builds catalog
      (each entry keeps its mechanism sentence + NOTES.md pointer)
-->

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
flashed unit is indistinguishable from stock until you opt in, and an OS upgrade
resets PERSONALIZE.

Which builds have run on real hardware and which are emulator-only is tracked in
[Hardware-test status](#hardware-test-status) — **read it before you flash.**

### Extended Features

- **MUTE MODE** — a PERSONALIZE choice for how audio-track mute behaves, now
  **four hardware-confirmed modes**: `OT` (stock, byte-for-byte), `OTFX` (hard
  dry cut with FX inserts ringing their tails while the sequencer is left
  alone, so unmuting picks up exactly where the pattern would have been),
  `OTFX-T` (the same dry cut and ringing tails, but a *trig*-mute — new trigs
  stay suppressed until you unmute), and `DT-T` (pure sequencer mute,
  Digitakt-style: a sounding voice rides out its own amp envelope and FX ring,
  only new trigs are suppressed). SOLO gets the same treatment as a manual
  mute; `CUE MUTES TRK` intentionally stays a hard cut in every mode. One
  persisted word in the `'ANDY'` battery-SRAM block holds the mode, so it
  survives a power cycle.
  → [`tools/build_mutemode_dt.py`](tools/build_mutemode_dt.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 9–12", "Session 57–58"

- **DIRECT JUMP** — an optional immediate pattern change, toggled with `[PTN]` +
  `[YES]`: a manually cued pattern switches on the next step tick instead of
  quantizing to the end of the current one, loads the new Part at once, and
  sends the MIDI Program Change ~1 step early. The arranger and pattern chains
  are untouched. The toggle's reachability and switch timing are
  **hardware-confirmed** (`v4` fixed a stock overlay that swallowed the
  toggle's dispatch while `[PTN]` was held — `v1`–`v3` were dead on hardware).
  **Still open:** it currently restarts the new pattern at step 1 instead of
  keeping the playhead position; root-caused but not yet fixed.
  → [`tools/build_directjump_v4.py`](tools/build_directjump_v4.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 15, 21, 35" → "Session 60–79"

- **SIDE-CHAIN COMPRESSOR** — an external key input for the stock DynamiX
  COMPRESSOR: a `KEY` parameter (plus `KEY FLT` / `KEY GAIN` / `SC LISTEN`) on the
  effect's page 2 picks any of the eight audio tracks to drive the compression,
  keying even when that track is muted — reaching **any of the 8 tracks**, not
  just the four sharing the compressor's own DSP core, via a cross-core
  generation-counter/shared-window mechanism. SPATIALIZER is donated for the
  code space. This is a DSP56300 job, built in stages, and is
  **hardware-confirmed on MKI (2026-09-20)**, single-core and cross-core both.
  A very mild HP↔OFF filter-pop remains, filed as research-only — it does not
  block shipping.
  → [`tools/build_sidechain.py`](tools/build_sidechain.py) (menu) ·
  [`tools/build_sidechain2.py`](tools/build_sidechain2.py) (+ DSP) ·
  [`tools/build_sidechain3.py`](tools/build_sidechain3.py) (+ filter / gain /
  listen / cross-core) · write-up [`NOTES.md`](NOTES.md) "Session 17" (+1–8) →
  "Session 77" (×3)

- **RELOAD FROM PROJECT** — reload a single pattern, or a single track, from the
  CF card without stopping playback and without the audio glitch that stock
  whole-bank RELOAD causes. Hold `[PTN]` ~0.5 s for a sticky picker (`TRK SEQ` /
  `PTN SEQ` / `PART + PTN SEQ`); `[YES]` runs it, `[NO]` cancels, no timeout.
  Adapted from the Digitone's RELOAD FROM PROJ. The first hardware flash
  (2026-09-20) found 3 real bugs — a `[PTN]`-held reachability issue (the same
  overlay problem DIRECT JUMP hit) and a permanent picker lockout are fixed but
  **not yet reflashed**; the reload's own timing (an audible gap and a reset to
  step 1) and a proper list-style picker UI are deferred.
  → [`tools/build_reload2.py`](tools/build_reload2.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 42–44, 47" → "Session 80"

### QOL Enhancements

- **QUANTIZE LIVE REC toggle** — a front-panel shortcut for the all-or-nothing
  QUANTIZE LIVE REC setting that otherwise lives only in PERSONALIZE: hold
  `[REC]`, tap `[PLAY]` twice close together, with an on/off toast that closes
  instantly on release. The first `[REC]` + `[PLAY]` still starts live recording
  exactly as on stock. **Hardware-confirmed** after a rewrite: the original
  design flashed and hung the unit (a one-shot toast call tail-jumped into a
  modal window/overlay stack); the fix re-arms a self-timing toast every few
  ticks instead, HW-confirmed with no hang. Two cosmetic issues are parked, not
  chased further.
  → [`tools/build_qlrec.py`](tools/build_qlrec.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 46", "Session 50", "Session 51/51-bis/51-ter"

- **Erase empty trigless locks** — a trigless lock (a step carrying parameter
  locks but no audible trig) left lit on the trig row forever once its last
  remaining lock was erased, even though it was now inert. The handler had been
  mis-identified for about fifty sessions; the real path (`opcode 8` →
  `FUN_40041af4` → `FUN_40038874`) has no `linkw`, which is why function-boundary
  scans kept missing it. The fix sits on the erase store itself, so a
  deliberately empty trigless lock placed with `FUNC`+`TRIG` is never mistaken
  for one that just lost its last lock. **Fixed, hardware-confirmed** (MKI,
  2026-09-21): multi-pass erase, last-lock removal, ordinary trigs, and
  `FUNC`+`TRIG` placeholders all check out.
  → [`tools/build_triglock.py`](tools/build_triglock.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 13", "Session 78"

### Bugfixes

- **MIDI Plays-Free trig fix** — a Plays-Free MIDI track with trig quantize
  *Direct* and pattern scale *Per Track* stalled after its first step on a manual
  trig (`FUN_4009b5c8` seeded the per-track scale index with the *audio*-track
  stride for MIDI tracks). Fixed with a 6-byte detour into a code cave.
  → [`tools/build_trigscale_only.py`](tools/build_trigscale_only.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 5–7"

- **Empty-pattern LED fix** — a pattern whose only content is parameter locks (on
  a MIDI track, or trigless locks on an audio track, with no trig anywhere) showed
  as an unused slot, its grid LED unlit under `[PTN]`. The stock "does this
  pattern have content" predicate (`FUN_4009a464`) scanned each track's trig masks
  but never its p-lock arrays. **Fixed, hardware-confirmed** — flashed to the MKI
  2026-09-13, no regression.
  → [`tools/build_pattern_led.py`](tools/build_pattern_led.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 48"

- **Part-change carryover fix** *(partial — the reported bug is still open)* —
  after a pattern-triggered Part change, stale per-track state from the old
  Part could leak into the new one: three Elektronauts reports describe a
  PICKUP machine still playing its old pickup loop after switching to a
  non-PICKUP one, a recorder track's SRC/RLEN carrying over, and a REC SETUP
  tweak leaking across Parts. Root cause: the pattern-change handler never ran
  Elektron's own full Part-apply (`FUN_40009094`). `tools/patch_partreapply.s`
  was flashed 2026-09-13: the recorder-cache and scene-morph pieces are
  behaviorally safe on hardware, though reports #2/#3 (recorder, REC SETUP)
  could not be reliably reproduced on stock and are treated as unconfirmed.
  **The originally reported #1 bug — a FLEX track stuck playing an old PICKUP
  loop — is NOT fixed:** it reproduces identically on stock and patched on a
  repeated pattern switch. Root cause still open.
  → [`tools/build_partreapply.py`](tools/build_partreapply.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 49", "Session 50"

### Comprehensive KYOTI Octatrack Firmware build

- **Octatrack KYOTI FW v1.0** *(deliberately withdrawn — no combined build
  today)* — every finished mod in one image, with all code caves and shared
  hooks de-conflicted, then round-tripped through the container tool
  (`elektron-firmware-tool`) with the checksums recalculated and verified. The
  build tooling was withdrawn so a single combined image can't quietly ship
  DIRECT JUMP, RELOAD FROM PROJECT, or the part-change carryover fix while
  they're still unfinished; it will be reconstructed from the allocation map
  once every feature is shippable.
  → *(see [`reference/MERGE.md`](reference/MERGE.md))* ·
  write-up [`NOTES.md`](NOTES.md) "Session 45"

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

Elektron ships **one OS 1.40C image for the Octatrack MKI and MKII**; the boot
`0x46c8d18c` probe adapts the unit-specific details. All hardware testing in this
project is on an Octatrack **MKI** the author owns — including the flash that
confirmed the MIDI Plays-Free fix.

The emulators (Unicorn for the ColdFire, on real image bytes; dsp56kEmu for the
DSP) prove control-flow and the frame-word edits, not how anything *sounds* on the
unit. Keep the official `.syx` on hand — `[FUNC]` + power on → `[TRIG 3]` recovers
the unit even from a bad OS, because an OS update never touches the bootloader.
Never cut power during `UPDATING FLASH`. Full procedure and recovery net:
**[`FLASHING.md`](FLASHING.md)**.

### Hardware-test status

| element | build | status (Octatrack MKI) |
|---|---|---|
| MIDI Plays-Free trig fix | all | **confirmed** — flashed 2026-08-28, stall gone, no regression |
| MUTE MODE — all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`), menu, SOLO handling | `build_mutemode_dt.py` | **confirmed, final** — flashed and hardware-tested 2026-09-21, MKI |
| ↳ `'ANDY'`-shadow persistence (survives power cycle) | `build_mutemode_dt.py` | **confirmed** — one persisted word, defaults verified on hardware |
| DIRECT JUMP pattern-change mode | `build_directjump_v4.py` | **active WIP, partly hardware-confirmed** — toggle reachability and switch timing confirmed; playhead-preserving behaviour (currently resets to step 1) is root-caused but not yet fixed |
| SIDE-CHAIN COMPRESSOR (`KEY`/`KEY FLT`/`KEY GAIN`/`SC LISTEN`, cross-core) | `build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | **confirmed, final for now** — flashed 2026-09-20, MKI, single-core and cross-core both |
| RELOAD FROM PROJECT — modal picker | `build_reload2.py` (TRK SEQ / PTN SEQ / PART + PTN SEQ) | **active WIP, partly hardware-confirmed** — first flash (2026-09-20) found 3 real bugs, 2 fixed but not yet reflashed; reload timing and a real list-style picker UI are deferred |
| Empty-pattern LED fix | `build_pattern_led.py` | **confirmed** — flashed 2026-09-13, grid LED lights correctly, no regression |
| Erase empty trigless locks | `build_triglock.py` | **confirmed, final** — flashed 2026-09-21, MKI; multi-pass erase, last-lock removal, ordinary trigs, and `FUNC`+`TRIG` placeholders all preserved |
| Part-change carryover — recorder cache / scene-morph pieces | `build_partreapply.py` | flashed 2026-09-13, behaviorally safe; reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock, treat as unconfirmed |
| ↳ report #1 (PICKUP→FLEX stuck loop) | `build_partreapply.py` | **fix does not address the real bug** — reproduces identically on stock and patched on a repeated pattern switch; root cause still open |
| QUANTIZE LIVE REC toggle | `build_qlrec.py` | **confirmed** — original design hung the unit 2026-09-13; rewrite (periodic re-arm) HW-confirmed, no hang; 2 cosmetic issues parked, not chased further |

---

## What has been investigated

Verified against the official **OS 1.40C** — from the firmware's own checksums,
byte-exact decompilation, or direct disassembly. This is the reverse-engineering
foundation the mods are built on. Consolidated write-ups:
[`ARCHITECTURE.md`](ARCHITECTURE.md); the address-keyed knowledge base:
[`reference/kb/`](reference/kb/); chronological log: [`NOTES.md`](NOTES.md);
mapped-vs-untouched: [`COVERAGE.md`](COVERAGE.md).

### Hardware
- **CPU:** Freescale/NXP **ColdFire** (likely MCF5445x, 32-bit, big-endian,
  ~266 MHz) — a 68000-family core, *not* ARM. The firmware drives the on-chip ATA
  controller in the MBAR region (`0xFC04_51xx`) characteristic of the MCF5445x.
- **Audio DSP:** Freescale **DSP56721** (two cores — tracks 1–4 / 5–8), confirmed
  by the 24-bit word size the boot loader uses uploading the DSP program 3 bytes
  at a time.
- **Storage:** **CompactFlash** (FAT16/32) over the ColdFire's on-chip ATA
  controller, reached through the FlexBus.

### Firmware format and update chain
Elektron ships a ZIP with **two transports of the same OS** — a `.bin` and a
`.syx` — both wrapping the same compressed container:

```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK( aPLib( MAIN OS ) ) ) + checksum
.syx  = SysEx 7-bit(              ELEK( aPLib( MAIN OS ) )              )
```

- **ELUP layer** (`.bin` only): XOR obfuscation with feedback plus an additive
  checksum. Reimplemented in `tools/make_bin.py` / `tools/bin_decode.py`,
  validated by regenerating Elektron's own official `.bin` byte-for-byte.
- **ELEK layer:** a proprietary container whose payload is compressed with
  **aPLib**; it decompresses to the **MAIN OS** (1,112,560 bytes, base
  `0x40000400`).
- **No cryptographic signature** on any layer — the OS is analyzable and, with
  recalculated checksums, rebuildable. That is *why* the format can be repacked;
  it is not a security bypass.
- The updater validates the OS (`FUN_4007f748`) with explicit error codes:
  `-2` not a valid OS · `-3` length · `-4` checksum · `-5` version string
  `<"0156"` · `-6` no downgrade. (`-5` is a version floor, not a unit-model gate.)

### Operating system
- A **proprietary preemptive microkernel** (banner `ElektronOctatrack DPS-1` —
  not MQX/ThreadX/VxWorks). Task Control Blocks, per-priority ready queues,
  context switch via `TRAP #0`, blocking message queues, a time slice driven by
  the ColdFire PIT timer (`0xFC08_0000`).
- The same message-queue pattern unifies the firmware: the ATA "async queues" and
  the audio "voice mailboxes" *are* kernel message queues.

### Audio engine and sequencer
- 8 track voices in the `0x80000000` shared-RAM window (base `0x800049d8`,
  stride `0xA8`).
- Control path: a sequencer trig writes a voice mailbox → a control-rate frame
  builder assembles a parameter frame into a **double buffer** → handshake to the
  **DSP56721** over MMIO at `0x20000000`, which does the real-time synthesis.
- Work split: **ColdFire = control** (RTOS, sequencer, parameter assembly);
  **DSP = signal** (playback, time-stretch, filters, FX).

---

## Repository layout

```
START_HERE.md        onboarding + current frontier (read first)
README.md            this — what the firmware is, and lineage
BUILD_KYOTI.md       roll-your-own build guide
CREDITS.md           lineage and acknowledgements
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map, container)
COVERAGE.md          what firmware subsystems are mapped vs untouched
NOTES.md             the full chronological reverse-engineering log
FLASHING.md          safe-flashing guide + bootloader recovery net (read before flashing)

reference/kb/         distilled knowledge base (address map, formats, DSP) — ours + external RE
reference/            EXTERNAL_RESEARCH.md (mined prior-art repos + workflow), UPSTREAM_INBOX.md
reference/upstream-notes.md   inherited octamax mod-design notes (not part of this firmware)
refs/                MANIFEST.{toml,lock} tracked; the clone cache under it is git-ignored
sysex/               the MIDI Plays-Free fix as JSON hunks + a no-assembler applier
tools/               build scripts, ColdFire patch sources, Unicorn + DSP56300 emulators, packers
tools/attic/         inherited octamax mod patch sources — kept for RE cross-reference, not built here
tools/refs/          sync.py / whatsnew.py — clone + track the external-RE repos
tools/ghidra/        Ghidra headless helpers; attic/ = one-shot probe scripts (provenance)
fetch-os.sh          download + extract the official OS
analyze.sh           entropy + binwalk + strings + container unpack -> out/
setup.sh             clone/patch/build elektron-firmware-tool into vendor/
disasm.sh            radare2 disassembly (m68k BE, base wired)
```

Downloaded Elektron binaries and generated images (`downloads/`, `out/`,
`vendor/*.bin`, `*.syx`, `*.bin`) are **git-ignored on purpose**. Maxolydian's own
octamax behaviour mods (lazy Part transitions, no BANK/PTN countdown, arp
key-scales, LED/encoder "dirty" indicators, boot branding) are **not** part of any
KYOTI build; their patch sources are kept in [`tools/attic/`](tools/attic/) for
reverse-engineering cross-reference (see [`CREDITS.md`](CREDITS.md)).

---

## Building

```sh
./fetch-os.sh && ./analyze.sh && ./setup.sh   # one-time: bring your own OS 1.40C + tools
python3 tools/build_mutemode.py               # -> out/OCTATRACK_*MUTEMODE.{syx,bin}
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

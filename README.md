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

**Branches.** `main` is the published line; `wip` is the active frontier, and it is
currently ahead — the finished part-change carryover fix and the Bugbuild
tooling are on `wip` only. RELOAD3 is final and is on `main`. If you are reading this on `main`, check `wip` for the
newest state.

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
  quantizing to the end of the current one, **keeps playing in master time**
  (the new pattern resumes at `masterStep mod newMasterLen`, each track at
  `that mod trackLen`, rather than restarting at step 1), loads the new Part at
  once, and sends the MIDI Program Change ~1 step early. The arranger and
  pattern chains are untouched, and the toggle deliberately does **not** persist
  — a performance feature comes up OFF on every power-on. The position rule is
  the Analog Rytm's own commit arithmetic, ported instruction for instruction
  after three flashed builds each implemented a different reading of an English
  sentence. **Hardware-confirmed at 1x (MKI, 2026-09-23)**: master time held
  through switches, correct landing step, mixed track lengths (7/12/16) in one
  pattern, MASTER LENGTH respected including `INF`.
  **Non-1x scales — root-caused and fixed, not yet flashed.** Hook P read the
  master step once and used that one value as every track's step index; the two
  are equal only when the master and the track run at the same ticks-per-step,
  which is exactly why 1x worked and nothing else did. The fix changes the hook's
  *input*, not its job: it now reads the per-track quantity stock's own rebuild
  already computed. At 1x it is bit-identical to the confirmed build, so the
  baseline is preserved by construction rather than by testing. Emulator-validated
  on four fixtures with the feature off proven byte-identical to stock — but **not
  on hardware yet**, and it does not explain a separate open report that the steps
  visited depend on which trigs are on the grid, and that LEDs and audio disagree.
  → [`tools/build_directjump_v4.py`](tools/build_directjump_v4.py) ·
  handoff [`reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md`](reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md) ·
  write-up [`NOTES.md`](NOTES.md) "Session 15, 21, 35" → "Session 60–87"

- **SIDE-CHAIN COMPRESSOR** — an external key input for the stock DynamiX
  COMPRESSOR: `KEY` on the effect's page 2 picks any of the eight audio tracks to
  drive the compression, keying even when that track is muted, and reaching **any
  of the 8 tracks** — not just the four sharing the compressor's own DSP core —
  via a cross-core generation-counter / shared-window mechanism. Alongside it,
  `KGN` trims the key (declick-smoothed), `KFLT` is a declicked one-pole filter
  (below centre LP, above centre HP, centre off), and `MON` auditions the
  filtered key. This is a DSP56300 job; the code space is donated by **SPRING
  REVERB**, an FX2-exclusive effect pulled from the FX2 list and null-stubbed for
  older projects — **SPATIALIZER is untouched** and stays a normal selectable
  effect. **Hardware-confirmed on MKI (2026-09-20)**, single-core and cross-core
  both. A very mild HP↔OFF filter-pop remains, filed as research-only; it does
  not block shipping.
  → [`tools/build_sidechain3.py`](tools/build_sidechain3.py) →
  `OCTATRACK_SIDECHAIN3_CROSS` · write-up [`NOTES.md`](NOTES.md) "Session 17"
  (+1–8) → "Session 77" (×3)

- **RELOAD FROM PROJECT** — reload a single track's sequence from the CF card
  **without touching the transport**. Stock can only reload a whole bank, and
  doing so stops the sequencer; what is new is the finer granularity plus staying
  in time with the master clock. Adapted from the Digitone's RELOAD FROM PROJ.
  Two direct chords — no modal window, no arrows, no timeout, no BUSY state:
  **`[PTN]` + `[TRACK n]`** reloads that track's card-saved sequence with the Part
  untouched, and **`[BANK]` + `[TRACK n]`** does the same plus re-applies the
  saved Part (from RAM — the saved copy of the Part currently associated with the
  pattern, using stock's own reload-part routine, so a never-saved Part gets
  stock's own verdict). It reloads the pattern that is *playing*, on an audio or a
  MIDI track, and never restarts the sequence or the internal metronome. The
  result is shown when the reload has actually **finished**, as a stock-style block
  toast: `TRK SEQ RELOADED`, or two lines for `[BANK]` (`TRK SEQ + PART` /
  `RELOADED`, or `TRK SEQ RELOADED` / `SAVE PART FIRST!` when the Part was never
  saved). A built-in check re-reads the restored trigs and shows `SEQ RELOAD LOST`
  / `NOT RESTORED!` if they did not land. SELECT BANK now opens on the `[BANK]`
  release, matching how `[PTN]` behaves. Deleting the picker was right by the bug
  tally: ~13 hardware bugs in the picker/keymap/popup machinery, **none** in the
  worker that does the reload; 10 detours became 6, and the build asserts it pokes
  no keymap record at all.
  **Final — hardware-confirmed on MKI, 2026-09-25.** What was confirmed: the last
  bug, the sequence *sometimes* not coming back while the toast still said
  RELOADED, was traced on the unit with an on-screen diagnostic build. The reload
  had read its own request (which track, audio or MIDI) from a RAM block the unit
  overwrites, so it sometimes reloaded a different, MIDI, track and then checked
  what it had written. The request now lives in the patch's own memory, and the
  user reported every reload issue resolved. Earlier flashes (2026-09-23/24)
  confirmed both chords and reloads "quick and on-time". All-tracks and
  whole-bank variants are deferred by the user.
  → [`tools/build_reload3.py`](tools/build_reload3.py) ·
  spec [`reference/RELOAD_REDESIGN.md`](reference/RELOAD_REDESIGN.md) ·
  write-up [`NOTES.md`](NOTES.md) "Session 42–44, 47" → "Session 80–98"

### QOL Enhancements

- **QUANTIZE LIVE REC toggle** — a front-panel shortcut for the all-or-nothing
  QUANTIZE LIVE REC setting that otherwise lives only in PERSONALIZE. Hold
  `[REC]` and tap `[PLAY]`: a toast shows the **current** setting. Tap `[PLAY]`
  again **while that toast is up** and the setting inverts, with the toast
  re-opening on the new value; tap again and it inverts back. Once the toast has
  gone (1 s), the next tap only shows the setting again. The first `[REC]` +
  `[PLAY]` still starts live recording exactly as on stock, and the toast closes
  instantly when `[REC]` is released. **Hardware-confirmed.** The flip window
  *is* the toast, because both are the same thing — stock's own notification
  handle. The patch deliberately keeps **no state of its own**: an earlier
  version's single scratch word turned out not to survive between key presses on
  real hardware, which no amount of static analysis or emulation had caught.
  → [`tools/build_qlrec.py`](tools/build_qlrec.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 46", "Session 50", "Session 51", "Sessions 92-96"

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

- **Part-change carryover fix** — after a pattern-triggered Part change, stale
  per-track state from the old Part could leak into the new one. Three
  Elektronauts reports drove the investigation; the two that could be reproduced
  are fixed and hardware-confirmed, and the thread is closed. This is the one
  finished feature that lives on `wip` only — `main` still carries the older,
  pre-Session-81 build:
  - **Report #1 (PICKUP→FLEX stuck loop)** — a track left as PICKUP on one Part,
    then switched to a Part where it's FLEX, kept playing the old Part's pickup
    loop, and once it broke it stayed broken on every later pass (a one-way
    latch). Root cause: the voice dispatch reads the sample slot it hands the
    resolver from a per-track pre-image that stock re-seeds only when a track
    *enters* PICKUP, never when it leaves — so the PICKUP slot survives into the
    new FLEX machine. **Fixed, hardware-confirmed** (MKI, 2026-09-22): the
    round trip now plays the correct sample on every pass.
  - **Spurious Part-edited flag** — found while testing #1: a pattern switch
    into a PICKUP track marked that Part edited/unsaved even when nothing
    changed (stock behaviour, not introduced by this fix). **Fixed,
    hardware-confirmed** (MKI, 2026-09-23) with a snapshot-and-restore detour
    that preserves a genuine edit made before the switch.
  - Reports #2/#3 (a recorder track's SRC/RLEN carrying over; a REC SETUP tweak
    leaking across Parts) could never be reliably reproduced on stock and
    remain unconfirmed. The recorder-cache and scene-morph mechanisms this fix
    also addresses are behaviorally safe on hardware regardless.
  → [`tools/build_partreapply.py`](tools/build_partreapply.py) ·
  write-up [`NOTES.md`](NOTES.md) "Session 49", "Session 50", "Session 81"

### Comprehensive KYOTI Octatrack Firmware build

- **Bugbuilds — every finished feature, with all three bug fixes folded in.**
  MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK and RELOAD3, each composed with
  PARTREAPPLY + PATTERNLED + PLAYSFREEFIX, written to `out/Bugbuilds/` so the
  standalone per-feature images are left alone. Each composite is built *onto*
  the finished feature image rather than re-derived (SIDE-CHAIN's DSP payloads
  and descriptor edits pass through untouched), with cave placement automatic and
  an interlock proof asserted on every run: caves all-zero before use, exact stock
  bytes at every detour site, no branch into a detour site, and a byte-level check
  that the composite's delta vs stock is exactly the *disjoint* union of the
  feature's delta and the bug fixes' own. All four report clean. Not yet flashed —
  every ingredient is individually hardware-confirmed, the composites are not.
  → [`tools/build_bugbuilds.py`](tools/build_bugbuilds.py)

- **Octatrack KYOTI FW v1.0 / v1.1** *(staged; the single all-in-one image is
  deliberately not buildable yet)* — `tools/build_merged.py` stays withdrawn so a
  combined image cannot quietly ship an unfinished feature.
  [`reference/MERGE.md`](reference/MERGE.md) is the authoritative allocation map
  it will be rebuilt from, re-scanned against true stock 2026-09-23: all 27 detour
  sites across all nine mods are distinct with zero byte overlap, the free zone is
  one contiguous 5986-byte run, and the old `[YES]`-handler collision is **gone**
  (DIRECT JUMP v4 reaches its toggle through the `[PTN]` keymap overlay, RELOAD3
  deleted its picker, so neither detours `0x4005e4c8` any more). Hence two stages:
  **`KYOTI_V1.0`** = the seven finished, hardware-confirmed mods, with nothing to
  resolve and 53 % headroom; **`KYOTI_V1.1`** = + DIRECT JUMP v4 + RELOAD3, about 1 %
  headroom now that RELOAD3 is final (234 B larger than when this was measured), behind two builder-assertion conflicts (both DIRECT-JUMP-vs-someone-
  else: the `'ANDY'` restore width it asserts stays stock while MUTE MODE widens
  it, and the `[PTN]`-overlay `[YES]` record it writes while RELOAD3 asserts that
  overlay is byte-for-byte stock).
  → write-up [`NOTES.md`](NOTES.md) "Session 45", "Session 86"

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
| DIRECT JUMP pattern-change mode | `build_directjump_v4.py` | **confirmed at 1x; the non-1x fix is unflashed** — flashed 2026-09-23: master time held through switches, correct landing step, mixed track lengths (7/12/16), MASTER LENGTH respected incl. `INF`, all at 1x. Non-1x scales were root-caused and fixed 2026-09-24 (Hook P was using the master step as every track's step index); emulator-validated, bit-identical to the confirmed build at 1x, **not yet on hardware**. A separate report — visited steps depending on the trigs present, LEDs and audio disagreeing — is unexplained and still open |
| SIDE-CHAIN COMPRESSOR (`KEY`/`KFLT`/`KGN`/`MON`, cross-core) | `build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | **confirmed, final** — flashed 2026-09-20, MKI, single-core and cross-core both. Donor is SPRING REVERB (pulled from the FX2 list); SPATIALIZER untouched |
| RELOAD FROM PROJECT — two direct chords | `build_reload3.py` (`[PTN]`/`[BANK]` + `[TRACK n]`) | **confirmed, final** — flashed 2026-09-25, MKI: the intermittent failure where the toast said RELOADED but the edited sequence kept playing no longer occurs, and the user reports no RELOAD issue remaining. Root cause, found with an on-screen diagnostic build: the reload's own request bytes lived in a RAM block the unit overwrites, so it sometimes reloaded a different (MIDI) track; they now live in the patch's own memory. Earlier flashes 2026-09-23/24 confirmed both chords and reloads "quick and on-time". All-tracks and whole-bank variants deferred |
| Empty-pattern LED fix | `build_pattern_led.py` | **confirmed** — flashed 2026-09-13, grid LED lights correctly, no regression |
| Erase empty trigless locks | `build_triglock.py` | **confirmed, final** — flashed 2026-09-21, MKI; multi-pass erase, last-lock removal, ordinary trigs, and `FUNC`+`TRIG` placeholders all preserved |
| Part-change carryover — recorder cache / scene-morph pieces | `build_partreapply.py` | flashed 2026-09-13, behaviorally safe; reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock, treat as unconfirmed |
| ↳ report #1 (PICKUP→FLEX stuck loop) | `build_partreapply.py` | **confirmed fixed** — flashed 2026-09-22, MKI; the round trip now plays the correct sample on every pass, latch gone |
| ↳ spurious Part-edited flag on entering PICKUP | `build_partreapply.py` | **confirmed fixed** — flashed 2026-09-23, MKI; a genuine edit made before the switch still shows correctly afterward |
| QUANTIZE LIVE REC toggle | `build_qlrec.py` | **confirmed** — original design hung the unit 2026-09-13; rewrite (periodic re-arm) HW-confirmed, no hang; 2 cosmetic issues parked, not chased further |
| Bugbuild composites (feature + all 3 bug fixes) | `build_bugbuilds.py` → `out/Bugbuilds/` | **not flashed** — every ingredient is individually confirmed above and each composite carries a per-run interlock proof, but no composite image has been on hardware |

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
BUILD_KYOTI.md       roll-your-own build guide (every build_*.py, prerequisites, version strings)
CREDITS.md           lineage and acknowledgements
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map, container)
COVERAGE.md          what firmware subsystems are mapped vs untouched
NOTES.md             the full chronological reverse-engineering log
FLASHING.md          safe-flashing guide + bootloader recovery net (read before flashing)

reference/kb/         distilled knowledge base (address map, formats, DSP) — ours + external RE
reference/            MERGE.md (the all-in-one allocation map), AR_DIRECT_JUMP.md, RELOAD_REDESIGN.md,
                      EXTERNAL_RESEARCH.md (mined prior-art repos + workflow), UPSTREAM_INBOX.md
reference/handoffs/   per-thread handoffs for the work still open (DIRECT JUMP scales; RELOAD3's failing-reload thread, now resolved)
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

# Roll your own OT Kyoti FW

This builds a **modified Octatrack OS 1.40C** from *your own* copy of the official
firmware. No Elektron binary is included here or produced for anyone but you; the
build is byte-for-byte reproducible from the stock file.

> **Read [`FLASHING.md`](FLASHING.md) before you flash anything.** Flashing
> non-official firmware risks the warranty and can leave the unit needing the
> bootloader recovery path. Static analysis is harmless; writing to hardware is
> not. All hardware testing is on an Octatrack **MKI** the author owns; nothing here has been tried on an MKII.

> **One branch, three tiers.** `main` carries every build in this repo, finished or
> not, and each builder announces its own tier when you run it — so you never have to
> work out which branch or which file is the real one:
>
> - **FINAL** — flashed on the author's MKI and working. It builds.
> - **PREVIEW** — incomplete, but safe to try and useful as far as it goes. It tells
>   you what is unfinished, then builds.
> - **WIP** — the author's own flash-and-measure loop, expected to be wrong and
>   changing between commits. It **refuses to build** unless you set
>   `KYOTI_ALLOW_WIP=1` in the environment.
> - **SUPERSEDED** — a dead end or an earlier stage of something below, kept only so
>   its reasoning stays readable. It **refuses to build** unless you set
>   `KYOTI_ALLOW_SUPERSEDED=1`, and names what replaced it. Fourteen builders are in
>   this tier; none of them appear in the table below, and three of them never worked
>   on hardware at all.
>
> Everything in the table below is **FINAL**; DIRECT JUMP became FINAL on 2026-09-27
> (`build_directjump_v7.py`; v1–v6 are SUPERSEDED, V6.4 kept as the OT↔AR parity build). The gates
> live in `tools/kyoti_status.py`; they are a courtesy, not a lock, and exist so that
> a diagnostic or abandoned image does not get flashed by accident. See *Hardware-test
> status* below for exact per-item state.

## What you get

| build command | version string | contents |
|---|---|---|
| `python3 tools/build_trigscale_only.py` | `1.40C` (unchanged) | **Bug 1 fix only** — the Plays-Free MIDI manual-trig stall — on otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_pattern_led.py` | `1.40C` (unchanged) | **Bug 2 fix only** — a pattern whose only content is p-locks (MIDI-track locks, or audio trigless locks) no longer reads as an empty slot; its grid LED lights under `[PTN]`. On otherwise-stock 1.40C. **Hardware-confirmed, final.** |
| `python3 tools/build_qlrec.py [VERSTR] [LIVE_DUR]` | `140C_KYOTI` | Bug 1 fix + **QUANTIZE LIVE REC** front-panel toggle, **toast-gated**: hold `[REC]` + tap `[PLAY]` → a toast shows the current QUANTIZE LIVE REC setting; tap `[PLAY]` again *while that toast is up* → the value inverts and the toast re-opens on it; again inverts it back. Once the toast has gone a tap only shows the value again. The first `[REC]`+`[PLAY]` still starts live recording, and the toast closes instantly on `[REC]` release. `LIVE_DUR` (default `0x3c` = 60 = **1.000 s** at the derived 1/60 s UI tick) is the toast's life *and* the flip window — they are the same thing, the OS's own countdown. **Hardware-confirmed working.** |
| `python3 tools/build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | `140C_KYOTI` | Bug 1 fix + the full **SIDE-CHAIN COMPRESSOR** on the COMPRESSOR's page 2: `KEY` (any of the 8 tracks), `KFLT` (declicked one-pole, below centre LP / above centre HP / centre off), `KGN` (declick-smoothed key trim) and `MON` (audition the filtered key). The DSP code space is donated by **SPRING REVERB**, pulled from the FX2 list (a project that still uses it loads as NONE in the UI). **Hardware-confirmed, final** — see below |
| `python3 tools/build_mutemode_dt.py` | `140C_KYOTI` | Bug 1 fix + **MUTE MODE**, all four values: `OT` (stock, byte-for-byte) / `OTFX` (hard dry cut, FX tails ring, sequencer untouched — unmuting resumes at the playhead) / `OTFX-T` (same cut, but new trigs stay suppressed) / `DT-T` (pure sequencer mute, Digitakt-style). SOLO follows the selected mode. **This is the shipping MUTE MODE build.** |
| `python3 tools/build_directjump_v7.py` | `140C_KDJ7` | Bug 1 fix + **DIRECT JUMP V7** (`[PTN]` + `[YES]`, toast; deliberately not persisted — OFF on every power-on): a cued pattern takes over on the next step and lands **exactly where it would be had it been playing since START** — every track, whatever its length, track scale, master length or master scale — so it is never shifted or fractional against the master clock. The outgoing pattern's pending trigs are dropped at the jump (the new pattern's first trig wins); jumping *into* a pattern with slow tracks (1/2x, 1/4x) waits until every track is at a step start. Program Change goes out when you cue and always ends on the pattern that plays (re-cues and cancels included); no MIDI START. **V7.0.1:** the jump changes the Part, applies START SILENT and restarts trig conditions exactly as a stock pattern change does. Arranger and chains untouched; DJ OFF = stock pattern changes. **Hardware-confirmed, final** (2026-09-27). `DJ_DIAG=1` builds an on-screen diagnostic variant (`140C_KDJ7D`, `_V7DIAG` files). The version string is distinct on purpose: SYSTEM STATUS tells you at a glance that this image is the one on the unit. |
| `python3 tools/build_reload3.py` | `140C_KYOTI` | Bug 1 fix + **RELOAD FROM PROJECT**, as two direct chords — no picker, no modal window, no timeout. **`[PTN]` + `[TRACK n]`** reloads that track's card-saved sequence with the Part untouched; **`[BANK]` + `[TRACK n]`** does the same and re-applies the saved Part (from RAM, via stock's own reload-part routine). From the card's last SAVE BANK, **without touching the transport**. **Hardware-confirmed, final** (2026-09-25). The result is shown when the reload has *finished*, and a built-in check reports `SEQ RELOAD LOST` if the trigs did not land. `--diag` builds an on-screen diagnostic variant (`python3 tools/build_reload3.py --diag`, separate `_DIAG` files) |
| `python3 tools/build_partreapply.py` | `1.40C` (unchanged) | **Bug 3 fix only** — Part-change carryover: after a pattern change that links a different Part, forces the full stock Part-reapply path (recorder record, scene morph, `TRK_PART`/`TRK_BANK` consistency) instead of the stock code's partial one, **re-seeds the per-track sample slot a track leaving PICKUP would otherwise keep**, and stops a pattern switch into a PICKUP track from spuriously marking its Part unsaved. On otherwise-stock 1.40C. **Hardware-confirmed, final** — see below |
| `python3 tools/build_bugbuilds.py` | per-image (`BUG_MUTEDT`, `BUG_QLREC`, `BUG_SC3X`, `BUG_TRIGLK`, `BUG_RL3`) | **One image per finished feature, with all three bug fixes folded into it** — MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS, TRIGLOCK and RELOAD3, each built as *that feature alone* + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX. Features are never combined with each other. Writes **only** to `out/Bugbuilds/`, so the standalone per-feature images above are left alone. Composes onto the finished feature image rather than re-deriving it, with an interlock proof asserted on every run. *Not flashed — every ingredient is individually confirmed, the composites are not* |
| `python3 tools/build_triglock.py` | `1.40C` (unchanged) | **Auto-remove an emptied trigless lock** — a LIVE-REC `[NO]`+knob erase that clears a step's last p-lock now also drops the now-purposeless trigless lock, instead of leaving it lit on the trig row indefinitely. An empty trigless lock placed deliberately with `FUNC`+`TRIG` is left alone. On otherwise-stock 1.40C. **Hardware-confirmed, final.** |

All mods are **OFF by default** (`MUTE MODE = OT`; `KEY = OFF`, stored per Part).
A freshly flashed unit is indistinguishable from stock until you opt in.

These are the Bug-1 fix + the Kyoti mods only. The third-party reference patch
sources in [`tools/attic/`](tools/attic/) are **not** built here; they are kept for
reverse-engineering cross-reference. See [`CREDITS.md`](CREDITS.md).

### Hardware-test status

| element | status |
|---|---|
| Bug 1 manual-trig fix (`build_trigscale_only.py`) | **hardware-confirmed, final** — flashed 2026-08-28 |
| Bug 2 p-lock-only pattern shows empty (`build_pattern_led.py`) | **hardware-confirmed, final** — flashed 2026-09-13; the grid LED lights correctly, no regression |
| **MUTE MODE** — all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`), the menu, SOLO handling and persistence (`build_mutemode_dt.py`) | **hardware-confirmed, final** — flashed 2026-09-21 |
| **QUANTIZE LIVE REC** toggle (`build_qlrec.py`) | **hardware-confirmed, final** — flashed 2026-09-25. Two things to expect: **any** toast on screen arms the flip, stock's included (a deliberate trade-off — the patch keeps no state of its own), and two cosmetic issues are parked: a brief textless-box flash, and the PERSONALIZE row not redrawing live. Three earlier builds failed on hardware, twice badly; `NOTES.md` and `FLASHING.md` have that story |
| **SIDE-CHAIN COMPRESSOR**, incl. cross-core `KEY` (`build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS`) | **hardware-confirmed, final** — flashed 2026-09-20; `KEY` / `KFLT` / `KGN` / `MON` all confirmed, single-core and cross-core both. What it costs you: **SPRING REVERB** leaves the FX2 list to donate the DSP code space, and a project that still has it in a slot loads as **NONE** (confirmed 2026-09-25). A very mild HP↔OFF filter pop remains, filed as research-only |
| **RELOAD FROM PROJECT** — two direct chords (`build_reload3.py`) | **hardware-confirmed, final** — flashed 2026-09-25; the user reports no RELOAD issue remaining. All-tracks and whole-bank variants are deliberately not built |
| **Auto-remove an emptied trigless lock** (`build_triglock.py`) | **hardware-confirmed, final** — flashed 2026-09-21 |
| **Bug 3 — Part-change carryover** (`build_partreapply.py`) | **hardware-confirmed, final** — two stock bugs fixed and confirmed: a track leaving PICKUP for FLEX kept playing the old Part's pickup loop (2026-09-22), and a pattern switch into a PICKUP track marked that Part edited when nothing had changed (2026-09-23). Two further reports in the same family (recorder `SRC`/`RLEN`, REC SETUP carryover) were never reliably reproducible on stock and are **not** claimed fixed |
| **Bugbuild composites** (`build_bugbuilds.py` → `out/Bugbuilds/`) | **not flashed.** Every ingredient is confirmed in the rows above, but no composite image has been on hardware. What *is* proven is the composition: each run asserts that the image's every changed byte belongs to exactly one mod, and that no mod's bytes were altered by another |
| **DIRECT JUMP V7** (`build_directjump_v7.py`) | **hardware-confirmed, final** — flashed 2026-09-27: 16 ↔ 7-step NORMAL switches against the metronome, master 1x ↔ 2x, swing / microtiming and rapid switching all clean. Graded before flashing by equality with a never-switched reference run of the same pattern, which passed on NORMAL and PER-TRACK patterns with mixed lengths and 2x…1/4x tracks. **Not yet on hardware: MIDI tracks** (emulator-locked in every run); PER-TRACK jumps with mixed lengths and 2x…1/4x track scales, and MASTER LENGTH `INF`, are hardware-confirmed (2026-09-28). **V7.0.1**: the Part change on a jump is **hardware-confirmed** (2026-09-28, with the V7.0 checks re-run); START SILENT and the trig-condition reset are emulator-verified against stock value for value; Program Change on fast re-cues is emulator-verified, not yet tested on hardware. History: the Session 87 image once called confirmed at 1x was **retracted** (2026-09-26); V6.4, AR's exact behaviour, is kept as `build_directjump_v6.py` (SUPERSEDED). `NOTES.md` Session 108, `reference/handoffs/DIRECTJUMP_V7_DESIGN.md` |

The ColdFire emulator (Unicorn, real image bytes) proves control-flow and the
DSP frame-word edits; the DSP emulator (dsp56kEmu) runs the actual DSP56300
code. Neither proves how anything *sounds* on the unit. `OT` mode is
byte-for-byte stock. Flash at your own risk.

Each build emits, in `out/`:

```
mainos_*.bin                      the patched MAIN OS section
elek_*.bin                        the rebuilt ELEK container
OCTATRACK_OS1.40C_*.syx           MIDI-DIN upgrade transport
OCTATRACK_*.bin                   CF-card OS UPGRADE transport (faster)
```

## Prerequisites

- **Python 3.8+**
- **ColdFire cross-assembler** — `m68k-elf-as`, `m68k-elf-ld`, `m68k-elf-objcopy`
  (targeting `-mcpu=5407`). On macOS: `brew install m68k-elf-gcc` (or a
  `m68k-elf-binutils` formula/tap).
- **Your own copy of the official OS 1.40C** — from
  <https://www.elektron.se/support-downloads/octatrack-mkii>. The same image
  serves MKI and MKII.
- *For `build_sidechain3.py`* — the DSP56300 toolchain (`dsp_asm`,
  `dsp56kDisassemble`) built into `vendor/dsp56300/`, and the external-RE
  clone cache (`python3 tools/refs/sync.py`, which it reads `dsp_modmap.py`
  from). Every other build here is ColdFire-only and needs neither.

## One-time setup

```sh
./fetch-os.sh     # downloads the official OS 1.40C into downloads/ and extracts it
./analyze.sh      # unpacks it -> out/raw/section_3_MAIN_OS.bin  (the decompressed MAIN OS)
./setup.sh        # clones + patches + builds elektron-firmware-tool into vendor/
```

`fetch-os.sh` pulls the Elektron download; if the URL has moved, drop the
`OCTATRACK_OS1.40C.zip` (or the extracted `.syx`) into `downloads/` yourself and
re-run `./analyze.sh`.

## Build

```sh
python3 tools/build_qlrec.py                  # one feature -> out/OCTATRACK_*QLREC.{syx,bin}
# or build_pattern_led.py / build_sidechain3.py (also finished + hardware-confirmed),
# or any other build command from the table above

python3 tools/build_bugbuilds.py              # each finished feature + all 3 bug fixes
                                              #   -> out/Bugbuilds/ (the images above are untouched)
```

There is deliberately **no single all-in-one image**: `tools/build_merged.py` is
withdrawn so a combined build cannot quietly ship an unfinished feature.
[`reference/MERGE.md`](reference/MERGE.md) is the authoritative allocation map it
will be rebuilt from, and it stages the merge as `KYOTI_V1.0` (the seven mods that
were finished when it was written, nothing to resolve) then `KYOTI_V1.1` (+ DIRECT
JUMP and RELOAD3). RELOAD3 has since been hardware-confirmed final; the map has not
yet been re-cut around that.

Every build is a **guarded binary patch**: it asserts the stock bytes at each
splice site, checks the code caves are free / non-overlapping / inside the free
zone, derives every detour target from the linker symbol table (never
hardcoded), and round-trips the result through `elektron-firmware-tool`. It
aborts before writing if anything is off — a wrong stock file, an already-patched
image, or a checksum mismatch.

Pass a custom version string as the first argument if you want
(`python3 tools/build_mutemode_dt.py MY_BUILD`), but the Kyoti builds default to
`140C_KYOTI` and that is what appears on the boot splash and SYSTEM STATUS — except DIRECT
JUMP V7, which stamps `140C_KDJ7` (diag `140C_KDJ7D`) so the image on the unit is
recognisable at a glance.

## The reproducible patch (no assembler needed)

`sysex/` carries the **Bug-1 fix** captured hunk-by-hunk as JSON (load address +
expected original bytes + replacement bytes) and applies it with
`sysex/apply_patch.py` — no cross-assembler required. See
[`sysex/README.md`](sysex/README.md). Everything else — the Bug-2 pattern-LED fix,
MUTE MODE, DIRECT JUMP, side-chain, RELOAD FROM PROJECT, QUANTIZE LIVE REC,
trigless-lock auto-remove and the Bug-3 part-change carryover fix — is build-from-source
only.

## Flashing

See [`FLASHING.md`](FLASHING.md). Short version: MIDI **DIN** (not USB) for the
`.syx`, or **PROJECT → OS UPGRADE** from the CF card for the `.bin` (much
faster). Keep the official `.syx` on hand — `[FUNC]` + power on → `[TRIG 3]`
recovers the unit even from a bad OS, because an OS update never touches the
bootloader. Never cut power during `UPDATING FLASH`. Your CF card, projects and
samples are untouched by an OS update.

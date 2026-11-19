# Building OT Kyoti FW

This builds a **modified Octatrack OS 1.40C** from *your own* copy of the official
firmware. No Elektron binary is included here, and the build is byte-for-byte
reproducible from the stock file.

> **Read [`FLASHING.md`](FLASHING.md) before you flash anything.** All hardware testing
> is on an Octatrack **MKI**; nothing here has been tried on an MKII.

## Prerequisites

- **Python 3.8+**
- **ColdFire cross-assembler** — `m68k-elf-as`, `m68k-elf-ld`, `m68k-elf-objcopy`. On
  macOS: `brew install m68k-elf-gcc`.
- **Your own copy of the official OS 1.40C** — from
  <https://www.elektron.se/support-downloads/octatrack-mkii>. The same image serves MKI
  and MKII.
- *For SIDECHAIN_COMPRESSOR and VARISPEED_EMUS* — the DSP56300 toolchain
  built into `vendor/dsp56300/`, and the external-RE clone cache
  (`python3 tools/refs/sync.py`). Every other build is ColdFire-only.

## One-time setup

```sh
./fetch-os.sh     # downloads the official OS 1.40C into downloads/ and extracts it
./analyze.sh      # unpacks it -> out/raw/section_3_MAIN_OS.bin (the decompressed MAIN OS)
./setup.sh        # clones, patches and builds elektron-firmware-tool into vendor/
```

If the download URL has moved, put `OCTATRACK_OS1.40C.zip` (or the extracted `.syx`)
into `downloads/` yourself and re-run `./analyze.sh`.

## Build

One command per final feature. **Every feature image carries the three BATCH_BUGFIXES**; there is no
image of a feature without them. Each writes its image to `out/<FEATURE>/`:

| feature | build command | OS VERSION reads |
|---|---|---|
| MUTE_MODES | `python3 tools/build_mute_modes.py` | `140C_MM` |
| DIRECT_JUMP_KYOTI | `python3 tools/build_direct_jump_kyoti.py` | `140C_KDJ7` |
| SIDECHAIN_COMPRESSOR | `python3 tools/build_sidechain_compressor.py` | `140C_SC` |
| CLYPS (with DIRECT_JUMP_KYOTI built in) | `python3 tools/build_clyps.py` | `CLYPS V1.0` |
| RELOAD_FROM_PROJECT | `python3 tools/build_reload_from_project.py` | `140C_RL` |
| QUANTIZE_LIVE_REC_TOGGLE | `python3 tools/build_quantize_live_rec_toggle.py` | `140C_QLR` |
| ERASE_EMPTY_TRIGLESS_LOCKS | `python3 tools/build_erase_empty_trigless_locks.py` | `140C_TL` |
| REC_TRIG_MUTE | `python3 tools/build_rec_trig_mute.py` | `140C_RTM` |
| BLACKPYRAMIDS_303 | `python3 tools/build_blackpyramids_303.py` | `140C_BP303` |
| VARISPEED | `python3 tools/build_varispeed.py` | `140C_VARI1` |
| VARISPEED_EMUS | `python3 tools/build_varispeed_emus.py` | `140C_VEM11` |
| BATCH_BUGFIXES (the three fixes alone) | `python3 tools/build_batch_bugfixes.py` | `140C_FIXES` |
| SIDECHAIN_COMPRESSOR light (the earlier version; WIP, not recommended; no bug fixes) | `KYOTI_ALLOW_WIP=1 python3 tools/build_sidechain_compressor_light.py` | `140C_SCLT` |

Each build writes, in `out/<FEATURE>/`:

```
mainos_<feature>.bin                  the patched MAIN OS section
OCTATRACK_OS1.40C_<FEATURE>.syx       flash over MIDI DIN
OCTATRACK_<FEATURE>.bin               flash from the CF card (faster)
```

How: a feature builder run on its own hands off to [`tools/feature_image.py`](tools/feature_image.py),
which builds the feature alone as a *unit* (`out/mainos_<feature>.bin`, never wrapped for flashing;
`KYOTI_UNIT=1 python3 tools/build_<feature>.py` builds only that, for the emulator harnesses) and
composes the three fixes onto it, proving that every changed byte has exactly one owner.
`python3 tools/feature_image.py` builds every feature image in one run (`--only NAME,...`). The
three fix builders (`build_midi_plays_free_fix.py`, `build_empty_pattern_led_fix.py`,
`build_part_change_carryover_fix.py`) give the BATCH_BUGFIXES image too.

### The combined images: KYOTI V1.8, V1.8C and V1.8BC

Every FINAL feature except BLACKPYRAMIDS_303 and VARISPEED_EMUS in one image, in two versions, and a
third with BLACKPYRAMIDS_303:

```sh
python3 tools/build_kyoti.py            # KYOTI V1.8:  RELOAD_FROM_PROJECT + DIRECT_JUMP_KYOTI
python3 tools/build_kyoti.py --clyps    # KYOTI V1.8C: CLYPS (Direct Jump Kyoti built in), no RELOAD
python3 tools/build_kyoti.py --clyps-bp # KYOTI V1.8BC: V1.8C + BLACKPYRAMIDS_303 (SPRING + PLATE REV given up)
```

They write `out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8.syx` (OS VERSION `KYOTI V1.8`),
`out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8C.syx` (OS VERSION `KYOTI 1.8C`) and
`out/KYOTI/OCTATRACK_OS1.40C_KYOTI_V1.8BC.syx` (OS VERSION `KYOTI1.8BC`), each with its `.bin`.
`build_clyps.py` runs `build_kyoti.py --clyps-standalone` (CLYPS + DIRECT_JUMP_KYOTI + BATCH_BUGFIXES,
`out/CLYPS/`). No builder puts CLYPS beside the standalone DIRECT_JUMP_KYOTI or RELOAD_FROM_PROJECT
(`tools/feature_exclusions.py`).

> **Sample memory.** RELOAD_FROM_PROJECT and DIRECT JUMP run from DRAM in V1.8: eleven 6 KB pages (66 KB)
> of the 85.5 MB pool. In V1.8C and the CLYPS image, CLYPS and DIRECT JUMP take 1,709 pages (about 10 MB; V1.8BC
> with the voice's runtime: 1,720),
> almost all of it Clyps' originals and working copies. The MEMORY page still reads 85.5 MB. An
> octabam-built image (octabam's own remixer) reserves a fixed **10 MiB** whenever any module runs from DRAM.

KYOTI V1.0 was withdrawn on 2026-10-06; V1.1 replaced it, V1.2 (with an earlier varispeed module) replaced V1.1,
V1.3 replaced V1.2, whose SPRING reclaim overwrote PLATE REVERB's page (`reference/kb/caves.md` §0),
V1.4 replaced V1.3 without that module, V1.5 replaced V1.4, adding VARISPEED, V1.6 replaced V1.5, and
V1.7 replaced V1.6: V1.1–V1.6 kept code on the stock DELAY's coefficient table (`reference/kb/caves.md`,
the cave table), which darkened DELAY repeats. V1.8, V1.8C and V1.8BC replace V1.7.
V1.7 builds from tag `ref/kyoti-v1.7-2026-11-09`, V1.6 from tag `ref/kyoti-v1.6-2026-10-29`. V1.4 still
builds from the commit it was promoted at (`git worktree add ../octatrack-kyoti-fw-v14 19348d9`,
with `vendor/`, `out/raw/`, `downloads/` and `refs/octabam` linked in by absolute path).

Every build is a **guarded binary patch**: it asserts the stock bytes at each splice
site, checks that its code caves are free and non-overlapping, takes every detour target
from the linker's symbol table, and round-trips the result through Elektron's own
firmware tool. It stops before writing anything if a check fails — a wrong stock file,
an already-patched image, or a checksum mismatch.

## The WIP gate

Only the builds above are final. Everything else in `tools/` is work in progress and
refuses to run unless you set `KYOTI_ALLOW_WIP=1`. A final build also refuses — without
the opt-in — if it would now produce a different image from the one that was promoted,
because an unpromoted update to a final feature is work in progress too. The gate lives
in [`tools/kyoti_status.py`](tools/kyoti_status.py); it is a courtesy, not a lock.

## Without an assembler

[`sysex/`](sysex/) carries MIDI_PLAYS_FREE_FIX as JSON hunks (address, original bytes,
replacement bytes) and applies it with `sysex/apply_patch.py` — no cross-assembler needed.
See [`sysex/README.md`](sysex/README.md). Every other feature is build-from-source only.

## As octabam modules

The features are also packaged as modules for
[octabam](https://github.com/sambanks/octabam)'s remixer, in
[`octabam-modules/`](octabam-modules/) — one self-contained folder per module.

## Flashing

See [`FLASHING.md`](FLASHING.md). Short version: MIDI **DIN** (not USB) for the `.syx`,
or **PROJECT → OS UPGRADE** from the CF card for the `.bin` (much faster). Your CF card,
projects and samples are untouched by an OS update.

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
- *For SIDECHAIN_COMPRESSOR and REPITCH_REPEAT98_KYOTI only* — the DSP56300 toolchain
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

One command per final feature. Each writes its image to `out/`:

| feature | build command | OS VERSION reads |
|---|---|---|
| MUTE_MODES | `python3 tools/build_mute_modes.py` | `140C_KYOTI` |
| DIRECT_JUMP_KYOTI | `python3 tools/build_direct_jump_kyoti.py` | `140C_KDJ7` |
| SIDECHAIN_COMPRESSOR | `python3 tools/build_sidechain_compressor.py` | `140C_KYOTI` |
| RELOAD_FROM_PROJECT | `python3 tools/build_reload_from_project.py` | `140C_KYOTI` |
| REPITCH_REPEAT98_KYOTI | `python3 tools/build_repitch_repeat98_kyoti.py` | `140C_RPK16` |
| QUANTIZE_LIVE_REC_TOGGLE | `python3 tools/build_quantize_live_rec_toggle.py` | `140C_KYOTI` |
| ERASE_EMPTY_TRIGLESS_LOCKS | `python3 tools/build_erase_empty_trigless_locks.py` | `1.40C` |
| REC_TRIG_MUTE | `python3 tools/build_rec_trig_mute.py` | `140C_RTM` |
| BATCH_BUGFIXES: MIDI_PLAYS_FREE_FIX | `python3 tools/build_midi_plays_free_fix.py` | `1.40C` |
| BATCH_BUGFIXES: EMPTY_PATTERN_LED_FIX | `python3 tools/build_empty_pattern_led_fix.py` | `1.40C` |
| BATCH_BUGFIXES: PART_CHANGE_CARRYOVER_FIX | `python3 tools/build_part_change_carryover_fix.py` | `1.40C` |
| each feature + BATCH_BUGFIXES (eight images) | `python3 tools/build_bugbuilds.py` | `BUG_MUTEDT`, `BUG_DJV7`, `BUG_SC3X`, `BUG_RL3`, `BUG_RPK16`, `BUG_QLREC`, `BUG_TRIGLK`, `BUG_RTM` |

Each build writes four files to `out/`, named after the feature:

```
mainos_<feature>.bin                  the patched MAIN OS section
elek_<feature>.bin                    the rebuilt container
OCTATRACK_OS1.40C_<FEATURE>.syx       flash over MIDI DIN
OCTATRACK_<FEATURE>.bin               flash from the CF card (faster)
```

`build_bugbuilds.py` writes its eight images to `out/Bugbuilds/`, as
`OCTATRACK_OS1.40C_<FEATURE>_BATCH_BUGFIXES.syx` and `.bin`, and leaves the images above
alone. MIDI_PLAYS_FREE_FIX writes only its `mainos_` image; to flash it on its own, use the
no-assembler patch below or wrap it as its builder's header shows.

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

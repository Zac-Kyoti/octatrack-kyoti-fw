# sysex/ — the no-assembler reproducible patch

This folder does **not** contain a firmware image. It contains the Bug-1 fix — the
ColdFire code authored in this repository — captured hunk by hunk as JSON, plus a
script that applies it to **your own** copy of the official Elektron OS.

No Elektron binary is redistributed here. You download the stock OS yourself; the
script produces a `.syx` byte-identical to the reference build. This is the
"fast path" for the one always-on change (the Plays-Free MIDI manual-trig fix)
that needs no cross-assembler. Every other mod — MUTE MODE, QUANTIZE LIVE REC, the
side-chain compressor, trigless-lock auto-remove, the pattern-LED and part-change
carryover fixes, DIRECT JUMP and RELOAD FROM PROJECT — is build-from-source only;
see [`../BUILD_KYOTI.md`](../BUILD_KYOTI.md).

| JSON | contents | size vs stock |
|---|---|---|
| `patches/playsfreefix-r1.json` | the MIDI manual-trig **bug fix** only, on otherwise-stock 1.40C | 2 hunks, 72 B |

Regenerate it from a fresh build with `gen_patch_json.py` (see its header).

## Requirements

- The **official OS 1.40C** (`OCTATRACK_OS1.40C.syx`), from elektron.se. Elektron
  ships one 1.40C image for the Octatrack MKI and MKII alike. `./fetch-os.sh` in
  the repo root downloads and extracts it.
- **`elektron-firmware-tool`** — `./setup.sh` clones it into `vendor/`, applies
  `tools/elektron-firmware-tool.patch` and builds it.
  Upstream: <https://github.com/mischa85/elektron-firmware-tool>

  The patch is two small local changes: `set_version()` writes the full
  10-character ELEK display field from offset `0x08` (upstream only writes from
  `0x0D`, which fits 5 characters), and `EFT_EMIT_CONTAINER` dumps the rebuilt
  container so `tools/make_bin.py` can wrap it.
- Python 3.8+

## Usage

```sh
./fetch-os.sh                      # downloads the official OS into downloads/
./setup.sh                         # builds elektron-firmware-tool into vendor/

python3 sysex/apply_patch.py \
    -i downloads/extracted/OCTATRACK_OS1.40C.syx \
    -o OCTATRACK_OS1.40C_PLAYSFREEFIX.syx
```

```
[1/5] stock .syx checksum ok
[2/5] extracted section_3_MAIN_OS.bin (1,112,560 bytes)
[3/5] applied 2 hunks (72 bytes)
[4/5] repacked -> OCTATRACK_OS1.40C_PLAYSFREEFIX.syx
[5/5] output checksum ok — byte-identical to the reference build
```

The script aborts before writing anything if the stock file's checksum is wrong,
if the original bytes under any hunk don't match (wrong firmware, or already
patched), or if the patched image's checksum is off. `--force` relaxes only the
outer file checks — the per-hunk byte verification always holds.

## What the patch changes

`playsfreefix-r1.json` changes 72 bytes out of 1,112,560 (0.006%) of the MAIN OS
section.

| id | source | effect | gate |
|---|---|---|---|
| `midi-trig-scale-fix` | `tools/patch_trigscale.s` | A Plays-Free MIDI track with trig quant *Direct* + pattern scale *Per Track* no longer stalls after step 1 on a manual trig. `FUN_4009b5c8` was seeding the per-track scale index with the audio track stride for MIDI tracks. | **always on** (bug fix) |

The fix is a detour at `0x4009b6f2` into a 62-byte code cave at `0x400d7b00`.
Design and RE notes: [`../NOTES.md`](../NOTES.md) ("Session 5 part 3" / "Session 6"),
[`../ARCHITECTURE.md`](../ARCHITECTURE.md).

The JSON holds every hunk with its load address, the original bytes and the
replacement bytes, so the change is auditable without running anything.

## Flashing from the CF card

`tools/make_bin.py` wraps the container into an ELUP `.bin` for the OS UPGRADE
menu, which is much faster than MIDI. Its correctness is not assumed: it
regenerates Elektron's own official `.bin` byte-for-byte from that file's
container.

```sh
EFT_EMIT_CONTAINER=elek.bin elektron-firmware-tool -i stock.syx -c 3 \
    out/mainos_trigscale_only.bin -o out.syx
python3 tools/make_bin.py elek.bin -o OCTATRACK_PLAYSFREEFIX.bin
```

## Before you flash

Read [`../FLASHING.md`](../FLASHING.md) first. Short version:

- The upgrade goes over **MIDI DIN, not USB** (or the CF-card OS UPGRADE menu).
- Keep the **official `.syx`** at hand — `[FUNC]` + power on → `[TRIG 3]` (MIDI
  UPGRADE) recovers the unit even if the OS is corrupt, because the bootloader is
  not touched.
- Never cut power during `UPDATING FLASH`.
- Your CF card, projects and samples are not affected.

## Disclaimer

This is unofficial, modified firmware, built for personal study of hardware its
author owns (an Octatrack MKI). It is not endorsed or supported by Elektron.
Validated in a ColdFire emulator; the Bug-1 fix is also hardware-confirmed on a
MKI. See `../FLASHING.md` §6 for the failure playbook. **Use at your own risk.**

# OS container & transport — ELUP / ELEK / aPLib / `.bin` vs `.syx`

How the firmware image is packed, checksummed, and delivered. This repo already
has the working knowledge in `ARCHITECTURE.md` + `sysex/` + `vendor/`; this file
is the merge point for anything the external tools add or correct.

## Status

Well covered here already (`COVERAGE.md`: "OS format & update — complete").
`vendor/elektron-firmware-tool` (patched, see `sysex/README.md`) does the real
pack/unpack. `refs/elektron-firmware-tool/` is the pristine upstream for diffing.

## Anchors (from this repo)

| Thing | Where |
|---|---|
| decompressed MAIN OS | `out/raw/section_3_MAIN_OS.bin`, base `0x40000400` |
| container / aPLib / checksum / ATA write / MIDI upgrade | `ARCHITECTURE.md`, `FUN_40001d4c` = DSP loader |
| in-firmware aPLib depack routine | `0x400e0aca` (`GK_STOCK_APLIB_DEPACK`, from ems-octakit `runtime/loader.S` @ `ca3b527`); boot continue `0x40001e50` |
| local patch to the tool | `tools/elektron-firmware-tool.patch` (2 changes, documented in `sysex/README.md`) |
| build a flashable | `tools/build_*.py` → `.syx` (MIDI) + `.bin` (CF) |

## `.bin` (ELUP) transport

`.bin` = ELUP container: `word[0]` magic `0x454C5550` ("ELUP"), then a
4-byte big-endian length and the ELEK container. The body scrambling is a
per-word XOR-with-feedback keyed off the running word.

We do **not** re-implement or restate the scramble here. Two existing
implementations cover it and this repo consumes one of them:

- `vendor/elektron-firmware-tool` (mischa85, fetched by `setup.sh`) — our
  `build_*.py` calls it; it is the reference.
- `refs/octa-bt-pt/tools/make_bin.py` (Bryan T, `@ e970dd0`) — an independent
  Python version; byte-identical round trip on the official 1.40C image. Read it
  there if a `build_*.py` `.bin` round trip ever fails and you need to diff the
  transform step by step.

`refs/` is a gitignored local cache, not redistributed. Keep it that way for
this file's subject in particular.

## ELEK header — version field layout (efw-tool `d407436`, 2026-09-08)

> source: `refs/elektron-firmware-tool/container.{c,h}` @ `a5bce9a`. confidence: **C**
> (upstream fix, comments cite the observed headers).

The `.syx`-side **ELEK** container's text header: `ELEK_BUILD_OFF = 0x04`,
**`ELEK_VERSION_OFF = 0x08`** (corrected from `0x0D`), `ELEK_SECT_OFF = 0x12`. The
version is a **fixed 10-byte field `0x08..0x12`, right-justified, space-padded** —
`"1.40C"` lands at `0x0D` only because it's right-justified, which is why the old
`0x0D` "worked" on one sample. `container_set_version` for ELEK must re-pad on the
left; ELE2/ELE3 instead locate it by scanning for `<digit>.<digit>` and write from
there. `container_header_end(ct)` is the new "stop scanning, binary past here"
bound (`ELE2_DEST_OFF` / `ELEK_SECT_OFF` / `ELE3_COUNT_OFF`). Section 2 of the
device layout was renamed **DSP → bootstrap** (`a5bce9a`).

**For us:** our builds stamp `140C_KYOTI` (exactly 10 chars → fills the field, no
pad). If a build ever writes a shorter tag it must right-justify in `0x08..0x12`,
or the ELEK header reads wrong. `main --emit-container` is a new dump flag.

Also (`cad66e8`): the aPLib depacker's `off -= APLIB_OFFSET_BIAS` **underflow is
deliberate** — a raw offset below the bias wraps near `UINT32_MAX` and is then
rejected by the "offset > bytes-written" check. Do not "fix" it to a signed
subtraction without adding an explicit guard.

## To import / verify from `refs/`

- **elektron-firmware-tool** `format.h`, `main.c`, `compress.c`, `integrity.c` —
  check for format-field or checksum fixes newer than our vendored copy
  (`whatsnew.py elektron-firmware-tool`). Vendored copy is 2 commits behind the
  version-field fix above; harmless for us (we stamp a 10-char tag) but re-sync
  `vendor/` before relying on `container_set_version` for a shorter string.
- **octabam** also rolls its own writer — third independent implementation.
- **ems-octakit** `patcher/` (Rust) is a fourth — `sparse-public-write-v3` +
  `authenticated-stock-local-reconstruction-v1`: it classifies every output byte
  by origin and embeds no stock-derived blobs. See `kb/octakit-abi.md` "Build
  recipe facts".

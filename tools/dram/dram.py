#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""Carry code in DRAM for the combined KYOTI image (tools/build_kyoti.py), sized to what it needs.

Why. The OS image's free ROM is ~8 KB, shared, and the parameter-page descriptor table
(0x400d2e52..0x400d5f00) is NOT free space (reference/kb/caves.md §0).
When a combined image does not fit, some code has to live elsewhere.
The proven way is octabam's platform loader (MKI-proven, reference/kb/caves.md §5).
Its pieces are vendored here unchanged: loader.S, pack.py, depack.py.

How it differs from octabam. octabam reserves a fixed 1,707 pages (10 MiB) for every remix
with DRAM code (its KITS / PLOCKS P2 keep megabytes there). This module reserves only
what the payload needs, rounded up to whole 6 KB arena pages. That is a few pages for
KYOTI, i.e. kilobytes, not megabytes, of the sample/recorder pool.

What it does to the image:
  * 24 operands that hold the arena base move up by the reserve (+ 4 geometry words:
    page count, free-list fill limit, clear length, recorder page cap). Every one is
    asserted stock first.
  * the boot site 0x4000050c `jsr 0x40001e50` -> `jsr 0x4010fdf0` (the loader). The loader
    replays that call first.
  * an append after the stock OS image: the loader, its payload table, and one packed
    payload (signature + GKA3 stream). At boot it is copied to a stage above the runtime,
    hash-gated, depacked by the firmware's own aPLib routine (0x400e0aca) into the reserve,
    and hash-gated again.
Facts and addresses: octabam docs/contributing/PLACEMENT.md and tools/remix/arena.py
@ 36a056c5 (MIT). Each one is re-checked here against the image being patched.
"""
import hashlib, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pack, depack           # noqa: E402  (vendored, unchanged)

HERE = pathlib.Path(__file__).resolve().parent
IMG_BASE = 0x40000400
LOADER_AT = 0x4010FDF0          # the byte after the stock OS image
BOOT_SITE = 0x4000050C          # stock `jsr 0x40001e50` (boot continue)
BOOT_STOCK = bytes.fromhex("4eb940001e50")
UNCACHED = 0x08000000
STAGE_ALIGN = 0x1000
SIGNATURE = b"OCTA"
MAX_CANDIDATES = 4096

# The audio page arena (octabam tools/remix/arena.py @ 36a056c5).
ARENA_BASE = 0x40A955E0
PAGE = 6144
PAGES = 14602
BASE_SITES = (
    0x4000045C, 0x4000046A, 0x400004C6, 0x400072A6, 0x40007642, 0x4000D5C0,
    0x400254F8, 0x4006C106, 0x40093432, 0x40094A0A, 0x40094A3C, 0x40094A9C,
    0x40095B28, 0x40095BBA, 0x40095C18, 0x40095C78, 0x40095CC2, 0x4009618C,
    0x400963C4, 0x4009700C, 0x4009761E, 0x40097748, 0x40098650,
)
DERIVED_SITES = ((0x40094A62, PAGE),)          # lea base+6144
COUNT_SITE = (0x40096F82, PAGES, "page count")
FILL_SITE = (0x40096FAC, PAGES + 1, "free-list fill limit")
CLEAR_SITE = (0x40097008, (PAGES + 1) * PAGE, "arena clear length")
CAP_SITE = (0x40097126, PAGES, "recorder page cap")


def roll(b):
    h = 0
    for x in b:
        h = (h * 33 + x) & 0xFFFFFFFF
    return h


def _run(args, cwd):
    r = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"dram: {args[0]} failed\n{r.stderr[-3000:]}")
    return r.stdout


def arena_writes(pages):
    """(operand address, stock bytes, new bytes, what) for a bottom reserve of `pages`."""
    base = ARENA_BASE + pages * PAGE
    count = PAGES - pages
    out = [(s + 2, ARENA_BASE.to_bytes(4, "big"), base.to_bytes(4, "big"), "arena base")
           for s in BASE_SITES]
    out += [(s + 2, (ARENA_BASE + off).to_bytes(4, "big"), (base + off).to_bytes(4, "big"),
             f"arena base + {off}") for s, off in DERIVED_SITES]
    for (operand, stock, what), new in ((COUNT_SITE, count), (FILL_SITE, count + 1),
                                        (CLEAR_SITE, (count + 1) * PAGE), (CAP_SITE, count)):
        out.append((operand, stock.to_bytes(4, "big"), new.to_bytes(4, "big"), what))
    return out


def build(raw, work, img):
    """`raw` = the DRAM image, linked at ARENA_BASE (already contiguous, units in order).
    `img` = the composed OS image (bytearray, stock length), patched in place.
    Returns (append bytes, report dict). The caller appends the bytes to `img`."""
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    base = ARENA_BASE
    stream = pack.PACKED_MAGIC + len(raw).to_bytes(4, "big") + pack.pack(raw, MAX_CANDIDATES)
    if depack.depack(stream) != raw:
        sys.exit("dram: the packed payload does not depack to the runtime -- refusing")
    blob = SIGNATURE + stream
    stage = (base + len(raw) + STAGE_ALIGN - 1) & ~(STAGE_ALIGN - 1)
    stage_end = stage + len(blob)
    pages = (stage_end - base + PAGE - 1) // PAGE
    ceiling = base + pages * PAGE

    # the arena geometry and the boot redirect, every operand asserted stock
    o = lambda a: a - IMG_BASE
    for at, stock, new, what in arena_writes(pages):
        if bytes(img[o(at):o(at) + 4]) != stock:
            sys.exit(f"dram: 0x{at:08x} ({what}) holds {bytes(img[o(at):o(at)+4]).hex()}, not stock "
                     f"{stock.hex()} -- refusing")
        img[o(at):o(at) + 4] = new
    if bytes(img[o(BOOT_SITE):o(BOOT_SITE) + 6]) != BOOT_STOCK:
        sys.exit(f"dram: boot site 0x{BOOT_SITE:08x} is not stock -- refusing")
    img[o(BOOT_SITE):o(BOOT_SITE) + 6] = b"\x4e\xb9" + LOADER_AT.to_bytes(4, "big")
    if len(img) != LOADER_AT - IMG_BASE:
        sys.exit(f"dram: the image is {len(img)} B, not the stock {LOADER_AT - IMG_BASE} B the "
                 f"loader address assumes -- refusing")

    # the loader with its one-entry table, assembled at LOADER_AT (addresses are the assembler's)
    (work / "blob0.bin").write_bytes(blob)
    (work / "table.inc").write_text("\n".join([
        "        .long 1",
        f"        .long blob0, {len(blob)}, 0x{roll(blob[4:]):08x}, 0x{stage + UNCACHED:08x}, "
        f"0x{base + UNCACHED:08x}, {len(raw)}, 0x{roll(raw):08x}, 0x00000000",
        "        .align 4", "blob0:", '        .incbin "blob0.bin"']) + "\n")
    _run(["m68k-elf-as", "-mcpu=5475", "-I", work, "-o", work / "loader.o", HERE / "loader.S"], work)
    _run(["m68k-elf-ld", f"-Ttext=0x{LOADER_AT:x}", "-o", work / "loader.elf", work / "loader.o"], work)
    _run(["m68k-elf-objcopy", "-O", "binary", work / "loader.elf", work / "append.bin"], work)
    append = (work / "append.bin").read_bytes()
    report = dict(base=base, raw=len(raw), packed=len(blob), stage=stage, stage_end=stage_end,
                  pages=pages, reserve_bytes=pages * PAGE, ceiling=ceiling,
                  arena_base_after=ceiling, pages_left=PAGES - pages, append=len(append),
                  raw_sha256=hashlib.sha256(raw).hexdigest())
    return append, report

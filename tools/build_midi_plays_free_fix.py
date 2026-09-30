#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build the MIDI manual-trig fix on TOP OF STOCK 1.40C ONLY -- none of the MAXOLYDIAN mods.

This is the same detour + code cave as octabam-modules/batch-bugfixes/patch_trigscale.s / the R13 build, but applied
to a clean stock MAIN OS (this is the Bug-1 fix on its own). Output:

    out/mainos_midi_plays_free_fix.bin      patched stock MAIN OS (2 hunks vs stock)

Then wrap it exactly like the full build:

    EFT_EMIT_CONTAINER=out/elek_midi_plays_free_fix.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_midi_plays_free_fix.bin \
        -o out/OCTATRACK_OS1.40C_MIDI_PLAYS_FREE_FIX.syx
    python3 tools/make_bin.py out/elek_midi_plays_free_fix.bin -o out/OCTATRACK_MIDI_PLAYS_FREE_FIX.bin

No -V flag -> the version string stays "1.40C" (this build is otherwise stock).
"""
import pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_midi_plays_free_fix.bin"
import kyoti_place                   # combined-image placement (build_kyoti.py); no-op standalone
CAVE_AT = kyoti_place.at("patch_trigscale", 0x400d7b00)
DETOUR_AT = 0x4009b6f2
DETOUR_EXPECT = bytes.fromhex("203c0000091a")      # move.l #0x91a,D0


def assemble():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_trigscale.o",
                    "octabam-modules/batch-bugfixes/patch_trigscale.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/patch_trigscale.elf",
                    "out/patch_trigscale.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_trigscale.elf",
                    "out/patch_trigscale.bin"], check=True, cwd=ROOT)
    return (ROOT / "out/patch_trigscale.bin").read_bytes()


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    cave = assemble()

    do = DETOUR_AT - BASE
    if bytes(img[do:do + len(DETOUR_EXPECT)]) != DETOUR_EXPECT:
        sys.exit(f"detour site 0x{DETOUR_AT:08x} unexpected: {bytes(img[do:do+6]).hex()} "
                 f"(wrong firmware, or already patched)")
    co = CAVE_AT - BASE
    if any(img[co:co + len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")

    # detour: jmp 0x400d7b00 (6 B, exactly replaces `move.l #0x91a,D0`) + 6x nop
    img[do:do + 18] = b"\x4e\xf9" + CAVE_AT.to_bytes(4, "big") + b"\x4e\x71" * 6
    img[co:co + len(cave)] = cave

    OUT.write_bytes(bytes(img))

    seal(__file__, OUT)
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock")
    print(f"  detour  0x{DETOUR_AT:08x}  jmp 0x{CAVE_AT:08x} + 6x nop  (18 B)")
    print(f"  cave    0x{CAVE_AT:08x}  {len(cave)} B")


if __name__ == "__main__":
    main()

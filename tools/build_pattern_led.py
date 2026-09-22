#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build the "pattern with only p-locks shows as empty" fix on TOP OF STOCK 1.40C.

Same detour + code-cave shape as tools/build_trigscale_only.py.  Root cause and
mechanism: tools/patch_pattern_led.s.

    out/mainos_patternled.bin           patched stock MAIN OS (2 hunks vs stock)

Wrap it like the other single-feature builds:

    EFT_EMIT_CONTAINER=out/elek_patternled.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_patternled.bin \
        -o out/OCTATRACK_OS1.40C_PATTERNLED.syx
    python3 tools/make_bin.py out/elek_patternled.bin -o out/OCTATRACK_PATTERNLED.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_patternled.bin"
CAVE_AT = 0x400d7000
DETOUR_AT = 0x4009a464
DETOUR_EXPECT = bytes.fromhex("2f02202f0008")      # move.l %d2,-(%sp) ; move.l 8(%sp),%d0

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_patternled.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_PATTERNLED.syx"
OUT_BIN = ROOT / "out/OCTATRACK_PATTERNLED.bin"
VERSTR = "1.40C"                                   # stock-transparent: one bug fix, no version bump


def assemble():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_pattern_led.o",
                    "tools/patch_pattern_led.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/patch_pattern_led.elf",
                    "out/patch_pattern_led.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_pattern_led.elf",
                    "out/patch_pattern_led.bin"], check=True, cwd=ROOT)
    return (ROOT / "out/patch_pattern_led.bin").read_bytes()


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

    # detour: jmp <cave>  (6 B, exactly replaces the two prologue instructions)
    img[do:do + 6] = b"\x4e\xf9" + CAVE_AT.to_bytes(4, "big")
    img[co:co + len(cave)] = cave

    OUT.write_bytes(bytes(img))
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock ({len(cave)} B cave + 6 B detour)")
    print(f"  detour  0x{DETOUR_AT:08x}  jmp 0x{CAVE_AT:08x}")
    print(f"  cave    0x{CAVE_AT:08x}  {len(cave)} B")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    for l in r.stdout.splitlines():
        if any(k in l for k in ("version", "emitted", "wrote", "section")):
            print("  " + l)
    if r.returncode != 0:
        sys.exit(f"EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)],
                   check=True, cwd=ROOT)

    # round-trip: decode the wrapped container's section 3 and diff vs OUT
    chk = subprocess.run([str(EFT), str(OUT_SYX)], capture_output=True, text=True, cwd=ROOT)
    print("  round-trip:", "container re-parses OK" if chk.returncode == 0 else "PARSE FAILED")
    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)   version stays {VERSTR}")
    print("  Fixes: a pattern whose only content is p-locks (MIDI-track locks, or")
    print("  audio trigless locks) now lights its grid LED instead of reading as empty.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

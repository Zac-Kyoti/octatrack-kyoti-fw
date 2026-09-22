#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build the trigless-lock DIAGNOSTIC image on top of stock 1.40C.

Two detours into one cave blob (see tools/patch_triglock_diag.s for the reasoning):

    0x40061ce2  caveA  the sys message dispatcher's opcode decode -- writes a beacon and
                       a per-opcode histogram, so the gesture's message stream is
                       measured rather than guessed
    0x400426fc  caveB  FUN_40042158's stored-p-lock bitmap update -- the candidate fix,
                       plus why-it-rejected instrumentation

Entry points are resolved from the linked ELF's symbol table rather than assumed, so
reordering the assembly cannot silently mis-aim a detour.

    out/mainos_triglock_diag.bin
    out/OCTATRACK_OS1.40C_TRIGLOCK_DIAG.syx   (MIDI DIN)
    out/OCTATRACK_TRIGLOCK_DIAG.bin           (CF card)
"""
import os
import pathlib
import subprocess
import sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_triglock_diag.bin"
CAVE_AT = 0x400d7200

# (address, expected stock bytes, cave symbol)
DETOURS = [
    (0x40061ce2, bytes.fromhex("101253807180"), "caveA"),   # moveb %a2@,%d0; subql #1,%d0; mvzb
    (0x400426fc, bytes.fromhex("123038008081"), "caveB"),   # moveb %a0@(0,%d3:l),%d1; orl %d1,%d0
]

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_triglock_diag.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_TRIGLOCK_DIAG.syx"
OUT_BIN = ROOT / "out/OCTATRACK_TRIGLOCK_DIAG.bin"
VERSTR = "1.40C"


def assemble():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_triglock_diag.o",
                    "tools/patch_triglock_diag.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/patch_triglock_diag.elf",
                    "out/patch_triglock_diag.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_triglock_diag.elf",
                    "out/patch_triglock_diag.bin"], check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", "out/patch_triglock_diag.elf"],
                        check=True, cwd=ROOT, capture_output=True, text=True).stdout
    syms = {}
    for line in nm.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return (ROOT / "out/patch_triglock_diag.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    cave, syms = assemble()

    co = CAVE_AT - BASE
    if any(img[co:co + len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")

    placed = []
    for addr, expect, sym in DETOURS:
        if sym not in syms:
            sys.exit(f"cave symbol {sym!r} not in the linked ELF -- cannot aim that detour")
        target = syms[sym]
        if not (CAVE_AT <= target < CAVE_AT + len(cave)):
            sys.exit(f"{sym} resolved to 0x{target:08x}, outside the cave")
        o = addr - BASE
        if bytes(img[o:o + len(expect)]) != expect:
            sys.exit(f"detour site 0x{addr:08x} unexpected: {bytes(img[o:o+6]).hex()} "
                     f"(expected {expect.hex()} -- wrong firmware, or already patched)")
        img[o:o + 6] = b"\x4e\xb9" + target.to_bytes(4, "big")
        placed.append((addr, sym, target))

    img[co:co + len(cave)] = cave
    OUT.write_bytes(bytes(img))
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock "
          f"({len(cave)} B cave + {6 * len(DETOURS)} B detours)")
    for addr, sym, target in placed:
        print(f"  detour  0x{addr:08x}  jsr 0x{target:08x}   ({sym})")
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
    chk = subprocess.run([str(EFT), str(OUT_SYX)], capture_output=True, text=True, cwd=ROOT)
    print("  round-trip:", "container re-parses OK" if chk.returncode == 0 else "PARSE FAILED")
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}   version stays {VERSTR}")
    print("  DIAGNOSTIC build: records the gesture's message stream into bank 1 /")
    print("  pattern 16 / track 8, readable with tools/read_triglock_log.py.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

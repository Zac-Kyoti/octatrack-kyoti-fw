#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build the "auto-remove an emptied trigless lock" fix on TOP OF STOCK 1.40C.

Root cause and mechanism: tools/patch_triglock.s. Section 13 (NOTES.md): a trigless
lock (a step holding only p-locks, no trig) whose last remaining p-lock is erased stays
lit on the trig row indefinitely. FUN_40042158 -- the sole writer of the stored p-lock
stays lit on the trig row indefinitely. FUN_40038874 -- the LIVE erase worker, reached
via opcode 8's case and FUN_40041af4, and identified by tracing the gesture on hardware
rather than by static guesswork -- already works out that the step's p-lock row has gone
empty and clears the track's bit from the per-step bitmap, but never clears the
trig-type-layer flag TRAC+0x10 that keeps the LED lit. This adds only that.

    out/mainos_triglock.bin           patched stock MAIN OS (2 hunks vs stock)

Wrap it like the other single-feature builds:

    EFT_EMIT_CONTAINER=out/elek_triglock.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_triglock.bin \
        -o out/OCTATRACK_OS1.40C_TRIGLOCK.syx
    python3 tools/make_bin.py out/elek_triglock.bin -o out/OCTATRACK_TRIGLOCK.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_triglock.bin"
CAVE_AT = 0x400d7200
# FUN_40038874's one commit point for "is this step's p-lock row now empty" -- the real
# LIVE erase worker, identified from a hardware trace (ARTLTEST8), not inferred.
DETOUR_AT = 0x40038a5c
DETOUR_EXPECT = bytes.fromhex("11812859d084")      # moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_triglock.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_TRIGLOCK.syx"
OUT_BIN = ROOT / "out/OCTATRACK_TRIGLOCK.bin"
VERSTR = "1.40C"                                   # stock-transparent: one bug fix, no version bump


def assemble():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_triglock.o",
                    "tools/patch_triglock.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/patch_triglock.elf",
                    "out/patch_triglock.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_triglock.elf",
                    "out/patch_triglock.bin"], check=True, cwd=ROOT)
    return (ROOT / "out/patch_triglock.bin").read_bytes()


def assert_no_branch_into(img, site, n, window=0x600):
    """Refuse a detour whose displaced bytes contain a branch TARGET.

    Overwriting n bytes with one `jsr` is only safe if nothing jumps into the middle of
    them. The first attempt at this patch detoured 0x40038af8, whose second instruction
    is the enclosing loop's `addql #1,%d7` -- and 0x40038afc is branched to from two
    skip-this-track paths. The result executed the middle of the `jsr` and never
    terminated. Decoding Bcc/BSR in a window around the site catches that statically.
    """
    lo, hi = site - BASE - window, site - BASE + window
    bad = []
    a = max(lo, 0)
    while a < min(hi, len(img) - 4):
        op = int.from_bytes(img[a:a + 2], "big")
        if 0x6000 <= op <= 0x6FFF:                      # Bcc / BRA / BSR
            d8 = op & 0xFF
            if d8 == 0x00:
                disp = int.from_bytes(img[a + 2:a + 4], "big")
                disp -= 0x10000 if disp & 0x8000 else 0
            elif d8 == 0xFF:
                disp = int.from_bytes(img[a + 4:a + 8], "big")
                disp -= 0x100000000 if disp & 0x80000000 else 0
            else:
                disp = d8 - 0x100 if d8 & 0x80 else d8
            tgt = BASE + a + 2 + disp
            if site < tgt < site + n:
                bad.append((BASE + a, tgt))
        a += 2
    if bad:
        detail = ", ".join(f"0x{s:08x} -> 0x{t:08x}" for s, t in bad)
        sys.exit(f"REFUSING detour at 0x{site:08x}: a branch lands inside the displaced "
                 f"{n} bytes ({detail}). Overwriting it would send that path into the "
                 f"middle of the jsr.")


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    cave = assemble()

    assert_no_branch_into(img, DETOUR_AT, 6)
    do = DETOUR_AT - BASE
    if bytes(img[do:do + len(DETOUR_EXPECT)]) != DETOUR_EXPECT:
        sys.exit(f"detour site 0x{DETOUR_AT:08x} unexpected: {bytes(img[do:do+6]).hex()} "
                 f"(wrong firmware, or already patched)")
    co = CAVE_AT - BASE
    if any(img[co:co + len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")

    # detour: jsr <cave>  (6 B, exactly replaces the displaced store + increment -- the
    # cave replays both itself before its own rts, which lands on 0x40038afe)
    img[do:do + 6] = b"\x4e\xb9" + CAVE_AT.to_bytes(4, "big")
    img[co:co + len(cave)] = cave

    OUT.write_bytes(bytes(img))
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock ({len(cave)} B cave + 6 B detour)")
    print(f"  detour  0x{DETOUR_AT:08x}  jsr 0x{CAVE_AT:08x}")
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
    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)   version stays {VERSTR}")
    print("  Fixes: a trigless lock (p-lock, no trig) whose last param is LIVE-erased")
    print("  ([NO]+knob) now clears from the trig row instead of staying lit forever.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

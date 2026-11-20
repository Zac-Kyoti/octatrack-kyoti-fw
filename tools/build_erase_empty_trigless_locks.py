#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Build the "auto-remove an emptied trigless lock" fix on TOP OF STOCK 1.40C.

Root cause and mechanism: octabam-modules/erase-empty-trigless-locks/patch_triglock.s. Section 13 (NOTES.md): a trigless
lock (a step holding only p-locks, no trig) whose last remaining p-lock is erased stays
lit on the trig row indefinitely. FUN_40042158 -- the sole writer of the stored p-lock
stays lit on the trig row indefinitely. FUN_40038874 -- the LIVE erase worker, reached
via opcode 8's case and FUN_40041af4, and identified by tracing the gesture on hardware
rather than by static guesswork -- already works out that the step's p-lock row has gone
empty and clears the track's bit from the per-step bitmap, but never clears the
trig-type-layer flag TRAC+0x10 that keeps the LED lit. This adds only that.

MIDI tracks (2026-11-20): FUN_40041af4 tail-calls the MIDI twin FUN_40038668 on the MIDI side, the
same worker on the MTRA block, missing the same clear of MTRA+0x10. A second detour on its erase
store (0x400387b8) enters the cave's MIDI entry `cave_midi`; one shared rule serves both
(patch_triglock.s, "MIDI tracks").

    out/mainos_erase_empty_trigless_locks.bin           patched stock MAIN OS (3 hunks vs stock)

Wrap it like the other single-feature builds:

    EFT_EMIT_CONTAINER=out/elek_erase_empty_trigless_locks.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_erase_empty_trigless_locks.bin \
        -o out/OCTATRACK_OS1.40C_ERASE_EMPTY_TRIGLESS_LOCKS.syx
    python3 tools/make_bin.py out/elek_erase_empty_trigless_locks.bin -o out/OCTATRACK_ERASE_EMPTY_TRIGLESS_LOCKS.bin
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_erase_empty_trigless_locks.bin"
import kyoti_place                   # combined-image placement (build_kyoti.py); no-op standalone
CAVE_AT = kyoti_place.at("patch_triglock", 0x400d7200)
# KYOTI V1.8BC (build_kyoti.py --clyps-bp): BLACKPYRAMIDS_303 shares the image, and on its tracks an empty
# trigless lock is a tie. tools/patch_triglock_bp.s, placed here, is then the detour's target: it leaves
# a BLKPYRAMD track's step alone and jumps to the cave on every other track. Unset (every other build):
# nothing of it is assembled, and the unit and image are unchanged.
# The MIDI detour never passes through it (BLKPYRAMD is an audio-track machine): jsr cave_midi always.
BP_AT = kyoti_place.at("patch_triglock_bp", None)
# FUN_40038874's one commit point for "is this step's p-lock row now empty" -- the real
# LIVE erase worker, identified from a hardware trace (ARTLTEST8), not inferred.
DETOUR_AT = 0x40038a5c
DETOUR_EXPECT = bytes.fromhex("11812859d084")      # moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0
# FUN_40038668's erase store, the MIDI twin (2026-11-20): jsr cave_midi, which replays both.
MIDI_AT = 0x400387b8
MIDI_EXPECT = bytes.fromhex("11414900d084")        # moveb %d1,%a0@(0x4900) ; addl %d4,%d0
MIDI_SYM = "cave_midi"
# The octabam module (manifest.py: one Linked unit, two jsr detours) pins the unit as linked here.
MANIFEST = ROOT / "octabam-modules/erase-empty-trigless-locks/manifest.py"
ORACLE_AT = 0x400d7200

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_erase_empty_trigless_locks.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_ERASE_EMPTY_TRIGLESS_LOCKS.syx"
OUT_BIN = ROOT / "out/OCTATRACK_ERASE_EMPTY_TRIGLESS_LOCKS.bin"
VERSTR = "1.40C"                                   # stock-transparent: one bug fix, no version bump


def assemble(at=None, stem="patch_triglock"):
    """the cave linked at `at` (default CAVE_AT) -> (bytes, {symbol: address})"""
    at = CAVE_AT if at is None else at
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", f"out/{stem}.o",
                    "octabam-modules/erase-empty-trigless-locks/patch_triglock.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{stem}.elf",
                    f"out/{stem}.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{stem}.elf",
                    f"out/{stem}.bin"], check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{stem}.elf"], check=True, cwd=ROOT,
                        capture_output=True, text=True).stdout
    syms = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
    if syms.get("cave") != at or MIDI_SYM not in syms:
        sys.exit(f"patch_triglock: `cave` must be the unit's first byte and `{MIDI_SYM}` must exist ({syms})")
    return (ROOT / f"out/{stem}.bin").read_bytes(), syms


def check_manifest():
    """the octabam module's REFERENCE = this source linked at ORACLE_AT (refuse a drift)"""
    import hashlib, re
    blob, _ = assemble(ORACLE_AT, "patch_triglock_oracle")
    sha = hashlib.sha256(blob).hexdigest()
    m = re.search(r'REFERENCE = \(0x([0-9a-f]+), "([0-9a-f]{64})"\)', MANIFEST.read_text())
    if not m or int(m.group(1), 16) != ORACLE_AT or m.group(2) != sha:
        sys.exit(f"{MANIFEST.relative_to(ROOT)}: REFERENCE must be (0x{ORACLE_AT:08x}, \"{sha}\") "
                 f"-- patch_triglock.s linked there ({len(blob)} B)")
    return len(blob), sha


def assemble_bp():
    """tools/patch_triglock_bp.s at BP_AT, jumping to the cave at CAVE_AT"""
    subprocess.run(["m68k-elf-as", "-mcpu=5407", f"--defsym=CAVE=0x{CAVE_AT:x}", "-o", "out/patch_triglock_bp.o",
                    "tools/patch_triglock_bp.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{BP_AT:x}", "-o", "out/patch_triglock_bp.elf",
                    "out/patch_triglock_bp.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_triglock_bp.elf",
                    "out/patch_triglock_bp.bin"], check=True, cwd=ROOT)
    return (ROOT / "out/patch_triglock_bp.bin").read_bytes()


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
    cave, syms = assemble()
    midi_entry = syms[MIDI_SYM]
    orc_len, orc_sha = check_manifest()

    for site, expect in ((DETOUR_AT, DETOUR_EXPECT), (MIDI_AT, MIDI_EXPECT)):
        assert_no_branch_into(img, site, 6)
        so = site - BASE
        if bytes(img[so:so + len(expect)]) != expect:
            sys.exit(f"detour site 0x{site:08x} unexpected: {bytes(img[so:so+6]).hex()} "
                     f"(wrong firmware, or already patched)")
    do = DETOUR_AT - BASE
    mo = MIDI_AT - BASE
    co = CAVE_AT - BASE
    if any(img[co:co + len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")

    # detour: jsr <cave>  (6 B, exactly replaces the displaced store + increment -- the
    # cave replays both itself before its own rts, which lands on 0x40038afe)
    img[do:do + 6] = b"\x4e\xb9" + CAVE_AT.to_bytes(4, "big")
    # MIDI: jsr cave_midi (6 B, the displaced store + increment; it lands back on 0x400387be)
    img[mo:mo + 6] = b"\x4e\xb9" + midi_entry.to_bytes(4, "big")
    img[co:co + len(cave)] = cave
    if BP_AT is not None:
        bp = assemble_bp()
        bo = BP_AT - BASE
        if any(img[bo:bo + len(bp)]) or (bo < co + len(cave) and co < bo + len(bp)):
            sys.exit(f"patch_triglock_bp at 0x{BP_AT:08x} is not free")
        img[bo:bo + len(bp)] = bp
        img[do:do + 6] = b"\x4e\xb9" + BP_AT.to_bytes(4, "big")
        print(f"  BLACKPYRAMIDS_303 beside it: detour -> patch_triglock_bp 0x{BP_AT:08x} ({len(bp)} B), "
              f"which skips a BLKPYRAMD track and jumps to the cave on every other")

    OUT.write_bytes(bytes(img))

    seal(__file__, OUT)
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock ({len(cave)} B cave + 2 x 6 B detour)")
    print(f"  detour  0x{DETOUR_AT:08x}  jsr 0x{int.from_bytes(img[do + 2:do + 6], 'big'):08x}  (AUDIO, FUN_40038874)")
    print(f"  detour  0x{MIDI_AT:08x}  jsr 0x{midi_entry:08x}  (MIDI, FUN_40038668)")
    print(f"  cave    0x{CAVE_AT:08x}  {len(cave)} B  (cave_midi +0x{midi_entry - CAVE_AT:x})")
    print(f"  octabam REFERENCE 0x{ORACLE_AT:08x}: {orc_len} B sha256 {orc_sha[:16]}... = manifest")

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
    print("  ([NO]+knob), on an audio or a MIDI track, now clears from the trig row instead of")
    print("  staying lit forever.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- phase 2 standalone build (reference/handoffs/CLYPS_SCOPE.md §8): stock 1.40C + Clyps
mode, the Clyps view and the Clyps grid, held / latched states, loads applied at once (no cued
landing yet). WIP until the user promotes it.

  [PATTERN] + [BANK] (either order)   Clyps mode: the active track's sequence in each of the 16
                                      patterns of a bank, on screen (2 x 8) and on the trigs.
  held   (chord held)    trig = load, Clyps stays; releasing the chord after a load closes.
  latched (released, nothing loaded)  trig = load + close; [YES] = load the cursor + close;
                                      [NO] = close.
  UP/DOWN cursor (wraps), LEFT/RIGHT bank (wraps), TRACK keys change the track.
  grid: full green = sample/note trigs, half green = other data only, off = empty, red = playing.

Detours (each asserts its stock bytes):
  0x4005a044  [PTN] key handler      move.l 8(sp),d0 ; moveq #1,d1          -> cl_ptn
  0x4007af80  [BANK] press handler   tst.l 0x460e73bc                        -> cl_bankp
  0x4007b3e0  [BANK] release handler moveq #2,d0 ; cmp.l 0x460e73c6,d0 (8 B) -> cl_bankr
  0x400a1f72  sequencer tick, phase D  move.b 0x80006687,d0               -> cl_land (cued landings)
  0x40062d1c  UI task loop tail        tst.l 0x46c7c72c                   -> cl_uitail (follow-up)
  0x400a43a0  wrap body entry (phase G) move.l (a2),d0 ; moveq #1,d2 ; or.l d2,d0 -> cl_wrap
Code + its keymap layer, LED layer and state: one blob in the classic cave at 0x400d6500
(reference/kb/caves.md: stock-zero 0x400d64da..0x400d7c3c).

Not in this image: RELOAD_FROM_PROJECT (its [BANK] deferral would share these sites; KYOTI work),
cued landings, originals, saved sequences, FULL loads, the page LEDs.

Usage:   KYOTI_ALLOW_WIP=1 python3 tools/build_clyps.py [VERSTR]   (default "140C_CLYP2")
Outputs: out/mainos_clyps.bin, out/OCTATRACK_OS1.40C_CLYPS.syx, out/OCTATRACK_CLYPS.bin
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
SRC = ROOT / "tools/clyps/patch_clyps.s"
OUT = ROOT / "out/mainos_clyps.bin"
ELEK = ROOT / "out/elek_clyps.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_CLYPS.syx"
OUT_BIN = ROOT / "out/OCTATRACK_CLYPS.bin"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_CLYP2"

CAVE = 0x400d6500
FREE_END = 0x400d7c3c
DETOURS = [  # (site, symbol, stock bytes, length)
    (0x4005a044, "cl_ptn", "202f00087201", 6),
    (0x4007af80, "cl_bankp", "4ab9460e73bc", 6),
    (0x4007b3e0, "cl_bankr", "7002b0b9460e73c6", 8),
    (0x400a1f72, "cl_land", "103980006687", 6),   # seq tick phase D: move.b 0x80006687,d0
    (0x40062d1c, "cl_uitail", "4ab946c7c72c", 6),  # UI task loop tail: tst.l 0x46c7c72c
    (0x400a43a0, "cl_wrap", "201274018082", 6),    # wrap body entry: move.l (a2),d0; moveq #1,d2; or.l d2,d0
]


def assemble():
    o, elf, binf = ROOT / "out/patch_clyps.o", ROOT / "out/patch_clyps.elf", ROOT / "out/patch_clyps.bin"
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", o, SRC], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE:x}", "-o", elf, o], check=True, cwd=ROOT,
                   capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", elf, binf], check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return binf.read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    o = lambda a: a - BASE
    blob, syms = assemble()
    if CAVE + len(blob) > FREE_END:
        sys.exit(f"patch_clyps ({len(blob)} B) runs past the free zone end 0x{FREE_END:x}")
    if any(img[o(CAVE):o(CAVE) + len(blob)]):
        sys.exit(f"cave 0x{CAVE:08x} is not stock-zero")
    img[o(CAVE):o(CAVE) + len(blob)] = blob
    print(f"  patch_clyps {len(blob)} B @ 0x{CAVE:08x}..0x{CAVE + len(blob) - 1:08x} "
          f"({FREE_END - CAVE - len(blob)} B left)")
    for site, sym, exp, n in DETOURS:
        exp = bytes.fromhex(exp)
        if bytes(img[o(site):o(site) + len(exp)]) != exp:
            sys.exit(f"detour 0x{site:08x} ({sym}): {bytes(img[o(site):o(site)+len(exp)]).hex()} "
                     f"is not stock {exp.hex()}")
        img[o(site):o(site) + n] = b"\x4e\xf9" + syms[sym].to_bytes(4, "big") + b"\x4e\x71" * ((n - 6) // 2)
        print(f"    0x{site:08x} -> {sym} 0x{syms[sym]:08x}")
    # the 0x80006a40..0x80006abf scratch block is not ours (CLAUDE.md)
    hits = [CAVE + i for i in range(0, len(blob) - 3, 2)
            if 0x80006a40 <= int.from_bytes(blob[i:i + 4], "big") < 0x80006ac0]
    if hits:
        sys.exit("patch_clyps references the 0x80006a40+ scratch block at " + ", ".join(map(hex, hits)))
    # stock keymap layers are never poked
    for rec in (0x400bf0be, 0x400bf0a4, 0x400d00ee, 0x400d00d4):
        if img[o(rec):o(rec) + 26] != stock[o(rec):o(rec) + 26]:
            sys.exit(f"stock layer record 0x{rec:08x} modified")
    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    print(f"  {OUT.name}: {sum(a != b for a, b in zip(stock, img))} bytes changed vs stock")
    (ROOT / "out/clyps_syms.txt").write_text("".join(f"{k} 0x{v:08x}\n" for k, v in sorted(syms.items())))
    if not EFT.exists() or not STOCK_SYX.exists():
        print("  (EFT tool or stock syx missing -- no .syx/.bin wrap)")
        return
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    if "too long" in r.stdout:
        sys.exit(f'version string "{VERSTR}" does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"  {OUT_SYX.name} (MIDI) + {OUT_BIN.name} (CF card), OS VERSION {VERSTR}")


if __name__ == "__main__":
    main()

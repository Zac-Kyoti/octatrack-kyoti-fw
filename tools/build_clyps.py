#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- standalone build (reference/handoffs/CLYPS_SCOPE.md): stock 1.40C + Clyps. WIP until the
user promotes it.

  [PATTERN] + [BANK] (either order)   Clyps mode: the active track's sequence in each of the 16
                                      patterns of a bank, on screen (2 x 8) and on the trigs.
  held   (chord held)    trig = load, Clyps stays; releasing the chord after a load closes.
  latched (released, nothing loaded)  trig = load + close; [YES] = load the cursor entry + close;
                                      [NO] = close.
  UP/DOWN cursor 1..16 -> ORIG (wraps), LEFT/RIGHT the other column, [BANK] + trig picks the bank,
  TRACK keys change the track.
  Outside Clyps: hold [YES] + TRACK = temp save that track, hold [NO] + TRACK = reload it (next
  step, in step); a quick tap of [YES] / [NO] is stock's ARM / DISARM.
  [PAGE] the track's original (as loaded) back; [FUNC]+[PAGE] every changed track's, one landing.
  grid: full green = sample/note trigs, half green = other data only, off = empty, red = playing,
  yellow = cued. Stopped: loads at once; running: cued (master wrap / CHAIN AFTER, phase-continuous).

Detours (each asserts its stock bytes):
  0x4005a044  [PTN] key handler      move.l 8(sp),d0 ; moveq #1,d1          -> cl_ptn
  0x4007af80  [BANK] press handler   tst.l 0x460e73bc                        -> cl_bankp
  0x4007b3e0  [BANK] release handler moveq #2,d0 ; cmp.l 0x460e73c6,d0 (8 B) -> cl_bankr
  0x400a1f72  sequencer tick, phase D  move.b 0x80006687,d0               -> cl_land (cued landings)
  0x40062d1c  UI task loop tail        tst.l 0x46c7c72c                   -> cl_uitail (follow-up)
  0x400a43a0  wrap body entry (phase G) move.l (a2),d0 ; moveq #1,d2 ; or.l d2,d0 -> cl_wrap
  0x400905d4  masked bank loader entry lea -328(sp),sp ; movem.l ... (8 B)   -> cl_projload
              (its return snapshots the banks it read: the originals; 8+ banks = a project load:
              the saved sequences and cues go)
  0x40025808  power-on resume         jsr 0x4000fbb4 (SRAM -> RAM, current bank) -> jsr cl_sramrest
              (the same call, then that bank's snapshot)
  0x4005e4c8  stock [YES]             move.l 4(sp),d1 ; move.l 8(sp),d0     -> cl_yes
  0x4005e25c  stock [NO]              move.l 8(sp),d0 ; beq.s (6 B)          -> cl_no
              (outside Clyps: hold + TRACK = temp save / reload; ARM / DISARM on a quick tap)
  0x4001fb1e, 0x4006bafe, 0x4007ec4c, 0x400909dc  jsr 0x4000fd34 (every bank to defaults)
              -> jsr cl_rstall (the same call, then every bank's snapshot once DRAM is in place)
One source, two parts, linked together:
  ROM   `.text`  the sequencer-tick code (phase D, the wrap body, the copy) and the cue state it
                 touches, in the classic cave at 0x400d6500 (reference/kb/caves.md: stock-zero
                 0x400d64da..0x400d7c3c). ISR code stays out of DRAM (build_kyoti.py's policy).
  DRAM  `.dram`  everything else (UI-task handlers, the view, the grid, the keymap / LED layers),
                 linked at the arena reserve and carried by the boot loader (tools/dram/), plus
                 CL_BSS_SIZE bytes of uninitialised buffers after it (the saved sequences and the
                 originals, scope §1.5 / §1.6).

Not in this image: RELOAD_FROM_PROJECT / DIRECT_JUMP_KYOTI (KYOTI work), FULL loads, the page LEDs.

Usage:   KYOTI_ALLOW_WIP=1 python3 tools/build_clyps.py [VERSTR]   (default "140C_CLYPS")
Outputs: out/mainos_clyps.bin, out/OCTATRACK_OS1.40C_CLYPS.syx, out/OCTATRACK_CLYPS.bin
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "dram"))
import dram                                    # noqa: E402  (tools/dram/dram.py)

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
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_CLYPS"
# CLYPS_VARIANT=NAME: assemble with --defsym NAME=1 (a layout proposal, e.g. ROW17) into
# out/clyps_variant_NAME/ -- render-only: no seal, no .syx, the main outputs untouched
VARIANT = os.environ.get("CLYPS_VARIANT", "")
if VARIANT:
    _vd = ROOT / f"out/clyps_variant_{VARIANT}"
    _vd.mkdir(parents=True, exist_ok=True)
    OUT = _vd / "mainos_clyps.bin"

CAVE = 0x400d6500
FREE_END = 0x400d7c3c
DETOURS = [  # (site, symbol, stock bytes, length[, opcode: jmp unless given])
    (0x4005a044, "cl_ptn", "202f00087201", 6),
    (0x4007af80, "cl_bankp", "4ab9460e73bc", 6),
    (0x4007b3e0, "cl_bankr", "7002b0b9460e73c6", 8),
    (0x400a1f72, "cl_land", "103980006687", 6),   # seq tick phase D: move.b 0x80006687,d0
    (0x40062d1c, "cl_uitail", "4ab946c7c72c", 6),  # UI task loop tail: tst.l 0x46c7c72c
    (0x400a43a0, "cl_wrap", "201274018082", 6),    # wrap body entry: move.l (a2),d0; moveq #1,d2; or.l d2,d0
    (0x400905d4, "cl_projload", "4feffeb848d77cfc", 8),  # masked bank loader entry (every LOAD PROJECT)
    (0x4005e4c8, "cl_yes", "222f0004202f0008", 8),        # stock [YES]: + TRACK = temp save; arm on a tap
    (0x4005e25c, "cl_no", "202f00086714", 6),             # stock [NO]: + TRACK = reload; disarm on a tap
    (0x40025808, "cl_sramrest", "4eb94000fbb4", 6, "4eb9"),  # power-on resume: jsr 0x4000fbb4 (SRAM -> RAM)
    (0x4001fb1e, "cl_rstall", "4eb94000fd34", 6, "4eb9"),    # the four jsr 0x4000fd34 (every bank
    (0x4006bafe, "cl_rstall", "4eb94000fd34", 6, "4eb9"),    # to defaults): the originals are retaken
    (0x4007ec4c, "cl_rstall", "4eb94000fd34", 6, "4eb9"),    # after it (cl_rstall is ROM: 0x4001fb1e
    (0x400909dc, "cl_rstall", "4eb94000fd34", 6, "4eb9"),    # may run before the DRAM part exists)
]


def assemble():
    """-> (ROM bytes at CAVE, DRAM bytes at dram.ARENA_BASE, symbols)"""
    o, elf = ROOT / "out/patch_clyps.o", ROOT / "out/patch_clyps.elf"
    rom, dr = ROOT / "out/patch_clyps.bin", ROOT / "out/patch_clyps_dram.bin"
    if VARIANT:
        o, elf = OUT.parent / "patch_clyps.o", OUT.parent / "patch_clyps.elf"
        rom, dr = OUT.parent / "patch_clyps.bin", OUT.parent / "patch_clyps_dram.bin"
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", o, SRC]
                   + (["--defsym", f"{VARIANT}=1"] if VARIANT else []), check=True, cwd=ROOT)
    r = subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE:x}", f"--section-start=.dram=0x{dram.ARENA_BASE:x}",
                        "-o", elf, o], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"link failed (a pc-relative branch between the ROM and DRAM parts?)\n{r.stderr}")
    hdr = subprocess.run(["m68k-elf-objdump", "-h", elf], capture_output=True, text=True, check=True).stdout
    lines = hdr.splitlines()
    for i, l in enumerate(lines):          # every allocated section with bytes must be one of the two
        f = l.split()
        if len(f) >= 7 and f[0].isdigit() and int(f[2], 16) and "ALLOC" in lines[i + 1] \
                and f[1] not in (".text", ".dram"):
            sys.exit(f"patch_clyps: unexpected section {f[1]} ({int(f[2], 16)} B)")
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "-j", ".text", elf, rom], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "-j", ".dram", elf, dr], check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    if syms.get("cl_bss") != dram.ARENA_BASE + dr.stat().st_size:
        sys.exit("cl_bss is not the DRAM part's end")
    return rom.read_bytes(), dr.read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    o = lambda a: a - BASE
    blob, dblob, syms = assemble()
    if CAVE + len(blob) > FREE_END:
        sys.exit(f"patch_clyps ({len(blob)} B) runs past the free zone end 0x{FREE_END:x}")
    if any(img[o(CAVE):o(CAVE) + len(blob)]):
        sys.exit(f"cave 0x{CAVE:08x} is not stock-zero")
    img[o(CAVE):o(CAVE) + len(blob)] = blob
    print(f"  patch_clyps {len(blob)} B @ 0x{CAVE:08x}..0x{CAVE + len(blob) - 1:08x} "
          f"({FREE_END - CAVE - len(blob)} B left)")
    for site, sym, exp, n, *op in DETOURS:
        exp = bytes.fromhex(exp)
        if bytes(img[o(site):o(site) + len(exp)]) != exp:
            sys.exit(f"detour 0x{site:08x} ({sym}): {bytes(img[o(site):o(site)+len(exp)]).hex()} "
                     f"is not stock {exp.hex()}")
        img[o(site):o(site) + n] = (bytes.fromhex(op[0]) if op else b"\x4e\xf9") + syms[sym].to_bytes(4, "big") \
            + b"\x4e\x71" * ((n - 6) // 2)
        print(f"    0x{site:08x} -> {sym} 0x{syms[sym]:08x}")
    # the 0x80006a40..0x80006abf scratch block is not ours (CLAUDE.md)
    hits = [at + i for at, b in ((CAVE, blob), (dram.ARENA_BASE, dblob)) for i in range(0, len(b) - 3, 2)
            if 0x80006a40 <= int.from_bytes(b[i:i + 4], "big") < 0x80006ac0]
    if hits:
        sys.exit("patch_clyps references the 0x80006a40+ scratch block at " + ", ".join(map(hex, hits)))
    # stock keymap layers are never poked
    for rec in (0x400bf0be, 0x400bf0a4, 0x400d00ee, 0x400d00d4):
        if img[o(rec):o(rec) + 26] != stock[o(rec):o(rec) + 26]:
            sys.exit(f"stock layer record 0x{rec:08x} modified")
    bss = syms["CL_BSS_SIZE"]
    append, rep = dram.build(dblob, (OUT.parent / "_dram") if VARIANT else ROOT / "out/_dram_clyps", img, bss=bss)
    print(f"  DRAM: {rep['raw']:,} B linked at 0x{rep['base']:08x} + {bss:,} B buffers "
          f"(0x{syms['cl_bss']:08x}..0x{syms['cl_bss'] + bss:08x}); packed {rep['packed']:,} B, stage "
          f"0x{rep['stage']:08x}; reserve {rep['pages']:,} pages ({rep['reserve_bytes']:,} B), "
          f"{rep['pages_left']:,} of {dram.PAGES:,} left; loader + payload {rep['append']:,} B at "
          f"0x{dram.LOADER_AT:08x}")
    img += append
    OUT.write_bytes(bytes(img))
    if VARIANT:
        (OUT.parent / "clyps_syms.txt").write_text("".join(f"{k} 0x{v:08x}\n" for k, v in sorted(syms.items())))
        print(f"  variant {VARIANT}: {OUT} (render only, not sealed, no .syx)")
        return
    seal(__file__, OUT)
    print(f"  {OUT.name}: {sum(a != b for a, b in zip(stock, img))} bytes changed vs stock, "
          f"+{len(img) - len(stock):,} B appended")
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

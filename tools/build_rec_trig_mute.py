#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build REC_TRIG_MUTE on TOP OF STOCK 1.40C (WIP).

[TRK]+[NO] mutes, [TRK]+[YES] unmutes the held tracks' recorder trigs; MIDI CC 80 does the
same (receive and transmit); the track-edge status glyph shows "..." / "..>" while a muted
track still has live recorder trigs.  Mechanism and proofs:
reference/handoffs/REC_TRIG_MUTE_SCOPE.md; source: tools/patch_rec_trig_mute.s.

The code has no cave: it overwrites four stock routines that nothing can reach.  That is
only safe while it stays true, so every build re-proves it on the image it patches:
  * each region's stock bytes are intact (no other patch got there first),
  * no 4-byte value anywhere in the image, at any byte offset, points into a region, and
    no PC-relative branch/call/lea/pea from outside lands in one -- except the four
    [TRK]-layer record fields that are meant to reach .keys,
  * nothing branches into the middle of the bytes each detour displaces,
  * RTM_MASK's byte is free.

    out/mainos_rec_trig_mute.bin                   patched MAIN OS
    out/OCTATRACK_OS1.40C_REC_TRIG_MUTE.syx        MIDI DIN
    out/OCTATRACK_REC_TRIG_MUTE.bin                CF card

Usage:  KYOTI_ALLOW_WIP=1 python3 tools/build_rec_trig_mute.py [VERSTR]
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
SRC = ROOT / "tools/patch_rec_trig_mute.s"
OBJ, ELF = ROOT / "out/patch_rec_trig_mute.o", ROOT / "out/patch_rec_trig_mute.elf"
OUT = ROOT / "out/mainos_rec_trig_mute.bin"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_rec_trig_mute.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_REC_TRIG_MUTE.syx"
OUT_BIN = ROOT / "out/OCTATRACK_REC_TRIG_MUTE.bin"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_RTM"

# the four reused stock routines: section -> (start, end)
REGIONS = {
    ".keys":  (0x40083488, 0x40083544),   # stock [TRK]-layer NO / YES handlers
    ".glyph": (0x40032bd4, 0x40032d08),   # orphaned encoder value helper
    ".draw":  (0x4005a0e0, 0x4005a14c),   # FUN_4005a0e0, bare text popup
    ".ccrx":  (0x4009e7dc, 0x4009e884),   # orphaned arranger-row resolver
}
# the only references that may point into a region: the [TRK]-held layer's YES / NO
# records (0x400d15e2 / 0x400d15fc), press + release fields -> our two entry points
ALLOWED_REFS = {0x400d15e4: 0x400834d8, 0x400d15e8: 0x400834d8,
                0x400d15fe: 0x40083488, 0x400d1602: 0x40083488}
RTM_MASK = 0x400d7c3a                     # classic cave, proven runtime-writable

# detours: site -> (stock bytes, symbol, kind)
SITES = {
    0x4009d9a4: ("4a83676e243c0000091a", "rtm_gate",  "gate"),   # step handler
    0x4004bee2: ("41f9400c0cb8",         "rtm_glyph", "jsr"),    # edge renderer: state
    0x4004c00c: ("7003b08c6618",         "rtm_draw",  "jmp"),    # edge renderer: draw
    0x4000f210: ("7c77bc816c5e",         "rtm_cc",    "jmp"),    # CC handler fall-through
}


def run(*cmd, **kw):
    r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r


def assemble():
    run("m68k-elf-as", "-mcpu=5407", "-o", str(OBJ), str(SRC))
    starts = [f"--section-start={s}=0x{a:x}" for s, (a, _) in REGIONS.items()]
    run("m68k-elf-ld", "-e", "rtm_no", *starts, "-o", str(ELF), str(OBJ))
    blobs = {}
    for s in REGIONS:
        out = ROOT / f"out/patch_rec_trig_mute{s.replace('.', '_')}.bin"
        run("m68k-elf-objcopy", "-O", "binary", "-j", s, str(ELF), str(out))
        blobs[s] = out.read_bytes()
    syms = {}
    for line in run("m68k-elf-nm", str(ELF)).stdout.splitlines():
        f = line.split()
        if len(f) != 3:
            sys.exit(f"unresolved symbol in {ELF.name}: {line}")
        syms[f[2]] = int(f[0], 16)
    return blobs, syms


def pc_targets(img, a):
    """PC-relative targets of an instruction that might start at image offset a."""
    op = int.from_bytes(img[a:a + 2], "big")
    pc = BASE + a + 2
    out = []
    if 0x6000 <= op <= 0x6FFF:                                   # Bcc / BRA / BSR
        d8 = op & 0xFF
        if d8 == 0:
            d = int.from_bytes(img[a + 2:a + 4], "big", signed=True)
        elif d8 == 0xFF:
            d = int.from_bytes(img[a + 2:a + 6], "big", signed=True)
        else:
            d = d8 - 0x100 if d8 & 0x80 else d8
        out.append(pc + d)
    elif op in (0x4EBA, 0x4EFA, 0x487A) or (op & 0xF1FF) == 0x41FA:   # jsr/jmp/pea/lea (d16,pc)
        out.append(pc + int.from_bytes(img[a + 2:a + 4], "big", signed=True))
    return out


def strict_scan(img, lo, hi, allowed):
    """Every way the image could reach [lo, hi) from outside it."""
    bad = []
    for o in range(0, len(img) - 3):                              # any byte offset
        a = BASE + o
        if lo <= a < hi or a in allowed:
            continue
        v = int.from_bytes(img[o:o + 4], "big")
        if lo <= v < hi:
            bad.append(f"pointer 0x{v:08x} at 0x{a:08x}")
    for o in range(0, len(img) - 6, 2):                           # any word as an opcode
        a = BASE + o
        if lo <= a < hi:
            continue
        for t in pc_targets(img, o):
            if lo <= t < hi:
                bad.append(f"pc-relative 0x{a:08x} -> 0x{t:08x}")
    return bad


def assert_no_branch_into(img, site, n):
    for o in range(0, len(img) - 6, 2):
        for t in pc_targets(img, o):
            if site < t < site + n:
                sys.exit(f"REFUSING detour at 0x{site:08x}: 0x{BASE + o:08x} branches to "
                         f"0x{t:08x}, inside the {n} displaced bytes")


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    img = bytearray(stock)
    blobs, syms = assemble()

    if syms["rtm_no"] != 0x40083488:
        sys.exit("rtm_no must sit on 0x40083488, the entry the [TRK]-layer NO record names")
    for s, (lo, hi) in REGIONS.items():
        if len(blobs[s]) > hi - lo:
            sys.exit(f"{s}: {len(blobs[s])} B does not fit 0x{lo:08x}..0x{hi:08x} ({hi - lo} B)")
        bad = strict_scan(img, lo, hi, ALLOWED_REFS)
        if bad:
            sys.exit(f"REFUSING {s} 0x{lo:08x}..0x{hi:08x}: still reachable --\n  " +
                     "\n  ".join(bad[:12]))
    for f, want in ALLOWED_REFS.items():
        if int.from_bytes(img[f - BASE:f - BASE + 4], "big") != want:
            sys.exit(f"[TRK]-layer record field 0x{f:08x} no longer names 0x{want:08x}")
    for site, (hexb, sym, kind) in SITES.items():
        o = site - BASE
        want = bytes.fromhex(hexb)
        if img[o:o + len(want)] != want:
            sys.exit(f"detour site 0x{site:08x}: {img[o:o + len(want)].hex()} is not stock {hexb}")
        assert_no_branch_into(img, site, len(want))
    mo = RTM_MASK - BASE
    if img[mo] != 0:
        sys.exit(f"RTM_MASK 0x{RTM_MASK:08x} is not free")

    for s, (lo, hi) in REGIONS.items():                 # region = our code, zero tail
        b = blobs[s]
        img[lo - BASE:hi - BASE] = b + bytes(hi - lo - len(b))
    for site, (hexb, sym, kind) in SITES.items():
        o, t = site - BASE, syms[sym].to_bytes(4, "big")
        if kind == "gate":      # jsr rtm_gate ; beq.s 0x4009da16 ; nop
            disp = 0x4009da16 - (site + 8)
            img[o:o + 10] = b"\x4e\xb9" + t + bytes([0x67, disp]) + b"\x4e\x71"
        else:
            img[o:o + 6] = (b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9") + t
    for f in (0x400d15e4, 0x400d15e8):                  # [TRK]-layer YES press / release
        img[f - BASE:f - BASE + 4] = syms["rtm_yes"].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT.name}: {changed} bytes changed vs stock")
    for s, (lo, hi) in REGIONS.items():
        print(f"  {s:7s} 0x{lo:08x}  {len(blobs[s]):3d} / {hi - lo} B")
    for site, (_, sym, _) in SITES.items():
        print(f"  detour 0x{site:08x} -> {sym} 0x{syms[sym]:08x}")
    print(f"  RTM_MASK 0x{RTM_MASK:08x}")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    if len(VERSTR) > 10:
        sys.exit(f'version string "{VERSTR}" does not fit the 10-char field')
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    run("python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN))
    chk = subprocess.run([str(EFT), str(OUT_SYX)], capture_output=True, text=True, cwd=ROOT)
    print("  round-trip:", "container re-parses OK" if chk.returncode == 0 else "PARSE FAILED")
    print(f"  {OUT_SYX.name} + {OUT_BIN.name}   OS VERSION reads {VERSTR}")


if __name__ == "__main__":
    main()

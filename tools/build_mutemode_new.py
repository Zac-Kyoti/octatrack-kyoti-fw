#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build MUTEMODE_NEW on top of stock 1.40C -- a from-scratch MUTE MODE redesign.
See tools/patch_mutemode_new.s for the design rationale, the dynamic evidence
each hook is built on, and each revision's notes (the .s file's header).

REVISION 3: mode selection is now a LIVE PERSONALIZE menu entry, not a
build-time flag. It repurposes the MKI-only-dead "LED BRIGHTNESS" row (slot
15 of 16 in the PERSONALIZE screen, never rendered or dispatched to on MKI
since MKI's own row count is 15) as "MUTE MODE" -- one byte flips the row
count to 16, three pointers retarget that slot's label/getter/setter at this
cave's own MUTE MODE code, reusing its existing storage word (0x800000d0,
shadow 0x100fff60 -- already in stock's restore range, no persistence patch
needed). DT-T and OTFX-T have real, dynamically-verified behaviour; OTFX is
presently byte-identical to stock (see the .s file for what it still needs).

    python3 tools/build_mutemode_new.py

    out/mainos_mutemode_new.bin          patched stock MAIN OS (3 code detours,
                                          1 byte patch, 3 pointer overwrites, 1 cave)

Wrap it like the other single-feature builds:

    EFT_EMIT_CONTAINER=out/elek_mutemode_new.bin vendor/elektron-firmware-tool/elektron-firmware-tool \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx -c 3 out/mainos_mutemode_new.bin \
        -o out/OCTATRACK_OS1.40C_MUTEMODE_NEW.syx
    python3 tools/make_bin.py out/elek_mutemode_new.bin -o out/OCTATRACK_MUTEMODE_NEW.bin

On the unit: PROJECT -> PERSONALIZE -> scroll to the last row ("MUTE MODE",
where LED BRIGHTNESS would be on an MKII) -> YES/arrows cycle OT / DT-T /
OTFX / OTFX-T. Persists across power cycles like any other PERSONALIZE row.
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_mutemode_new.bin"
CAVE_AT = 0x400d2500

# (detour address, expected stock bytes, cave symbol the jmp targets) -- code caves
HOOKS = [
    (0x40004dc6, bytes.fromhex("2a3980000008"), "cave_perframe"),   # move.l 0x80000008,%d5
    (0x4000d350, bytes.fromhex("4fef00106708"), "cave_armgate"),    # lea.l 0x10(%sp),%sp ; beq.b 0x4000d35e
    (0x4000d36e, bytes.fromhex("24c0226f00a0"), "cave_ampgate"),    # move.l %d0,(%a2)+ ; movea.l 0xa0(%sp),%a1
]

# (address, expected stock byte, new byte) -- the MKI PERSONALIZE row-count immediate
ROWCOUNT_PATCH = (0x40068fb3, 0x0f, 0x10)   # moveq #0x0f,d1 -> moveq #0x10,d1

# (address, expected stock pointer, cave symbol to point at instead) -- slot 15's triple
POINTER_PATCHES = [
    (0x400b2a70, 0x400b63f8, "mute_menu_label"),   # label:  "LED BRIGHTNESS" -> "MUTE MODE"
    (0x400b2ab0, 0x40068c80, "mute_menu_getter"),  # getter: slot15_getter    -> mute_menu_getter
    (0x400b2afc, 0x4006907c, "mute_menu_setter"),  # setter: slot15_setter    -> mute_menu_setter
]

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / "out/elek_mutemode_new.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_MUTEMODE_NEW.syx"
OUT_BIN = ROOT / "out/OCTATRACK_MUTEMODE_NEW.bin"
VERSTR = "1.40C"


def assemble():
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", "out/patch_mutemode_new.o",
                    "tools/patch_mutemode_new.s"], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", "out/patch_mutemode_new.elf",
                    "out/patch_mutemode_new.o"], check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "out/patch_mutemode_new.elf",
                    "out/patch_mutemode_new.bin"], check=True, cwd=ROOT)
    cave = (ROOT / "out/patch_mutemode_new.bin").read_bytes()

    syms = {}
    r = subprocess.run(["m68k-elf-nm", "out/patch_mutemode_new.elf"], check=True,
                        cwd=ROOT, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            addr, _, name = parts
            syms[name] = int(addr, 16)
    return cave, syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    cave, syms = assemble()

    for name in ("cave_perframe", "cave_armgate", "cave_ampgate",
                 "mute_menu_label", "mute_menu_getter", "mute_menu_setter"):
        if name not in syms:
            sys.exit(f"linked cave is missing expected symbol {name!r}")

    co = CAVE_AT - BASE
    if any(img[co:co + len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")

    for addr, expect, sym in HOOKS:
        do = addr - BASE
        if bytes(img[do:do + len(expect)]) != expect:
            sys.exit(f"detour site 0x{addr:08x} unexpected: {bytes(img[do:do+len(expect)]).hex()} "
                      f"(wrong firmware, or already patched)")

    rc_addr, rc_old, rc_new = ROWCOUNT_PATCH
    rc_off = rc_addr - BASE
    if img[rc_off] != rc_old:
        sys.exit(f"row-count byte at 0x{rc_addr:08x} is 0x{img[rc_off]:02x}, expected 0x{rc_old:02x}")

    for addr, expect_ptr, sym in POINTER_PATCHES:
        off = addr - BASE
        cur = int.from_bytes(img[off:off + 4], "big")
        if cur != expect_ptr:
            sys.exit(f"pointer at 0x{addr:08x} is 0x{cur:08x}, expected 0x{expect_ptr:08x}")

    img[co:co + len(cave)] = cave

    for addr, expect, sym in HOOKS:
        do = addr - BASE
        target = syms[sym]
        img[do:do + 6] = b"\x4e\xf9" + target.to_bytes(4, "big")
        pad = len(expect) - 6
        if pad > 0:
            img[do + 6:do + 6 + pad] = b"\x4e\x71" * (pad // 2)  # nop-fill

    img[rc_off] = rc_new

    for addr, expect_ptr, sym in POINTER_PATCHES:
        off = addr - BASE
        img[off:off + 4] = syms[sym].to_bytes(4, "big")

    OUT.write_bytes(bytes(img))
    stock = STOCK_SECT.read_bytes()
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT}: {len(img):,} bytes, {changed} changed vs stock "
          f"({len(cave)} B cave + {len(HOOKS)} code detours + 1 byte patch + "
          f"{len(POINTER_PATCHES)} pointer patches)")
    for addr, _, sym in HOOKS:
        print(f"  detour   0x{addr:08x}  jmp 0x{syms[sym]:08x}  ({sym})")
    print(f"  byte     0x{rc_addr:08x}  0x{rc_old:02x} -> 0x{rc_new:02x}  (PERSONALIZE row count, MKI 15->16)")
    for addr, _, sym in POINTER_PATCHES:
        print(f"  pointer  0x{addr:08x}  -> 0x{syms[sym]:08x}  ({sym})")

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
    print("  MUTE MODE is now a live PERSONALIZE row (last row on the MKI screen).")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

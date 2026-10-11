#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
OT-303 machine, test image 1 (MT1; reference/handoffs/OT303_SCOPE.md §12 item 1b): the OT-303 DSP
voice as a track machine. "OT-303" is the sixth row of the track's machine chooser and of SRC SETUP,
on any track, one per DSP core (T1-4, T5-8). The track is stored as FLEX plus a signature in unused
NEIGHBOR page bytes, so a stock OS loads the project as a FLEX track. Its FLEX renderer sends the
DSP a control record (signature, trig flag, the twelve knobs) instead of sample data; the voice
runs at the per-track source seam (DIAG14, hardware-proven), upstream of stock AMP, FX1 and FX2.
In MT1 each trig plays the next step of the built-in Hot bar (the knobs are stored and sent, not
used yet: the sequencer and the pages drive the voice in item 2 and 3). Registration ported from
octabam's ANALOG BD (repeat98, MIT).

Stock 1.40C plus exactly this:
  * DSP, both payloads: tools/ot303/host.asm + the engine over SPRING REV's P words (DARK REV's
    helper moved to the module's end, callers retargeted), SPRING's X records, the source seam
    (A P:$39c / B P:$1a2) -> jsr the host; SPRING's dispatch -> the passthrough stub.
  * ColdFire: SPRING REV out of the FX choosers; tools/ot303/cf/{machine.s,control.c} in the classic
    cave from 0x400d6500; 16 detours, 6 pokes and the FLEX renderer slot (ANALOG BD's seams, each
    asserted against stock).

Usage:   python3 tools/build_ot303.py      (WIP: KYOTI_ALLOW_WIP=1)
Outputs: out/mainos_ot303_mt1.bin, out/OCTATRACK_OS1.40C_OT303_MT1.syx, out/OCTATRACK_OT303_MT1.bin
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ot303"))
import dsp_patch

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
CF = ROOT / "tools/ot303/cf"
WORK = ROOT / "out/ot303/cf"
OUT = ROOT / "out/mainos_ot303_mt1.bin"
ELEK = ROOT / "out/elek_ot303_mt1.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_OT303_MT1.syx"
OUT_BIN = ROOT / "out/OCTATRACK_OT303_MT1.bin"
VERSTR = "140C_303T1"      # the field takes 10 characters

# the classic cave, from 0x400d6500 (reference/kb/caves.md §2b: 0x400d64ca.. is a live record table);
# the cave's end, 0x400d7c3c, is where the zero run stops
CAVE, CAVE_END = 0x400D6500, 0x400D7C3C
CFLAGS = ["-mcpu=5407", "-msoft-float", "-O2", "-ffreestanding", "-fno-builtin", "-fno-common", "-fno-jump-tables",
          "-fno-asynchronous-unwind-tables", "-fno-ident", "-fomit-frame-pointer", "-fno-zero-initialized-in-bss",
          "-Wall", "-Wextra", "-Werror"]
H = bytes.fromhex
# ANALOG BD's seams (octabam modules/analog-bassdrum/manifest.py), each re-read against our image:
# (site, stock bytes, symbol, kind, bytes written)
DETOURS = (
    (0x400334D8, H("2f02222f0008"), "ot_machine_name", "jmp", 6),          # chooser row 5's name
    (0x4003C928, H("4bf9400a78c8"), "ot_src_names", "lea", 6),             # SRC SETUP's six names
    (0x4003D718, H("41f9400a78c8"), "ot_name_a", "jmp", 6),                # main page name lookup
    (0x4004C36A, H("41f9400a78c8"), "ot_name_b", "jmp", 6),                # the second one
    (0x4003C980, H("71104fef0018"), "ot_setup_row", "jmp", 6),             # SRC SETUP row highlight
    (0x400786C8, H("7110b480662e"), "ot_chooser_row", "jmp", 6),           # chooser row highlight
    (0x400585DC, H("161079034879400bb704"), "ot_setup_open", "jmp", 10),   # SRC SETUP opens on row 5
    (0x4005221E, H("4ebaff1c4eb94007e940"), "ot_tick_hook", "jmp", 10),    # publish the page
    (0x40078886, H("71102f004879460e7386"), "ot_chooser_open", "jmp", 10),  # chooser opens on row 5
    (0x40031E74, H("710541f9400d5f386050"), "ot_resolve_pb", "jmp", 10),   # the track's page
    (0x4007981C, H("77101084d081"), "ot_main_commit", "jmp", 6),           # chooser commit
    (0x4005A616, H("2239460d5c30"), "ot_src_commit", "jmp", 6),            # SRC SETUP commit
    (0x4005A850, H("2239460d5c30"), "ot_src_commit2", "jmp", 6),           # its second path
    (0x4003A52E, H("2002e788d4829082"), "ot_setup_edit6", "jmp", 8),       # SETUP edits row 5 as FLEX
    (0x4003CD98, H("2e06e78fdc869e86"), "ot_setup_draw6", "jmp", 8),       # SETUP draws it so
    (0x40002318, H("4fefffa048d77cfc"), "ot_validate", "jmp", 8),          # the Part validator
)
POKES = (
    (0x40079248, H("48780005"), H("48780006"), "machine chooser has six rows, OT-303 the last"),
    (0x400585FA, H("48780005"), H("48780006"), "SRC SETUP selector has six rows"),
    (0x4003C950, H("7204"), H("7205"), "SRC SETUP name lookup admits row 5"),
    (0x40078678, H("7004"), H("7005"), "machine chooser draws row 5"),
    (0x400786CE, H("7004"), H("7005"), "machine chooser highlights row 5"),
    (0x40079904, H("7604"), H("7605"), "machine chooser persists row 5"),
)
FLEX_SLOT, FLEX_RENDER = 0x400D6438, 0x40004008     # the source-supplier table's FLEX entry


def run(*cmd):
    r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r


def build_cf():
    """-> (blob, {symbol: address}) linked at CAVE: .text, .rodata, .data back to back, no .bss"""
    WORK.mkdir(parents=True, exist_ok=True)
    run("m68k-elf-gcc", *CFLAGS, "-c", str(CF / "control.c"), "-o", str(WORK / "control.o"))
    run("m68k-elf-as", "-mcpu=5407", "-o", str(WORK / "machine.o"), str(CF / "machine.s"))
    (WORK / "cave.ld").write_text(f"""SECTIONS {{
  . = 0x{CAVE:x};
  .text : {{ *(.text) *(.text.*) }}
  .rodata : {{ *(.rodata) *(.rodata.*) }}
  .data : ALIGN(4) {{ *(.data) *(.data.*) }}
  .bss : {{ *(.bss) *(COMMON) }}
  /DISCARD/ : {{ *(.comment) *(.note*) }}
}}
""")
    elf = WORK / "ot303_cf.elf"
    run("m68k-elf-ld", "-T", str(WORK / "cave.ld"), "-o", str(elf), str(WORK / "machine.o"), str(WORK / "control.o"))
    sizes = {}
    for line in run("m68k-elf-objdump", "-h", str(elf)).stdout.splitlines():
        f = line.split()
        if len(f) >= 4 and f[1].startswith("."):
            sizes[f[1]] = (int(f[2], 16), int(f[3], 16))
    if sizes.get(".bss", (0, 0))[0]:
        sys.exit(f"the ColdFire unit has .bss ({sizes['.bss'][0]} B): it would not be in the image")
    run("m68k-elf-objcopy", "-O", "binary", "-j", ".text", "-j", ".rodata", "-j", ".data", str(elf), str(WORK / "ot303_cf.bin"))
    blob = (WORK / "ot303_cf.bin").read_bytes()
    syms = {}
    for line in run("m68k-elf-nm", str(elf)).stdout.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] in "TtDdRr":
            syms[f[2]] = int(f[0], 16)
    und = [l for l in run("m68k-elf-nm", "-u", str(elf)).stdout.splitlines() if l.strip()]
    if und:
        sys.exit(f"undefined symbols in the ColdFire unit: {und}")
    return blob, syms, sizes


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT}")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    mm = dsp_patch.modmap()

    def o(a):
        return a - BASE

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    dsp_patch.patch_dsp(img, mm, host=True)
    print()
    dsp_patch.remove_spring(img)

    print("\n=== ColdFire: the OT-303 machine (registration + renderer) in the classic cave ===")
    blob, syms, sizes = build_cf()
    end = CAVE + len(blob)
    assert end <= CAVE_END, f"the unit ends at 0x{end:08x}, past the cave's end 0x{CAVE_END:08x}"
    assert stock[o(CAVE):o(end)] == bytes(len(blob)), "the cave is not zeros in stock"
    img[o(CAVE):o(end)] = blob
    print(f"  {len(blob)} B at 0x{CAVE:08x}..0x{end:08x} ({CAVE_END - end} B of the cave left); "
          + ", ".join(f"{k} {v[0]} B" for k, v in sizes.items() if v[0]))
    written = []
    for site, expect, sym, kind, n in DETOURS:
        assert stock[o(site):o(site) + len(expect)] == expect, f"detour 0x{site:08x}: not the stock bytes"
        assert len(expect) >= n
        tgt = syms[sym]
        if kind == "lea":                              # the six-byte `lea abs.l,An` keeps its opcode
            new = expect[:2] + tgt.to_bytes(4, "big")
        else:
            new = bytes.fromhex("4ef9") + tgt.to_bytes(4, "big") + bytes.fromhex("4e71") * ((n - 6) // 2)
        assert len(new) == n
        img[o(site):o(site) + n] = new
        written.append((site, site + n, sym))
        print(f"    0x{site:08x} {kind} -> {sym} 0x{tgt:08x} ({n} B)")
    for site, expect, new, note in POKES:
        assert stock[o(site):o(site) + len(expect)] == expect, f"poke 0x{site:08x}: not the stock bytes"
        img[o(site):o(site) + len(new)] = new
        written.append((site, site + len(new), note))
        print(f"    0x{site:08x} {expect.hex()} -> {new.hex()}  {note}")
    assert u32(FLEX_SLOT) == FLEX_RENDER, "the FLEX renderer slot is not stock"
    img[o(FLEX_SLOT):o(FLEX_SLOT) + 4] = syms["ot_render"].to_bytes(4, "big")
    written.append((FLEX_SLOT, FLEX_SLOT + 4, "FLEX renderer"))
    print(f"    0x{FLEX_SLOT:08x} FLEX renderer 0x{FLEX_RENDER:08x} -> ot_render 0x{syms['ot_render']:08x}")
    written.sort()
    for (a0, a1, n0), (b0, b1, n1) in zip(written, written[1:]):
        assert a1 <= b0, f"{n0} and {n1} overlap"
    assert all(not (CAVE <= a < end) for a, _, _ in written)

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("  (EFT / stock syx missing -- skipping wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if r.returncode or "too long" in r.stdout:
        sys.exit(f"wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}")


if __name__ == "__main__":
    main()

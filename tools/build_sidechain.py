#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
SIDE-CHAIN COMPRESSOR -- step 1 of 4: menu only.

Stock 1.40C + the MIDI manual-trig fix (patch_trigscale, byte-identical to
build_trigscale_only.py / build_mutemode.py) + a new  KEY  parameter on the
COMPRESSOR effect's page 2.  The DSP is untouched, so KEY does nothing audible
yet -- this build exists to prove the parameter shows up, counts 0..4, p-locks,
survives save/recall, and that the dynamic "T1".."T8" formatter is correct on
real hardware.

What it changes in the COMPRESSOR parameter descriptor (E = 0x400d5a4a),
parameter slot 7 (page-2 encoder position 1, immediately after RMS):

  name    E+0x4e+6*7  = 0x400d5ac2   000000000000 -> "KEY\\0\\0\\0"
  count   E+0xd2+4*7  = 0x400d5b38   00000002     -> 00000005   (OFF + 4 tracks)
  default E+0x96+  7  = 0x400d5ae7   01           -> 00         (OFF)
  A-fmt   E+0x102+4*7 = 0x400d5b68   00000000     -> key_fmt    (this build's cave)
  B-wgt   E+0x132+4*7 = 0x400d5b98   400475f8     -> 00000000   (plain dial, A's text)
  (min    E+0xa2+4*7  = 0x400d5b08   00000000     -- asserted, unchanged)

  Also flips the KEY slot's bit in the per-parameter ENABLE BITMAP -- a field
  the name/count/default/formatter pokes above do NOT touch and that is NOT
  relative to E like they are. `refs/octabam/docs/firmware/PARAM_PAGES.md`
  ("P+0x18a / P+0x18e -- the per-parameter ENABLE BITMAP"): the real struct
  base for this one field is P = E + 0x38, and FUN_400a6994(P+0x18a, P+0x18e,
  slot) gates whether the generic page renderer stages OR DRAWS a knob at all
  -- independent of whether the knob's own name/count/default are valid.
  Without this poke the parameter would compile clean and simply never
  appear on screen (confirmed against stock: slot 8's bit in P+0x18a reads 0;
  slot 6, RMS, reads 1). One nibble per slot, slots 8-11 packed into the u32
  at P+0x18a (slot 8 = bit 0 of the low nibble):
  enable  E+0x38+0x18a = 0x400d5c0c   00000000     -> 00000001

Usage:   python3 tools/build_sidechain.py [VERSTR]      (default "140C_KYOTI")
Outputs: out/mainos_sidechain.bin, out/elek_sidechain.bin,
         out/OCTATRACK_OS1.40C_SIDECHAIN.syx, out/OCTATRACK_SIDECHAIN.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_sidechain.bin"
ELEK = ROOT / "out/elek_sidechain.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_SIDECHAIN.syx"
OUT_BIN = ROOT / "out/OCTATRACK_SIDECHAIN.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# --- code caves: (source, load addr, [(detour site, symbol, expected hex, len, kind)]) ---
PATCHES = [
    ("patch_trigscale", 0x400d7b00,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_sidechain", 0x400d7000, []),   # formatter only, referenced from the descriptor
]
FREE_END = 0x400d7c3c

# --- COMPRESSOR parameter-descriptor pokes: (addr, expected hex, new bytes, tag) ---
#  KEY goes in descriptor slot 8 (page-2 encoder position 3).  Page-2 words pack
#  two controls each (octabam PARAM_PAGES / dsp_host: slot 6 -> r6+$c bits16-23,
#  slot 7 -> r6+$c bits8-15, slot 8 -> r6+$d bits16-23, ...).  The step-2 DSP
#  hook `scdet` reads x:(r6+$d) then asr #$10 -> bits 16-23 -> slot 8's knob.
#  RMS stays at slot 6; slot 7 blank -> a stock-normal page-2 gap (cf. CHORUS,
#  EQ, which also skip slots).
E = 0x400d5a4a
KEY_SLOT = 8
POKES = [
    (E + 0x4e + 6 * KEY_SLOT, "000000000000", b"KEY\x00\x00\x00",     "KEY name (slot 8)"),
    (E + 0xd2 + 4 * KEY_SLOT, "00000080",     (5).to_bytes(4, "big"), "KEY value-count 128 -> 5"),
    (E + 0x96 + KEY_SLOT,     "7f",           b"\x00",                "KEY default 127 -> 0 (OFF)"),
    (E + 0xa2 + 4 * KEY_SLOT, "00000000",     None,                   "KEY min (assert 0)"),
    (E + 0x132 + 4 * KEY_SLOT, "00000000",    None,                   "KEY widget ptr (assert 0)"),
    (E + 0x38 + 0x18a,        "00000000",     (1).to_bytes(4, "big"), "KEY enable bit (P+0x18a, slot 8)"),
]
A_ARRAY_SLOT7 = E + 0x102 + 4 * KEY_SLOT   # <- key_fmt address, filled after assembly (name kept)


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def jsr(t):
    return b"\x4e\xb9" + t.to_bytes(4, "big")


def assemble(name, at):
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", f"out/{name}.o", f"tools/{name}.s"],
                   check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{name}.elf", f"out/{name}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{name}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    syms = {}
    spans = []
    print("=== assemble + place caves ===")
    for name, at, detours in PATCHES:
        blob, s = assemble(name, at)
        syms[name] = s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}")
        for site, sym, exp, n, kind in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            branch = jsr(s[sym]) if kind == "jsr" else jmp(s[sym])
            img[do:do + n] = branch + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({kind}, {n} B)")

    for a1, b1, _ in spans:
        for a2, b2, _ in spans:
            if (a1, b1) != (a2, b2) and a1 < b2 and a2 < b1:
                sys.exit("cave overlap")
    if max(b for _, b, _ in spans) > FREE_END:
        sys.exit("cave runs past the free zone")

    key_fmt = syms["patch_sidechain"]["key_fmt"]
    print(f"\n  key_fmt = 0x{key_fmt:08x}")

    print("\n=== COMPRESSOR descriptor pokes ===")
    for addr, exp, new, tag in POKES:
        do = o(addr)
        cur = bytes(img[do:do + len(exp) // 2]).hex()
        if cur != exp:
            sys.exit(f"poke 0x{addr:08x} ({tag}) unexpected: {cur} != {exp}")
        if new is not None:
            img[do:do + len(new)] = new
        print(f"  0x{addr:08x}  {tag}")
    # A-array slot 7 -> key_fmt
    do = o(A_ARRAY_SLOT7)
    if bytes(img[do:do + 4]) != b"\x00\x00\x00\x00":
        sys.exit(f"A[7] 0x{A_ARRAY_SLOT7:08x} not zero: {bytes(img[do:do+4]).hex()}")
    img[do:do + 4] = key_fmt.to_bytes(4, "big")
    print(f"  0x{A_ARRAY_SLOT7:08x}  KEY formatter -> 0x{key_fmt:08x}")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # the manual-trig fix must stay byte-identical to build_trigscale_only.py
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if "version" in l or "emitted" in l or "wrote" in l))
    if "too long" in r.stdout:
        sys.exit(f'  version string "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)

    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  OS VERSION will read:  {VERSTR}")
    print("  Test: COMPRESSOR on any track -> FX page 2 -> the KEY encoder after RMS.")
    print("        OFF, then T1..T4 on tracks 1-4 / T5..T8 on tracks 5-8. Does nothing audible yet.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

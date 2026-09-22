#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
DIRECT JUMP -- stock 1.40C + the MIDI manual-trig fix + a [PTN]+[YES] front-panel
toggle and the three sequencer hooks it gates.  (Session 21 re-scope: NO PERSONALIZE
entry -- so NO menu-array surgery, the riskiest part of the earlier build.)

  1. patch_trigscale  -- MIDI manual-trig stall fix.  Byte-identical detour + cave to
                         build_trigscale_only.py / build_mutemode.py.
  2. patch_directjump -- four detours:
                           dj_toggle @0x4005e4c8  the YES handler.  [PTN]+[YES] flips
                                                  DIRECT JUMP 0<->1, flashes "DIRECT JUMP
                                                  ON/OFF" ~0.7 s, writes the 'ANDY' shadow
                                                  + re-checksums, suppresses the PTN
                                                  chooser, swallows YES.  Any other YES
                                                  press replays the displaced prologue.
                           Hook A @0x400a4006  arm + send Program Change + force step==0
                           Hook B @0x400a42fa  bypass the CHAIN-AFTER gate when armed
                           Hook C @0x400a4840  resume every position at the playhead
                         The 3 sequencer hooks are inert when DIRECT JUMP == 0 (a fresh
                         unit) and when the arranger or a pattern chain is running.

  State word 0x800000d8 (was 0x800000a8): 0 stock refs, not a stock PERSONALIZE word,
  and it gets the MUTE-MODE persistence treatment (Session 19): dj_toggle writes shadow
  0x100fff68 and the build extends the 'ANDY' block restore pea 0x64 -> pea 0x70 at the
  3 sites (0x4001f322 / 0x4001f3be / 0x4001fb24), so DIRECT JUMP survives a power cycle.

  UNFLASHED / UNVERIFIED: hooks are emulator-checked only (tools/emu_directjump.py);
  FUN_400a1eea has Unicorn-unsupported instructions so the harness exercises the stubs
  on a hand-built state, not the whole handler.  Needs a hardware pass.

Usage:   python3 tools/build_directjump.py [VERSTR]      (default VERSTR = "140C_KYOTI")
Outputs: out/mainos_directjump.bin, out/elek_directjump.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP.syx, out/OCTATRACK_DIRECTJUMP.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump.bin"
ELEK = ROOT / "out/elek_directjump.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# --- code stubs: (source, load addr, defsym, [(detour site, symbol, expected bytes, len, kind)]) ---
#   kind "jmp"  -> 4ef9 (replace a whole instruction, cave jumps back itself)
#   kind "jsr"  -> 4eb9 (stub does work then rts to the next instruction) + nop pad
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_directjump", 0x400d7400, None,
     [(0x4005e4c8, "dj_toggle", "222f0004202f0008", 8, "jmp"),  # YES handler: move.l 4(sp),d1 ; move.l 8(sp),d0
      (0x400a4006, "dj_a", "4a398000667e",     6, "jsr"),   # tst.b (0x8000667e).l
      (0x400a42fa, "dj_b", "203c00008e56",     6, "jsr"),   # move.l #0x8e56,d0
      (0x400a4840, "dj_c", "420013c0800065b6", 8, "jsr")]), # clr.b d0 ; move.b d0,(0x800065b6).l
]

# --- PERSONALIZE persistence: 0x800000d8 rides the 'ANDY' battery-SRAM restore ---
#     memcpy(0x80000070, 0x100fff00, 0x64) at 3 sites -> 0x64 ends at 0x800000d3, one
#     short of DIRECT JUMP's word.  Extend each to 0x70 (identical to build_mutemode.py).
RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)     # boot / validate / defaults
FREE_END = 0x400d7c3c


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def jsr(t):
    return b"\x4e\xb9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{name}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
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
    print("=== assemble + detour ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
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

    # --- PERSONALIZE persistence: extend the 'ANDY' block restore 0x64 -> 0x70 ---
    print("\n=== PERSONALIZE persistence ===")
    for site in RESTORE_SITES:
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70  (0x800000d8 now rides the boot restore)")

    # --- no cave span may overlap another, nor run past the free zone ---
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > FREE_END:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x{FREE_END:x})")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # --- the manual-trig fix must stay byte-identical to build_trigscale_only.py ---
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
    print(f"  version screen / SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  [PTN] + [YES]  ->  toggles DIRECT JUMP, flashes DIRECT JUMP ON / OFF (~0.7 s).")
    print("  ON = next-step switch, playhead-resume, PC ~1 step ahead.  Default OFF = stock.  Survives a power cycle.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

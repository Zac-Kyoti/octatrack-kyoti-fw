#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build a flashable Octatrack OS on TOP OF STOCK 1.40C ONLY (no MAXOLYDIAN mods):

  1. patch_trigscale  -- the MIDI manual-trig stall fix (Plays Free + Direct + Per-Track
                         scale).  Byte-identical detour + cave to build_trigscale_only.py.
  2. patch_softmute   -- SOFT MUTE (V6): an audio-track mute now behaves like a single STOP
                         for that track -- the sample audio cuts (fast clean fade), the
                         track's FX inserts ring their delay/reverb tails out, and a muted
                         track's sequencer trigs make no sound.
                         Two hooks:
                           `pre`   @ FUN_40004dbc (0x40004dc6) -- the per-frame mute gate:
                             keep the muted track's DSP-frame level words + maintain a
                             per-track note-off (DAT_8000184a) + FUN_40008f84 on the edge.
                           `pre_v` @ FUN_40005178 (0x40005178) -- drop "start" voice commands
                             for a muted audio track (kills the 1-frame trig attack blip).
                         SOLO is left stock.  _DAT_80000008 is untouched, so the MUTE LED and
                         the pattern-stored mute state keep working.
                         SOFT MUTE is ALWAYS ON in this build (no PERSONALIZE toggle yet).

  + version string set to VERSTR (default "140C_KYOTI"; the field is a fixed 10 chars, so
    "1.40C_KYOTI" (11) does not fit).  The internal version code stays intact.

Usage:  python3 tools/build_softmute.py [VERSTR]
Outputs: out/mainos_softmute.bin, out/elek_softmute.bin,
         out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.syx, out/OCTATRACK_SOFTMUTE_PFFIX.bin
"""
import os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from kyoti_status import status, SUPERSEDED

status(SUPERSEDED, "SOFT MUTE, always on", """
    SOFT MUTE (V6) with no menu -- the behaviour is always on, before MUTE MODE
    existed as a PERSONALIZE choice.  build_mutemode_dt.py supersedes it: same cut,
    selectable, and OT mode is byte-for-byte stock.
""")

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_softmute.bin"
ELEK = ROOT / "out/elek_softmute.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_SOFTMUTE_PFFIX.syx"
OUT_BIN = ROOT / "out/OCTATRACK_SOFTMUTE_PFFIX.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

CAVE = {"patch_trigscale": 0x400d7b00, "patch_softmute": 0x400d7400}

# each: (source, load addr, [(detour site, symbol, expected original bytes, total detour len)])
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18)]),            # jmp + 6 nop; == build_trigscale_only.py
    ("patch_softmute", 0x400d7400, "ALWAYS_ON=1",
     [(0x40004dc6, "pre",   "2a3980000008", 6),              # `move.l 0x80000008,D5`  -> jmp
      (0x40005178, "pre_v", "4feffff448d7001c", 8)]),         # `lea -0xc,SP`+`movem {D2-D4}` -> jmp + nop
]


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


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

    blobs = {}
    print("=== assemble + detour ===")
    spans = []
    for name, at, defsym, detours in PATCHES:
        blob, syms = assemble(name, at, defsym)
        blobs[name] = blob
        co = at - BASE
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob)))
        img[co:co + len(blob)] = blob
        for site, sym, exp, n in detours:
            exp = bytes.fromhex(exp)
            do = site - BASE
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            img[do:do + n] = jmp(syms[sym]) + b"\x4e\x71" * ((n - 6) // 2)
            print(f"  0x{site:08x} -> {name}:{sym} 0x{syms[sym]:08x}  ({n} B)")

    spans.sort()
    for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap 0x{a1:x}..0x{b1:x} / 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > 0x400d7c3c:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x400d7c3c)")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock  "
          f"(caves: {', '.join(f'{n} {len(b)}B' for n, b in blobs.items())})")

    # --- verify the manual-trig fix is byte-identical to build_trigscale_only.py ---
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    # --- wrap: ELEK container (with version) -> .syx -> .bin ---
    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines() if "version" in l or "emitted" in l or "wrote" in l))
    if "too long" in r.stdout:
        sys.exit(f'  version string "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)

    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  version screen / SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  SOFT MUTE is ALWAYS ON.  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

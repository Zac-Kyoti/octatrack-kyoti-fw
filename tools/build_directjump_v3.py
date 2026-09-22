#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
DIRECT JUMP v3 -- identical to build_directjump.py except the confirmation overlay.

  v1 (build_directjump.py)   FUN_40059f8c -- the SELECT-BANK/PATTERN timed window:
                             text + 4 draining countdown boxes, borrows that window's
                             handle 0x460d1e5c for < 1 s.  The boxes are inherited
                             chrome (that routine paints them); they were never a
                             DIRECT JUMP design choice.
  v2 (build_directjump_v2.py) FUN_4005a0e0 -- the dead-code bare text popup, NO
                             timeout of its own, so v2 splices dj_tick2 into the engine
                             per-frame handler at 0x400522ca (next to the SOFT MUTE
                             release watchdog) to close it, and shares the popup handle
                             0x460d1e64 with RELOAD's picker.
  v3 (this, --defsym DJ_V3=1) FUN_4005a2b8(text, dur) -- the OS's OWN self-timing
                             notification: the call stock uses for "PART n RELOADED"
                             (ems-octakit GK_STOCK_NOTIFICATION_SHOW), also the one
                             patch_reload2's rl_yes uses.  Plain one-line toast, no
                             boxes, no borrowed/shared handle, and NO extra hook --
                             so v3's detour set is exactly v1's three sequencer hooks
                             + the [PTN]+[YES] toggle, nothing more.

  Everything else -- the toggle logic, the 'ANDY'-shadow persistence (pea 0x64->0x70),
  dj_a/dj_b/dj_c, the manual-trig fix -- is byte-for-byte v1's recipe.

  DJ_TOAST_DUR (default 0x44, the dwell patch_reload2 uses) is --defsym-tunable.

  ** v3 is the overlay build_merged.py uses.  It removes every DIRECT JUMP merge
     friction: no 0x400522ca splice (v2), no SELECT-window handle grab (v1), no
     FUN_4005a0e0 / 0x460d1e64 collision with the RELOAD picker (v2). **

  UNFLASHED -- emulator-checked only (tools/emu_directjump_v3.py).

Usage:   python3 tools/build_directjump_v3.py [VERSTR] [DJ_TOAST_DUR]
Outputs: out/mainos_directjump_v3.bin, out/elek_directjump_v3.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP_V3.syx, out/OCTATRACK_DIRECTJUMP_V3.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump_v3.bin"
ELEK = ROOT / "out/elek_directjump_v3.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP_V3.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP_V3.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"
TOAST_DUR = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x44

DEFSYM = f"DJ_V3=1,DJ_TOAST_DUR=0x{TOAST_DUR:x}"

PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_directjump", 0x400d7400, DEFSYM,
     [(0x4005e4c8, "dj_toggle", "222f0004202f0008", 8, "jmp"),
      (0x400a4006, "dj_a", "4a398000667e",     6, "jsr"),
      (0x400a42fa, "dj_b", "203c00008e56",     6, "jsr"),
      (0x400a4840, "dj_c", "420013c0800065b6", 8, "jsr")]),
]

RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)
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

    syms, spans = {}, []
    print(f"=== assemble + detour  (DJ_V3, DJ_TOAST_DUR=0x{TOAST_DUR:x}) ===")
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

    print("\n=== PERSONALIZE persistence ===")
    for site in RESTORE_SITES:
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70")

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

    for ext in ("bin", "elf"):
        (ROOT / f"out/patch_directjump_v3.{ext}").write_bytes(
            (ROOT / f"out/patch_directjump.{ext}").read_bytes())

    # --- v3 must touch EXACTLY what v1 touches, save for its own cave bytes ---
    v1 = ROOT / "out/mainos_directjump.bin"
    if v1.exists():
        v1b = v1.read_bytes()
        v1_touched = {i for i in range(len(v1b)) if v1b[i] != stock[i]}
        v3_touched = {i for i in range(len(img)) if img[i] != stock[i]}
        cave = set(range(o(0x400d7400), o(0x400d7c3c)))
        stray = [i for i in (v3_touched ^ v1_touched) if i not in cave]
        print(f"  vs mainos_directjump.bin: v3 touches {len(v3_touched)} vs v1 {len(v1_touched)}; "
              f"{len(stray)} differ outside the cave")
        if stray:
            sys.exit(f"  v3 DIVERGED from v1 outside the cave: {[hex(BASE+i) for i in stray[:8]]}")

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
    print("  [PTN] + [YES]  ->  toggles DIRECT JUMP; a plain 'DIRECT JUMP ON / OFF'")
    print(f"    notification (OS toast, ~{TOAST_DUR} frames), no countdown boxes.")
    print("  Behaviour + persistence identical to build_directjump.py.  Default OFF = stock.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

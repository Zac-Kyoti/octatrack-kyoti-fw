#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
DIRECT JUMP v2 -- identical to build_directjump.py except the [PTN]+[YES] overlay.

  v1 (build_directjump.py):  FUN_40059f8c -- "DIRECT JUMP ON" + 4 draining countdown
                             boxes, styled as the SELECT BANK / SELECT PATTERN window,
                             borrows that window's handle (0x460d1e5c) for < 1 s.
  v2 (this):  FUN_4005a0e0 -- a bare 18px text box, NO countdown boxes, its own private
              handle (0x460d1e64), no SELECT-window side effect.  Auto-dismiss is a
              tiny frame countdown (dj_tick2) spliced into the engine per-control-frame
              handler at 0x400522ca (the fn that decrements the SOFT MUTE release
              watchdog 0x46c7dfba, so it runs every frame whether playing or stopped).

  Everything else -- the toggle, the 'ANDY'-shadow persistence, the three sequencer
  hooks (dj_a/b/c), the manual-trig fix -- is byte-for-byte the same recipe as v1;
  patch_directjump.s just switches the overlay under `.ifdef DJ_V2`.

  TOAST_FRAMES (default 0xc0 ~ 0.6 s) is `--defsym`-tunable; the exact frame rate of
  0x40052200 is unmeasured, so expect one tweak after the first hardware pass.

  UNFLASHED / UNVERIFIED -- emulator-checked only (tools/emu_directjump_v2.py).

Usage:   python3 tools/build_directjump_v2.py [VERSTR] [TOAST_FRAMES]
Outputs: out/mainos_directjump_v2.bin, out/elek_directjump_v2.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP_V2.syx, out/OCTATRACK_DIRECTJUMP_V2.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump_v2.bin"
ELEK = ROOT / "out/elek_directjump_v2.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP_V2.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP_V2.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"
TOAST_FRAMES = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0xC0

DEFSYM = f"DJ_V2=1,TOAST_FRAMES=0x{TOAST_FRAMES:x}"

# --- code stubs -- same as build_directjump.py plus the v2 frame-countdown detour ---
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_directjump", 0x400d7400, DEFSYM,
     [(0x4005e4c8, "dj_toggle", "222f0004202f0008", 8, "jmp"),   # YES handler prologue
      (0x400a4006, "dj_a", "4a398000667e",     6, "jsr"),   # tst.b (0x8000667e).l
      (0x400a42fa, "dj_b", "203c00008e56",     6, "jsr"),   # move.l #0x8e56,d0
      (0x400a4840, "dj_c", "420013c0800065b6", 8, "jsr"),   # clr.b d0 ; move.b d0,(STEP).l
      (0x400522ca, "dj_tick2", "45f946c7dfba", 6, "jsr")]), # lea 0x46c7dfba,%a2  (v2 toast tick)
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

    syms = {}
    spans = []
    print(f"=== assemble + detour  (DJ_V2, TOAST_FRAMES=0x{TOAST_FRAMES:x}) ===")
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

    # keep a v2 copy of the stub so emu_directjump_v2.py never races build_directjump.py
    for ext in ("bin", "elf"):
        (ROOT / f"out/patch_directjump_v2.{ext}").write_bytes(
            (ROOT / f"out/patch_directjump.{ext}").read_bytes())

    # --- v2 must touch only what v1 touches, plus its own detour sites ---
    #     (the dj_a/b/c cave stubs shift because dj_tick2 is inserted, so their detour
    #      target words move too -- that is expected; the only NEW touched region is the
    #      0x400522ca frame-tick detour.)
    v1 = ROOT / "out/mainos_directjump.bin"
    if v1.exists():
        v1b = v1.read_bytes()
        v1_touched = {i for i in range(len(v1b)) if v1b[i] != stock[i]}
        v2_touched = {i for i in range(len(img)) if img[i] != stock[i]}
        cave = set(range(o(0x400d7400), o(0x400d7c3c)))
        det_sites = set()
        for lo, n in ((0x4005e4c8, 8), (0x400a4006, 6), (0x400a42fa, 6),
                      (0x400a4840, 8), (0x400522ca, 6)):
            det_sites |= set(range(o(lo), o(lo) + n))
        allowed = cave | det_sites
        stray = [i for i in (v2_touched - v1_touched) if i not in allowed]
        also_gone = [i for i in (v1_touched - v2_touched) if i not in allowed]
        print(f"  vs mainos_directjump.bin: v2 touches {len(v2_touched)} vs v1 {len(v1_touched)}; "
              f"{len(stray)} new outside cave/detours, {len(also_gone)} v1-only outside them")
        if stray or also_gone:
            sys.exit(f"  v2 DIVERGED from v1: new {[hex(BASE+i) for i in stray[:6]]} "
                     f"gone {[hex(BASE+i) for i in also_gone[:6]]}")

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
    print("  [PTN] + [YES]  ->  toggles DIRECT JUMP; v2 flashes a plain box-free "
          f"'DIRECT JUMP ON / OFF' toast (~{TOAST_FRAMES/300:.1f} s guess -- tune TOAST_FRAMES on HW).")
    print("  Behaviour + persistence identical to build_directjump.py.  Default OFF = stock.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

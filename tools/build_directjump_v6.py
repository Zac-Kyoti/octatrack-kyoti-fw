#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
DIRECT JUMP V6 -- Session 105 (2026-09-26): AR's DIRECT JUMP through OT's own landing.

The V1-V5 line committed a jump by re-entering the pattern-boundary body with an offset
in 0x80006628 -- which turned out to be the arranger's cycle-start step feeding AR's
WRAP-CHANGE algorithm (ceil / remainder / hold / catch-up / deferred landing), a path AR
uses only at natural cycle wraps and never for a jump.  Hardware retracted "gold"
(step-fractional at 1x, NORMAL mode, 16<->7 step patterns), and the AR decompilation
(reference/AR_SEQUENCER_ENGINE.md) showed AR's real commit is a synchronous re-landing on
a master step boundary.  OT already has that landing as stock code, behind the countdown
byte 0x80006687 in phase D of its tick handler (NOTES.md "Session 105 continued").

V6 therefore touches the sequencer in two 6-byte detours only:
    0x400a1f72  dj_land  arm (0x80006687 = tps - TICK_CTR) / prepare the snapshot on the
                         landing tick (ACT<-PEND, 0x80006638 = MASTER_STEP mod masterLen,
                         0x80006516[t] = new_step mod len_t, 0x80006536[t] = 0)
    0x400a221c  dj_nofa  no MIDI START (0xFA) on a jump
plus the unchanged UI pieces (the [PTN]+[YES] keymap slot, dj_ptnrel, the toast) and the
manual-trig fix cave (patch_trigscale @0x400d7b00, byte-identical to build_trigscale_only).
The pattern-boundary body, the rebuild loops, 0x80006628 and every per-track counter are
STOCK.  DJ_MODE off -> byte-identical stock behaviour.

Usage:   python3 tools/build_directjump_v6.py [VERSTR] [DJ_TOAST_DUR]
Outputs: out/mainos_directjump_v6.bin, out/elek_directjump_v6.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP_V6.syx, out/OCTATRACK_DIRECTJUMP_V6.bin
"""
import hashlib, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from kyoti_status import status, WIP

status(WIP, "DIRECT JUMP V6", """
    Session 105: the AR-discipline rewrite -- a jump re-lands the sequencer through
    stock's own landing path (0x80006687) on the next master step boundary.  Two
    sequencer detours, boundary body untouched.  Emulator gates first, then the
    user's 16<->7 NORMAL-mode case on hardware.  Not flashed yet.
""")

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump_v6.bin"
ELEK = ROOT / "out/elek_directjump_v6.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP_V6.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP_V6.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"
TOAST_DUR = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x44

CAVE_DJ = 0x400d7400
CAVE_TRIGSCALE = 0x400d7b00
FREE_END = 0x400d7c3c

PATCHES = [
    ("patch_trigscale", CAVE_TRIGSCALE, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_directjump_v6", CAVE_DJ, f"DJ_TOAST_DUR=0x{TOAST_DUR:x}",
     [(0x400a1f72, "dj_land", "103980006687", 6, "jsr"),   # move.b (0x80006687).l,%d0
      (0x400a221c, "dj_nofa", "4a398000002a", 6, "jsr"),   # tst.b (0x8000002a).l
      (0x40043418, "dj_ptnrel", "4879400bf0f2", 6, "jmp")]),
]

# [PTN]-held keymap layer 0x400bf0f2, 26-byte record for YES (code 0x31): all-NULL in stock.
PTN_LAYER_YES = 0x400bf0be
PTN_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)
STOCK_YES_HANDLER = 0x4005e4c8
RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)
DJ_MODE_ADDR = 0x800000D8
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006AC0   # Session 98: overwritten on hardware


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

    syms, spans, sites = {}, [], set()
    print(f"=== assemble + detour  (DJ V6, DJ_TOAST_DUR=0x{TOAST_DUR:x}) ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        syms[name] = s
        bad = [i for i in range(0, len(blob) - 3, 2)
               if SCRATCH_LO <= int.from_bytes(blob[i:i + 4], "big") < SCRATCH_HI]
        if bad:
            sys.exit(f"{name} references the 0x80006a40+ scratch block at blob offsets "
                     f"{[hex(i) for i in bad]} -- Session 98 forbids it")
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:20s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}")
        for site, sym, exp, n, kind in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            branch = jsr(s[sym]) if kind == "jsr" else jmp(s[sym])
            img[do:do + n] = branch + b"\x4e\x71" * ((n - 6) // 2)
            sites |= set(range(do, do + n))
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({kind}, {n} B)")

    print("\n=== [PTN]-held keymap layer: [YES] press -> dj_toggle ===")
    ro = o(PTN_LAYER_YES)
    if bytes(img[ro:ro + 26]) != PTN_LAYER_YES_STOCK:
        sys.exit(f"PTN-layer YES record 0x{PTN_LAYER_YES:08x} unexpected: {bytes(img[ro:ro+26]).hex()}")
    dj = syms["patch_directjump_v6"]["dj_toggle"]
    img[ro + 2:ro + 6] = dj.to_bytes(4, "big")
    sites |= set(range(ro + 2, ro + 6))
    print(f"  0x{PTN_LAYER_YES + 2:08x}  press NULL -> dj_toggle 0x{dj:08x}")
    yo = o(STOCK_YES_HANDLER)
    if bytes(img[yo:yo + 8]) != bytes.fromhex("222f0004202f0008"):
        sys.exit("stock YES handler 0x4005e4c8 was modified -- V6 must not detour it")

    print("\n=== power-on default: DIRECT JUMP must come up OFF ===")
    for site in RESTORE_SITES:
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
    DSP_ROM_IMAGE, DSP_WINDOW, REIMAGE_LEN = 0x401086F4, 0x80000000, 0x3E88
    dj_off = DJ_MODE_ADDR - DSP_WINDOW
    if dj_off >= REIMAGE_LEN:
        sys.exit("DJ_MODE outside the boot re-image")
    seed_at = DSP_ROM_IMAGE + dj_off
    seed = bytes(img[o(seed_at):o(seed_at) + 4])
    if seed != b"\x00\x00\x00\x00":
        sys.exit(f"boot ROM seed for DJ_MODE at 0x{seed_at:08x} is {seed.hex()}, not 0")
    print(f"  ANDY restore left stock at all 3 sites; boot ROM seed 0x{seed_at:08x} = 00000000")

    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > FREE_END:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x{FREE_END:x})")
    print("  no overlaps; all within the free cave")

    # Every byte that differs from STOCK must be inside a cave or at a declared site.
    cave = set()
    for a, b, _n in spans:
        cave |= set(range(o(a), o(b)))
    diff = [i for i in range(len(img)) if img[i] != stock[i]]
    stray = [i for i in diff if i not in cave and i not in sites]
    print(f"\n  vs stock: {len(diff)} bytes differ; {len(stray)} outside caves + declared sites")
    if stray:
        sys.exit(f"  STRAY BYTES at {[hex(BASE + i) for i in stray[:8]]} -- refusing to build")

    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    OUT.write_bytes(bytes(img))
    print(f"  {OUT.name}: sha256 {hashlib.sha256(bytes(img)).hexdigest()[:16]}")
    for ext in ("bin", "elf"):
        (ROOT / f"out/patch_directjump_v6.{ext}").write_bytes(
            (ROOT / f"out/patch_directjump_v6.{ext}").read_bytes())

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
    print(f"  SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  hold [PTN], tap [YES] -> toggles DIRECT JUMP (toast).  Default OFF = stock.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

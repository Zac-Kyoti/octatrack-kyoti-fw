#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
QUANTIZE LIVE REC front-panel toggle.

  [REC] held + [PLAY] x2   flips the PERSONALIZE "QUANTIZE LIVE REC" row
                           (0x800000ac) and shows a "QUANT LIVE REC ON/OFF"
                           toast that clears when [REC] is released.

  This is the all-or-nothing live-record quantize, not the per-track TRIG QUANT.

Base = stock 1.40C + the Bug-1 MIDI manual-trig fix (patch_trigscale), same as
every other Kyoti standalone build.  No PERSONALIZE menu surgery: the variable,
its getter/setter and its power-cycle persistence are all stock -- we only add a
front-panel gesture that writes the same word + 'ANDY' shadow and re-checksums.

Detours:
  0x40061778  6 B  jsr 0x4009b5c0        -> jmp qlr_play    ([PLAY] press)
  0x4004883a  6 B  clr.l 0x460d1726      -> jmp qlr_recrel   ([REC] release)
  0x400522ca  6 B  lea 0x46c7dfba,%a2    -> jsr qlr_tick     (per-control-frame re-arm tick)

Session 50 REWRITE: the toast is now a periodically re-armed dur>0 (self-timing)
notification instead of a one-shot dur<=0 ("persistent") one -- the dur<=0 form
was flashed and confirmed to hang the unit (it registers on what real disassembly
of FUN_4005a2b8 shows is a modal window stack, not a passive banner). See
tools/patch_qlrec.s's header and NOTES.md "Session 50" for the full root cause
and fix design. NOT yet reflashed -- emulator-validate before trying again.

Usage:   python3 tools/build_qlrec.py [VERSTR]
Outputs: out/mainos_qlrec.bin, out/elek_qlrec.bin,
         out/OCTATRACK_OS1.40C_QLREC.syx, out/OCTATRACK_QLREC.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_qlrec.bin"
ELEK = ROOT / "out/elek_qlrec.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_QLREC.syx"
OUT_BIN = ROOT / "out/OCTATRACK_QLREC.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_qlrec", 0x400d7400, None,
     [(0x40061778, "qlr_play",   "4eb94009b5c0", 6, "jmp"),
      (0x4004883a, "qlr_recrel", "42b9460d1726", 6, "jmp"),
      (0x400522ca, "qlr_tick",   "45f946c7dfba", 6, "jsr")]),   # lea 0x46c7dfba,%a2
]

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

    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > FREE_END:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x{FREE_END:x})")
    print("  no overlaps; all within the free cave")

    # QUANTIZE LIVE REC is a stock PERSONALIZE word already inside the 0x64
    # 'ANDY' restore span -- assert stock leaves it there (so no pea 0x64->0x70).
    q = 0x800000ac - 0x80000070
    assert 0 <= q < 0x64, "QLR word slipped outside the stock restore span"
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        assert bytes(img[o(site):o(site) + 4]) == b"\x48\x78\x00\x64", \
            f"restore-length pea at 0x{site:08x} not stock -- another mod widened it?"
    print(f"  QLR word 0x800000ac is +0x{q:02x} in the stock restore span; no build change")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

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
    print("  Hold [REC], tap [PLAY] twice CLOSE TOGETHER (within MAX_GAP ticks) ->")
    print("  toggles QUANTIZE LIVE REC; toast shows while [REC] is held (periodic")
    print("  dur>0 re-arm, Session 50/51 -- never a persistent dur<=0 toast, which hung")
    print("  the unit) and closes instantly on release.  PERSONALIZE row + power-cycle")
    print("  persistence unchanged.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

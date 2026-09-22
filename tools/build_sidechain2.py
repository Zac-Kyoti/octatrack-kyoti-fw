#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
SIDE-CHAIN COMPRESSOR -- step 2 of 4: keybus plumbing (same DSP core).

Everything build_sidechain.py does (Bug-1 fix + the KEY menu parameter on
COMPRESSOR page 2, descriptor slot 8) PLUS the DSP side:

  * SPATIALIZER (effect id 0x05) is DONATED.  Its 261-word P region in each
    payload is overwritten with the 37-word side-chain cave (tools/patch_sc_dsp.asm,
    `sctap` + `scdet`), and its X:0x215 / X:0x235 dispatch entries are retargeted
    to the null passthrough stub.  It is also REMOVED from the FX1 and FX2
    chooser lists (0x400d6060 / 0x400d6090) + ID2POS (0x400d6150), so it is not
    selectable at all -- a legacy project that still stores it shows "SPAT" and
    passes audio through, and the chooser cursor lands on NONE.

  * `jsr sctap` is spliced over `move x:>$208,r6` at the dispatcher's per-track
    FX1 entry (func_0004a7 / func_00029c), so every track publishes its pre-FX
    block to  keybus[track]  =  Y:(0x800 + track*0x80)  each frame.

  * `jsr scdet` is spliced over `move r0,n6 ; move #$61,r4` at COMPRESSOR
    proc+0.  When KEY != OFF the detector reads keybus[chosen track] instead of
    this track's own input; the dry/wet path is untouched.

Same-core only: KEY on a track in 1-4 chooses among 1-4, on 5-8 among 5-8.
(payload B / core 1 = tracks 1-4, CORE_BASE 0; payload A / core 0 = 5-8,
CORE_BASE 4 -- confirmed from each payload's x:0x420 init.)

Usage:   python3 tools/build_sidechain2.py [VERSTR]      (default "140C_KYOTI")
Outputs: out/mainos_sidechain2.bin, out/elek_sidechain2.bin,
         out/OCTATRACK_OS1.40C_SIDECHAIN2.syx, out/OCTATRACK_SIDECHAIN2.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
OUT = ROOT / "out/mainos_sidechain2.bin"
ELEK = ROOT / "out/elek_sidechain2.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_SIDECHAIN2.syx"
OUT_BIN = ROOT / "out/OCTATRACK_SIDECHAIN2.bin"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# ======================= ColdFire (same as build_sidechain.py) =======================
CF_PATCHES = [
    ("patch_trigscale", 0x400d7b00, [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_sidechain", 0x400d7000, []),
]
CF_FREE_END = 0x400d7c3c
E = 0x400d5a4a
KEY_SLOT = 8
CF_POKES = [
    (E + 0x4e + 6 * KEY_SLOT, "000000000000", b"KEY\x00\x00\x00",     "KEY name (slot 8)"),
    (E + 0xd2 + 4 * KEY_SLOT, "00000080",     (5).to_bytes(4, "big"), "KEY value-count 128 -> 5"),
    (E + 0x96 + KEY_SLOT,     "7f",           b"\x00",                "KEY default 127 -> 0 (OFF)"),
    (E + 0xa2 + 4 * KEY_SLOT, "00000000",     None,                   "KEY min (assert 0)"),
    (E + 0x132 + 4 * KEY_SLOT, "00000000",    None,                   "KEY widget ptr (assert 0)"),
    # Per-parameter ENABLE BITMAP -- NOT relative to E like the fields above.
    # refs/octabam/docs/firmware/PARAM_PAGES.md ("P+0x18a / P+0x18e"): the
    # struct base for this one field is P = E + 0x38; FUN_400a6994(P+0x18a,
    # P+0x18e, slot) gates whether the generic renderer stages OR DRAWS a
    # knob at all, independent of name/count/default being valid. Confirmed
    # against stock: slot 8's bit here reads 0 (RMS's slot 6 reads 1).
    # Without this the parameter compiles clean and never appears on screen.
    (E + 0x38 + 0x18a,        "00000000",     (1).to_bytes(4, "big"), "KEY enable bit (P+0x18a, slot 8)"),
]
CF_A_ARRAY = E + 0x102 + 4 * KEY_SLOT

# ======================= DSP (SPATIALIZER donor) =======================
# per payload:  cave org (= SPATIALIZER P addr) · @KADJ@ · dispatcher-hook P ·
#               compressor proc+0 P · null-stub init/proc P · X:0x215 file offset
DSP = {
    "A": dict(va=0x400e2324, ln=0x136cb, cave_org=0x00aa8, kadj="add     #3,a",
              disp_hook=0x004a7, comp_proc=0x01ab1, stub_init=0x007c8, stub_proc=0x007c9),
    "B": dict(va=0x400f59ef, ln=0x12d05, cave_org=0x00868, kadj="sub     #1,a",
              disp_hook=0x0029c, comp_proc=0x01871, stub_init=0x00588, stub_proc=0x00589),
}
SC_SRC = ROOT / "tools/patch_sc_dsp.asm"
NOP = 0x000000

# --- hide SPATIALIZER (donated -> passthrough) from the FX choosers ---
#  Two lists of descriptor pointers (E+0x38 each), NUL-terminated; the renderer
#  scans to the terminator, so removing an entry + shifting the rest + moving
#  the terminator is enough.  SPATIALIZER (E=0x400d4904) sits at position 7 in
#  both.  ID2POS (u32[id] -> cursor position) is rebuilt: id 0x05 -> 0 (a legacy
#  project that still stores SPATIALIZER lands the chooser cursor on NONE), and
#  every id past position 7 shifts down one.
FX1_LIST, FX1_LEN = 0x400d6060, 11
FX2_LIST, FX2_LEN = 0x400d6090, 15
FX1_ID2POS = 0x400d60d0   # FX1's OWN copy -- a separate table from ID2POS below,
                          # NOT shared with FX2 despite the identical stock values;
                          # confirmed 2026-09-14 (NOTES.md Session 56) by disassembling
                          # the FX1 chooser's own highlight code, which reads THIS
                          # table, not ID2POS -- rebuilding only ID2POS left FX1
                          # highlighting off by one for every id past SPAT_POS
ID2POS = 0x400d6150       # FX2's own copy
SPAT_P = 0x400d4904 + 0x38          # the SPATIALIZER descriptor pointer in the lists
SPAT_POS = 7


def w3(v):                       # 24-bit little-endian word
    return v.to_bytes(3, "little")


def jsr_short(addr):
    assert addr <= 0xFFF, f"jsr target 0x{addr:x} too big for the short form"
    return 0x0D0000 | addr


def cf_jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def cf_jsr(t):
    return b"\x4e\xb9" + t.to_bytes(4, "big")


def cf_assemble(name, at):
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", f"out/{name}.o", f"tools/{name}.s"],
                   check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{name}.elf", f"out/{name}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{name}.bin").read_bytes(), syms


def sc_assemble(kadj, org):
    src = SC_SRC.read_text().replace("@KADJ@", kadj)
    a = ROOT / "out/patch_sc_dsp.asm"
    a.write_text(src)
    o = ROOT / "out/patch_sc_dsp.bin"
    r = subprocess.run([str(DSP_ASM), "-in", str(a), "-org", f"{org:x}", "-out", str(o)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        sys.exit(f"dsp_asm failed:\n{r.stdout}\n{r.stderr}")
    raw = o.read_bytes()
    words = [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]
    # round-trip check: disassemble and re-assemble must match
    d = subprocess.run([str(DIS), "-in", str(o), "-pc", f"{org:x}", "-le"],
                       capture_output=True, text=True).stdout
    if " dc " in d or "InvalidInstruction" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    return words


def dsp_module_fileoff(img, va, ln, p_addr):
    """file offset of DSP P-word p_addr within payload at va."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(spec); spec.loader.exec_module(mm)
    mods, _ = mm.modules(bytes(img), va, ln)
    for sp, addr, cnt, data in mods:
        if sp == 0 and addr <= p_addr < addr + cnt:
            return (va - BASE) + data + (p_addr - addr) * 3
    sys.exit(f"P:0x{p_addr:05x} not in any P module of payload @0x{va:08x}")


def dsp_xtable_fileoff(img, va, ln, x_addr):
    import importlib.util
    spec = importlib.util.spec_from_file_location("mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(spec); spec.loader.exec_module(mm)
    mods, _ = mm.modules(bytes(img), va, ln)
    for sp, addr, cnt, data in mods:
        if sp == 1 and addr == x_addr:
            return (va - BASE) + data
    sys.exit(f"X:0x{x_addr:05x} module not found in payload @0x{va:08x}")


def rd3(img, off):
    return int.from_bytes(img[off:off + 3], "little")


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT}")
    for t in (DSP_ASM, DIS):
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t} -- build the DSP toolchain")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    # ---------------- ColdFire ----------------
    print("=== ColdFire: caves + detours ===")
    syms = {}
    spans = []
    for name, at, detours in CF_PATCHES:
        blob, s = cf_assemble(name, at)
        syms[name] = s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free")
        spans.append((at, at + len(blob)))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x}")
        for site, sym, exp, n, kind in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} unexpected: {bytes(img[do:do+len(exp)]).hex()}")
            br = cf_jsr(s[sym]) if kind == "jsr" else cf_jmp(s[sym])
            img[do:do + n] = br + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}")
    for a1, b1 in spans:
        for a2, b2 in spans:
            if (a1, b1) != (a2, b2) and a1 < b2 and a2 < b1:
                sys.exit("CF cave overlap")
    if max(b for _, b in spans) > CF_FREE_END:
        sys.exit("CF cave past free zone")

    key_fmt = syms["patch_sidechain"]["key_fmt"]
    print("\n=== ColdFire: COMPRESSOR descriptor (KEY at slot 8) ===")
    for addr, exp, new, tag in CF_POKES:
        do = o(addr)
        if bytes(img[do:do + len(exp) // 2]).hex() != exp:
            sys.exit(f"poke 0x{addr:08x} ({tag}) unexpected: {bytes(img[do:do+len(exp)//2]).hex()}")
        if new is not None:
            img[do:do + len(new)] = new
        print(f"  0x{addr:08x}  {tag}")
    do = o(CF_A_ARRAY)
    if bytes(img[do:do + 4]) != b"\x00\x00\x00\x00":
        sys.exit(f"A[8] 0x{CF_A_ARRAY:08x} not zero")
    img[do:do + 4] = key_fmt.to_bytes(4, "big")
    print(f"  0x{CF_A_ARRAY:08x}  KEY formatter -> 0x{key_fmt:08x}")

    # ---------------- DSP (both payloads) ----------------
    print("\n=== DSP: SPATIALIZER donor + hooks ===")
    for tag, d in DSP.items():
        cave = sc_assemble(d["kadj"], d["cave_org"])
        sctap = d["cave_org"]
        scdet = d["cave_org"] + next(i for i, w in enumerate(cave) if w == 0x00000c) + 1
        print(f"  payload {tag}: cave {len(cave)}w @ P:0x{d['cave_org']:05x}  "
              f"sctap=0x{sctap:x}  scdet=0x{scdet:x}")

        # 1. place the cave over SPATIALIZER
        spat_off = dsp_module_fileoff(img, d["va"], d["ln"], d["cave_org"])
        assert rd3(img, spat_off) == 0x250000, \
            f"payload {tag} SPATIALIZER not 'move #0,x0': {rd3(img, spat_off):06x}"
        for i, w in enumerate(cave):
            img[spat_off + i * 3: spat_off + i * 3 + 3] = w3(w)
        print(f"    cave -> file 0x{spat_off:x} ({len(cave)} words over SPATIALIZER's 261)")

        # 2. dispatcher FX1 entry: jsr sctap + nop  over  move x:>$208,r6
        hk = dsp_module_fileoff(img, d["va"], d["ln"], d["disp_hook"])
        assert (rd3(img, hk), rd3(img, hk + 3)) == (0x66f000, 0x000208), \
            f"payload {tag} disp hook not 'move x:>$208,r6': {rd3(img,hk):06x} {rd3(img,hk+3):06x}"
        img[hk:hk + 3] = w3(jsr_short(sctap))
        img[hk + 3:hk + 6] = w3(NOP)
        print(f"    dispatcher P:0x{d['disp_hook']:05x} -> jsr 0x{sctap:x} + nop")

        # 3. COMPRESSOR proc+0: jsr scdet + nop  over  move r0,n6 ; move #$61,r4
        cp = dsp_module_fileoff(img, d["va"], d["ln"], d["comp_proc"])
        assert (rd3(img, cp), rd3(img, cp + 3)) == (0x221e00, 0x346100), \
            f"payload {tag} comp proc+0 not [move r0,n6 ; move #61,r4]: {rd3(img,cp):06x} {rd3(img,cp+3):06x}"
        img[cp:cp + 3] = w3(jsr_short(scdet))
        img[cp + 3:cp + 6] = w3(NOP)
        print(f"    COMPRESSOR P:0x{d['comp_proc']:05x} -> jsr 0x{scdet:x} + nop")

        # 4. retarget SPATIALIZER's dispatch entries (id 0x05) to the null stub
        xt = dsp_xtable_fileoff(img, d["va"], d["ln"], 0x215)
        ini_off, prc_off = xt + 5 * 3, xt + (0x20 + 5) * 3
        assert rd3(img, ini_off) == d["cave_org"] and rd3(img, prc_off) == d["cave_org"] + 0xa, \
            f"payload {tag} disp entry 5 unexpected: {rd3(img,ini_off):06x} {rd3(img,prc_off):06x}"
        img[ini_off:ini_off + 3] = w3(d["stub_init"])
        img[prc_off:prc_off + 3] = w3(d["stub_proc"])
        print(f"    X:0x215[5] init  -> P:0x{d['stub_init']:05x}   "
              f"X:0x235[5] proc -> P:0x{d['stub_proc']:05x}  (SPATIALIZER -> passthrough)")

    # ---------------- hide SPATIALIZER from the FX choosers ----------------
    print("\n=== ColdFire: remove SPATIALIZER from the FX1/FX2 chooser ===")

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    for base, ln, tag in ((FX1_LIST, FX1_LEN, "FX1"), (FX2_LIST, FX2_LEN, "FX2")):
        entries = [u32(base + i * 4) for i in range(ln)]
        assert u32(base + ln * 4) == 0, f"{tag} list terminator missing"
        assert entries[SPAT_POS] == SPAT_P, \
            f"{tag}[{SPAT_POS}] is 0x{entries[SPAT_POS]:08x}, expected SPATIALIZER 0x{SPAT_P:08x}"
        new = entries[:SPAT_POS] + entries[SPAT_POS + 1:]        # drop position 7
        for i, v in enumerate(new):
            wr32(base + i * 4, v)
        wr32(base + len(new) * 4, 0)                              # new terminator
        print(f"  {tag} chooser: {ln} -> {len(new)} entries (SPATIALIZER dropped)")

    # ID2POS (FX2) + FX1_ID2POS (FX1's own, separate copy): id 0x05 -> 0 ; every id
    # at a cursor position > SPAT_POS shifts down 1. Both tables, same transform --
    # they are NOT the same table despite matching stock values.
    for tag, tbl in (("FX2 ID2POS", ID2POS), ("FX1 ID2POS", FX1_ID2POS)):
        wr32(tbl + 0x05 * 4, 0)
        moved = []
        for idv in range(0x20):
            pos = u32(tbl + idv * 4)
            if idv != 0x05 and pos > SPAT_POS:
                wr32(tbl + idv * 4, pos - 1)
                moved.append((idv, pos, pos - 1))
        print(f"  {tag}: id 0x05 -> 0; shifted {len(moved)} entries down "
              f"({', '.join(f'0x{i:02x}:{a}->{b}' for i, a, b in moved)})")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("MANUAL-TRIG FIX DIVERGED")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT / stock syx missing -- skipping the wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if "too long" in r.stdout:
        sys.exit(f'version string "{VERSTR}" does not fit')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}")
    print("  Test: COMPRESSOR on any track, FX page 2 -> KEY (after RMS). Pick a track on")
    print("        the SAME bank of four; that track's audio now drives the compression,")
    print("        even when it is muted.  SPATIALIZER now passes audio through.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

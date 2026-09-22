#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
SIDE-CHAIN COMPRESSOR -- DIAGNOSTIC / TESTING-ONLY BUILD.

Forked from build_sidechain3.py. Identical ColdFire side (descriptor slots,
SPATIALIZER removal from the FX choosers, the version wrap) -- only the DSP
cave differs: tools/patch_sc_diag.asm instead of patch_sc_dsp3.asm. See that
file's own header for exactly what's kept (KEY chooser, MON) vs fixed (KEY
FLT hardcoded to mid-LP) vs removed entirely (KEY GAIN, and the actual
compressor: RMS/envelope/gain-reduction math, ~140 words, P:comp_proc+2
onward in stock).

NOT A SHIPPING BUILD. Built to isolate whether SIDECHAIN3's reported
"metallic, resonant" ringing (MON on, KFLT != OFF) lives in the KEY-select/
KEY-FLT/MON plumbing this build keeps, or in the compressor math this build
removes.

Usage:   python3 tools/build_sidechain_diag.py [VERSTR]   (default "140C_DIAG")
Outputs: out/mainos_sidechain_diag.bin, out/elek_sidechain_diag.bin,
         out/OCTATRACK_OS1.40C_SIDECHAIN_DIAG.syx, out/OCTATRACK_SIDECHAIN_DIAG.bin
"""
import os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sc_tables

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
OUT = ROOT / "out/mainos_sidechain_diag.bin"
ELEK = ROOT / "out/elek_sidechain_diag.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_SIDECHAIN_DIAG.syx"
OUT_BIN = ROOT / "out/OCTATRACK_SIDECHAIN_DIAG.bin"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_DIAG"

# ======================= ColdFire ======================= (unchanged from
# build_sidechain3.py -- same descriptor slots, same free cave, same trig-
# scale carry-forward; KFLT/KGN knobs still draw and are still turnable,
# they just no longer do anything on the DSP side -- see patch_sc_diag.asm)
CF_PATCHES = [
    ("patch_trigscale", 0x400d7b00, [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_sidechain", 0x400d7000, []),
]
CF_FREE_END = 0x400d7c3c
E = 0x400d5a4a
FMT_BIPOLAR = 0x4003c7a0        # stock "-N" / "+N" about centre 64
FMT_ONOFF = 0x4003c14c          # stock "ON" / "OFF"

SLOTS = [
    (8,  b"KEY\x00\x00\x00", 5,   0,  "key_fmt",
     dict(name="000000000000", cnt="00000080", dflt="7f", b="00000000")),
    (9,  b"KFLT\x00\x00",     128, 64, "kfilt_fmt",
     dict(name="000000000000", cnt="00000002", dflt="00", b="400475f8")),
    (10, b"KGN\x00\x00\x00",  128, 64, FMT_BIPOLAR,
     dict(name="000000000000", cnt="00000080", dflt="00", b="00000000")),
    (11, b"MON\x00\x00\x00",  2,   0,  FMT_ONOFF,
     dict(name="000000000000", cnt="00000080", dflt="00", b="00000000")),
]

# ======================= DSP (SPATIALIZER donor) =======================
# comp_proc / commit_hook / disp_hook: identical addresses to build_sidechain3.py
# (same stock detour sites -- this build changes what our OWN cave code does,
# never the stock splice points themselves). `ctail` is NEW: the stock
# module's own 2-instruction bookkeeping tail (`move m0,x:(r7+$f)` / `rts`),
# verified by disassembly (not assumed) to be comp_proc + 0xa4 in BOTH
# payloads -- extracted and disassembled each payload's own copy of the
# module (NOTES.md Session 73): B tail = P:0x1915, A tail = P:0x1b55 =
# B_tail + 0x240, exactly matching comp_proc's own A-vs-B offset (0x1ab1 -
# 0x1871 = 0x240), i.e. a pure constant-offset relocation, not two
# independently-linked copies that happen to differ -- same class of
# per-payload address as @KADJ@ resolves, so uses the same mechanism.
DSP = {
    "A": dict(va=0x400e2324, ln=0x136cb, cave_org=0x00aa8, kadj="add     #3,a",
              disp_hook=0x004a7, comp_proc=0x01ab1, commit_hook=0x0050e,
              stub_init=0x007c8, stub_proc=0x007c9, ctail=0x01ab1 + 0xa4),
    "B": dict(va=0x400f59ef, ln=0x12d05, cave_org=0x00868, kadj="sub     #1,a",
              disp_hook=0x0029c, comp_proc=0x01871, commit_hook=0x00303,
              stub_init=0x00588, stub_proc=0x00589, ctail=0x01871 + 0xa4),
}
SC_SRC = ROOT / "tools/patch_sc_diag.asm"
DONOR_WORDS = 261
NOP = 0x000000

FX1_LIST, FX1_LEN = 0x400d6060, 11
FX2_LIST, FX2_LEN = 0x400d6090, 15
FX1_ID2POS = 0x400d60d0
ID2POS = 0x400d6150
SPAT_P = 0x400d4904 + 0x38
SPAT_POS = 7


def w3(v):
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


def sc_assemble(kadj, ctail, org):
    """assemble patch_sc_diag.asm at `org`, append the (now-unused-by-code
    but harmless) gain table + the f table the fixed-index KEY FLT lookup
    still needs. Two passes so `move #>@FTAB@` / `move #>@CTAIL@` widths
    don't shift. Returns (words, sctap, scdet, moncommit, ctail_jump)."""
    def one(ft):
        src = (SC_SRC.read_text().replace("@KADJ@", kadj)
               .replace("@CTAIL@", f"${ctail:x}").replace("@FTAB@", f"${ft:x}"))
        a = ROOT / "out/patch_sc_diag.asm"; a.write_text(src)
        o = ROOT / "out/patch_sc_diag.bin"
        r = subprocess.run([str(DSP_ASM), "-in", str(a), "-org", f"{org:x}", "-out", str(o)],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            sys.exit(f"dsp_asm failed:\n{r.stdout}\n{r.stderr}")
        raw = o.read_bytes()
        return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]

    code = one(org)
    n = len(code)
    code = one(org + n + sc_tables.GAIN_N)
    assert len(code) == n, "cave size shifted between the two sizing passes"
    words = code + sc_tables.gain_table() + sc_tables.flt_table()
    if len(words) > DONOR_WORDS:
        sys.exit(f"cave {len(words)} words > SPATIALIZER donor's {DONOR_WORDS}")
    (ROOT / "out/patch_sc_diag_code.bin").write_bytes(
        b"".join(w.to_bytes(3, "little") for w in code))
    d = subprocess.run([str(DIS), "-in", str(ROOT / "out/patch_sc_diag_code.bin"),
                        "-pc", f"{org:x}", "-le"], capture_output=True, text=True).stdout
    if " dc " in d or "InvalidInstruction" in d or "mpysu" in d or "macsu" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    rts = [i for i, w in enumerate(code) if w == 0x00000c]
    # Same rts[0..3] convention as build_sidechain3.py: rts[0] = sctap/scdet
    # boundary, rts[1] = zz16 (KEY-present exit), rts[2] = zz20 (KEY-OFF
    # exit), rts[3] = zz18's own -- moncommit starts right after it. Adding
    # the jsr-to-ctail pair before zz16/zz20's rts does not add or remove
    # any rts opcodes, so this indexing is unaffected by the diagnostic
    # build's changes (verified below by asserting scdet's own count).
    # moncommit (HOOK 3) has its own 2 rts (the early no-match exit, mc11's
    # final one): rts[4], rts[5]. zz21 (HOOK 4, NEW -- the comp_proc+2 guard,
    # see patch_sc_diag.asm's own header) starts right after, at rts[5]+1,
    # and has one rts of its own (rts[6], unused here but keeps the count
    # assertion below honest for anyone extending this file further).
    assert len(rts) >= 7, f"expected >=7 rts (sctap + scdet's 3 + moncommit's 2 + zz21's 1), got {len(rts)}"
    return words, org, org + rts[0] + 1, org + rts[3] + 1, org + rts[5] + 1


def dsp_module_fileoff(img, va, ln, p_addr):
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

    # ---------------- ColdFire: caves + detours ----------------
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
    if max(b for _, b in spans) > CF_FREE_END:
        sys.exit("CF cave past free zone")
    fmt_sym = syms["patch_sidechain"]

    # ---------------- ColdFire: COMPRESSOR descriptor (KEY/KFLT/KGAIN/MON) ----
    print("\n=== ColdFire: COMPRESSOR descriptor slots 8..11 ===")
    for slot, name, cnt, dflt, fmt, cur in SLOTS:
        na, ca, da, aa, ba = (E + 0x4e + 6 * slot, E + 0xd2 + 4 * slot, E + 0x96 + slot,
                              E + 0x102 + 4 * slot, E + 0x132 + 4 * slot)
        assert bytes(img[o(na):o(na) + 6]).hex() == cur["name"], f"slot {slot} name"
        assert f"{int.from_bytes(img[o(ca):o(ca)+4],'big'):08x}" == cur["cnt"], f"slot {slot} count"
        assert f"{img[o(da)]:02x}" == cur["dflt"], f"slot {slot} default"
        assert f"{int.from_bytes(img[o(ba):o(ba)+4],'big'):08x}" == cur["b"], f"slot {slot} B"
        assert int.from_bytes(img[o(aa):o(aa) + 4], "big") == 0, f"slot {slot} A not zero"
        img[o(na):o(na) + 6] = name
        img[o(ca):o(ca) + 4] = cnt.to_bytes(4, "big")
        img[o(da)] = dflt
        img[o(ba):o(ba) + 4] = (0).to_bytes(4, "big")
        a_val = fmt_sym[fmt] if isinstance(fmt, str) else fmt
        img[o(aa):o(aa) + 4] = a_val.to_bytes(4, "big")
        label = name.rstrip(b"\x00").decode()
        print(f"  slot {slot:2d}  {label:5s}  count {cnt:3d}  "
              f"default {dflt:3d}  A 0x{a_val:08x}")

    ea = E + 0x38 + 0x18a
    assert int.from_bytes(img[o(ea):o(ea) + 4], "big") == 0, "enable bitmap (slots 8-11) not 0"
    img[o(ea):o(ea) + 4] = (0x1111).to_bytes(4, "big")
    print(f"  enable bitmap 0x{ea:08x}  slots 8-11 -> 0x00001111 (all on)")

    # ---------------- DSP (both payloads) ----------------
    print("\n=== DSP: SPATIALIZER donor + sctap / scdet(diag) / moncommit ===")
    for tag, d in DSP.items():
        words, sctap, scdet, moncommit, ctail_jump = sc_assemble(d["kadj"], d["ctail"], d["cave_org"])
        print(f"  payload {tag}: cave {len(words)}w @ P:0x{d['cave_org']:05x}  "
              f"sctap=0x{sctap:x} scdet=0x{scdet:x} moncommit=0x{moncommit:x} "
              f"ctail=0x{d['ctail']:x} ctail_jump=0x{ctail_jump:x}")

        spat_off = dsp_module_fileoff(img, d["va"], d["ln"], d["cave_org"])
        assert rd3(img, spat_off) == 0x250000, \
            f"payload {tag} SPATIALIZER not 'move #0,x0': {rd3(img, spat_off):06x}"
        for i, wv in enumerate(words):
            img[spat_off + i * 3: spat_off + i * 3 + 3] = w3(wv)
        print(f"    cave -> file 0x{spat_off:x} ({len(words)}/{DONOR_WORDS} donor words)")

        hk = dsp_module_fileoff(img, d["va"], d["ln"], d["disp_hook"])
        assert (rd3(img, hk), rd3(img, hk + 3)) == (0x66f000, 0x000208), \
            f"payload {tag} disp hook: {rd3(img,hk):06x} {rd3(img,hk+3):06x}"
        img[hk:hk + 3] = w3(jsr_short(sctap))
        img[hk + 3:hk + 6] = w3(NOP)
        print(f"    dispatcher P:0x{d['disp_hook']:05x} -> jsr 0x{sctap:x} + nop")

        cp = dsp_module_fileoff(img, d["va"], d["ln"], d["comp_proc"])
        assert (rd3(img, cp), rd3(img, cp + 3)) == (0x221e00, 0x346100), \
            f"payload {tag} comp proc+0: {rd3(img,cp):06x} {rd3(img,cp+3):06x}"
        img[cp:cp + 3] = w3(jsr_short(scdet))
        img[cp + 3:cp + 6] = w3(NOP)
        print(f"    COMPRESSOR P:0x{d['comp_proc']:05x} -> jsr 0x{scdet:x} + nop")

        # Verify the ctail target really is the module's own 2-word tail
        # BEFORE it gets overwritten by anything else -- `move m0,x:(r7+$f)`
        # then `rts`, byte-identical in both payloads (confirmed by disasm,
        # NOTES.md Session 73). This is what scdet(diag) jumps to instead of
        # falling through into the real compressor body.
        ct = dsp_module_fileoff(img, d["va"], d["ln"], d["ctail"])
        assert (rd3(img, ct), rd3(img, ct + 3)) == (0x0a77a0, 0x00000f), \
            f"payload {tag} ctail not 'move m0,x:(r7+$f)': {rd3(img,ct):06x} {rd3(img,ct+3):06x}"
        assert rd3(img, ct + 6) == 0x00000c, \
            f"payload {tag} ctail+2 not rts: {rd3(img,ct+6):06x}"
        print(f"    ctail P:0x{d['ctail']:05x} confirmed 'move m0,x:(r7+$f) / rts' (untouched)")

        # HOOK 4 (patch_sc_diag.asm's own header, NOTES.md Session 73): a
        # second, independent entry into the real compressor body was found
        # dynamically (--dsp-pcwatch on a first build of this diagnostic
        # image showed P:comp_proc+2 reached with a genuine per-track r7,
        # even though scdet's own redirect never falls through there) --
        # the caller was not identified, so guard the body's own entry
        # directly instead of chasing it further. comp_proc+2 is always
        # `move x:(r0)+,x0` (0x44d800) in stock, ONE word -- detour it
        # (short jsr, no nop needed) to zz21, which does exactly what
        # scdet's own tail does (jsr the module's own ctail, then rts).
        cb = dsp_module_fileoff(img, d["va"], d["ln"], d["comp_proc"] + 2)
        assert rd3(img, cb) == 0x44d800, \
            f"payload {tag} comp_proc+2 not 'move x:(r0)+,x0': {rd3(img,cb):06x}"
        img[cb:cb + 3] = w3(jsr_short(ctail_jump))
        print(f"    COMPRESSOR P:0x{d['comp_proc']+2:05x} -> jsr 0x{ctail_jump:x} (2nd-entry guard)")

        mc = dsp_module_fileoff(img, d["va"], d["ln"], d["commit_hook"])
        assert (rd3(img, mc), rd3(img, mc + 3)) == (0x60f000, 0x000206), \
            f"payload {tag} commit hook not `move x:>$206,r0`: {rd3(img,mc):06x} {rd3(img,mc+3):06x}"
        img[mc:mc + 3] = w3(jsr_short(moncommit))
        img[mc + 3:mc + 6] = w3(NOP)
        print(f"    dispatcher P:0x{d['commit_hook']:05x} -> jsr 0x{moncommit:x} + nop")

        xt = dsp_xtable_fileoff(img, d["va"], d["ln"], 0x215)
        ini_off, prc_off = xt + 5 * 3, xt + (0x20 + 5) * 3
        assert rd3(img, ini_off) == d["cave_org"] and rd3(img, prc_off) == d["cave_org"] + 0xa, \
            f"payload {tag} disp entry 5: {rd3(img,ini_off):06x} {rd3(img,prc_off):06x}"
        img[ini_off:ini_off + 3] = w3(d["stub_init"])
        img[prc_off:prc_off + 3] = w3(d["stub_proc"])
        print(f"    X:0x215[5] -> null stub (SPATIALIZER -> passthrough)")

    # ---------------- hide SPATIALIZER from the FX choosers ----------------
    print("\n=== ColdFire: remove SPATIALIZER from FX1/FX2 chooser ===")

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    for base, ln, tag in ((FX1_LIST, FX1_LEN, "FX1"), (FX2_LIST, FX2_LEN, "FX2")):
        entries = [u32(base + i * 4) for i in range(ln)]
        assert u32(base + ln * 4) == 0, f"{tag} terminator"
        assert entries[SPAT_POS] == SPAT_P, f"{tag}[{SPAT_POS}] != SPATIALIZER"
        new = entries[:SPAT_POS] + entries[SPAT_POS + 1:]
        for i, v in enumerate(new):
            wr32(base + i * 4, v)
        wr32(base + len(new) * 4, 0)
        print(f"  {tag}: {ln} -> {len(new)} entries")
    for tbl in (ID2POS, FX1_ID2POS):
        wr32(tbl + 0x05 * 4, 0)
        for idv in range(0x20):
            pos = u32(tbl + idv * 4)
            if idv != 0x05 and pos > SPAT_POS:
                wr32(tbl + idv * 4, pos - 1)
    print("  ID2POS + FX1_ID2POS rebuilt (id 0x05 -> 0)")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT / stock syx missing -- skipping wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if "too long" in r.stdout:
        sys.exit(f'version "{VERSTR}" does not fit')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}")
    print("  DIAGNOSTIC BUILD -- not a shipping image. COMPRESSOR on a track still shows")
    print("  RMS/KEY/KFLT/KGAIN/MON on FX page 2, but only KEY and MON do anything; KFLT")
    print("  always runs fixed at mid-LP regardless of its knob; KGAIN does nothing; RMS")
    print("  is read by nothing (the real envelope-follower/gain code never runs at all).")
    print("  Test: COMPRESSOR on target track, KEY = a different track, MON = ON. Confirms")
    print("  whether the reported ringing lives in the KEY/KFLT/MON path (still present")
    print("  here) or in the actual compressor math (entirely absent here).")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

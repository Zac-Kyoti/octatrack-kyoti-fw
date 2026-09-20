#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
SIDE-CHAIN COMPRESSOR -- step 3 of 4: KEY GAIN, KEY FLT and SC LISTEN in the DSP.

Everything build_sidechain2.py ships (Bug-1 fix, a DSP donor pulled from the FX
choosers, sctap publish tap, scdet detector redirect) PLUS:

  * three more COMPRESSOR page-2 parameters -- KFLT (slot 9), KGAIN (slot 10),
    MON / "SC LISTEN" (slot 11) -- next to KEY (slot 8) and RMS (slot 6).
  * the DSP cave is tools/patch_sc_dsp3.asm (a superset of patch_sc_dsp.asm):
      scdet      now also scales the staged key by KEY GAIN and runs a
                 one-pole-pair Chamberlin SVF (KEY FLT: <64 LP, >64 HP, 64
                 bypass); when MON is on it also publishes MON_ON/MON_KEY
                 (Y:0x800+track*0x80+0x40/0x41, this track's own otherwise-
                 dead keybus gen-2 slot) for moncommit to read.
      moncommit  a THIRD hook, spliced at the DISPATCHER's per-track COMMIT
                 step (NOT inside the compressor module -- Session 55/57
                 found the old proc-end splice shared an unmapped, buggy
                 timing dependency with the compressor's own undocumented
                 envelope/gain math; Session 58 redesigned around it entirely
                 rather than keep chasing it). Runs strictly after this
                 track's whole FX1+FX2 processing has already returned, and
                 if MON_ON says so, overwrites X:0 with a fresh re-fetch of
                 keybus[key] gen 1 before this track's audio is committed.
  * two coefficient tables (tools/sc_tables.py: 16-word gain, 32-word f) are
    appended to the cave; @GTAB@ / @FTAB@ in the .asm are resolved to their
    absolute P addresses in a first sizing pass.

Session 76 continued: donor swapped from SPATIALIZER (261 stock words, no slack
left) to SPRING REVERB (id 0x15, FX2-exclusive) -- its module measures 1063
words in each payload (`refs/octabam/tools/build/dsp_modmap.py` module walk,
init to next-module boundary), so SPATIALIZER is now fully RESTORED as a
selectable effect (nothing here touches it any more) and SPRING REVERB gets
the same "null dispatch -> shared generic empty-FX stub" backward-compat
treatment SPATIALIZER used to get, for any older project that still
references it by id. Cave + tables must fit within SPRING REVERB's 1063-word
P region in each payload (currently ~230 + 48, i.e. still nowhere near full).

Usage:   python3 tools/build_sidechain3.py [VERSTR]      (default "140C_KYOTI")
Outputs: out/mainos_sidechain3.bin, out/elek_sidechain3.bin,
         out/OCTATRACK_OS1.40C_SIDECHAIN3.syx, out/OCTATRACK_SIDECHAIN3.bin
"""
import os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sc_tables
import dsp_asm_util

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
OUT = ROOT / "out/mainos_sidechain3.bin"
ELEK = ROOT / "out/elek_sidechain3.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_SIDECHAIN3.syx"
OUT_BIN = ROOT / "out/OCTATRACK_SIDECHAIN3.bin"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# ======================= ColdFire =======================
CF_PATCHES = [
    ("patch_trigscale", 0x400d7b00, [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_sidechain", 0x400d7000, []),
]
CF_FREE_END = 0x400d7c3c
E = 0x400d5a4a
FMT_BIPOLAR = 0x4003c7a0        # stock "-N" / "+N" about centre 64
FMT_ONOFF = 0x4003c14c          # stock "ON" / "OFF"

# Stock generic bipolar-switch draw callback (descriptor field B, E+0x132+4*slot).
# Confirmed by cross-referencing 5 real stock 2-position switches across two
# unrelated page classes -- machine-page FLEX/STATIC page-2 SLIC (slot 7) /
# LEN (slot 8) / RATE (slot 9), and FX-page FILTER page-2 ENV (slot 8) / HOLD
# (slot 9) -- every one of them has count=2 and this exact B value, despite
# each pairing a *different* A-formatter (own label text), proving the
# function is generic/context-driven, not baked per-parameter. FILTER's HOLD
# is a byte-for-byte match of what we want for MON (A=FMT_ONOFF, count=2, B=
# this), so this is as close to a proven-on-hardware precedent as static RE
# gets short of flashing it. Disassembled (`m68k-elf-objdump`) alongside its
# two siblings 0x400477d4 (SPATIALIZER M/S / DELAY X,TAPE,SYNC,LOCK,PASS) and
# 0x400475f8 (KFLT's own B, PLATE REV's unnamed switch) -- three distinct,
# differently-coded functions, so the choice is NOT interchangeable; picked
# this one specifically because it's the one the user's own SLIC/LEN/RATE
# reference actually uses.
SWITCH_FN = 0x40046f10

# Stock N-way scrolling-list draw callback (LFO page-2 TRIG's own B, E=
# 0x400d37be per refs/octabam/docs/firmware/PARAM_PAGES.md -- LFO shares
# COMPRESSOR's own page-class 0x400328e4). Picked over LFO MULT's own B
# (0x400467a4, structurally near-identical opening preamble on disassembly,
# so not ruled out as the SAME family, but the user specifically wants
# TRIG's visual behaviour -- "nothing but a simple list that gets scrolled
# through" -- not MULT's, and TRIG is the one actually asked for). Unlike
# CHORUS TAPS's own tick-selector (0x40047254, `moveq #4,%d0 / cmpl
# %d2,%d0` -- the option count compiled directly into the function, single
# use per octabam's own inventory, PARAM_PAGES.md SS7), TRIG's disassembly
# (`m68k-elf-objdump`, this session) shows NO compiled-in count comparison
# anywhere -- every option-count-shaped value it touches comes from its own
# stack parameters, not a literal. That matters beyond just "looks right
# today": KEY is headed for cross-core (any of 8 tracks, count 9 not 5) --
# a hardcoded-count renderer like CHORUS TAPS's would need re-picking (or
# re-deriving) later, where a genuinely count-agnostic one, if that's what
# this is, would not. NOT hardware-cross-verified the way SWITCH_FN was (5
# independent real 2-position switches, before this project trusted it) --
# this is one confirmed disassembly read, not a cross-reference. Cosmetic-
# only risk if wrong (a menu render, not DSP/audio), unlike everything else
# this project touches -- worth trying and looking at, not worth blocking
# on more RE first.
LIST_FN = 0x40046450

# descriptor slot -> (name, count, default, A-formatter, current-bytes to assert)
#   A-formatter: "key_fmt"/"kfilt_fmt" resolved from patch_sidechain.elf, else a literal
#   bnew: descriptor field B to WRITE (0 = plain knob widget, unchanged from
#   before; SWITCH_FN = render as a stock bipolar switch instead)
SLOTS = [
    (8,  b"KEY\x00\x00\x00", 5,   0,  "key_fmt",
     dict(name="000000000000", cnt="00000080", dflt="7f", b="00000000"), "key_list_fix"),
    (9,  b"KFLT\x00\x00",     128, 64, "kfilt_fmt",
     dict(name="000000000000", cnt="00000002", dflt="00", b="400475f8"), 0),
    (10, b"KGN\x00\x00\x00",  128, 64, FMT_BIPOLAR,
     dict(name="000000000000", cnt="00000080", dflt="00", b="00000000"), 0),
    (11, b"MON\x00\x00\x00",  2,   0,  FMT_ONOFF,
     dict(name="000000000000", cnt="00000080", dflt="00", b="00000000"), SWITCH_FN),
]

# ======================= DSP (SPRING REVERB donor) ======================
# commit_hook: the dispatcher's per-track COMMIT step (`move x:>$206,r0`,
# reading this track's output-slot pointer immediately before the copy-to-
# output-slot call) -- confirmed identical in both payloads by disassembly
# (NOTES.md Session 58): same instruction, same 5-instruction tail after it
# (`move #$0,r1 / move #$1,n1 / move x:>$419,r3 / jsr <per-payload commit fn>`),
# just at each payload's own address. `moncommit` splices here instead of the
# old proc-end `sctail` site -- it runs after the WHOLE compressor module
# (including its own undocumented envelope/gain math) has already returned.
#
# cave_org = SPRING REVERB's own dispatch-table init address (id 0x15,
# X:0x215[0x15]) in each payload -- verified by `dsp_modmap.py`'s module walk
# to be the START of a standalone 1063-word P module (init to the next
# module's own start, no overlap either side, Session 76 continued). Unlike
# the old SPATIALIZER donor, SPRING REVERB's stock init/proc entries are NOT
# 0xa words apart (its own real init routine is ~0x6c/108 words long) -- that
# stock relationship is irrelevant here since X:0x215[0x15] gets fully
# retargeted at our own stub below, nothing stock ever reaches SPRING REVERB's
# real proc address again. `spring_proc` is that stock proc address, kept only
# for the pre-write sanity assert (so a future firmware revision that moved it
# fails loud instead of silently splicing over the wrong bytes).
DSP = {
    "A": dict(va=0x400e2324, ln=0x136cb, cave_org=0x01252, spring_proc=0x012be,
              kadj="add     #3,a",
              disp_hook=0x004a7, comp_proc=0x01ab1, commit_hook=0x0050e,
              stub_init=0x007c8, stub_proc=0x007c9),
    "B": dict(va=0x400f59ef, ln=0x12d05, cave_org=0x01012, spring_proc=0x0107e,
              kadj="sub     #1,a",
              disp_hook=0x0029c, comp_proc=0x01871, commit_hook=0x00303,
              stub_init=0x00588, stub_proc=0x00589),
}
SC_SRC = ROOT / "tools/patch_sc_dsp3.asm"
DONOR_WORDS = 1063
NOP = 0x000000

FX2_LIST, FX2_LEN = 0x400d6090, 15
ID2POS = 0x400d6150       # FX2's own id->position table (FX1 has a separate copy, untouched here)
SPRING_P = 0x400d5726 + 0x38
SPRING_POS = 13


def w3(v):
    return v.to_bytes(3, "little")


def jsr_short(addr):
    # Kept only because tools/build_merged.py imports it (`sc3.jsr_short`) --
    # this build's own main() no longer calls it (see bsr_long() below).
    # NOTE: build_merged.py still assumes the OLD SPATIALIZER cave_org, which
    # this file no longer uses at all -- it needs the same donor-swap pass
    # before its next real build (Session 76 continued left this for later,
    # scope was build_sidechain3.py/patch_sc_dsp3.asm only).
    assert addr <= 0xFFF, f"jsr target 0x{addr:x} too big for the short form"
    return 0x0D0000 | addr


def bsr_long(from_addr, to_addr):
    """2-word PC-relative call (opcode 0x0D1080 + signed displacement),
    replacing the old jsr_short()+NOP pair now that the SPRING REVERB donor's
    cave_org sits past 0xfff, past dsp_asm's short-jsr absolute-address range
    (Session 76 continued). Encoding verified empirically against dsp_asm
    itself (assembling `bsr $addr` at various origins, including negative and
    >0xfff displacements) -- opcode word is constant, only the displacement
    word varies. `rts` pops a `bsr`-pushed return address exactly like a
    `jsr`-pushed one; the two are interchangeable here, only the addressing
    mode (relative vs. absolute) differs."""
    disp = (to_addr - from_addr) & 0xFFFFFF
    return 0x0D1080, disp


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
    """assemble patch_sc_dsp3.asm at `org`, append the gain/f tables.
    Two passes so `move #>@GTAB@` / `move #>@FTAB@` widths don't shift.
    Returns (words, sctap, scdet, moncommit)."""
    def one(gt, ft):
        src = (SC_SRC.read_text().replace("@KADJ@", kadj)
               .replace("@GTAB@", f"${gt:x}").replace("@FTAB@", f"${ft:x}")
               .replace("@LPEDGE@", f"${sc_tables.lp_edge():x}")
               .replace("@HPEDGE@", f"${sc_tables.hp_edge():x}")
               .replace("@KGNA@", f"${sc_tables.kgn_smooth_a():x}"))
        a = ROOT / "out/patch_sc_dsp3.asm"; a.write_text(src)
        o = ROOT / "out/patch_sc_dsp3.bin"
        r = subprocess.run([str(DSP_ASM), "-in", str(a), "-org", f"{org:x}", "-out", str(o)],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            sys.exit(f"dsp_asm failed:\n{r.stdout}\n{r.stderr}")
        raw = o.read_bytes()
        return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]

    code = one(org, org)
    n = len(code)
    code = one(org + n, org + n + sc_tables.GAIN_N)
    assert len(code) == n, "cave size shifted between the two sizing passes"
    words = code + sc_tables.gain_table() + sc_tables.flt_table()
    if len(words) > DONOR_WORDS:
        sys.exit(f"cave {len(words)} words > SPRING REVERB donor's {DONOR_WORDS}")
    # round-trip the code region; reject mpysu/macsu (dsp_asm's `mpy x0,y0` trap)
    (ROOT / "out/patch_sc_dsp3_code.bin").write_bytes(
        b"".join(w.to_bytes(3, "little") for w in code))
    d = subprocess.run([str(DIS), "-in", str(ROOT / "out/patch_sc_dsp3_code.bin"),
                        "-pc", f"{org:x}", "-le"], capture_output=True, text=True).stdout
    if " dc " in d or "InvalidInstruction" in d or "mpysu" in d or "macsu" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    # rts[0] = sctap's own rts (sctap/scdet boundary).
    # scdet has THREE internal rts as of the zz18 shared OFF-publish sub
    # (patch_sc_dsp3.asm, called via `jsr` from zz17 and zz20): rts[1] =
    # zz16's (the KEY-present exit), rts[2] = zz20's (the KEY-OFF exit,
    # unchanged position from before zz18 existed), rts[3] = zz18's own --
    # placed deliberately AFTER zz20's in the source so it lands last and
    # moncommit (HOOK 3, immediately following) starts right after it.
    # Found via dsp_asm_util.find_rts() (disassembler-parsed instruction
    # boundaries), NOT a raw word scan for 0x00000c -- that also matches a
    # 2-word branch's own displacement operand (Session 76 continued yet
    # again: a new branch with a displacement of exactly 12 silently
    # mis-located moncommit by one rts index before this fix -- caught only
    # because emu_sc_dsp3_moncommit.py failed after a full rebuild, not by
    # this same round-trip check above, which only rejects invalid opcodes).
    rts = dsp_asm_util.find_rts(d, org)
    return words, org, org + rts[0] + 1, org + rts[3] + 1


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
    for slot, name, cnt, dflt, fmt, cur, bnew in SLOTS:
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
        b_val = fmt_sym[bnew] if isinstance(bnew, str) else bnew
        img[o(ba):o(ba) + 4] = b_val.to_bytes(4, "big")
        a_val = fmt_sym[fmt] if isinstance(fmt, str) else fmt
        img[o(aa):o(aa) + 4] = a_val.to_bytes(4, "big")
        label = name.rstrip(b"\x00").decode()
        print(f"  slot {slot:2d}  {label:5s}  count {cnt:3d}  "
              f"default {dflt:3d}  A 0x{a_val:08x}  B 0x{b_val:08x}")

    # Per-parameter ENABLE BITMAP -- NOT relative to E like the fields above.
    # refs/octabam/docs/firmware/PARAM_PAGES.md ("P+0x18a / P+0x18e"): the
    # struct base for this one field is P = E + 0x38; FUN_400a6994(P+0x18a,
    # P+0x18e, slot) gates whether the generic renderer stages OR DRAWS a
    # knob at all, independent of name/count/default being valid. Confirmed
    # against stock: slots 8-11's nibbles here all read 0 (RMS's slot 6, in
    # the neighbouring P+0x18e word, reads 1). Without this poke KEY/KFLT/
    # KGAIN/MON compile clean and never appear on screen.
    ea = E + 0x38 + 0x18a
    assert int.from_bytes(img[o(ea):o(ea) + 4], "big") == 0, "enable bitmap (slots 8-11) not 0"
    img[o(ea):o(ea) + 4] = (0x1111).to_bytes(4, "big")
    print(f"  enable bitmap 0x{ea:08x}  slots 8-11 -> 0x00001111 (all on)")

    # ---------------- DSP (both payloads) ----------------
    print("\n=== DSP: SPRING REVERB donor + sctap / scdet / moncommit ===")
    for tag, d in DSP.items():
        words, sctap, scdet, moncommit = sc_assemble(d["kadj"], d["cave_org"])
        print(f"  payload {tag}: cave {len(words)}w @ P:0x{d['cave_org']:05x}  "
              f"sctap=0x{sctap:x} scdet=0x{scdet:x} moncommit=0x{moncommit:x}")

        # SPRING REVERB's own real init routine's first 3 words -- a much more
        # distinctive canary than SPATIALIZER's single "move #0,x0" was, given
        # how much more this donor now carries. Read directly off stock
        # section_3_MAIN_OS.bin, identical in both payloads.
        donor_off = dsp_module_fileoff(img, d["va"], d["ln"], d["cave_org"])
        sig = [rd3(img, donor_off + 3 * i) for i in range(3)]
        assert sig == [0x22ee00, 0x0140c0, 0x000040], \
            f"payload {tag} SPRING REVERB init signature mismatch: {[hex(x) for x in sig]}"
        for i, wv in enumerate(words):
            img[donor_off + i * 3: donor_off + i * 3 + 3] = w3(wv)
        print(f"    cave -> file 0x{donor_off:x} ({len(words)}/{DONOR_WORDS} donor words)")

        # Detour sites patch in a 2-word `bsr` (PC-relative call), not the old
        # jsr_short()+NOP pair -- the SPRING REVERB donor's cave_org is past
        # dsp_asm's short-jsr absolute-address range (Session 76 continued,
        # see bsr_long()'s own docstring). Each site was already exactly 2
        # stock words, so bsr's own 2 words fill it with no separate NOP.
        hk = dsp_module_fileoff(img, d["va"], d["ln"], d["disp_hook"])
        assert (rd3(img, hk), rd3(img, hk + 3)) == (0x66f000, 0x000208), \
            f"payload {tag} disp hook: {rd3(img,hk):06x} {rd3(img,hk+3):06x}"
        op, disp = bsr_long(d["disp_hook"], sctap)
        img[hk:hk + 3] = w3(op)
        img[hk + 3:hk + 6] = w3(disp)
        print(f"    dispatcher P:0x{d['disp_hook']:05x} -> bsr 0x{sctap:x}")

        cp = dsp_module_fileoff(img, d["va"], d["ln"], d["comp_proc"])
        assert (rd3(img, cp), rd3(img, cp + 3)) == (0x221e00, 0x346100), \
            f"payload {tag} comp proc+0: {rd3(img,cp):06x} {rd3(img,cp+3):06x}"
        op, disp = bsr_long(d["comp_proc"], scdet)
        img[cp:cp + 3] = w3(op)
        img[cp + 3:cp + 6] = w3(disp)
        print(f"    COMPRESSOR P:0x{d['comp_proc']:05x} -> bsr 0x{scdet:x}")

        # dispatcher-level commit hook (payload A P:0x50e / payload B P:0x303,
        # both `move x:>$206,r0` -- confirmed identical detour bytes in both
        # payloads by disassembly, NOTES.md Session 58)
        mc = dsp_module_fileoff(img, d["va"], d["ln"], d["commit_hook"])
        assert (rd3(img, mc), rd3(img, mc + 3)) == (0x60f000, 0x000206), \
            f"payload {tag} commit hook not `move x:>$206,r0`: {rd3(img,mc):06x} {rd3(img,mc+3):06x}"
        op, disp = bsr_long(d["commit_hook"], moncommit)
        img[mc:mc + 3] = w3(op)
        img[mc + 3:mc + 6] = w3(disp)
        print(f"    dispatcher P:0x{d['commit_hook']:05x} -> bsr 0x{moncommit:x}")

        # SPRING REVERB's dispatch id (0x15) -> the SAME generic empty-FX
        # stub SPATIALIZER used to be redirected to (stub_init/stub_proc are
        # not SPATIALIZER-specific -- confirmed by reading X:0x215 across all
        # 32 ids: this exact pair is already the init/proc target for 18
        # OTHER unused ids in stock firmware, i.e. it's the shared "no real
        # effect assigned here" passthrough). Any older project's pattern
        # that still references SPRING REVERB by id gets exactly the same
        # graceful silent-passthrough behaviour those already get.
        xt = dsp_xtable_fileoff(img, d["va"], d["ln"], 0x215)
        ini_off, prc_off = xt + 0x15 * 3, xt + (0x20 + 0x15) * 3
        assert rd3(img, ini_off) == d["cave_org"] and rd3(img, prc_off) == d["spring_proc"], \
            f"payload {tag} disp entry 0x15: {rd3(img,ini_off):06x} {rd3(img,prc_off):06x}"
        img[ini_off:ini_off + 3] = w3(d["stub_init"])
        img[prc_off:prc_off + 3] = w3(d["stub_proc"])
        print(f"    X:0x215[0x15] -> null stub (SPRING REVERB -> passthrough)")

    # ---------------- hide SPRING REVERB from the FX2 chooser --------------
    # SPRING REVERB is FX2-exclusive (reverbs never appear on FX1, hardware
    # menu restriction -- reference/kb/memory-map.md), confirmed directly
    # against stock: it's absent from FX1_LIST entirely. So unlike the old
    # SPATIALIZER donor swap (which needed BOTH FX1_LIST/FX1_ID2POS and
    # FX2_LIST/ID2POS rebuilt -- the Session 56 "chooser highlights the wrong
    # effect" bug came from missing FX1's own separate id->position table),
    # this only ever touches FX2_LIST/ID2POS. SPATIALIZER itself needs no
    # code here at all any more -- it's fully restored simply by no longer
    # being removed.
    print("\n=== ColdFire: remove SPRING REVERB from FX2 chooser ===")

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    entries = [u32(FX2_LIST + i * 4) for i in range(FX2_LEN)]
    assert u32(FX2_LIST + FX2_LEN * 4) == 0, "FX2 terminator"
    assert entries[SPRING_POS] == SPRING_P, f"FX2[{SPRING_POS}] != SPRING REVERB"
    new = entries[:SPRING_POS] + entries[SPRING_POS + 1:]
    for i, v in enumerate(new):
        wr32(FX2_LIST + i * 4, v)
    wr32(FX2_LIST + len(new) * 4, 0)
    print(f"  FX2: {FX2_LEN} -> {len(new)} entries")
    wr32(ID2POS + 0x15 * 4, 0)
    for idv in range(0x20):
        pos = u32(ID2POS + idv * 4)
        if idv != 0x15 and pos > SPRING_POS:
            wr32(ID2POS + idv * 4, pos - 1)
    print("  ID2POS rebuilt (id 0x15 -> 0); FX1_LIST/FX1_ID2POS untouched "
          "(SPRING REVERB was never on FX1, SPATIALIZER is no longer removed)")

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
    print("  Test: COMPRESSOR on a track -> FX page 2: RMS (gap) KEY KFLT KGAIN MON.")
    print("        Kick on T1, pad+COMPRESSOR on T2, KEY=T1 -> pad ducks. KFLT left =")
    print("        low-pass the key (isolate the thump); KGAIN drives a quiet key;")
    print("        MON = ON auditions the filtered key. SPATIALIZER is back as a normal")
    print("        selectable effect; SPRING REVERB now passes through instead.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()

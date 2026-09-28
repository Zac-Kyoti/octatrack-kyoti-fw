#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti, gate 1 (ColdFire only), on TOP OF STOCK 1.40C.

Scope and design record: reference/handoffs/REPITCH_KYOTI_SCOPE.md (read §0).
Mechanism and per-hook comments: tools/patch_repitch_kyoti.s.

What this image does:
  * SETUP TSTR on STATIC/FLEX: OFF AUTO NORM BEAT RPCH RPS9 RPSP (raw 0..6).
    All three repitch values are tempo-following varispeed; in gate 1 they
    PLAY IDENTICALLY (the DSP character modes are gates 3/4).
  * Audio editor ATTR: TIMESTRETCH gains REPITCH (raw 4); SETUP AUTO resolves
    it to RPCH, never RPS9/RPSP.
  * QUANT on the reclaimed PTCH slot of a repitch track: 8 exact ratios
    1/2 2/3 3/4 1/1 5/4 4/3 3/2 2/1, stored in the PTCH word (neutral = 1/1,
    so old projects load as today), p-lockable, octave-folded so the
    increment stays rational and <= 2x.

Cave: 0x400d6f80 (the KYOTI_V1.0 free run; overlaps V1.1's staging -- see
MERGE.md and the scope §5). Layout: [logic][widget7 clone][icon table]
[icon records][glyph data].

    out/mainos_repitch_kyoti.bin        patched MAIN OS
    out/OCTATRACK_OS1.40C_REPITCH_KYOTI.syx / out/OCTATRACK_REPITCH_KYOTI.bin

The 7-position TSTR widget is the stock 5-position select body (0x40046ab4,
372 B, position-independent: absolute jsr/lea only) cloned into the cave with
two words patched: the bound (moveq #4 -> #6 at +0x54) and the icon-table lea
operand (+0xea). Its glyphs keep stock's visual language: 17x7 bordered box,
dithered field, a clear cell at the selected position (stride 2 for 7).
"""
import importlib.util, os, pathlib, struct, subprocess, sys

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from kyoti_status import status, WIP

status(WIP, "REPITCH KYOTI (rev 12: RPS9 + RPSP tonal correction)", """
REV 12 = A TONAL CORRECTION of rev 11's virtual samplers (NOTES Session 111;
reference/handoffs/REPITCH_FIDELITY_SCOPE.md). RPS9 = Akai S900/S950: the
source band-limited as a 40 kHz Akai sample would be (the MF6CN-50 record
filter, 6th-order Butterworth @ 16 kHz = the S900's maximum bandwidth) and
stored at 12 bits, pitched cleanly (16-tap least-squares "virtual ADC").
RPSP = E-mu SP-1200 heard on its RAW outputs 7/8: a fixed 26.04 kHz clock
stepping through a 26.04 kHz grid by repeat/skip, 12-bit, a staircase, no
output filter; its 12-tap record filter is flat to 10 kHz with a steep
42 dB/oct-style cutoff and the box render's droop folded out. Both run on
both DSP cores from a 674-word cave in SPRING REVERB's tail (hooked at each
voice engine's kernel prologue, A P:0x40b / B P:0x20e, as rev 10/11); tables
and state in Y:$A00-$DFF (free on stock; SIDECHAIN3 keeps $800-$9FF). RPCH
is stock. *** THIS IMAGE REMOVES SPRING REVERB *** (Session 109 decision) --
neutered byte-identically to SIDECHAIN3_CROSS; the cave leaves that
builder's 388 words free, so a merged build remains possible.
Proven in emulation: DSP 80/80 bit-exact against the model's integer twin on
both cores + mode switch away/back (python3 tools/repitch_dsp_engine_check.py);
ColdFire unchanged from rev 10 (hardware: "everything works"); rev 11 is
on hardware and working, rev 12 NOT yet flashed.
""")



BASE = 0x40000400
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
SUF = "_diag" if os.environ.get("RPK_DIAG") == "1" else ""
OUT = ROOT / f"out/mainos_repitch_kyoti{SUF}.bin"
CAVE_AT = 0x400d6f80
# bugbuilds' shared base -- the mainline build stays under it so it can be
# folded in. The diagnostic never coexists with those, so it may run up to
# patch_trigscale's pinned base (0x400d7bfc, MERGE.md).
CAVE_CEIL = 0x400d7bfc if os.environ.get("RPK_DIAG") == "1" else 0x400d7b00
PATCH_S = HERE / "patch_repitch_kyoti.s"

EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ELEK = ROOT / f"out/elek_repitch_kyoti{SUF}.bin"
OUT_SYX = ROOT / f"out/OCTATRACK_OS1.40C_REPITCH_KYOTI{SUF.upper()}.syx"
OUT_BIN = ROOT / f"out/OCTATRACK_REPITCH_KYOTI{SUF.upper()}.bin"
VERSTR = "140C_RPKD" if os.environ.get("RPK_DIAG") == "1" else "140C_RPK1"

# --- the seven detours (site, displaced bytes, cave symbol) -----------------
DETOURS = [
    (0x4000406A, "082f000400436608",     "rate_gate"),
    (0x4000409E, "71d6a3460c404000",     "pitch_gate"),
    (0x40004100, "a1c0eca027400024",     "rate_hook"),
    (0x40007D96, "712a00147404",         "tstr_resolve"),
    (0x4006E71C, "4879400b94f660000154", "attr_label"),
    (0x4006EE56, "7202b28066000094",     "attr_up"),
    (0x4006EF7C, "20280110b2806608",     "attr_down"),
    # page-1 dial renderers: resolve widget from record+48, knob when null
    (0x40036698, "206c00304a88660641f9400479b4", "qdial1"),
    (0x4003690C, "206b00304a88660641f9400479b4", "qdial2"),
    (0x4003786A, "206b00304a88660641f9400479b4", "qdial3"),
    (0x40037C06, "206b00304a88660641f9400479b4", "qdial4"),
    # part applies reset the swap bookkeeping: adopt, never swap, after these
    (0x40009094, "4fefff9848d77cfc", "rp_apply1"),
    (0x40009E00, "4fefffb448d77cfc", "rp_apply2"),
]

# --- descriptor pokes (addr, stock long, new long or symbol) ----------------
SELECT5, KNOB, STOCK_FMT = 0x40046AB4, 0x400479B4, 0x4003B6A4
POKES = [
    (0x400D30DE, 0x00000004, 7,             "STATIC TSTR count 4 -> 7"),
    (0x400D3270, 0x00000004, 7,             "FLEX   TSTR count 4 -> 7"),
    (0x400D310E, STOCK_FMT,  "tstr_fmt",    "STATIC TSTR formatter -> cave"),
    (0x400D32A0, STOCK_FMT,  "tstr_fmt",    "FLEX   TSTR formatter -> cave"),
    (0x400D313E, 0x40046C28, "widget7",     "STATIC TSTR widget -> 7-position clone"),
    (0x400D32D0, 0x40046C28, "widget7",     "FLEX   TSTR widget -> 7-position clone"),
    (0x400D3116, KNOB,       "quant_widget","STATIC PTCH widget -> QUANT"),
    (0x400D32A8, KNOB,       "quant_widget","FLEX   PTCH widget -> QUANT"),
    # P+0x12a slot 0: the encoder-step handler -- one detent, one ratio
    (0x400D3146, 0x40032D08, "quant_step",  "STATIC PTCH step -> quant_step"),
    (0x400D32D8, 0x40032D08, "quant_step",  "FLEX   PTCH step -> quant_step"),
]

WIDGET_SRC, WIDGET_LEN = 0x40046AB4, 0x174
BOUND_OFF, LEA_OFF = 0x54, 0xE8          # moveq #4 word; lea 0x400be316,%a0
ICON_SHARED = 0x400C89A6                 # 5th long of every stock icon record

FORBIDDEN = range(0x80006A40, 0x80006AC0)  # RELOAD3's proven-clobberable window


DIAG = os.environ.get("RPK_DIAG") == "1"


def assemble():
    # The diag variant gets its OWN .o/.elf/.bin: its symbols are shifted, and
    # feeding diag addresses to the oracle against the mainline image silently
    # fails four contracts (hit 2026-09-27; the probe cannot detect it).
    tag = "_diag" if DIAG else ""
    o = ROOT / f"out/patch_repitch_kyoti{tag}.o"
    elf = ROOT / f"out/patch_repitch_kyoti{tag}.elf"
    binf = ROOT / f"out/patch_repitch_kyoti{tag}.bin"
    cmd = ["m68k-elf-as", "-mcpu=5407"]
    if DIAG:
        cmd += ["--defsym", "RPK_DIAG=1"]
    subprocess.run(cmd + ["-o", str(o), str(PATCH_S)], check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{CAVE_AT:x}", "-o", str(elf), str(o)],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", "--only-section=.text", str(elf), str(binf)],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", str(elf)], check=True, capture_output=True, text=True).stdout
    syms = {}
    for line in nm.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in "Tt":
            syms[parts[2]] = int(parts[0], 16)
    return binf.read_bytes(), syms


def make_glyphs(cave_tab_at):
    """7 position glyphs in stock's language + records + table, at known addrs."""
    tab = b"".join(struct.pack(">I", cave_tab_at + 28 + 20*k) for k in range(7))
    recs, data = b"", b""
    data_base = cave_tab_at + 28 + 140
    for k in range(7):
        cols = [0xFE] + [(0xAA if j % 2 else 0xD6) for j in range(1, 16)] + [0xFE]
        for j, pix in enumerate((0xFE, 0x82, 0x82, 0x82, 0xFE)):
            cols[2*k + j] = pix
        recs += struct.pack(">5I", 17, 7, 1, data_base + 68*k, ICON_SHARED)
        data += b"".join(struct.pack(">I", c << 24) for c in cols)
    return tab + recs + data


# ---------------------------------------------------------------------------
# DSP: the RPS9/RPSP kernel (tools/patch_repitch_dsp.asm), in the SPRING REVERB
# donor's LAST words. Every donor fact is IMPORTED from build_sidechain3.py
# (the FINAL, hardware-confirmed SIDECHAIN3_CROSS builder) so it stays
# single-sourced; that builder is not modified. The sidechain builds from the
# module's START (388 of 1063 words today), so the tail is stable no matter
# how it grows, and a merged build costs nothing beyond what it already does.
# MERGE NOTE: both builders assert they find spring's STOCK dispatch entry;
# in a merged build whichever runs second must accept the neutered state.
DSP_SRC = HERE / "patch_repitch_dsp.asm"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
VOICE_HOOK = {"A": 0x0040b, "B": 0x0020e}      # the kernel prologue, per payload
HOOK_WORDS = (0x76e500, 0x5edd00)             # move x:(r5),n6 / move y:(r5)+,a
SPRING_SIG = [0x22ee00, 0x0140c0, 0x000040]    # spring's init, the sidechain's canary


def dsp_assemble(org):
    """The rev-12 engine: constants + patch_repitch_dsp.asm + tables, through
    tools/dsp_xasm.py (every word disassembled back and checked)."""
    import dsp_xasm
    import repitch_dsp_src
    try:
        words, _, _ = repitch_dsp_src.assemble(org)
    except dsp_xasm.AsmError as e:
        sys.exit(f"DSP cave: {e}")
    # the sidechain builds from the donor's start and needs its first 388 words
    if len(words) > 1063 - 388:
        sys.exit(f"DSP cave is {len(words)} words; more than 675 would collide with SIDECHAIN3_CROSS")
    return words


def dsp_install(img, touched):
    """Returns {payload: cave org}. Records every changed byte in `touched`."""
    import build_sidechain3 as sc3
    mm_spec = importlib.util.spec_from_file_location(
        "mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(mm_spec)
    mm_spec.loader.exec_module(mm)

    def put(off, word):
        img[off:off + 3] = sc3.w3(word)
        touched.update(range(off, off + 3))

    orgs = {}
    n = len(dsp_assemble(0x1000))                  # size; absolute LAs need the real org
    for tag, d in sc3.DSP.items():
        start = d["cave_org"]
        # the donor must be exactly the 1063-word module the sidechain measured
        mods, _ = mm.modules(bytes(img), d["va"], d["ln"])
        mod = [m for m in mods if m[0] == 0 and m[1] == start]
        if len(mod) != 1 or mod[0][2] != sc3.DONOR_WORDS:      # (sp, addr, count, data)
            sys.exit(f"payload {tag}: no {sc3.DONOR_WORDS}-word P module at P:0x{start:05x}")
        so = sc3.dsp_module_fileoff(img, d["va"], d["ln"], start)
        sig = [sc3.rd3(img, so + 3 * i) for i in range(3)]
        if sig != SPRING_SIG:
            sys.exit(f"payload {tag}: SPRING REVERB init signature {[hex(x) for x in sig]}")
        org = start + sc3.DONOR_WORDS - n
        words = dsp_assemble(org)
        if len(words) != n:
            sys.exit("DSP cave size shifted between the sizing and final passes")
        co = sc3.dsp_module_fileoff(img, d["va"], d["ln"], org)
        for i, w in enumerate(words):
            put(co + 3 * i, w)

        hook = VOICE_HOOK[tag]
        ho = sc3.dsp_module_fileoff(img, d["va"], d["ln"], hook)
        if (sc3.rd3(img, ho), sc3.rd3(img, ho + 3)) != HOOK_WORDS:
            sys.exit(f"payload {tag}: voice hook P:0x{hook:05x} holds "
                     f"{sc3.rd3(img, ho):06x} {sc3.rd3(img, ho + 3):06x}")
        op, disp = sc3.bsr_long(hook, org)
        put(ho, op)
        put(ho + 3, disp)

        # spring's dispatch entry -> the shared empty-FX stub, exactly as the
        # sidechain does: its code is now partly ours and must never run
        xt = sc3.dsp_xtable_fileoff(img, d["va"], d["ln"], 0x215)
        ini, prc = xt + sc3.DONOR_ID * 3, xt + (0x20 + sc3.DONOR_ID) * 3
        if (sc3.rd3(img, ini), sc3.rd3(img, prc)) != (start, d["spring_proc"]):
            sys.exit(f"payload {tag}: X:0x215[0x{sc3.DONOR_ID:02x}] not stock spring "
                     f"({sc3.rd3(img, ini):06x} {sc3.rd3(img, prc):06x})")
        put(ini, d["stub_init"])
        put(prc, d["stub_proc"])
        orgs[tag] = org
        print(f"  DSP {tag}: cave {n}w @P:0x{org:05x} (spring tail), hook P:0x{hook:05x} "
              f"-> bsr {op:06x} {disp:06x}, X:0x215[0x{sc3.DONOR_ID:02x}] -> stub")

    # the ColdFire half: not offered on either bus, and old projects load NONE
    def u32(a):
        return int.from_bytes(img[a - BASE:a - BASE + 4], "big")

    def wr32(a, v):
        img[a - BASE:a - BASE + 4] = v.to_bytes(4, "big")
        touched.update(range(a - BASE, a - BASE + 4))

    for bus in sc3.FX_BUSES:
        entries = []
        while (v := u32(bus["lst"] + len(entries) * 4)):
            entries.append(v)
            if len(entries) >= 0x20:
                sys.exit(f"{bus['tag']}: no terminator in the chooser list")
        offered = sc3.DONOR_P in entries
        if offered:
            pos = entries.index(sc3.DONOR_P)
            del entries[pos]
            for i, v in enumerate(entries):
                wr32(bus["lst"] + i * 4, v)
            wr32(bus["lst"] + len(entries) * 4, 0)
            wr32(bus["id2pos"] + sc3.DONOR_ID * 4, 0)
            for idv in range(0x20):
                p = u32(bus["id2pos"] + idv * 4)
                if idv != sc3.DONOR_ID and p > pos:
                    wr32(bus["id2pos"] + idv * 4, p - 1)
        if u32(bus["id2pos"] + sc3.DONOR_ID * 4) != 0:
            sys.exit(f"{bus['tag']}: id2pos[donor] should land on NONE's row")
        if u32(bus["id2e"] + sc3.DONOR_ID * 4) not in (sc3.DONOR_P, sc3.NONE_P):
            sys.exit(f"{bus['tag']}: id2e[donor] is neither the donor nor NONE")
        wr32(bus["id2e"] + sc3.DONOR_ID * 4, sc3.NONE_P)
        print(f"  {bus['tag']}: " + ("SPRING REVERB removed from the chooser" if offered
                                      else "SPRING REVERB was never offered here")
              + "; id2e -> NONE (old projects load the NONE page)")
    return orgs


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    img = bytearray(stock)
    logic, syms = assemble()

    # cave layout
    w7_at = CAVE_AT + ((len(logic) + 3) & ~3)
    tab_at = w7_at + WIDGET_LEN
    glyphs = make_glyphs(tab_at)
    cave_end = tab_at + len(glyphs)
    syms["widget7"] = w7_at
    if cave_end > CAVE_CEIL:
        sys.exit(f"cave overflows: end 0x{cave_end:08x} > ceil 0x{CAVE_CEIL:08x}")

    # the widget clone, two words patched
    src = stock[WIDGET_SRC-BASE : WIDGET_SRC-BASE+WIDGET_LEN]
    if src[BOUND_OFF:BOUND_OFF+2] != b"\x70\x04":
        sys.exit("widget clone: bound word is not moveq #4")
    if src[LEA_OFF:LEA_OFF+6] != bytes.fromhex("41f9400be316"):
        sys.exit("widget clone: icon-table lea mismatch")
    w7 = bytearray(src)
    w7[BOUND_OFF:BOUND_OFF+2] = b"\x70\x06"
    w7[LEA_OFF+2:LEA_OFF+6] = struct.pack(">I", tab_at)

    cave = bytearray(cave_end - CAVE_AT)
    cave[:len(logic)] = logic
    cave[w7_at-CAVE_AT : w7_at-CAVE_AT+WIDGET_LEN] = w7
    cave[tab_at-CAVE_AT:] = glyphs

    # forbidden-window scan (RELOAD3's rule): no absolute refs into 0x80006a40..abf
    for i in range(len(cave) - 3):
        v = struct.unpack(">I", cave[i:i+4])[0]
        if v in FORBIDDEN:
            sys.exit(f"cave holds a forbidden ref 0x{v:08x} at +0x{i:x}")

    co = CAVE_AT - BASE
    if any(img[co:co+len(cave)]):
        sys.exit(f"cave at 0x{CAVE_AT:08x} is not free: {bytes(img[co:co+16]).hex()}")
    img[co:co+len(cave)] = cave

    # detours
    for site, disp, sym in DETOURS:
        disp = bytes.fromhex(disp)
        o = site - BASE
        if bytes(img[o:o+len(disp)]) != disp:
            sys.exit(f"detour 0x{site:08x} unexpected bytes {bytes(img[o:o+len(disp)]).hex()}")
        jmp = b"\x4e\xf9" + struct.pack(">I", syms[sym])
        img[o:o+len(disp)] = jmp + b"\x4e\x71" * ((len(disp) - 6) // 2)

    # descriptor pokes
    for addr, old, new, why in POKES:
        o = addr - BASE
        if struct.unpack(">I", img[o:o+4])[0] != old:
            sys.exit(f"poke {why}: 0x{addr:08x} holds {bytes(img[o:o+4]).hex()}, wanted {old:#x}")
        val = syms[new] if isinstance(new, str) else new
        img[o:o+4] = struct.pack(">I", val)

    # DSP half + SPRING neutering (records its own bytes)
    touched = set()
    orgs = dsp_install(img, touched)

    # accounting: every changed byte must be a detour, a poke, the cave, or a
    # byte dsp_install recorded
    expected = set(touched)
    for site, disp, _ in DETOURS:
        expected |= set(range(site-BASE, site-BASE+len(bytes.fromhex(disp))))
    for addr, *_ in POKES:
        expected |= set(range(addr-BASE, addr-BASE+4))
    expected |= set(range(co, co+len(cave)))
    stray = [i for i in range(len(img)) if img[i] != stock[i] and i not in expected]
    if stray:
        sys.exit(f"{len(stray)} stray changed bytes, first at 0x{stray[0]+BASE:08x}")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"{OUT.name}: {changed} B changed, 0 strays")
    print(f"  cave 0x{CAVE_AT:08x}..0x{cave_end:08x} = {cave_end-CAVE_AT} B "
          f"(logic {len(logic)}, widget7 {WIDGET_LEN} @0x{w7_at:08x}, icons {len(glyphs)})")
    for site, _, sym in DETOURS:
        print(f"  detour 0x{site:08x} -> {sym} @0x{syms[sym]:08x}")
    for addr, _, new, why in POKES:
        val = syms[new] if isinstance(new, str) else new
        print(f"  poke   0x{addr:08x} = 0x{val:08x}  {why}")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n(EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode:
        sys.exit(f"EFT failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run([sys.executable, str(HERE/"make_bin.py"), str(ELEK), "-o", str(OUT_BIN)],
                   check=True, cwd=ROOT)
    import hashlib
    for f in (OUT, OUT_SYX, OUT_BIN):
        print(f"  {f.name}: sha256 {hashlib.sha256(f.read_bytes()).hexdigest()[:16]}…")


if __name__ == "__main__":
    main()

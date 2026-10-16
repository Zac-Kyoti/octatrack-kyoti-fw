# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
REPITCH REWRITE -- RETAINED DSP INSTALL (clean-room input, extracted 2026-10-14).

The DSP half of the old standalone builder, verbatim and ours: it places vem_dsp's kernel in
SPRING REVERB's P module (ending below DARK REV's routine), its tables in SPRING's X data, the
voice-kernel and boot hooks, SPRING's dispatch entry -> the empty stub, and SPRING's removal
from both FX choosers. Every donor fact comes from build_sidechain_compressor.py (imported as
sc3). Nothing in it is from Jannik's module. The old builder's ColdFire half is NOT here.

Context the extract assumes (the old builder's module scope):
    BASE = 0x40000400; HERE = tools/; ROOT = the repo root
    import importlib.util, os, pathlib, struct, subprocess, sys   (tools/ on sys.path)
    dsp_install(img: bytearray, touched: set) -> {payload: cave org}
Copy it into the new builder; do not import this file.
"""
# ---------------------------------------------------------------------------
# DSP: the RPS9/RPSP kernel (tools/varispeed_emus_dsp.asm), in the SPRING REVERB
# donor. Every donor fact is IMPORTED from build_sidechain_compressor.py (the FINAL,
# hardware-confirmed SIDECHAIN_COMPRESSOR builder) so it stays single-sourced; that
# builder is not modified. The sidechain builds from the module's START (388 of
# 1063 words). Rev 10-13 sat in the module's last words and overwrote a 35-word
# routine DARK REVERB calls there (A P:0x1586 / B P:0x1346 -- DARK REV was broken
# on those images); since rev 14 the cave ENDS below that routine (placement:
# varispeed_emus_dsp_src.cave_org), and its tables live in SPRING's X data modules.
# MERGE NOTE: both builders assert they find spring's STOCK dispatch entry;
# in a merged build whichever runs second must accept the neutered state.
DSP_SRC = HERE / "varispeed_emus_dsp.asm"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
VOICE_HOOK = {"A": 0x0040b, "B": 0x0020e}      # the kernel prologue, per payload
HOOK_WORDS = (0x76e500, 0x5edd00)             # move x:(r5),n6 / move y:(r5)+,a
# rev 17: the table copy at boot -- each payload's one-time memory clear, `do b,LA`
# (octabam docs/firmware/DSP.md: payload B's boot zero, P:0x40-0x4a; A's alike)
BOOT_HOOK = {"A": (0x00046, (0x06cf00, 0x000049)), "B": (0x00047, (0x06cf00, 0x00004a))}
SPRING_SIG = [0x22ee00, 0x0140c0, 0x000040]    # spring's init, the sidechain's canary


def dsp_assemble(org, payload):
    """The rev-14 engine: constants + varispeed_emus_dsp.asm through
    tools/dsp_xasm.py (every word disassembled back and checked)."""
    import dsp_xasm
    import varispeed_emus_dsp_src
    try:
        words, syms, _ = varispeed_emus_dsp_src.assemble(org, payload)
    except dsp_xasm.AsmError as e:
        sys.exit(f"DSP cave: {e}")
    return words, syms


# SPRING REVERB's X data modules the tables go into (varispeed_emus_dsp_src.SPRING_X),
# asserted stock by content before they are rewritten; DARK REVERB's routine in
# SPRING's P module (varispeed_emus_dsp_src.DARK_SUB), asserted stock AFTER the build.
X_STOCK_SHA = ["dbbbb85c7676e526", "65cd65b39fcb59e2", "24bed15804f05d8a", "2f169dfb83d9765b", "14716e3d630dd7aa"]
DARK_SHA = {"A": "4e1de47f64f651fd", "B": "e10bdef29d036c96"}


def dsp_install(img, touched):
    """Returns {payload: cave org}. Records every changed byte in `touched`."""
    import build_sidechain_compressor as sc3
    mm_spec = importlib.util.spec_from_file_location(
        "mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(mm_spec)
    mm_spec.loader.exec_module(mm)

    def put(off, word):
        img[off:off + 3] = sc3.w3(word)
        touched.update(range(off, off + 3))

    import hashlib
    import varispeed_emus_dsp_src as dsrc
    orgs = {}
    for tag, d in sc3.DSP.items():
        start = d["cave_org"]
        # the donor must be exactly the 1063-word module the sidechain measured
        mods, blob = mm.modules(bytes(img), d["va"], d["ln"])
        mod = [m for m in mods if m[0] == 0 and m[1] == start]
        if len(mod) != 1 or mod[0][2] != sc3.DONOR_WORDS:      # (sp, addr, count, data)
            sys.exit(f"payload {tag}: no {sc3.DONOR_WORDS}-word P module at P:0x{start:05x}")
        if start != dsrc.SPRING_P[tag]:
            sys.exit(f"payload {tag}: SPRING at P:0x{start:05x}, varispeed_emus_dsp_src says 0x{dsrc.SPRING_P[tag]:05x}")
        so = sc3.dsp_module_fileoff(img, d["va"], d["ln"], start)
        sig = [sc3.rd3(img, so + 3 * i) for i in range(3)]
        if sig != SPRING_SIG:
            sys.exit(f"payload {tag}: SPRING REVERB init signature {[hex(x) for x in sig]}")
        n = len(dsp_assemble(0x1000, tag)[0])           # size; absolute LAs need the real org
        try:
            org = dsrc.cave_org(tag, n)                  # ends right below DARK REV's routine
        except ValueError as e:
            sys.exit(str(e))
        words, syms = dsp_assemble(org, tag)
        if len(words) != n:
            sys.exit("DSP cave size shifted between the sizing and final passes")
        co = sc3.dsp_module_fileoff(img, d["va"], d["ln"], org)
        for i, w in enumerate(words):
            put(co + 3 * i, w)
        sub, sn = dsrc.DARK_SUB[tag]
        if org + n > sub:
            sys.exit(f"payload {tag}: cave runs into DARK REV's routine at P:0x{sub:05x}")
        do = sc3.dsp_module_fileoff(img, d["va"], d["ln"], sub)
        if hashlib.sha256(bytes(img[do:do + 3 * sn])).hexdigest()[:16] != DARK_SHA[tag]:
            sys.exit(f"payload {tag}: DARK REV's routine P:0x{sub:05x} is not stock")

        # the tables: over SPRING's own X data modules (stock content asserted first)
        xd = dsrc.x_data(tag)
        spans = {}
        for (addr, cnt), sha in zip(dsrc.SPRING_X[tag], X_STOCK_SHA):
            xm = [m for m in mods if m[0] == 1 and m[1] == addr]
            if len(xm) != 1 or xm[0][2] != cnt:
                sys.exit(f"payload {tag}: no {cnt}-word X module at X:0x{addr:05x}")
            xo = (d["va"] - BASE) + xm[0][3]
            if hashlib.sha256(bytes(img[xo:xo + 3 * cnt])).hexdigest()[:16] != sha:
                sys.exit(f"payload {tag}: X:0x{addr:05x} is not SPRING's stock table")
            spans[addr] = (cnt, xo)
        for a, w in xd.items():
            base = [x for x in spans if x <= a < x + spans[x][0]]
            if len(base) != 1:
                sys.exit(f"payload {tag}: table word for X:0x{a:05x} falls outside SPRING's X modules")
            put(spans[base[0]][1] + 3 * (a - base[0]), w)
        print(f"  DSP {tag}: {len(xd)} table words into SPRING's X modules "
              f"({', '.join(f'X:0x{a:05x}' for a in sorted(spans))})")

        hook = VOICE_HOOK[tag]
        ho = sc3.dsp_module_fileoff(img, d["va"], d["ln"], hook)
        if (sc3.rd3(img, ho), sc3.rd3(img, ho + 3)) != HOOK_WORDS:
            sys.exit(f"payload {tag}: voice hook P:0x{hook:05x} holds "
                     f"{sc3.rd3(img, ho):06x} {sc3.rd3(img, ho + 3):06x}")
        op, disp = sc3.bsr_long(hook, org)
        put(ho, op)
        put(ho + 3, disp)
        bsite, bstock = BOOT_HOOK[tag]
        bo = sc3.dsp_module_fileoff(img, d["va"], d["ln"], bsite)
        if (sc3.rd3(img, bo), sc3.rd3(img, bo + 3)) != bstock:
            sys.exit(f"payload {tag}: boot hook P:0x{bsite:05x} holds "
                     f"{sc3.rd3(img, bo):06x} {sc3.rd3(img, bo + 3):06x}")
        bop, bdisp = sc3.bsr_long(bsite, syms["zqboot"])
        put(bo, bop)
        put(bo + 3, bdisp)

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
        print(f"  DSP {tag}: cave {n}w @P:0x{org:05x}..0x{org + n - 1:05x} (DARK REV's routine at "
              f"P:0x{dsrc.DARK_SUB[tag][0]:05x} kept stock), hook P:0x{hook:05x} "
              f"-> bsr {op:06x} {disp:06x}, boot hook P:0x{bsite:05x} -> zqboot "
              f"P:0x{syms['zqboot']:05x}, X:0x215[0x{sc3.DONOR_ID:02x}] -> stub")

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



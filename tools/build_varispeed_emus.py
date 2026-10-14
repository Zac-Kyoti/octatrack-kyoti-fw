#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build VARISPEED_EMUS on TOP OF STOCK 1.40C (WIP).

STATIC / FLEX TSTR gets a fifth position, VARI: the track plays dry at
(project BPM x p) / (sample BPM x q), p/q the QUAN ratio on the PTCH knob, exact in
integers, RATE still applying; its TSNS knob becomes EMUS (S950 / OT / SP12), the DSP
engine latched at each trig. The audio editor's ATTR TIMESTRETCH gains VARI.
Spec: reference/handoffs/REPITCH_REWRITE_SPEC.md (clean-room); facts:
REPITCH_REWRITE_SCOPE.md + REPITCH_REWRITE_SCOPE_EMUS.md; this build:
reference/handoffs/REPITCH_REWRITE_IMPL.md.

  ColdFire: octabam-modules/varispeed-emus/varispeed_emus.s, one unit linked at the
            classic cave's proven start (0x400d6500), 18 detours, 12 descriptor pokes.
  DSP:      the hardware-proven RPS9/RPSP kernel (tools/patch_repitch_dsp.asm via
            tools/repitch_dsp_src.py) in SPRING REVERB's P module and X data, its voice
            and boot hooks, SPRING removed from both FX choosers -- the old builder's DSP
            half, copied in verbatim from reference/handoffs/REPITCH_REWRITE_DSP_INSTALL.py.

    out/mainos_varispeed_emus.bin                   patched MAIN OS
    out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx        MIDI DIN
    out/OCTATRACK_VARISPEED_EMUS.bin                CF card
    out/elek_varispeed_emus.bin                     the EFT container (make_bin's input)
    out/varispeed_emus_syms.json                    unit symbols, hooks, pokes (the tests read it)

Every splice asserts the stock bytes it overwrites and that nothing branches into the
middle of what it displaces; the cave must be zero in stock and inside the classic
cave from 0x400d6500; no reference into 0x80006a40..0x80006abf; the unit must link to
the same bytes for -mcpu=5407 and 54455 (octabam assembles DRAM units for 54455).

Usage:  KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py [VERSTR]   (default 140C_VEM1)
"""
import hashlib, importlib.util, json, os, pathlib, struct, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

BASE = 0x40000400
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
SRC = ROOT / "octabam-modules/varispeed-emus/varispeed_emus.s"
OUT = ROOT / "out/mainos_varispeed_emus.bin"
ELEK = ROOT / "out/elek_varispeed_emus.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx"
OUT_BIN = ROOT / "out/OCTATRACK_VARISPEED_EMUS.bin"
SYMS_JSON = ROOT / "out/varispeed_emus_syms.json"
WORK = ROOT / "out/vem_build"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_VEM1"
# A TEST variant (the harness's deliberately wrong builds): VEM_VARIANT=<tag> and
# VEM_VARIANT_SRC=<.s> build out/vem_variants/mainos_varispeed_emus_<tag>.bin from that
# source, with every check, and no wrap. Never a flash candidate.
VARIANT = os.environ.get("VEM_VARIANT")
if VARIANT:
    SRC = pathlib.Path(os.environ["VEM_VARIANT_SRC"]).resolve()
    OUT = ROOT / f"out/vem_variants/mainos_varispeed_emus_{VARIANT}.bin"
    SYMS_JSON = ROOT / f"out/vem_variants/varispeed_emus_{VARIANT}_syms.json"
    WORK = ROOT / f"out/vem_variants/build_{VARIANT}"
    OUT.parent.mkdir(parents=True, exist_ok=True)

CAVE = 0x400d6500            # the classic cave's proven start (kb/caves.md §2b)
CAVE_END = 0x400d7c3c        # its end (kb/caves.md §1)
SCRATCH = (0x80006a40, 0x80006ac0)   # never ours (CLAUDE.md)

# detours: site -> (stock bytes, symbol, kind). kind jmp/jsr: `jmp|jsr sym` + nops.
DETOURS = {
    # the core: the render's increment store (frame ISR, second pass, ST/FL/PU)
    0x40004100: ("a1c0eca027400024", "vem_frame", "jmp"),
    # EMUS: P2EDIT's only delta conversion
    0x4003a566: ("4eb94003249c", "emus_p2step", "jsr"),
    # audio editor ATTR, TIMESTRETCH row: label else, up row 2, down row 2, both tails
    0x4006e71c: ("4879400b94f660000154", "attr_label", "jmp"),
    0x4006ee48: ("202801106608", "attr_up", "jmp"),
    0x4006ef7c: ("20280110b280", "attr_down", "jmp"),
    0x4006eef0: ("245f4ef94006dbdc", "attr_tail", "jmp"),
    0x4006f026: ("245f4ef94006dbdc", "attr_tail", "jmp"),
    # retained: the four SETUP-page dial resolvers
    0x40036698: ("206c00304a88660641f9400479b4", "qdial1", "jmp"),
    0x4003690c: ("206b00304a88660641f9400479b4", "qdial2", "jmp"),
    0x4003786a: ("206b00304a88660641f9400479b4", "qdial3", "jmp"),
    0x40037c06: ("206b00304a88660641f9400479b4", "qdial4", "jmp"),
    # retained: the two Part applies, RELOAD PART
    0x40009094: ("4fefff9848d77cfc", "rp_apply1", "jmp"),
    0x40009e00: ("4fefffb448d77cfc", "rp_apply2", "jmp"),
    0x4004aab4: ("4fefffe048d70c3c", "rp_reload", "jmp"),
    # O2: the bulk writers -- SRC page paste (and its undo), track paste (and its undo),
    # the PART menu's paste core (PASTE and UNDO) and CLEAR
    0x40027e4c: ("4fefffcc48d77cfc", "vh_srcpaste", "jmp"),
    0x4002b654: ("4fefffbc48d77cfc", "vh_trkpaste", "jmp"),
    0x40029a4c: ("4fefffec48d7043c", "vh_partpaste", "jmp"),
    0x4004a9d0: ("4feffff048d70c0c", "vh_partclear", "jmp"),
}
# Each body replays its site's displaced bytes and jumps back here: the builder checks
# the jump target equals site + displaced length.
RETURNS = {"vem_frame": None, "vb_srcpaste": 0x40027e54, "vb_trkpaste": 0x4002b65c,
           "vb_partpaste": 0x40029a54, "vb_partclear": 0x4004a9d8, "vb_reload": 0x4004aabc}

# descriptor pokes (u32): addr -> (stock value, new value or symbol, what)
POKES = {
    0x400d30de: (4, 5, "STATIC TSTR count"),
    0x400d3270: (4, 5, "FLEX TSTR count"),
    0x400d313e: (0x40046c28, 0x40046ab4, "STATIC TSTR widget -> stock 5-position select"),
    0x400d32d0: (0x40046c28, 0x40046ab4, "FLEX TSTR widget -> stock 5-position select"),
    0x400d310e: (0x4003b6a4, "tstr_fmt", "STATIC TSTR formatter"),
    0x400d32a0: (0x4003b6a4, "tstr_fmt", "FLEX TSTR formatter"),
    0x400d3142: (0, "emus_widget", "STATIC TSNS widget"),
    0x400d32d4: (0, "emus_widget", "FLEX TSNS widget"),
    0x400d3116: (0x400479b4, "quant_widget", "STATIC PTCH widget"),
    0x400d32a8: (0x400479b4, "quant_widget", "FLEX PTCH widget"),
    0x400d3146: (0x40032d08, "quant_step", "STATIC PTCH encoder step"),
    0x400d32d8: (0x40032d08, "quant_step", "FLEX PTCH encoder step"),
}
# Stock bytes the code relies on without patching them (asserted, not written):
CONTEXT = {
    # P2EDIT around R1: d2 = the old byte (mvs.b), a3 = slot2, d3 = delta, d4 = track
    0x4003a55a: "d1fc0008ef5a75102f032f0b4eb94003249c41eb00062235",
    # the stock 5-position select: bound `moveq #4` and its icon table operand
    0x40046b08: "7004b0856500",
    # the render around H1: the second-pass test and the voice record pointer
    0x4000406a: "082f000400436608202b002460000090",
    0x40004108: "28798000",
    # the voice loop clears the trig byte's bits 4-7 after the second pass
    0x4000d52e: "1012780fc08414c0",
    # stock's 4-entry TSTR string table (OFF AUTO NORM BEAT)
    0x400a7e2e: "400b4e78400b571e400b5728400b572d",
}


# "Branches" the word-by-word scan finds that are operand words of a real instruction,
# each checked by objdump: source -> (the instruction's address, its bytes).
FALSE_BRANCHES = {
    0x4003670e: (0x4003670a, "4eb9400a6994"),   # jsr 0x400a6994's low address word
}


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r


def link_unit(cpu, at, tag):
    WORK.mkdir(parents=True, exist_ok=True)
    o, e, b = (WORK / f"vem_{tag}.{x}" for x in ("o", "elf", "bin"))
    run("m68k-elf-as", f"-mcpu={cpu}", "-o", o, SRC)
    run("m68k-elf-ld", "-e", "vem_frame", f"-Ttext=0x{at:x}", "-o", e, o)
    run("m68k-elf-objcopy", "-O", "binary", e, b)
    syms = {}
    for line in run("m68k-elf-nm", e).stdout.splitlines():
        f = line.split()
        if len(f) != 3:
            sys.exit(f"unresolved symbol in {e.name}: {line}")
        syms[f[2]] = int(f[0], 16)
    return b.read_bytes(), syms


def pc_targets(img, a):
    """PC-relative targets of an instruction that might start at image offset a."""
    op = int.from_bytes(img[a:a + 2], "big")
    pc = BASE + a + 2
    out = []
    if 0x6000 <= op <= 0x6FFF:                                   # Bcc / BRA / BSR
        d8 = op & 0xFF
        if d8 == 0:
            d = int.from_bytes(img[a + 2:a + 4], "big", signed=True)
        elif d8 == 0xFF:
            d = int.from_bytes(img[a + 2:a + 6], "big", signed=True)
        else:
            d = d8 - 0x100 if d8 & 0x80 else d8
        out.append(pc + d)
    elif op in (0x4EBA, 0x4EFA, 0x487A) or (op & 0xF1FF) == 0x41FA:   # jsr/jmp/pea/lea (d16,pc)
        out.append(pc + int.from_bytes(img[a + 2:a + 4], "big", signed=True))
    return out


def branch_targets(img):
    t = {}
    for o in range(0, len(img) - 6, 2):
        for x in pc_targets(img, o):
            t.setdefault(x, []).append(BASE + o)
    return t


# ---------------------------------------------------------------------------
# DSP: copied VERBATIM from reference/handoffs/REPITCH_REWRITE_DSP_INSTALL.py (the old
# builder's DSP half, ours), below the marker; the module scope it assumes is above.
# ---------------------------------------------------------------------------
# ---- begin REPITCH_REWRITE_DSP_INSTALL.py ----
DSP_SRC = HERE / "patch_repitch_dsp.asm"
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
VOICE_HOOK = {"A": 0x0040b, "B": 0x0020e}      # the kernel prologue, per payload
HOOK_WORDS = (0x76e500, 0x5edd00)             # move x:(r5),n6 / move y:(r5)+,a
# rev 17: the table copy at boot -- each payload's one-time memory clear, `do b,LA`
# (octabam docs/firmware/DSP.md: payload B's boot zero, P:0x40-0x4a; A's alike)
BOOT_HOOK = {"A": (0x00046, (0x06cf00, 0x000049)), "B": (0x00047, (0x06cf00, 0x00004a))}
SPRING_SIG = [0x22ee00, 0x0140c0, 0x000040]    # spring's init, the sidechain's canary


def dsp_assemble(org, payload):
    """The rev-14 engine: constants + patch_repitch_dsp.asm through
    tools/dsp_xasm.py (every word disassembled back and checked)."""
    import dsp_xasm
    import repitch_dsp_src
    try:
        words, syms, _ = repitch_dsp_src.assemble(org, payload)
    except dsp_xasm.AsmError as e:
        sys.exit(f"DSP cave: {e}")
    return words, syms


# SPRING REVERB's X data modules the tables go into (repitch_dsp_src.SPRING_X),
# asserted stock by content before they are rewritten; DARK REVERB's routine in
# SPRING's P module (repitch_dsp_src.DARK_SUB), asserted stock AFTER the build.
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
    import repitch_dsp_src as dsrc
    orgs = {}
    for tag, d in sc3.DSP.items():
        start = d["cave_org"]
        # the donor must be exactly the 1063-word module the sidechain measured
        mods, blob = mm.modules(bytes(img), d["va"], d["ln"])
        mod = [m for m in mods if m[0] == 0 and m[1] == start]
        if len(mod) != 1 or mod[0][2] != sc3.DONOR_WORDS:      # (sp, addr, count, data)
            sys.exit(f"payload {tag}: no {sc3.DONOR_WORDS}-word P module at P:0x{start:05x}")
        if start != dsrc.SPRING_P[tag]:
            sys.exit(f"payload {tag}: SPRING at P:0x{start:05x}, repitch_dsp_src says 0x{dsrc.SPRING_P[tag]:05x}")
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
# ---- end REPITCH_REWRITE_DSP_INSTALL.py ----


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    for t in (DSP_ASM, DSP_DIS):
        if not t.exists():
            sys.exit(f"missing {t} -- build the DSP toolchain")
    stock = STOCK_SECT.read_bytes()
    img = bytearray(stock)
    o = lambda a: a - BASE
    if VARIANT:                          # a test variant without some detours (e.g. the O2 holds)
        for a in filter(None, os.environ.get("VEM_VARIANT_SKIP", "").split(",")):
            print(f"  test variant {VARIANT}: detour 0x{DETOURS.pop(int(a, 16)) and int(a, 16):08x} left stock")

    # ---- the ColdFire unit ---------------------------------------------------------
    print("=== ColdFire: varispeed_emus.s ===")
    blob, syms = link_unit("5407", CAVE, "5407")
    blob2, syms2 = link_unit("54455", CAVE, "54455")
    if blob != blob2 or syms != syms2:
        sys.exit("the unit links to different bytes for -mcpu=5407 and 54455 -- refusing")
    end = CAVE + len(blob)
    if syms["vem_end"] != end:
        sys.exit(f"vem_end 0x{syms['vem_end']:08x} != the blob's end 0x{end:08x}")
    if not (0x400d6500 <= CAVE and end <= CAVE_END):
        sys.exit(f"cave 0x{CAVE:08x}..0x{end:08x} outside the classic cave 0x400d6500..0x{CAVE_END:08x}")
    if any(img[o(CAVE):o(end)]):
        sys.exit(f"cave 0x{CAVE:08x}..0x{end:08x} is not zero in stock")
    for i in range(0, len(blob) - 3):
        v = int.from_bytes(blob[i:i + 4], "big")
        if SCRATCH[0] <= v < SCRATCH[1]:
            sys.exit(f"the unit references 0x{v:08x} (the unreliable scratch block) at +0x{i:x}")
    print(f"  {len(blob)} B @ 0x{CAVE:08x}..0x{end:08x}  ({CAVE_END - end} B of the classic cave left); "
          f"5407 == 54455 bytes")

    # ---- context bytes, detours, pokes: all asserted against stock first ------------
    targets = branch_targets(img)
    for at, hexb in CONTEXT.items():
        want = bytes.fromhex(hexb)
        if bytes(img[o(at):o(at) + len(want)]) != want:
            sys.exit(f"context 0x{at:08x}: {bytes(img[o(at):o(at)+len(want)]).hex()} is not stock {hexb}")
    for site, (hexb, sym, kind) in DETOURS.items():
        want = bytes.fromhex(hexb)
        if bytes(img[o(site):o(site) + len(want)]) != want:
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o(site):o(site)+len(want)]).hex()} is not stock {hexb}")
        inside = []
        for t in targets:
            if site < t < site + len(want):
                for src in targets[t]:
                    fp = FALSE_BRANCHES.get(src)
                    if fp and bytes(img[o(fp[0]):o(fp[0]) + len(fp[1]) // 2]).hex() == fp[1] \
                            and fp[0] < src < fp[0] + len(fp[1]) // 2:
                        continue
                    inside.append(t)
        if inside:
            sys.exit(f"REFUSING detour at 0x{site:08x}: {[hex(x) for x in targets[inside[0]]]} branch "
                     f"to 0x{inside[0]:08x}, inside the {len(want)} displaced bytes")
        if sym not in syms:
            sys.exit(f"detour 0x{site:08x}: no symbol {sym}")
    for at, (old, new, what) in POKES.items():
        cur = int.from_bytes(img[o(at):o(at) + 4], "big")
        if cur != old:
            sys.exit(f"poke 0x{at:08x} ({what}): 0x{cur:08x} is not stock 0x{old:08x}")
    # the 5-position select must still be unreferenced in stock (we point TSTR at it)
    for i in range(0, len(img) - 3):
        if int.from_bytes(img[i:i + 4], "big") == 0x40046ab4:
            sys.exit(f"0x40046ab4 is referenced in stock at 0x{BASE + i:08x}")
    if 0x40046ab4 in targets:
        sys.exit("0x40046ab4 is a PC-relative target in stock")

    img[o(CAVE):o(end)] = blob
    for site, (hexb, sym, kind) in DETOURS.items():
        n = len(bytes.fromhex(hexb))
        br = (b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9") + syms[sym].to_bytes(4, "big")
        img[o(site):o(site) + n] = br + b"\x4e\x71" * ((n - 6) // 2)
    for at, (old, new, what) in POKES.items():
        v = syms[new] if isinstance(new, str) else new
        img[o(at):o(at) + 4] = v.to_bytes(4, "big")
    # every body jumps back right behind the bytes its site displaced
    for sym, back in RETURNS.items():
        if back is None:
            continue
        a = syms[sym]
        # lea -N(sp),sp (4) ; movem.l regs,(sp) (4) ; jmp abs.l (6)
        if img[o(a) + 8:o(a) + 10] != b"\x4e\xf9" or \
                int.from_bytes(img[o(a) + 10:o(a) + 14], "big") != back:
            sys.exit(f"{sym} does not jump back to 0x{back:08x}")
    print(f"  {len(DETOURS)} detours, {len(POKES)} descriptor pokes")
    for site, (hexb, sym, kind) in DETOURS.items():
        print(f"    0x{site:08x} {kind} {sym} 0x{syms[sym]:08x}  ({len(hexb) // 2} B displaced)")
    for at, (old, new, what) in POKES.items():
        v = syms[new] if isinstance(new, str) else new
        print(f"    0x{at:08x} 0x{old:08x} -> 0x{v:08x}  {what}")

    # ---- DSP -----------------------------------------------------------------------
    print("\n=== DSP: the RPS9/RPSP kernel (SPRING REVERB donor) ===")
    touched = set()
    orgs = dsp_install(img, touched)

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    sha = hashlib.sha256(bytes(img)).hexdigest()
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock, sha256 {sha}")
    SYMS_JSON.write_text(json.dumps(dict(
        cave=CAVE, end=end, size=len(blob), unit_sha256=hashlib.sha256(blob).hexdigest(),
        syms={k: v for k, v in sorted(syms.items())},
        detours={f"0x{k:08x}": [v[1], v[2], len(v[0]) // 2] for k, v in DETOURS.items()},
        pokes={f"0x{k:08x}": [v[0], syms[v[1]] if isinstance(v[1], str) else v[1], v[2]]
               for k, v in POKES.items()},
        dsp_orgs=orgs, mainos_sha256=sha), indent=1))
    print(f"  octabam reference: unit linked at 0x{CAVE:08x}, {len(blob)} B, sha256 "
          f"{hashlib.sha256(blob).hexdigest()}")
    if not VARIANT:                      # the octabam module's REFERENCE must be this unit
        import re
        man = (ROOT / "octabam-modules/varispeed-emus/manifest.py").read_text()
        m = re.search(r'reference=\(0x([0-9a-f]+),\s*"([0-9a-f]{64})"\)', man)
        if not m or (int(m.group(1), 16), m.group(2)) != (CAVE, hashlib.sha256(blob).hexdigest()):
            sys.exit(f"octabam-modules/varispeed-emus/manifest.py: reference is "
                     f"{m.groups() if m else 'missing'}, the unit is 0x{CAVE:08x} "
                     f"{hashlib.sha256(blob).hexdigest()} -- update it")
        print("  = octabam-modules/varispeed-emus/manifest.py reference")

    # ---- wrap ------------------------------------------------------------------------
    if VARIANT:
        print(f"  test variant {VARIANT}: no wrap")
        return
    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    if len(VERSTR) > 10:
        sys.exit(f'version string "{VERSTR}" does not fit the 10-char field')
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0 or "too long" in r.stdout:
        sys.exit(f"EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    run("python3", "tools/make_bin.py", ELEK, "-o", OUT_BIN)
    chk = subprocess.run([str(EFT), str(OUT_SYX)], capture_output=True, text=True, cwd=ROOT)
    if chk.returncode != 0:
        sys.exit("round-trip: the .syx container does not re-parse")
    print("  round-trip: container re-parses OK")
    for f in (OUT, OUT_SYX, OUT_BIN, ELEK):
        print(f"  {f.relative_to(ROOT)}  sha256 {hashlib.sha256(f.read_bytes()).hexdigest()}")
    print(f"  OS VERSION reads {VERSTR}")


if __name__ == "__main__":
    main()

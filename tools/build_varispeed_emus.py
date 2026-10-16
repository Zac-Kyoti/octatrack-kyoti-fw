#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build VARISPEED_EMUS on TOP OF STOCK 1.40C (WIP).

STATIC / FLEX TSTR gets a fifth position, VARI: the track plays dry at
(project BPM x p) / (sample BPM x q), p/q the QUAN ratio on the PTCH knob, exact in
integers, RATE still applying; its TSNS knob becomes EMUS (OT / S950 / SP12), the DSP
engine latched at each trig. The audio editor's ATTR TIMESTRETCH gains VARI. A DSP load
guard (spec §6b) keeps each DSP core's estimated load -- a property of the settings --
within its budget: EMUS and FX-type changes that would overload a core are refused at
their UI handlers; a TSTR / ATTR TIMESTRETCH edit that puts a track on VARI over budget
steps THAT track's EMUS to OT (VEM7, spec "6b, answers"), and so does a track that
becomes a VARI track indirectly -- its gate on with its TSTR untouched: a sample's ATTR
TEMPO, a slot assign, a sample loaded into its slot (VEM8, spec "6b, option B"), and a
slot picked from a slot list that changes its machine (VEM10, "6b, option B extended"); and one
safety net -- run in the UI task's message loop when a signature of the estimate's inputs
changes -- steps just enough tracks to OT however else a core got over (Part change,
reload, loads, machine, paste), in its order; the toast MAX DSP: EMU LIMIT is raised from
that loop only.
Spec: reference/handoffs/VARISPEED_SPEC.md (clean-room); facts:
VARISPEED_SCOPE.md + VARISPEED_SCOPE_EMUS.md; this build:
reference/handoffs/VARISPEED_IMPL.md.

  ColdFire: octabam-modules/varispeed-emus/varispeed_emus.s (VEM_EMUS = 1, its default),
            one unit linked at the classic cave's proven start (0x400d6500), 24 detours,
            12 descriptor pokes; the sites, pokes and splice it shares with VARISPEED
            (tools/build_varispeed.py, the same source with VEM_EMUS = 0) are in
            tools/varispeed_buildlib.py.
  DSP:      the hardware-proven S950/SP12 kernel (tools/varispeed_emus_dsp.asm via
            tools/varispeed_emus_dsp_src.py) in SPRING REVERB's P module and X data, its voice
            and boot hooks, SPRING removed from both FX choosers -- the old builder's DSP
            half, copied in verbatim from reference/handoffs/VARISPEED_DSP_INSTALL.py.

    out/mainos_varispeed_emus.bin                   patched MAIN OS
    out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx        MIDI DIN
    out/OCTATRACK_VARISPEED_EMUS.bin                CF card
    out/elek_varispeed_emus.bin                     the EFT container (make_bin's input)
    out/varispeed_emus_syms.json                    unit symbols, hooks, pokes (the tests read it)

Every splice asserts the stock bytes it overwrites and that nothing branches into the
middle of what it displaces; the cave must be zero in stock and inside the classic
cave from 0x400d6500; no reference into 0x80006a40..0x80006abf; the unit must link to
the same bytes for -mcpu=5407 and 54455 (octabam assembles DRAM units for 54455).

Usage:  KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed_emus.py [VERSTR]   (default 140C_VEM10)
"""
import hashlib, importlib.util, json, os, pathlib, struct, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)

import varispeed_buildlib as L

BASE = L.BASE
HERE = L.HERE
ROOT = L.ROOT
sys.path.insert(0, str(HERE))
STOCK_SECT = L.STOCK_SECT
SRC = L.SRC
OUT = ROOT / "out/mainos_varispeed_emus.bin"
ELEK = ROOT / "out/elek_varispeed_emus.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_VARISPEED_EMUS.syx"
OUT_BIN = ROOT / "out/OCTATRACK_VARISPEED_EMUS.bin"
SYMS_JSON = ROOT / "out/varispeed_emus_syms.json"
WORK = ROOT / "out/vem_build"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_VEM10"
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

# The VARI core's sites, pokes and context (shared with VARISPEED: tools/varispeed_buildlib.py),
# plus VARISPEED_EMUS's own: EMUS and the DSP load guard.
CAVE = L.CAVE
# detours: site -> (stock bytes, symbol, kind). kind jmp/jsr: `jmp|jsr sym` + nops.
DETOURS = dict(L.CORE_DETOURS)
DETOURS.update({
    # EMUS: P2EDIT's only delta conversion (also notes a TSTR edit for the guard, VEM7)
    0x4003a566: ("4eb94003249c", "emus_p2step", "jsr"),
    # EMUS: SRC SETUP's open, its encoder set-up call (every open, and a track change's
    # re-open): the detent count restarts
    0x400585f4: ("4eb9400326d4", "emus_open", "jsr"),
    # ---- the DSP load guard (spec §6b; IMPL §12, §13)
    # the UI task's message-loop tail (every message ends here): the guard's due check and
    # the only place its toast is raised
    0x40062d1c: ("4ab946c7c72c", "vg_tick", "jmp"),
    # the FX1 / FX2 choosers' YES (the only applies of a chosen FX type): refused when
    # emulated engines would tip the core over
    0x400526e4: ("4fefffbc48d77cfc", "vh_fx1", "jmp"),
    0x40052474: ("4fefffbc48d77cfc", "vh_fx2", "jmp"),
    # VEM10 (spec "6b, option B extended"): the slot columns of the two machine / slot
    # choosers that reach the slot assign 0x40079424 mark their track (vg_pick): a machine
    # change that follows is a slot pick's, and names that track; the machine columns do not
    # pass here. SRC menu: its slot selection call; audio editor: its machine load.
    0x4005a760: ("4eb94003d014", "vg_pick_src", "jsr"),
    0x400796d6: ("2839460e738e", "vg_pick_ae", "jsr"),
})
# Each body replays its site's displaced bytes and jumps back here: the builder checks
# the jump target equals site + displaced length.
RETURNS = dict(L.CORE_RETURNS, vb_fx1=0x400526ec, vb_fx2=0x4005247c)

# descriptor pokes (u32): addr -> (stock value, new value or symbol, what)
POKES = dict(L.CORE_POKES)
POKES.update({
    0x400d3142: (0, "emus_widget", "STATIC TSNS widget"),
    0x400d32d4: (0, "emus_widget", "FLEX TSNS widget"),
})
# Stock bytes the code relies on without patching them (asserted, not written):
CONTEXT = dict(L.CORE_CONTEXT)
CONTEXT.update({
    # P2EDIT around R1: d2 = the old byte (mvs.b), a3 = slot2, d3 = delta, d4 = track
    0x4003a55a: "d1fc0008ef5a75102f032f0b4eb94003249c41eb00062235",
    # P2EDIT's x7: the delta is multiplied by 7 while [0x46c7d8ee + 24 * (slot2 + 0x38)]
    # (the encoder's push) is set -- emus_p2step reads the same flag for encoder F
    0x4003a480: "262f0028200b0680000000382200eb89e7889280068146c7d8ee20414a9067082003e78890832600",
    # SRC SETUP's open around R2: the encoder set-up's arguments (P, -1, the records)
    0x400585e0: "4879400bb7044878ffff41f9400d5f382f304c004eb9400326d4",
    # the voice loop clears the trig byte's bits 4-7 after the second pass (the engine latch)
    0x4000d52e: "1012780fc08414c0",
    # ---- the DSP load guard's stock facts (VARISPEED_IMPL.md §10.1)
    # the live FX type ids 0x80000ec4[t] (FX1) / 0x80000ecc[t] (FX2): every frame they go
    # into the frame's per-track DSP record (+54 / +56) ...
    0x40004d2e: "421512164881354100362044d1fc8000011014280dbc4882",
    # ... and the Part applies copy them from the Part (+0 FX1, +8 FX2)
    0x4000220e: "41f980000ec4d3c6119168002243d3fc40170f6841f980000eccd3c611916800",
    # the voice state 0x800049d8 + 168t: +0 = sounding (the stream engine outputs silence
    # when it is 0; the voice reset clears it)
    0x40007978: "223c000000a84c0108002440d5fc8000",
    0x400079b2: "4a126616",
    0x40006856: "41f9800049d8420013808800",
    # the frame index 0x800000e0: the DSP's buffer word, read at every frame ISR
    0x4000aaee: "41f9800000e023d0800000e430392000001c714023c0800000e0",
    # the voice loop's machine bytes 0x80000eb4 + 8 * frame + t, and the render table by
    # machine type (ST, FL, PU share 0x40004008: the only renders that carry an engine)
    0x4000d3ea: "2e3c80000eb4",
    0x400d6434: "4000400840004008400044244000466c40004008400047f0400047f0400047f0",
    # ---- the guard's toast (spec §6a; IMPL §11): NOTIFY(text, dur). Its entry (closes an
    # open toast, measures the text in the toast font 0x400ba862, opens a textpx + 15 wide
    # window), and dur > 0 = the self-timing countdown (dur <= 0 takes the modal path that
    # hung a unit: never used)
    0x4005a2b8: "2f032f02242f000c262f00104ab9460d1e7067044ebac91e2f024878ffff4879400ba8624eb940012f30",
    0x4005a324: "4a836f0c23c3460d1e6c",
    # the window it opens is centred on the 128 x 64 screen: x = (128 - w) / 2
    0x40058184: "203c000000809083",
    # ---- the guard of spec §6b (IMPL §12.1)
    # the UI task's loop: receive from the UI queue 0x460d17ae, dispatch by type (78)
    0x40061cd2: "4879460d17ae4eb940000d002440588f101253807180784db880",
    # ... the tail every case reaches, its test and the branch back to the receive
    0x40062d1a: "508f4ab946c7c72c6700efae",
    # stock's own message cases raise NOTIFY at this level (27/29: "%s" 0x78; 31: 0x30)
    0x40062cba: "487800782f024eb94005a2b84fef00106050",
    # DTIM1's ISR posts message type 5 (0x400a7279) to the UI queue: the 60 Hz tick
    0x40055ce4: "4879400a72794879460d17ae4e92",
    0x400a7278: "1205",
    # the FX1 chooser's YES: cursor 0x460d5c94, rows 0x400d6060, the Part's +0x8ed80 byte,
    # the same type returns at once (0x4005293a)
    0x400526ec: "77b9800000037fb9800000002439460d5c94247946c8245647f9400d6060",
    0x40052722: "d1fc0008ed807110b2806700020c",
    # the FX2 chooser's YES: cursor 0x460d5ca8, rows 0x400d6090, +0x8ed88
    0x4005247c: "77b9800000037fb9800000002439460d5ca8247946c8245647f9400d6090",
    0x400524b2: "d1fc0008ed887110b2806700021c",
    # their only references: the choosers' YES records ({0x31, 0, press})
    0x400bc148: "3100400526e4",
    0x400bc372: "310040052474",
    # the three Part applies write their (bank, part) to 0x80001828 / 0x80001829 (whose
    # live bytes these are, vg_step_ot)
    0x400090a4: "300d1f40004a13c080001828320e1f41004b13c18000",
    0x40009e10: "13c68000182813c580001829",
    # ---- VEM10: what tells a slot pick's machine change from the machine selector's (IMPL §17.1)
    # the SRC menu's handler 0x4005a5a8: column 0x460d1a48 != 0 -> 0x4005a758, which goes on
    # (to the vg_pick_src site 0x4005a760) only for column 1; column 0 writes the machine from
    # PAGE_M at 0x4005a61c (the machine selector)
    0x4005a5b8: "2039460d1a4866000198",
    0x4005a758: "7201b2806600015c",
    0x4005a614: "79102239460d5c301081",
    # ... its slot column: the other machine with its slot byte already on the slot picked
    # skips the slot assign and writes the machine straight (0x4005a826)
    0x4005a7f0: "7100b0846704b483672c",
    # the audio editor's chooser 0x400796a0: column 0x460e739a == 1 falls into the
    # vg_pick_ae site 0x400796d6; any other column -> 0x400798fe (its machine path)
    0x400796ca: "7401b4b9460e739a6600022a",
    # the slot assign 0x40079424: the picked machine's slot byte already the slot -> out
    # (0x40079672, no machine write); else the machine byte written at 0x40079522
    0x400794b6: "7190b081670001b6",
    0x40079520: "79101082",
})


# ---------------------------------------------------------------------------
# DSP: copied VERBATIM from reference/handoffs/VARISPEED_DSP_INSTALL.py (the old
# builder's DSP half, ours), below the marker; the module scope it assumes is above.
# ---------------------------------------------------------------------------
# ---- begin VARISPEED_DSP_INSTALL.py ----
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
# ---- end VARISPEED_DSP_INSTALL.py ----


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    for t in (DSP_ASM, DSP_DIS):
        if not t.exists():
            sys.exit(f"missing {t} -- build the DSP toolchain")
    stock = STOCK_SECT.read_bytes()
    img = bytearray(stock)
    if VARIANT:                          # a test variant without some detours (e.g. the O2 holds)
        for a in filter(None, os.environ.get("VEM_VARIANT_SKIP", "").split(",")):
            print(f"  test variant {VARIANT}: detour 0x{DETOURS.pop(int(a, 16)) and int(a, 16):08x} left stock")

    # ---- the ColdFire unit (VEM_EMUS = 1, the source's default) ----------------------
    print("=== ColdFire: varispeed_emus.s (VEM_EMUS = 1) ===")
    blob, syms, end = L.build_unit(SRC, WORK)
    # ---- context bytes, detours, pokes: all asserted against stock first ------------
    L.splice(img, blob, syms, DETOURS, POKES, CONTEXT, RETURNS)

    # ---- DSP -----------------------------------------------------------------------
    print("\n=== DSP: the S950/SP12 kernel (SPRING REVERB donor) ===")
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
        L.check_manifest_reference(ROOT / "octabam-modules/varispeed-emus/manifest.py", blob)

    # ---- wrap ------------------------------------------------------------------------
    if VARIANT:
        print(f"  test variant {VARIANT}: no wrap")
        return
    L.wrap(OUT, ELEK, OUT_SYX, OUT_BIN, VERSTR)


if __name__ == "__main__":
    main()

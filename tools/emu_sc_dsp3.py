#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Isolation check of the step-3 side-chain DSP hooks (tools/patch_sc_dsp3.asm)
under octabam's dsp_host / dsp56kEmu.

Like emu_sc_dsp.py (step 2) this runs each hook AS its own -proc entry with the
entry conditions seeded into the .mem, then reads back exactly what it produced.
dsp_host can't run the stock COMPRESSOR end to end, so the compressor's
gain-reduction response to the keybus is still a hardware test -- but the three
new stages here (KEY GAIN scaler, one-pole KEY FLT, SC LISTEN stash) are pure
data transforms and ARE checked numerically against a Python reference:

  copy    KEY!=0, KFLT/KGAIN neutral  -> X:$40 == keybus[k]   (step-2 regression)
  KEY=0                               -> X:$40 untouched
  KEY GAIN  cold (r7+$17==0)          -> X:$40 == keybus[k] * gain_table[idx]  (snaps)
  KEY GAIN  warm                      -> X:$40 == keybus[k] * one_pole(prev, target, KGNA)
  KEY FLT LP / HP                     -> X:$40 == python_onepole(keybus[k], a_table[idx])
  KEY FLT bypass (KFLT == 64)         -> X:$40 == keybus[k]
  KEY FLT edge override (idx 31/0)    -> X:$40 == python_onepole(keybus[k], LP_EDGE/HP_EDGE)
  KEY FLT HP re-entry declick         -> r7+$14 set on OFF -> HP's first block seeds tracker=0
  state persistence (block 2)         -> continues the python tracker, no reset
  SC LISTEN  MON=1                    -> keybus[k] gen 1 == the processed X:$40

Payload B (tracks 1-4, CORE_BASE 0) only -- emu_sc_dsp.py already checks the
A/B detour encodings. Session 77 (cross-core SIDECHAIN) added per-payload
cross-core tokens (corebase/fcorebase/sbase/fsbase/gcnt/gseed/foreign_br,
see patch_sc_dsp3.asm's own header) but this file still only exercises the
SAME-CORE KEY path numerically -- the cross-core publish/read path has its
own dedicated test, tools/emu_sc_dsp3_xcore.py (dual-core, via dsp_host_xcore).
"""
import pathlib, re, struct, subprocess, sys
import sc_tables
import sc_keyfilt
import dsp_asm_util

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_HOST = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_host"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
MODMAP = ROOT / "refs/octabam/tools/build/dsp_modmap.py"
SRC = ROOT / "tools/patch_sc_dsp3.asm"
SCRATCH = ROOT / "out/dsp"
SCRATCH.mkdir(parents=True, exist_ok=True)
RTS_ADDR = 0
S17 = None                              # set by main() once r7 is known; see base_mem()
KFB = None                              # the key-filter block, r7+$1c (main())
SYMS = {}

# default: throwaway placement of the cave over stock payload B (isolation test).
# --patched: regenerate payload B's .mem from out/mainos_sidechain_compressor.bin -- the
#   cave is over the real donor and the three detours are live.
PATCHED = "--patched" in sys.argv
# --ftab-lua: the key-filter table base as octabam's wrapper had it until 2026-10-24,
#   `lua (r1+$10),r1` from the KEY GAIN base (wrong since the gain store moved r1 to r5+$20).
FTAB_LUA = "--ftab-lua" in sys.argv
if PATCHED:
    MEM_B = SCRATCH / "payload_B_sc3.mem"
    CAVE_ORG = 0x1012                   # SPRING REVERB P addr, payload B (Session 76 continued)
    COMP_MOD, COMP_PROC = 0x1864, 0x1871
    COMMIT_HOOK = 0x303                  # dispatcher's per-track commit step
else:
    MEM_B = ROOT / "out/dsp/payload_B.mem"
    # matches --patched's CAVE_ORG (SPRING REVERB donor, Session 76 continued)
    # so this isolation placement is proven collision-free against the real
    # thing. No longer constrained to stay under 0xfff for a short-jsr's sake
    # -- zz17/zz20's internal calls into zz18 are `bsr` (PC-relative) now,
    # not `jsr`, precisely because the donor swap moved the cave past 0xfff.
    CAVE_ORG = 0x1012
    COMP_MOD, COMP_PROC = 0x1864, 0x1871
    COMMIT_HOOK = 0x303
# --layout octabam: the keybus/MON layout octabam's manifest builds ($800/$7f0, Session 115's);
# the default is the standalone builder's (the FX2 slot tail, 2026-10-15).
OCTABAM_LAYOUT = "--layout" in sys.argv and sys.argv[sys.argv.index("--layout") + 1] == "octabam"
KB_BASE = 0x800 if OCTABAM_LAYOUT else 0x7e00
KB_STRIDE = 0x40     # keybus slot(track) = KB_BASE + track*$40 ($800 since Session 115, $7e00 since 2026-10-15)
MON_BASE = 0x7f0 if OCTABAM_LAYOUT else 0x7df0   # MON_ON/MON_KEY[track] = Y:MON_BASE + track*2
Q23 = 1 << 23
MON_N = 16                              # moncommit's fade length in blocks (4 until 2026-10-24)
NW = 30                                 # dsp_host caps n7 at 15 frames = 30 words

fails = []
GAIN_T = sc_tables.gain_table()


def sh(*a, **kw):
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True, cwd=ROOT, **kw)
    if r.returncode != 0:
        sys.exit(f"cmd failed: {' '.join(map(str,a))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def load_mem(p):
    b = pathlib.Path(p).read_bytes(); off = 0; mods = []
    while True:
        sp, addr, cnt = struct.unpack_from("<BII", b, off); off += 9
        if sp == 0xff:
            break
        mods.append([sp, addr, list(struct.unpack_from("<%dI" % cnt, b, off))]); off += 4 * cnt
    return mods


def save_mem(p, mods):
    with open(p, "wb") as f:
        for sp, addr, w in mods:
            f.write(struct.pack("<BII", sp, addr, len(w)))
            f.write(struct.pack("<%dI" % len(w), *w))
        f.write(struct.pack("<BII", 0xff, 0, 0))


def s24(v):
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


def assemble():
    """assemble patch_sc_dsp3.asm for payload B, append the real tables,
    return (words, sctap, scdet, sctail, gtab_off, ftab_off)."""
    # pass 1: placeholder table addrs to size the code
    def build(gt, ft):
        # payload B's cross-core tokens (Session 77) -- same literals as
        # build_sidechain_compressor.py's DSP["B"] entry.
        txt = SRC.read_text() \
                             .replace("@COREBASE@", "0").replace("@FCOREBASE@", "4") \
                             .replace("@SBASE@", "$3be00").replace("@FSBASE@", "$33e00") \
                             .replace("@GCNT@", "$3bdff").replace("@GSEED@", "$3bdfe") \
                             .replace("@FOREIGN_BR@", "bne zz24") \
                             .replace("@KEYB@", f"${KB_BASE:x}").replace("@KEYB1@", f"${KB_BASE + 0x20:x}") \
                             .replace("@MONB@", f"${MON_BASE:x}") \
                             .replace("$fab1e0", f"${gt:x}").replace("move    #>$fab2e0,r1", "lua     (r1+$10),r1\n        nop" if FTAB_LUA
                                                                     else f"move    #>${ft:x},r1") \
                             .replace("@LPEDGE@", f"${sc_tables.lp_edge():x}") \
                             .replace("@HPEDGE@", f"${sc_tables.hp_edge():x}") \
                             .replace("@KGNA@", f"${sc_tables.kgn_smooth_a():x}")
        for k, v in sc_keyfilt.asm_tokens().items():
            txt = txt.replace(k, v)
        a = SCRATCH / "sc3_test.asm"; a.write_text(txt)
        o = SCRATCH / "sc3_test.bin"
        sym = SCRATCH / "sc3_test.sym"
        sh(DSP_ASM, "-in", a, "-org", f"{CAVE_ORG:x}", "-out", o, "-sym", sym)
        raw = o.read_bytes()
        syms = {name: int(addr, 16) for name, addr in
                (line.split() for line in sym.read_text().splitlines() if line.strip())}
        return ([int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)], syms)

    code, _ = build(CAVE_ORG, CAVE_ORG)
    n = len(code)
    gtab_off, ftab_off = n, n + sc_tables.GAIN_N
    code, syms = build(CAVE_ORG + gtab_off, CAVE_ORG + ftab_off)
    assert len(code) == n, "code size shifted between sizing passes"
    words = code + GAIN_T + sc_keyfilt.GT
    total = len(words)
    if total > 1063:
        sys.exit(f"cave {total} words > SPRING REVERB donor's 1063")
    # round-trip sanity on the code region
    (SCRATCH / "sc3_code.bin").write_bytes(b"".join(w.to_bytes(3, "little") for w in words[:n]))
    d = sh(DIS, "-in", SCRATCH / "sc3_code.bin", "-pc", f"{CAVE_ORG:x}", "-le")
    if " dc " in d or "InvalidInstruction" in d or "mpysu" in d or "macsu" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    # (the disassembler lists no line for --ftab-lua's nop, so the round trip would misalign)
    bad = [] if FTAB_LUA else dsp_asm_util.mnemonic_mismatches((SCRATCH / "sc3_test.asm").read_text(), d)
    if bad:
        sys.exit("dsp_asm encoded instructions as something else:\n" +
                 "\n".join(f"  #{i}: {s}  ->  {x}" for i, s, x in bad))
    # rts positions delimit the three routines. scdet now has THREE internal
    # rts (zz16's, zz20's, and zz18's -- the shared OFF-publish sub zz17/zz20
    # both `jsr` into, added to reclaim word budget for moncommit's exact-
    # match fix): rts[0] = sctap's own, rts[3] = zz18's (last in source order,
    # so moncommit/HOOK 3 starts right after it). See build_sidechain_compressor.py's
    # matching comment. Found via dsp_asm_util.find_rts() (disassembler-
    # parsed instruction boundaries), NOT a raw word scan for 0x00000c -- a
    # scan matches that value anywhere, including a 2-word branch's own
    # displacement operand (Session 76 continued yet again: this exact
    # collision silently mis-located moncommit after this session's own new
    # branch happened to have a displacement of 12).
    # the routines by name (the key filters' subroutines put rts inside scdet); scdet still
    # follows sctap's own rts
    rts = dsp_asm_util.find_rts(d, CAVE_ORG)
    global SYMS
    SYMS = syms
    sctap, scdet, sctail = syms["sctap"], syms["scdet"], syms["moncommit"]
    assert sctap == CAVE_ORG and scdet == CAVE_ORG + rts[0] + 1, "sctap/scdet layout"
    if syms.get("scmonbody") != sctail + 2:
        sys.exit(f"scmonbody is at {syms.get('scmonbody')!r}, expected the first word after "
                 f"moncommit's two-word displaced load at 0x{sctail + 2:x}")
    global RTS_ADDR
    RTS_ADDR = CAVE_ORG + rts[0]                       # sctap's own rts -- a safe -init
    return words, sctap, scdet, sctail, gtab_off, ftab_off


def ensure_patched_mem(words):
    """--patched: build payload B's .mem from out/mainos_sidechain_compressor.bin
    (octabam's dsp_modmap only dumps the stock image, so replicate its dumpmem
    here), then assert the cave + the three jsr detours landed as
    build_sidechain_compressor.py wrote."""
    import importlib.util
    imgp = ROOT / "out/mainos_sidechain_compressor.bin"
    if not imgp.exists():
        sys.exit("run tools/build_sidechain_compressor.py first (out/mainos_sidechain_compressor.bin missing)")
    spec = importlib.util.spec_from_file_location("mm", MODMAP)
    mm = importlib.util.module_from_spec(spec); spec.loader.exec_module(mm)
    img = imgp.read_bytes()
    va, ln = 0x400f59ef, 0x12d05                          # payload B
    pmods, b = mm.modules(img, va, ln)
    with open(MEM_B, "wb") as fh:
        for sp, addr, cnt, data in pmods:
            fh.write(struct.pack("<BII", sp, addr, cnt))
            for i in range(cnt):
                fh.write(struct.pack("<I", mm.w24(b, data + i * 3)))
        fh.write(struct.pack("<BII", 0xff, 0, 0))
    mods = load_mem(MEM_B)
    cave = next(m for m in mods if m[0] == 0 and m[1] <= CAVE_ORG < m[1] + len(m[2]))
    base = CAVE_ORG - cave[1]
    got = cave[2][base:base + len(words)]
    if got != list(words):
        for k, (x, y) in enumerate(zip(got, words)):
            if x != y:
                sys.exit(f"--patched cave word {k} differs: image 0x{x:06x} vs asm 0x{y:06x}")
    # detour opcode word is always exactly 0x0D1080 (bsr_long's constant
    # opcode half, build_sidechain_compressor.py) -- was `w >> 12 == 0x0D0` (jsr_short's
    # pattern) before the SPRING REVERB donor swap moved the cave past
    # dsp_asm's short-jsr range (Session 76 continued).
    cmod = next(m for m in mods if m[0] == 0 and m[1] == COMP_MOD)
    w = cmod[2][COMP_PROC - COMP_MOD]
    if w != 0x0D1080:
        sys.exit(f"--patched: COMPRESSOR P:0x{COMP_PROC:x} is 0x{w:06x}, not `bsr` to the cave")
    # moncommit's detour lives in the DISPATCHER module, not the compressor's --
    # find whichever loaded module actually contains it.
    dmod = next(m for m in mods if m[0] == 0 and m[1] <= COMMIT_HOOK < m[1] + len(m[2]))
    w = dmod[2][COMMIT_HOOK - dmod[1]]
    if w != 0x0D1080:
        sys.exit(f"--patched: dispatcher P:0x{COMMIT_HOOK:x} is 0x{w:06x}, not `bsr` to the cave")
    print(f"  --patched: cave + scdet/moncommit detours verified against {imgp.name}")


def r7_of(mem):
    """run a no-op proc once, parse the instance line for r7."""
    out = sh(DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{RTS_ADDR:x}",
             "-frames", "15", "-blocks", "1")
    m = re.search(r"r7 = X:0x([0-9a-fA-F]+)", out)
    if not m:
        sys.exit(f"could not parse r7 from:\n{out}")
    return int(m.group(1), 16)


def base_mem(words, scdet, moncommit, patch_tail, xseed, yseed):
    # `moncommit`/`patch_tail` are unused here in isolation mode: moncommit no
    # longer lives inside the compressor module (it's a dispatcher-level hook
    # now, NOTES.md Session 58), so there is nothing of it to splice into
    # COMP_MOD. Kept as a parameter only so existing call sites (all pass
    # `moncommit, False`) don't need touching; see emu_sc_dsp3_moncommit.py
    # for moncommit's own isolated test, which builds its own mem directly.
    mods = load_mem(MEM_B)
    if not PATCHED:
        for m in mods:
            if m[0] == 0 and m[1] == COMP_MOD:
                i = COMP_PROC - COMP_MOD
                assert (m[2][i], m[2][i + 1]) == (0x221e00, 0x346100), \
                    f"comp proc+0 not [move r0,n6 ; move #61,r4]: {m[2][i]:06x} {m[2][i+1]:06x}"
                m[2][i], m[2][i + 1] = 0x0bf080, scdet         # jsr scdet (long, test only)
                break
        mods.append([0, CAVE_ORG, list(words)])                # PATCHED: already in .mem
    mods.append([1, 0x20c, [15]])                      # n7 = frames (headless ctx = 0)
    for sp, addr, w in (xseed or []):
        mods.append([sp, addr, list(w)])
    for sp, addr, w in (yseed or []):
        mods.append([sp, addr, list(w)])
    # KEY GAIN's own state (r7+$17, Session 76 continued yet again) is real,
    # never-zeroed DSP memory like $16/$18 -- every test here that doesn't
    # explicitly care about it (i.e. every test predating this session) needs
    # a deterministic cold start, not whatever garbage the dumped payload
    # happens to hold, or a call at the (very common) default KGAIN=64 would
    # smooth from that garbage instead of landing on an exact unity multiply.
    # Auto-seed cold UNLESS the caller already put an explicit S17 poke in
    # xseed (the KEY GAIN-specific tests below do, to exercise the smoother
    # itself) -- centralized here instead of touching every call site.
    if S17 is not None and not any(sp == 1 and addr == S17 for sp, addr, w in (xseed or [])):
        mods.append([1, S17, [0]])
    # the key-filter block's magic word ($2a): 0 = "not set up" unless the caller seeds the
    # block (a real instance always passes through scinit first)
    if KFB is not None and not any(sp == 1 and addr <= KFB + 14 < addr + len(w)
                                   for sp, addr, w in (xseed or [])):
        mods.append([1, KFB + 14, [0]])
    # the KEY declick's key in use ($2c) and its flag ($2d): steady state on KEY 1 (the key
    # most tests select) unless the caller seeds them
    if KFB is not None and not any(sp == 1 and addr <= KFB + 16 < addr + len(w)
                                   for sp, addr, w in (xseed or [])):
        mods.append([1, KFB + 16, [1, 0]])
    m = SCRATCH / "sc3_iso.mem"
    save_mem(m, mods)
    return m


def run(mem, proc, dumps, params, pokey=None, frames=15, audio=None):
    """dumps: list of ('x'|'y', lo, hi). One dsp_host run per dump.

    `audio`, if given, overrides dsp_host's own r0 base (`-audio`, default
    0x80). Left unset by default -- dsp_host ALSO uses this same base as
    where it writes its own synthetic tone samples in X-memory (dsp_host.cpp
    line ~745), so forcing it to 0 for every caller here once corrupted
    `emu_sc_dsp3_moncommit.py`'s own X:0-0x20 dump (Session 75: found by
    that test going from all-green to failing after an earlier, too-broad
    version of this default). Pass `audio=0` explicitly only where the
    real dispatcher's r0 value actually matters to the code under test --
    `scdet`'s own repeat-call guard is the one case so far (it keys off
    r0's incoming value being exactly 0 for the frame's only/first
    PROCESS_TABLE call); every other existing check here never depended
    on r0's incoming value at all (`scdet` always overwrites it itself
    before using it), which is why they passed under either default."""
    res = []
    for i, (sp, lo, hi) in enumerate(dumps):
        df = SCRATCH / f"sc3_d{i}.bin"
        a = [DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{proc:x}",
             "-frames", str(frames), "-blocks", "1", "-params", params,
             "-dumpy", f"{'@' if sp == 'x' else ''}{df},{lo:x},{hi:x}"]
        if audio is not None:
            a += ["-audio", f"{audio:x}"]
        if pokey:
            a += ["-pokey", pokey]
        sh(*a)
        raw = df.read_bytes()
        res.append([int.from_bytes(raw[j:j + 4], "little") for j in range(0, len(raw), 4)])
    return res


def read_r0(mem, proc, params, audio=None):
    """run one -proc call, parse dsp_host's own end-of-run REGS dump for r0's
    final value (same technique r7_of() already uses for r7's instance-line
    printout) -- used to verify the split-detector-offset fix (Session 76
    continued yet again): no dump/memory check can observe r0 directly, only
    the register itself."""
    a = [DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{proc:x}",
         "-frames", "15", "-blocks", "1", "-params", params]
    if audio is not None:
        a += ["-audio", f"{audio:x}"]
    out = sh(*a)
    m = re.search(r"REGS r0=([0-9a-fA-F]+)", out)
    if not m:
        sys.exit(f"could not parse r0 from:\n{out}")
    return int(m.group(1), 16)


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def close(a, b, tol):
    return all(abs(s24(x) - s24(y)) <= tol for x, y in zip(a, b))


# ---- python reference models -------------------------------------------------
def ref_kgn_applied(target, prev):
    """block-rate one-pole smoother on the APPLIED KEY GAIN coefficient
    itself (Session 76 continued yet again), mirroring the .asm's own
    cold-sentinel + coefficient-weighted-feedback update exactly: prev==0
    (r7+$17's own "never seeded" sentinel -- gain_table() entries are all
    strictly positive, so a real applied value can never collide with it)
    snaps straight to target; otherwise one-pole toward it."""
    if prev == 0:
        return s24(target) & 0xFFFFFF
    t, p, a = s24(target), s24(prev), s24(sc_tables.kgn_smooth_a())
    return (p + ((a * (t - p)) >> 23)) & 0xFFFFFF


def ref_gain(src, kgain, prev=0):
    idx = kgain >> 3
    g = ref_kgn_applied(GAIN_T[idx], prev)
    out = []
    for s in src:
        acc = (s24(g) * s24(s) * 128) >> 24   # mpy (frac, <<1) then asl #6, take a1
        out.append(max(-Q23, min(Q23 - 1, acc)) & 0xFFFFFF)
    return out


def _sat24(v):
    return max(-Q23, min(Q23 - 1, v))


def ref_mon_weights(pos, on):
    """moncommit's mix weight g for each of a block's 16 pairs, as the .asm computes it:
    g starts at pos / MON_N (saturated; MON_N -> just under 1.0) and moves 1/(16 MON_N) per
    pair, each step through an accumulator and a saturating move to y1. The fast paths (pos 0
    off, pos MON_N on) return a constant 0 / 1.0."""
    pos = pos if 0 <= s24(pos) <= MON_N else 0
    if (not on and pos == 0) or (on and pos == MON_N):
        return [0 if not on else Q23 - 1] * 16
    step = Q23 // (16 * MON_N) * (1 if on else -1)
    g, out = _sat24(pos * (Q23 // MON_N)), []
    for _ in range(16):
        g = _sat24(g + step)
        out.append(g)
    return out


def ref_mon(dry, key, pos, on):
    """moncommit's output block and its new MON_FADE: dry + g*(key - dry) per sample, in
    the .asm's arithmetic (halve the difference, fractional mpy, asl, add dry, take a1)."""
    pos = pos if 0 <= s24(pos) <= MON_N else 0
    if not on and pos == 0:
        return list(dry), 0
    if on and pos == MON_N:
        return list(key), MON_N
    ws = ref_mon_weights(pos, on)
    out = []
    for k in range(32):
        d, s = s24(dry[k]), s24(key[k])
        x0 = (s - d) >> 1
        out.append(_sat24(d + ((x0 * ws[k >> 1]) >> 22)) & 0xFFFFFF)
    return out, pos + (1 if on else -1)


# ---- signals ---------------------------------------------------------------
def sine(n, cyc):
    import math
    return [int(0.4 * Q23 * math.sin(2 * math.pi * cyc * i / n)) & 0xFFFFFF for i in range(n)]


def main():
    need = (DSP_ASM, DSP_HOST, DIS) + (() if PATCHED else (MEM_B,))
    for t in need:
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t}")

    words, sctap, scdet, sctail, gtab_off, ftab_off = assemble()
    print(f"{'[--patched] ' if PATCHED else ''}cave {len(words)}w @ P:0x{CAVE_ORG:x}   "
          f"sctap=0x{sctap:x} scdet=0x{scdet:x} sctail=0x{sctail:x}   "
          f"GTAB +0x{gtab_off:x}  FTAB +0x{ftab_off:x}\n")
    if PATCHED:
        ensure_patched_mem(words)

    global S17
    probe = base_mem(words, scdet, sctail, False, None, None)
    r7 = r7_of(probe)
    global KFB
    S17, KFB = r7 + 0x17, r7 + 0x1c
    print(f"r7 = X:0x{r7:05x}   KGN applied-gain state X:0x{S17:05x}   "
          f"key-filter block X:0x{KFB:05x}..0x{KFB + 14:05x}\n")

    MARK = [((0x10 + i) << 12) | 0xABC for i in range(0x20)]
    KEYV, K = 1, 0                       # KEY=1 -> abs track 0 (CORE_BASE 0)
    SLOT = KB_BASE + K * KB_STRIDE
    pk = ",".join(f"{SLOT + i:x}={MARK[i]:x}" for i in range(0x20))

    def P(key=0, kgn=64, hp=0, lp=127, mon=False):
        # major version layout: 6 RMS, 7 MON (stored 1 = OFF, 0 = ON), 8 KEY, 9 KGN,
        # 10 KBAS, 11 KWID (a base-width pair since 2026-10-21)
        return f"0,0,0,0,0,0,0,{0 if mon else 1},{key},{kgn},{hp},{lp}"

    def kf_ref(src, hp=0, lp=127, kf=None, kgn=64, prev=0):
        """the DSP's X:$40 after KEY GAIN and the key filters (sc_keyfilt's model)."""
        kf = kf or sc_keyfilt.KeyFilter()
        return kf.block(ref_gain(src, kgn, prev), hp, lp), kf

    def kf_state(kf):
        c = list(kf.c)
        return [v & 0xFFFFFF for v in [kf.s1, kf.h1, kf.h2, kf.l1, kf.l2] + c +
                [kf.vh, kf.vl, sc_keyfilt.MAGIC]]

    # 1. stage copy (step-2 regression) ------------------------------------
    print("copy / KEY select:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0xBEEF] * 0x20)], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV), pokey=pk, audio=0)
    exp, _ = kf_ref(MARK)
    check("KEY=1, filters OFF: X:$40 == keybus[0] through the model", x40 == exp,
          f"got[:3]={[hex(v) for v in x40[:3]]} exp[:3]={[hex(v) for v in exp[:3]]}")
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=0), pokey=pk, audio=0)
    check("KEY=0: X:$40 untouched", all(v == 0xBEEF for v in x40))

    # 1a. split-detector-offset fix (Session 76 continued yet again): a mid-block split's
    # SECOND call arrives with its own r0 already offset into the real audio buffer (`n6`
    # here, scdet's saved copy); the redirect must be $40+n6, not a bare $40. read_r0()
    # parses dsp_host's end-of-run REGS printout.
    print("\nsplit-detector-offset (r0 must be $40+n6, not a bare $40):")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
    r0 = read_r0(mem, scdet, P(key=KEYV), audio=0)
    check("unsplit/first call (n6=0): r0 == $40", r0 == 0x40, f"got=0x{r0:x}")
    for split_words in (2, 10, 30):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
        r0 = read_r0(mem, scdet, P(key=KEYV), audio=split_words)
        exp = 0x40 + split_words
        check(f"split 2nd call (n6=0x{split_words:x}): r0 == 0x{exp:x}",
              r0 == exp, f"got=0x{r0:x}")

    # 2. KEY GAIN (slot 9 since the major version) -- cold (r7+$17==0) snaps to the
    # table target; warm smooths (block rate). The filters (OFF) run after it, so the
    # expectation is the model on top of ref_gain (ref_gain is +-2 LSB of the DSP).
    print("\nKEY GAIN (cold -> snaps to target), through the filters at OFF:")
    for kgain in (64, 88, 40, 120, 0):
        mem = base_mem(words, scdet, sctail, False,
                       [(1, 0x40, [0] * 0x20), (1, S17, [0])], None)
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kgn=kgain), pokey=pk, audio=0)
        exp, _ = kf_ref(MARK, kgn=kgain)
        db = (((kgain >> 3) * 8) - 64) * 0.375
        check(f"KGN {kgain:3d} ({db:+.0f} dB)", close(x40, exp, 24),
              f"got[:2]={[hex(v) for v in x40[:2]]} exp[:2]={[hex(v) for v in exp[:2]]}")
    print("\nKEY GAIN block-rate smoothing (warm -> one-pole toward target, not instant):")
    prev_g = GAIN_T[64 >> 3]
    mem = base_mem(words, scdet, sctail, False,
                   [(1, 0x40, [0] * 0x20), (1, S17, [prev_g])], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kgn=120), pokey=pk, audio=0)
    exp_s, _ = kf_ref(MARK, kgn=120, prev=prev_g)
    exp_i, _ = kf_ref(MARK, kgn=120)
    check("warm KGN 64->120: one block does NOT jump straight to target",
          close(x40, exp_s, 24) and not close(x40, exp_i, 200),
          f"got[:2]={[hex(v) for v in x40[:2]]} smoothed[:2]={[hex(v) for v in exp_s[:2]]}")
    check("all 16 GAIN_T entries are strictly nonzero (0 is the cold sentinel)",
          all(v != 0 for v in GAIN_T))

    # 3. KEY FILTERS (major version), bit-exact against tools/sc_keyfilt.py. KGN 64 is an
    # exact identity (gain 1/64 then asl #6), so these compare every word.
    print("\nkey filters, first block after a reset (bit-exact vs sc_keyfilt):")
    import random
    rnd = random.Random(19)
    def noise(amp=0.6):
        v = [int(rnd.uniform(-amp, amp) * Q23) for _ in range(16)]
        out = []
        for k in range(16):
            out += [v[k] & 0xFFFFFF, (v[k] // 2 + v[(k + 3) % 16] // 3) & 0xFFFFFF]
        return out
    sig = [((s24(a) + s24(b)) // 2) & 0xFFFFFF for a, b in zip(sine(0x20, 3), noise(0.3))]
    pk_sig = ",".join(f"{SLOT + i:x}={sig[i]:x}" for i in range(0x20))
    for hp, lp, tag in ((0, 127, "both OFF"), (1, 127, "KBAS 20 Hz"), (33, 127, "KBAS 115 Hz"),
                        (127, 127, "KBAS 19.6 kHz"), (0, 0, "KBAS OFF: LP 28 Hz"),
                        (0, 64, "KBAS OFF: LP 784 Hz"), (0, 126, "KBAS OFF: LP 19.6 kHz"),
                        (14, 10, "kick: 41-97 Hz"), (49, 40, "band 280 Hz-2.6 kHz"),
                        (65, 0, "narrowest: half an octave"), (127, 0, "top: LP at OFF"),
                        (97, 126, "wide: LP past the top")):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
        (x40, st) = run(mem, scdet, [('x', 0x40, 0x60), ('x', KFB, KFB + 15)],
                        P(key=KEYV, hp=hp, lp=lp), pokey=pk_sig, audio=0)
        exp, kf = kf_ref(sig, hp, lp)
        check(f"KBAS {hp:3d} KWID {lp:3d} {tag:26s}", x40 == exp and st == kf_state(kf),
              f"out {sum(a != b for a, b in zip(x40, exp))} words differ; state "
              f"{[i for i, (a, b) in enumerate(zip(st, kf_state(kf))) if a != b]}")

    # 3a. a chain of blocks, the DSP's own r7 block carried from run to run: glides,
    # coefficient recomputes, the octave floor, both OFF ends, warm steady state
    print("\nkey filters, 24 chained blocks (state carried in the DSP's own words):")
    sched = [(0, 127)] * 3 + [(33, 127)] * 4 + [(33, 9)] * 4 + [(127, 0)] * 3 + \
            [(65, 81)] * 4 + [(65, 81)] * 2 + [(0, 127)] * 4
    kf = sc_keyfilt.KeyFilter()
    blk, s17 = None, 0
    bad = []
    for i, (hp, lp) in enumerate(sched):
        src = noise()
        pks = ",".join(f"{SLOT + k:x}={src[k]:x}" for k in range(0x20))
        xs = [(1, 0x40, [0] * 0x20), (1, S17, [s17])] + ([(1, KFB, blk)] if blk else [])
        mem = base_mem(words, scdet, sctail, False, xs, None)
        (x40, blk, (s17,)) = run(mem, scdet, [('x', 0x40, 0x60), ('x', KFB, KFB + 15),
                                              ('x', S17, S17 + 1)],
                                 P(key=KEYV, hp=hp, lp=lp), pokey=pks, audio=0)
        exp = kf.block(src, hp, lp)
        if x40 != exp or blk != kf_state(kf):
            bad.append(i)
    check("every block's output and state equal the model", not bad, f"bad blocks {bad}")

    # 3a'. leaving and entering the bypass (both OFF, settled) is continuous: the model's
    # largest sample-to-sample step across each switch stays within the signal's own
    print("\nkey filters: bypass in and out without a step (model):")
    import math
    kf = sc_keyfilt.KeyFilter()
    sw_steps, own = [], 0
    prev = None
    sched2 = [(0, 127)] * 6 + [(1, 127)] * 150 + [(0, 127)] * 200 + [(0, 126)] * 150 + [(0, 127)] * 200
    for i, (hp, lp) in enumerate(sched2):
        blk2 = []
        for k in range(16):
            v = int(0.5 * Q23 * math.sin(2 * math.pi * 220 * (16 * i + k) / 44100)) & 0xFFFFFF
            blk2 += [v, v]
        out = [s24(v) for v in kf.block(blk2, hp, lp)[0::2]]
        bypass = kf.vh == 0 and kf.vl == sc_keyfilt.LP_OFF_V
        steps = [abs(b - a) for a, b in zip(([prev] if prev is not None else []) + out, out)]
        if i > 0 and bypass != was_bypass:
            sw_steps.append(max(steps[:3]))
        elif i > 4:
            own = max(own, max(steps))
        prev, was_bypass = out[-1], bypass
    # the switch adds what the 5 Hz HP / 19.6 kHz LP did to the key: allow 0.5 % of full scale
    check(f"{len(sw_steps)} bypass switches, largest step {max(sw_steps)} vs the signal's own "
          f"{own} (+{100 * (max(sw_steps) - own) / Q23:.2f} % of full scale)",
          len(sw_steps) >= 4 and max(sw_steps) <= own + Q23 // 200)

    # 3b. the loop is a fixed 16 pairs (a split frame's n7 is shorter; Session 74)
    print("\nkey filters: n7 does not bound the loop:")
    exp, _ = kf_ref(sig, 33, 64)
    for short_n7 in (1, 6, 14):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, hp=33, lp=64),
                     pokey=pk_sig, frames=short_n7, audio=0)
        check(f"n7={short_n7:2d}: all 16 pairs filtered", x40 == exp)

    # 3c. garbage in the block (another effect used it) without scinit: the magic word
    # decides; and scinit itself clears the magic and KEY GAIN's state
    print("\nkey filters: reset and scinit:")
    mem = base_mem(words, scdet, sctail, False,
                   [(1, 0x40, [0] * 0x20), (1, KFB, [0x5a5a5a] * 14 + [0x123456])], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, hp=33, lp=64), pokey=pk_sig, audio=0)
    check("garbage block, no magic: starts over (as the model's first block)", x40 == exp)
    mem = base_mem(words, scdet, sctail, False,
                   [(1, KFB + 14, [sc_keyfilt.MAGIC]), (1, S17, [0x123456]), (1, KFB + 16, [5, 1])], None)
    (m2a, ms17, mkin) = run(mem, SYMS["scinit"], [('x', KFB + 14, KFB + 15), ('x', S17, S17 + 1),
                                                  ('x', KFB + 16, KFB + 18)], P())
    check("scinit clears r7+$2a, $17 and the KEY declick's $2c/$2d",
          m2a == [0] and ms17 == [0] and mkin == [0, 0], f"{m2a} {ms17} {mkin}")

    # 5. SC LISTEN stash (scdet -> keybus gen 1) --------------------------
    print("\nSC LISTEN:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
    (x40, g1) = run(mem, scdet, [('x', 0x40, 0x60), ('y', SLOT + 0x20, SLOT + 0x40)],
                    P(key=KEYV, hp=33, lp=64, mon=True), pokey=pk_sig, audio=0)
    check("MON=1: keybus[0] gen1 == processed X:$40", g1 == x40,
          f"g1[:3]={[hex(v) for v in g1[:3]]} x40[:3]={[hex(v) for v in x40[:3]]}")
    # MON off: the loop borrows the first 8 words of this track's gen-1 slot (gain, coefficients)
    # scratch (2026-10-19 cycle pass); moncommit reads the slot only while MON is on or fading,
    # and then the MON tail rewrites it after the loop
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
    (g1, blk) = run(mem, scdet, [('y', SLOT + 0x20, SLOT + 0x40), ('x', KFB, KFB + 15)],
                    P(key=KEYV, hp=33, lp=64, mon=False), pokey=pk_sig, audio=0)
    check("MON=0: gen1 = the gain + 7 coefficients (scratch), the rest untouched",
          g1[0] == GAIN_T[8] and g1[1:8] == blk[5:12] and all(v == 0 for v in g1[8:]))

    # 6. MON publish (scdet -> MON_ON[my track], Y:MON_BASE+track*2; the word after it is
    #    MON_FADE, moncommit's, since 2026-10-19) and the stash, now indexed by MY track ------
    print("\nMON publish (scdet -> MON_ON for moncommit; stash at keybus[my track] gen 1):")
    MYTRACK = 3
    MON_ADDR = MON_BASE + MYTRACK * 2
    MYSTASH = KB_BASE + MYTRACK * KB_STRIDE + 0x20
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0xdead, 0xdead])])
    (pub, x40, st, src) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2), ('x', 0x40, 0x60),
                                           ('y', MYSTASH, MYSTASH + 0x20),
                                           ('y', SLOT + 0x20, SLOT + 0x40)],
                              P(key=KEYV, hp=33, lp=64, mon=True), pokey=pk_sig, audio=0)
    # `move #1,b`'s short immediate is left-aligned (q2): the ON sentinel is $10000, which
    # moncommit matches exactly.
    check("MON=1: MON_ON == $10000, MON_FADE untouched", pub == [0x10000, 0xdead], f"got={pub}")
    check("MON=1: keybus[my track] gen1 == processed X:$40", st == x40,
          f"st[:3]={[hex(v) for v in st[:3]]} x40[:3]={[hex(v) for v in x40[:3]]}")
    check("MON=1: the SOURCE track's gen1 is not written", all(v == 0 for v in src))

    for fade, want_stash in ((0, False), (2, True)):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                       [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0x10000, fade])])
        (pub, x40, st) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2), ('x', 0x40, 0x60),
                                          ('y', MYSTASH, MYSTASH + 0x20)],
                             P(key=KEYV, hp=33, lp=64, mon=False), pokey=pk_sig, audio=0)
        check(f"MON=0, MON_FADE={fade}: MON_ON published OFF, MON_FADE untouched",
              pub == [0, fade], f"got={pub}")
        check(f"MON=0, MON_FADE={fade}: stash {'written (fade-out source)' if want_stash else 'not written past the coefficient scratch'}",
              (st == x40) if want_stash else all(v == 0 for v in st[8:]),
              f"st[:3]={[hex(v) for v in st[:3]]}")

    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0x10000, MON_N])])
    (pub,) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2)], P(key=0, mon=True), pokey=pk_sig, audio=0)
    check("KEY=0: MON_ON published OFF (even with MON=1)", pub == [0, MON_N], f"got={pub}")

    # 6b. KEY declick (2026-10-19): while MON is audible a KEY change waits (old key runs,
    # MON forced off this block); with MON silent it is taken at once
    print("\nKEY declick (a KEY change waits for MON to fade out):")
    SLOT2 = KB_BASE + 1 * KB_STRIDE
    sig2 = [((s24(v) * 3) // 4) & 0xFFFFFF for v in sine(0x20, 7)]
    pk2 = pk_sig + "," + ",".join(f"{SLOT2 + i:x}={sig2[i]:x}" for i in range(0x20))
    exp1, _ = kf_ref(sig, 33, 64)
    exp2, _ = kf_ref(sig2, 33, 64)
    KIN = KFB + 16
    for tag, kin, fade, key, x_exp, kin_exp, flag_exp, on_exp in (
            ("MON audible, KEY 1 -> 2: waits", 1, MON_N, 2, exp1, 1, 1, 0),
            ("MON silent, KEY 1 -> 2: taken", 1, 0, 2, exp2, 2, 0, 0x10000),
            ("MON audible, KEY 1 -> OFF: old key fades out", 1, MON_N, 0, exp1, 1, 1, 0),
            ("cold key in use: taken at once", 0x123456, MON_N, 2, exp2, 2, 0, 0x10000)):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20), (1, KIN, [kin, 0])],
                       [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0, fade])])
        (x40, kf2, pub) = run(mem, scdet, [('x', 0x40, 0x60), ('x', KIN, KIN + 2),
                                           ('y', MON_ADDR, MON_ADDR + 1)],
                              P(key=key, hp=33, lp=64, mon=True), pokey=pk2, audio=0)
        check(f"{tag:46s}", x40 == x_exp and kf2[0] == kin_exp and bool(kf2[1]) == bool(flag_exp)
              and pub == [on_exp],
              f"key in use/flag {kf2}, MON_ON {pub}, out {'ok' if x40 == x_exp else 'differs'}")

    # 7. moncommit: the MON crossfade (2026-10-19) ------------------------------------------
    print(f"\nmoncommit (MON declick: {16 * MON_N}-sample linear crossfade, MON_ON consumed):")
    DRY = sine(0x20, 2)
    KEYA = [(-s24(v) // 2) & 0xFFFFFF for v in sine(0x20, 5)]
    R0_IN = 0x1234
    PBLK = 0x300      # dsp_host writes its -params block at x:$208+6: keep it off X:0..$1f
    for mon_on, fade, tag in ((0x10000, 0, "ON from 0: fade in, block 1"),
                              (0x10000, MON_N - 1, "ON from N-1: fade in, last block"),
                              (0x10000, MON_N, "ON at N: plain copy"),
                              (0, 0, "OFF at 0: dry"),
                              (0, MON_N, "OFF from N: fade out, block 1"),
                              (0, 1, "OFF from 1: fade out, last block"),
                              (0x123456, MON_N, "garbage MON_ON: fades out"),
                              (0x10000, 0x654321, "garbage MON_FADE: reads as 0"),
                              (0x10000, 0xfffffe, "negative MON_FADE: reads as 0"),
                              (0, 0x654321, "OFF, garbage MON_FADE: dry, cleared")):
        mem = base_mem(words, scdet, sctail, False,
                       [(1, 0, DRY), (1, 0x206, [R0_IN]), (1, 0x208, [PBLK])],
                       [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [mon_on, fade]), (2, MYSTASH, KEYA)])
        (x0, pub) = run(mem, sctail, [('x', 0, 0x20), ('y', MON_ADDR, MON_ADDR + 2)], P())
        exp, pos = ref_mon(DRY, KEYA, fade, mon_on == 0x10000)
        bad = [k for k in range(32) if x0[k] != exp[k]]
        check(f"{tag:34s}", x0 == exp and pub == [0, pos],
              f"bad={bad[:6]} state={pub} exp=[0, {pos}] got[:4]={[s24(v) for v in x0[:4]]} "
              f"exp[:4]={[s24(v) for v in exp[:4]]} last={s24(x0[31])}/{s24(exp[31])}")
    r0 = read_r0(base_mem(words, scdet, sctail, False, [(1, 0, DRY), (1, 0x206, [R0_IN]), (1, 0x208, [PBLK])],
                          [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0x10000, 1]),
                           (2, MYSTASH, KEYA)]), sctail, P())
    check("r0 == x:$206 after a fading block (stock's commit pointer)", r0 == R0_IN,
          f"got=0x{r0:x}")

    # a full fade in and out, block by block: the weight never steps
    g, pos = [], 0
    for blk in range(2 * MON_N + 2):
        on = blk < MON_N + 1
        g += ref_mon_weights(pos, on)
        _, pos = ref_mon(DRY, KEYA, pos, on)
    steps = [abs(b - a) for a, b in zip(g, g[1:])]
    check(f"model: full on/off weight sequence moves at most 1/{16 * MON_N} per pair",
          max(steps) <= Q23 // (16 * MON_N) + 1 and g[0] == Q23 // (16 * MON_N) and g[-1] == 0,
          f"max step 0x{max(steps):x}, first 0x{g[0]:x}, last 0x{g[-1]:x}")

    print()
    if fails:
        print(f"FAIL -- {len(fails)}: " + ", ".join(fails)); sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

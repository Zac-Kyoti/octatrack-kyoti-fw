#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
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
  KEY GAIN  KGAIN != 64               -> X:$40 == keybus[k] * gain_table[idx]
  KEY FLT LP / HP                     -> X:$40 == python_onepole(keybus[k], a_table[idx])
  KEY FLT bypass (KFLT == 64)         -> X:$40 == keybus[k]
  KEY FLT edge override (idx 31/0)    -> X:$40 == python_onepole(keybus[k], LP_EDGE/HP_EDGE)
  state persistence (block 2)         -> continues the python tracker, no reset
  SC LISTEN  MON=1                    -> keybus[k] gen 1 == the processed X:$40

Payload B (tracks 1-4, CORE_BASE 0) only -- the code is byte-identical bar
@KADJ@, and emu_sc_dsp.py already checks the A/B detour encodings.
"""
import pathlib, re, struct, subprocess, sys
import sc_tables

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_HOST = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_host"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
MODMAP = ROOT / "refs/octabam/tools/build/dsp_modmap.py"
SRC = ROOT / "tools/patch_sc_dsp3.asm"
SCRATCH = ROOT / "out/dsp"
RTS_ADDR = 0

# default: throwaway placement of the cave over stock payload B (isolation test).
# --patched: regenerate payload B's .mem from out/mainos_sidechain3.bin -- the
#   cave is over the real donor and the three detours are live.
PATCHED = "--patched" in sys.argv
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
KB_BASE = 0x800
Q23 = 1 << 23
NW = 30                                 # dsp_host caps n7 at 15 frames = 30 words

fails = []
GAIN_T = sc_tables.gain_table()
FLT_T = sc_tables.flt_table()


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
        txt = SRC.read_text().replace("@KADJ@", "sub     #1,a") \
                             .replace("@GTAB@", f"${gt:x}").replace("@FTAB@", f"${ft:x}") \
                             .replace("@LPEDGE@", f"${sc_tables.lp_edge():x}") \
                             .replace("@HPEDGE@", f"${sc_tables.hp_edge():x}")
        a = SCRATCH / "sc3_test.asm"; a.write_text(txt)
        o = SCRATCH / "sc3_test.bin"
        sh(DSP_ASM, "-in", a, "-org", f"{CAVE_ORG:x}", "-out", o)
        raw = o.read_bytes()
        return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]

    code = build(CAVE_ORG, CAVE_ORG)
    n = len(code)
    gtab_off, ftab_off = n, n + sc_tables.GAIN_N
    code = build(CAVE_ORG + gtab_off, CAVE_ORG + ftab_off)
    assert len(code) == n, "code size shifted between sizing passes"
    words = code + GAIN_T + FLT_T
    total = len(words)
    if total > 1063:
        sys.exit(f"cave {total} words > SPRING REVERB donor's 1063")
    # rts positions delimit the three routines. scdet now has THREE internal
    # rts (zz16's, zz20's, and zz18's -- the shared OFF-publish sub zz17/zz20
    # both `jsr` into, added to reclaim word budget for moncommit's exact-
    # match fix): rts[0] = sctap's own, rts[3] = zz18's (last in source order,
    # so moncommit/HOOK 3 starts right after it). See build_sidechain3.py's
    # matching comment.
    rts = [i for i, w in enumerate(words[:n]) if w == 0x00000c]
    sctap, scdet, sctail = CAVE_ORG, CAVE_ORG + rts[0] + 1, CAVE_ORG + rts[3] + 1
    global RTS_ADDR
    RTS_ADDR = CAVE_ORG + rts[0]                       # sctap's own rts -- a safe -init
    # round-trip sanity on the code region
    (SCRATCH / "sc3_code.bin").write_bytes(b"".join(w.to_bytes(3, "little") for w in words[:n]))
    d = sh(DIS, "-in", SCRATCH / "sc3_code.bin", "-pc", f"{CAVE_ORG:x}", "-le")
    if " dc " in d or "InvalidInstruction" in d or "mpysu" in d or "macsu" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    return words, sctap, scdet, sctail, gtab_off, ftab_off


def ensure_patched_mem(words):
    """--patched: build payload B's .mem from out/mainos_sidechain3.bin (octabam's
    dsp_modmap only dumps the stock image, so replicate its dumpmem here), then
    assert the cave + the three jsr detours landed as build_sidechain3.py wrote."""
    import importlib.util
    imgp = ROOT / "out/mainos_sidechain3.bin"
    if not imgp.exists():
        sys.exit("run tools/build_sidechain3.py first (out/mainos_sidechain3.bin missing)")
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
    # opcode half, build_sidechain3.py) -- was `w >> 12 == 0x0D0` (jsr_short's
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


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def close(a, b, tol):
    return all(abs(s24(x) - s24(y)) <= tol for x, y in zip(a, b))


# ---- python reference models -------------------------------------------------
def ref_gain(src, kgain):
    idx = kgain >> 3
    g = GAIN_T[idx]
    out = []
    for s in src:
        acc = (s24(g) * s24(s) * 128) >> 24   # mpy (frac, <<1) then asl #6, take a1
        out.append(max(-Q23, min(Q23 - 1, acc)) & 0xFFFFFF)
    return out


def a_for_kflt(kflt):
    """mirrors the .asm's own idx-calc + edge-override dispatch exactly:
    KFLT<64 -> LP (idx = KFLT>>1, idx==31 -> LP_EDGE instead of FLT_T[31]);
    KFLT>64 -> HP (idx = (KFLT-64)>>1, idx==0 -> HP_EDGE instead of FLT_T[0]).
    Returns (a_coefficient, is_lp)."""
    if kflt < 64:
        idx = kflt >> 1
        a = sc_tables.lp_edge() if idx == 31 else FLT_T[idx]
        return a, True
    idx = (kflt - 64) >> 1
    a = sc_tables.hp_edge() if idx == 0 else FLT_T[idx]
    return a, False


def ref_onepole(src, kflt, tracker=0):
    """mono-sum (L+R)/2, one-pole EMA tracker (Session 76 continued, 3rd
    pass): tracker += a*(in-tracker); LP output = tracker, HP output =
    in-tracker. Replaces the old 2-pole Chamberlin SVF -- see
    patch_sc_dsp3.asm's KEY FLT header for why (coefficient-weighted
    feedback: at a's Q23 ceiling the tracker becomes literally `in`, no
    history dependence at all -- unlike the old SVF, whose `hp = in - lp -
    2*bp` used state unweighted, so stale state always mattered regardless
    of coefficient). src is interleaved L/R; returns interleaved, same
    length, plus the final tracker value (state-persistence checks)."""
    a, is_lp = a_for_kflt(kflt)
    a = s24(a)
    out = list(src)
    for k in range(0, len(src) - 1, 2):
        inp = (s24(src[k]) + s24(src[k + 1])) >> 1
        diff = inp - tracker
        tracker = tracker + ((a * diff) >> 23)
        o = tracker if is_lp else (inp - tracker)
        o = max(-Q23, min(Q23 - 1, o)) & 0xFFFFFF
        out[k] = out[k + 1] = o
    return out, tracker


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

    probe = base_mem(words, scdet, sctail, False, None, None)
    r7 = r7_of(probe)
    FF, S16, S18 = r7 + 0xf, r7 + 0x16, r7 + 0x18
    print(f"r7 = X:0x{r7:05x}   first-block gate X:0x{FF:05x}   "
          f"tracker state X:0x{S16:05x}   our own seed latch X:0x{S18:05x}\n")

    MARK = [((0x10 + i) << 12) | 0xABC for i in range(0x20)]
    KEYV, K = 1, 0                       # KEY=1 -> abs track 0 (CORE_BASE 0)
    SLOT = KB_BASE + K * 0x80
    pk = ",".join(f"{SLOT + i:x}={MARK[i]:x}" for i in range(0x20))

    def P(key=0, kflt=64, kgain=64, mon=0):
        return f"0,0,0,0,0,0,0,0,{key},{kflt},{kgain},{mon}"

    # 1. stage copy (step-2 regression) ------------------------------------
    print("copy / KEY select:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0xBEEF] * 0x20)], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV), pokey=pk, audio=0)
    check("KEY=1: X:$40 == keybus[0]", x40 == MARK, f"got[:3]={[hex(v) for v in x40[:3]]}")
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=0), pokey=pk, audio=0)
    check("KEY=0: X:$40 untouched", all(v == 0xBEEF for v in x40))

    # 2. KEY GAIN ---------------------------------------------------------
    print("\nKEY GAIN:")
    for kgain in (64, 88, 40, 120, 0):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kgain=kgain), pokey=pk, audio=0)
        exp = list(MARK) if kgain == 64 else ref_gain(MARK, kgain)
        db = (((kgain >> 3) * 8) - 64) * 0.375
        check(f"KGAIN {kgain:3d} ({db:+.0f} dB)", close(x40, exp, 2),
              f"got[:2]={[hex(v) for v in x40[:2]]} exp[:2]={[hex(v) for v in exp[:2]]}")

    # 3. KEY FLT --------------------------------------------------------
    print("\nKEY FLT (numeric vs python one-pole tracker):")
    sig = sine(0x20, 3)                 # 3 cycles over the 16-frame block
    pk_sig = ",".join(f"{SLOT + i:x}={sig[i]:x}" for i in range(0x20))
    for kflt, tag in ((64, "bypass"), (10, "LP idx5"), (40, "LP idx20"),
                      (78, "HP idx7"), (120, "HP idx28"),
                      (60, "LP idx30 (one step in)"), (62, "LP idx31 (edge override)"),
                      (65, "HP idx0 (edge override)"), (67, "HP idx1 (one step in)")):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                       [(1, S18, [0])])         # fresh: our own seed latch = 0
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig, audio=0)
        if kflt == 64:
            exp = sig
        else:
            exp, _ = ref_onepole(sig, kflt)
        check(f"KFLT {kflt:3d} {tag:24s}", close(x40[:NW], exp[:NW], 3),
              f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp[:4]]}")

    # 3a. split-block regression (Session 74, NOTES.md): a mid-block trig sets
    # n7 to the segment length (x:0x20c/x:0x20d in the real dispatcher, both
    # < 16), NOT the full 16-sample block -- the fix makes this loop's own
    # trip count a fixed `#<$10`, independent of whatever n7 the caller sets.
    # Prove that directly: call scdet with `-frames` set LOW (dsp_host loads
    # n7 from it, same mechanism the real dispatcher's split path uses) and
    # confirm ALL 16 pairs still come out filtered -- comparing the FULL
    # 32-word dump against ref_onepole's full output, not the NW=30 truncation
    # the other checks above use (that truncation exists to work around
    # dsp_host's own "-frames" cap at 15, unrelated to this loop's own
    # trip count now that it no longer reads n7 at all).
    print("\nKEY FLT split-block regression (n7 must NOT bound this loop):")
    kflt = 40
    exp_full, _ = ref_onepole(sig, kflt)
    for short_n7 in (1, 6, 14):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                       [(1, S18, [0])])
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt),
                     pokey=pk_sig, frames=short_n7, audio=0)
        check(f"n7={short_n7:2d} at call time -> all 16 pairs still filtered",
              close(x40, exp_full, 3),
              f"last pair got={[s24(v) for v in x40[30:32]]} "
              f"exp={[s24(v) for v in exp_full[30:32]]}")

    # 3b. dirty-state regression: stock's own "first-block" bit ($f) falsely
    # warm (as it can be from ordinary stock activity before our KEY FLT code
    # has ever run) + garbage sitting in $16, but OUR OWN latch ($18) is
    # still 0 -- must still cold-start (tracker=0), NOT read the garbage.
    print("\nKEY FLT dirty-state guard (our own latch, not stock's $f):")
    kflt = 40
    exp_cold, _ = ref_onepole(sig, kflt)
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, FF, [1]),                     # stock bit falsely "warm"
                    (1, S16, [0x7fffff]),               # garbage
                    (1, S18, [0])])                    # our latch: never seeded
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig, audio=0)
    check("$f warm + garbage $16, $18=0 -> still cold-starts",
          close(x40[:NW], exp_cold[:NW], 3),
          f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp_cold[:4]]}")

    # 4. tracker state persistence (block 2 continues, no reset) -----------
    print("\nKEY FLT state persistence:")
    kflt = 24
    exp1, tr1 = ref_onepole(sig, kflt)
    exp2, _ = ref_onepole(sig, kflt, tr1)
    mem = base_mem(words, scdet, sctail, False,
                   [(1, 0x40, [0] * 0x20), (1, S18, [1]),          # our latch: warm
                    (1, S16, [tr1 & 0xFFFFFF])], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig, audio=0)
    check("block 2 continues the tracker", close(x40[:NW], exp2[:NW], 3),
          f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp2[:4]]}")

    # 4b. UNCONDITIONAL STABILITY (Session 76 continued, 3rd pass): the old
    # 2-pole Chamberlin SVF needed a hardware-forced q=2 damping (Session 64)
    # specifically because a 2-pole system CAN resonate for some parameter
    # choice -- the old version of this check proved q=2 kept every FTAB
    # entry's poles real (non-oscillating) by discriminant. A one-pole
    # tracker has exactly ONE pole, at (1-a): a single real pole can never
    # form a complex-conjugate pair, so it structurally cannot resonate --
    # there is no discriminant to satisfy, no q to tune, and Session 64's
    # ringing bug cannot recur here by construction, not by a tuned margin.
    # What CAN still go wrong: a coefficient outside [0, Q23 ceiling] would
    # make the pole magnitude |1-a| exceed 1 -> genuine instability (not
    # coloration, a diverging filter) -- check every FTAB entry AND both
    # edge overrides are in range, protecting against exactly the mistake
    # that blocked pushing the OLD SVF's LP edge toward transparent (its
    # q=2 pole went unstable well before reaching a useful cutoff; this
    # topology has no such ceiling, which is WHY LP_EDGE can target the Q23
    # ceiling directly instead of a compromise value).
    print("\nKEY FLT unconditional stability (a in [0, Q23] for every coefficient):")
    all_ok = True
    for idx in range(sc_tables.FLT_N):
        a = FLT_T[idx]
        if not (0 <= a < Q23):
            all_ok = False
    for name, a in (("LP_EDGE", sc_tables.lp_edge()), ("HP_EDGE", sc_tables.hp_edge())):
        if not (0 <= a < Q23):
            all_ok = False
    check(f"all {sc_tables.FLT_N} FTAB entries + LP_EDGE/HP_EDGE give |pole|=|1-a|<=1",
          all_ok, f"LP_EDGE=0x{sc_tables.lp_edge():06x} HP_EDGE=0x{sc_tables.hp_edge():06x}")

    # 5. SC LISTEN stash (scdet -> keybus gen 1) --------------------------
    print("\nSC LISTEN:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], [(1, S18, [0])])
    (x40, g1) = run(mem, scdet, [('x', 0x40, 0x60), ('y', SLOT + 0x20, SLOT + 0x40)],
                    P(key=KEYV, kflt=40, mon=1), pokey=pk_sig, audio=0)
    check("MON=1: keybus[0] gen1 == processed X:$40", g1 == x40,
          f"g1[:3]={[hex(v) for v in g1[:3]]} x40[:3]={[hex(v) for v in x40[:3]]}")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], [(1, S18, [0])])
    (g1,) = run(mem, scdet, [('y', SLOT + 0x20, SLOT + 0x40)], P(key=KEYV, mon=0), pokey=pk_sig, audio=0)
    check("MON=0: keybus[0] gen1 untouched", all(v == 0 for v in g1))

    # 6. MON publish (scdet -> MON_ON[my track]/MON_KEY[my track], Y:0x800+
    #    track*0x80+0x40/0x41 -- the moncommit hook's only input) ------------
    print("\nMON publish (scdet -> MON_ON/MON_KEY for moncommit):")
    MYTRACK = 3
    MON_ADDR = KB_BASE + MYTRACK * 0x80 + 0x40   # this track's own dead gen-2 slot
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [0xdead, 0xdead])])
    (pub,) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2)], P(key=KEYV, mon=1), pokey=pk_sig, audio=0)
    # MON_ON is only ever gated by `tst` (nonzero = on) in moncommit, never
    # compared for an exact value -- `move #1,b`'s short-immediate encoding
    # is left-aligned (this file's own documented dsp_asm quirk, q2) and
    # actually loads 0x10000, not 1. Harmless (still nonzero) -- left as-is,
    # matching moncommit's own compensating exact-match check against
    # $10000, not because the cave is still short on words (Session 76
    # continued: the SPRING REVERB donor swap left ~800 words of slack).
    check("MON=1: MON_ON!=0, MON_KEY==key track", pub[0] != 0 and pub[1] == K,
          f"got={pub}")

    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [1, K])])
    (pub,) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2)], P(key=KEYV, mon=0), pokey=pk_sig, audio=0)
    check("MON=0: MON_ON published OFF", pub[0] == 0, f"got={pub}")

    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, 0x420, [MYTRACK]), (2, MON_ADDR, [1, K])])
    (pub,) = run(mem, scdet, [('y', MON_ADDR, MON_ADDR + 2)], P(key=0, mon=1), pokey=pk_sig, audio=0)
    check("KEY=0: MON_ON published OFF (even with MON=1)", pub[0] == 0, f"got={pub}")

    print()
    if fails:
        print(f"FAIL -- {len(fails)}: " + ", ".join(fails)); sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

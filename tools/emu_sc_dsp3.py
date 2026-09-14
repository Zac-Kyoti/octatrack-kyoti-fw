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
new stages here (KEY GAIN scaler, 2-pole KEY FLT, SC LISTEN stash) are pure
data transforms and ARE checked numerically against a Python reference:

  copy    KEY!=0, KFLT/KGAIN neutral  -> X:$40 == keybus[k]   (step-2 regression)
  KEY=0                               -> X:$40 untouched
  KEY GAIN  KGAIN != 64               -> X:$40 == keybus[k] * gain_table[idx]
  KEY FLT LP / HP                     -> X:$40 == python_svf(keybus[k], f_table[idx])
  KEY FLT bypass (KFLT == 64)         -> X:$40 == keybus[k]
  state persistence (block 2)         -> continues the python SVF, no reset
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
MODMAP = ROOT / "refs/octabam/tools/dsp_modmap.py"
SRC = ROOT / "tools/patch_sc_dsp3.asm"
SCRATCH = ROOT / "out/dsp"
RTS_ADDR = 0

# default: throwaway placement of the cave over stock payload B (isolation test).
# --patched: regenerate payload B's .mem from out/mainos_sidechain3.bin -- the
#   cave is over the real SPATIALIZER donor and the three `jsr` detours are live.
PATCHED = "--patched" in sys.argv
if PATCHED:
    MEM_B = SCRATCH / "payload_B_sc3.mem"
    CAVE_ORG = 0x868                    # SPATIALIZER P addr, payload B
    COMP_MOD, COMP_PROC, COMP_TAIL = 0x1864, 0x1871, 0x1915
else:
    MEM_B = ROOT / "out/dsp/payload_B.mem"
    CAVE_ORG = 0x1da0
    COMP_MOD, COMP_PROC, COMP_TAIL = 0x1864, 0x1871, 0x1b55
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
                             .replace("@GTAB@", f"${gt:x}").replace("@FTAB@", f"${ft:x}")
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
    if total > 261:
        sys.exit(f"cave {total} words > SPATIALIZER donor's 261")
    # rts positions delimit the three routines
    rts = [i for i, w in enumerate(words[:n]) if w == 0x00000c]
    sctap, scdet, sctail = CAVE_ORG, CAVE_ORG + rts[0] + 1, CAVE_ORG + rts[2] + 1
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
    cmod = next(m for m in mods if m[0] == 0 and m[1] == COMP_MOD)
    for off, nm in ((COMP_PROC, "scdet"), (COMP_TAIL, "sctail")):
        w = cmod[2][off - COMP_MOD]
        if w >> 12 != 0x0D0:
            sys.exit(f"--patched: COMPRESSOR P:0x{off:x} is 0x{w:06x}, not `jsr` to the cave")
    print(f"  --patched: cave + scdet/sctail detours verified against {imgp.name}")


def r7_of(mem):
    """run a no-op proc once, parse the instance line for r7."""
    out = sh(DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{RTS_ADDR:x}",
             "-frames", "15", "-blocks", "1")
    m = re.search(r"r7 = X:0x([0-9a-fA-F]+)", out)
    if not m:
        sys.exit(f"could not parse r7 from:\n{out}")
    return int(m.group(1), 16)


def base_mem(words, scdet, sctail, patch_tail, xseed, yseed):
    mods = load_mem(MEM_B)
    if not PATCHED:
        for m in mods:
            if m[0] == 0 and m[1] == COMP_MOD:
                i = COMP_PROC - COMP_MOD
                assert (m[2][i], m[2][i + 1]) == (0x221e00, 0x346100), \
                    f"comp proc+0 not [move r0,n6 ; move #61,r4]: {m[2][i]:06x} {m[2][i+1]:06x}"
                m[2][i], m[2][i + 1] = 0x0bf080, scdet         # jsr scdet (long, test only)
                if patch_tail:
                    j = COMP_TAIL - COMP_MOD
                    assert (m[2][j], m[2][j + 1]) == (0x0a77a0, 0x00000f), \
                        f"comp proc-end not `move m0,x:(r7+$f)`: {m[2][j]:06x} {m[2][j+1]:06x}"
                    m[2][j], m[2][j + 1] = 0x0bf080, sctail    # jsr sctail
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


def run(mem, proc, dumps, params, pokey=None):
    """dumps: list of ('x'|'y', lo, hi). One dsp_host run per dump."""
    res = []
    for i, (sp, lo, hi) in enumerate(dumps):
        df = SCRATCH / f"sc3_d{i}.bin"
        a = [DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{proc:x}",
             "-frames", "15", "-blocks", "1", "-params", params,
             "-dumpy", f"{'@' if sp == 'x' else ''}{df},{lo:x},{hi:x}"]
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


def ref_svf(src, kflt, lp=0, bp=0):
    """mono-sum (L+R)/2, one-pole-pair Chamberlin SVF, q=1, dup L/R.
    src is interleaved L/R; returns interleaved, same length."""
    if kflt < 64:
        idx, is_lp = kflt >> 1, True
    else:
        idx, is_lp = (kflt - 64) >> 1, False
    f = s24(FLT_T[idx])
    out = list(src)
    for k in range(0, len(src) - 1, 2):
        inp = (s24(src[k]) + s24(src[k + 1])) >> 1
        lp = lp + ((f * bp) >> 23)
        hp = inp - lp - bp
        bp = bp + ((f * hp) >> 23)
        o = lp if is_lp else hp
        o = max(-Q23, min(Q23 - 1, o)) & 0xFFFFFF
        out[k] = out[k + 1] = o
    return out, lp, bp


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
    FF, S16, S17, S18 = r7 + 0xf, r7 + 0x16, r7 + 0x17, r7 + 0x18
    print(f"r7 = X:0x{r7:05x}   first-block gate X:0x{FF:05x}   "
          f"SVF state X:0x{S16:05x}/0x{S17:05x}   our own seed latch X:0x{S18:05x}\n")

    MARK = [((0x10 + i) << 12) | 0xABC for i in range(0x20)]
    KEYV, K = 1, 0                       # KEY=1 -> abs track 0 (CORE_BASE 0)
    SLOT = KB_BASE + K * 0x80
    pk = ",".join(f"{SLOT + i:x}={MARK[i]:x}" for i in range(0x20))

    def P(key=0, kflt=64, kgain=64, mon=0):
        return f"0,0,0,0,0,0,0,0,{key},{kflt},{kgain},{mon}"

    # 1. stage copy (step-2 regression) ------------------------------------
    print("copy / KEY select:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0xBEEF] * 0x20)], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV), pokey=pk)
    check("KEY=1: X:$40 == keybus[0]", x40 == MARK, f"got[:3]={[hex(v) for v in x40[:3]]}")
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=0), pokey=pk)
    check("KEY=0: X:$40 untouched", all(v == 0xBEEF for v in x40))

    # 2. KEY GAIN ---------------------------------------------------------
    print("\nKEY GAIN:")
    for kgain in (64, 88, 40, 120, 0):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], None)
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kgain=kgain), pokey=pk)
        exp = list(MARK) if kgain == 64 else ref_gain(MARK, kgain)
        db = (((kgain >> 3) * 8) - 64) * 0.375
        check(f"KGAIN {kgain:3d} ({db:+.0f} dB)", close(x40, exp, 2),
              f"got[:2]={[hex(v) for v in x40[:2]]} exp[:2]={[hex(v) for v in exp[:2]]}")

    # 3. KEY FLT --------------------------------------------------------
    print("\nKEY FLT (numeric vs python SVF):")
    sig = sine(0x20, 3)                 # 3 cycles over the 16-frame block
    pk_sig = ",".join(f"{SLOT + i:x}={sig[i]:x}" for i in range(0x20))
    for kflt, tag in ((64, "bypass"), (10, "LP idx5"), (40, "LP idx20"),
                      (78, "HP idx7"), (120, "HP idx28")):
        mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                       [(1, S18, [0])])         # fresh: our own seed latch = 0
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig)
        if kflt == 64:
            exp = sig
        else:
            exp, _, _ = ref_svf(sig, kflt)
        check(f"KFLT {kflt:3d} {tag:9s}", close(x40[:NW], exp[:NW], 3),
              f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp[:4]]}")

    # 3b. dirty-state regression: stock's own "first-block" bit ($f) falsely
    # warm (as it can be from ordinary stock activity before our KEY FLT code
    # has ever run) + garbage sitting in $16/$17, but OUR OWN latch ($18) is
    # still 0 -- must still cold-start (lp=bp=0), NOT read the garbage.
    print("\nKEY FLT dirty-state guard (our own latch, not stock's $f):")
    kflt = 40
    exp_cold, _, _ = ref_svf(sig, kflt)
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)],
                   [(1, FF, [1]),                     # stock bit falsely "warm"
                    (1, S16, [0x7fffff]), (1, S17, [0x7fffff]),   # garbage
                    (1, S18, [0])])                    # our latch: never seeded
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig)
    check("$f warm + garbage $16/$17, $18=0 -> still cold-starts",
          close(x40[:NW], exp_cold[:NW], 3),
          f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp_cold[:4]]}")

    # 4. SVF state persistence (block 2 continues, no reset) ---------------
    print("\nKEY FLT state persistence:")
    kflt = 24
    exp1, lp1, bp1 = ref_svf(sig, kflt)
    exp2, _, _ = ref_svf(sig, kflt, lp1, bp1)
    mem = base_mem(words, scdet, sctail, False,
                   [(1, 0x40, [0] * 0x20), (1, S18, [1]),          # our latch: warm
                    (1, S16, [lp1 & 0xFFFFFF]), (1, S17, [bp1 & 0xFFFFFF])], None)
    (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], P(key=KEYV, kflt=kflt), pokey=pk_sig)
    check("block 2 continues the SVF", close(x40[:NW], exp2[:NW], 3),
          f"got[:4]={[s24(v) for v in x40[:4]]} exp[:4]={[s24(v) for v in exp2[:4]]}")

    # 5. SC LISTEN stash (scdet -> keybus gen 1) --------------------------
    print("\nSC LISTEN:")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], [(1, S18, [0])])
    (x40, g1) = run(mem, scdet, [('x', 0x40, 0x60), ('y', SLOT + 0x20, SLOT + 0x40)],
                    P(key=KEYV, kflt=40, mon=1), pokey=pk_sig)
    check("MON=1: keybus[0] gen1 == processed X:$40", g1 == x40,
          f"g1[:3]={[hex(v) for v in g1[:3]]} x40[:3]={[hex(v) for v in x40[:3]]}")
    mem = base_mem(words, scdet, sctail, False, [(1, 0x40, [0] * 0x20)], [(1, S18, [0])])
    (g1,) = run(mem, scdet, [('y', SLOT + 0x20, SLOT + 0x40)], P(key=KEYV, mon=0), pokey=pk_sig)
    check("MON=0: keybus[0] gen1 untouched", all(v == 0 for v in g1))

    print()
    if fails:
        print(f"FAIL -- {len(fails)}: " + ", ".join(fails)); sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

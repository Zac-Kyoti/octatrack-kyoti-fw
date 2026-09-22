#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Isolation check of the step-2 side-chain DSP hooks (tools/patch_sc_dsp.asm)
under octabam's dsp_host / dsp56kEmu.

dsp_host's generic ABI setup does NOT correctly run the *stock* COMPRESSOR
(it targets octabam's own effects: r7 lands at 0x200, tables aside).  So we
don't run the whole compressor here -- we run each hook AS its own -proc
entry, with the entry conditions seeded into the .mem, and read back exactly
what the hook produced:

  sctap : seed X:0 with 32 marker words + x:$420 = <idx>.  Run sctap.
          Assert Y:($800 + idx*$80 .. +$20) == the markers, nothing else touched.
  scdet : seed Y:keybus[k] with markers + x:(r6+$d) = KEY<<16.  Run scdet.
          KEY != 0 -> assert X:$40..$60 == keybus[k] markers (detector redirected).
          KEY == 0 -> assert X:$40..$60 untouched (stock self-detection).

The compressor's own detour byte-patch (jsr scdet over move r0,n6 ; move #$61,r4)
is asserted here against the real payload-B module, so the wiring is checked
even though the end-to-end audio is a hardware test.
"""
import pathlib, struct, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_HOST = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_host"
SRC = ROOT / "tools/patch_sc_dsp.asm"
SCRATCH = ROOT / "out/dsp"

# default: build a throwaway placement over stock payload B (cave at 0x1da0).
# --patched: use the real build (out/dsp/payload_B_patched.mem, cave at SPATIALIZER 0x868).
PATCHED = "--patched" in sys.argv
MEM_B = ROOT / ("out/dsp/payload_B_patched.mem" if PATCHED else "out/dsp/payload_B.mem")
CAVE_ORG = 0x868 if PATCHED else 0x1da0
COMP_MOD, COMP_PROC = 0x1864, 0x1871
KB_BASE = 0x800

fails = []


def sh(*a):
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"cmd failed: {' '.join(map(str,a))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def load_mem(p):
    b = p.read_bytes(); off = 0; mods = []
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


def assemble(kadj):
    a = SCRATCH / "sc_test.asm"
    a.write_text(SRC.read_text().replace("@KADJ@", kadj))
    o = SCRATCH / "sc_test.bin"
    sh(DSP_ASM, "-in", a, "-org", f"{CAVE_ORG:x}", "-out", o)
    raw = o.read_bytes()
    return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]


def label_addr(kadj, name):
    """assemble with -list and pull a label's address."""
    a = SCRATCH / "sc_test.asm"
    a.write_text(SRC.read_text().replace("@KADJ@", kadj))
    out = sh(DSP_ASM, "-in", a, "-org", f"{CAVE_ORG:x}", "-list")
    # -list prints "addr: text ; hex" per line; labels are the .asm labels.
    # simpler: reproduce the two-pass sizing here from the disasm of the blob.
    return None


def base_mem(cave, xseed=None, yseed=None):
    mods = load_mem(MEM_B)
    if PATCHED:
        # the real build already has the cave over SPATIALIZER + the jsr detour.
        for m in mods:
            if m[0] == 0 and m[1] == COMP_MOD:
                i = COMP_PROC - COMP_MOD
                assert m[2][i] == (0x0D0000 | (CAVE_ORG + scdet_addr(cave) - CAVE_ORG)), \
                    f"patched compressor proc+0 not jsr scdet: {m[2][i]:06x}"
    else:
        for m in mods:
            if m[0] == 0 and m[1] == COMP_MOD:
                i = COMP_PROC - COMP_MOD
                assert (m[2][i], m[2][i + 1]) == (0x221e00, 0x346100), \
                    f"compressor proc+0 not [move r0,n6 ; move #61,r4]: {m[2][i]:06x} {m[2][i+1]:06x}"
                m[2][i], m[2][i + 1] = 0x0bf080, CAVE_ORG      # jsr scdet (long, test only)
                break
        mods.append([0, CAVE_ORG, list(cave)])
    for sp, addr, words in (xseed or []):
        mods.append([sp, addr, list(words)])
    m = SCRATCH / "sc_iso.mem"
    save_mem(m, mods)
    return m


RTS_ADDR = 0        # set in main() to an address holding a bare rts (harmless -init)


def run(mem, proc, ranges, pokey=None, params=None):
    """ranges: list of (space 'x'|'y', lo, hi).  One dsp_host run per range
    (dumpy takes one).  Returns list of word-lists."""
    res = []
    for i, (sp, lo, hi) in enumerate(ranges):
        df = SCRATCH / f"sc_dump{i}.bin"
        a = [DSP_HOST, "-mem", mem, "-init", f"{RTS_ADDR:x}", "-proc", f"{proc:x}",
             "-frames", "15", "-blocks", "1",
             "-dumpy", f"{'@' if sp == 'x' else ''}{df},{lo:x},{hi:x}"]
        if pokey:
            a += ["-pokey", pokey]
        if params:
            a += ["-params", params]
        sh(*a)
        raw = df.read_bytes()
        res.append([int.from_bytes(raw[j:j + 4], "little") for j in range(0, len(raw), 4)])
    return res


def scdet_addr(cave):
    # scdet is the 2nd routine: it starts right after sctap's rts.
    for i, w in enumerate(cave):
        if w == 0x00000c:                     # first rts -> end of sctap
            return CAVE_ORG + i + 1
    sys.exit("no rts in cave")


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


MARK = [((0x10 + i) << 12) | 0xABC for i in range(0x20)]   # 32 distinct 24-bit markers


def main():
    for t in (DSP_ASM, DSP_HOST, MEM_B):
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t}")

    global RTS_ADDR
    cave = assemble("sub     #1,a")        # payload B, CORE_BASE 0
    scdet = scdet_addr(cave)
    RTS_ADDR = scdet - 1                   # sctap's rts -- a harmless -init target
    print(f"cave {len(cave)}w @ P:0x{CAVE_ORG:x}   sctap=0x{CAVE_ORG:x}  scdet=0x{scdet:x}  rts=0x{RTS_ADDR:x}\n")

    # ---- sctap: whatever ends up in X:0, keybus[x:$420] must equal it ----
    #  (dsp_host stamps params into X:6..$b / X:$12.. before proc runs, so we
    #   compare keybus against the POST-run X:0, not our pre-seed.)
    print("sctap -- publish tap:")
    for idx in (0, 3, 7):
        mem = base_mem(cave, xseed=[(1, 0x000, MARK), (1, 0x420, [idx])])
        (x0, ring) = run(mem, CAVE_ORG, [('x', 0x000, 0x020), ('y', KB_BASE, KB_BASE + 0x400)])
        slot = idx * 0x80
        got = ring[slot:slot + 0x20]
        others = [v for j, v in enumerate(ring) if not (slot <= j < slot + 0x20)]
        check(f"idx {idx}: keybus[{idx}] == X:0 (32 words)", got == x0,
              f"keybus[:3]={[hex(v) for v in got[:3]]}  x0[:3]={[hex(v) for v in x0[:3]]}")
        check(f"idx {idx}: rest of ring untouched", all(v == 0 for v in others))

    # ---- scdet: keybus[k] markers (pokey, Y is not stamped) + KEY via -params
    #      -> X:$40 == keybus[k]  (KEY!=0)  or untouched  (KEY==0) ----
    print("\nscdet -- detector redirect:")
    for key, k in ((0, 0), (1, 0), (4, 3)):
        pk = ",".join(f"{KB_BASE + k*0x80 + i:x}={MARK[i]:x}" for i in range(0x20))
        mem = base_mem(cave, xseed=[(1, 0x040, [0xDEAD] * 0x20)])
        params = "0,0,0,0,0,0,0,0,%d" % key          # index 8 -> pblock+$d bits 16-23 = KEY
        (x40,) = run(mem, scdet, [('x', 0x40, 0x60)], pokey=pk, params=params)
        if key == 0:
            check("KEY=0: X:$40 untouched (stock self-detect)", all(v == 0xDEAD for v in x40),
                  f"got[:3]={[hex(v) for v in x40[:3]]}")
        else:
            check(f"KEY={key}: X:$40 == keybus[{k}]", x40 == MARK,
                  f"got[:3]={[hex(v) for v in x40[:3]]}")

    print()
    if fails:
        print(f"FAIL -- {len(fails)}: " + ", ".join(fails)); sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()

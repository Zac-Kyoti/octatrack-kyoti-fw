#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
SIDE-CHAIN's tap (`sctap`, tools/patch_sc_dsp3.asm) under dsp_host, payload B's tokens.

emu_sc_dsp3.py tests the detector and MON; this tests the hook that runs for every track
every block. A wrapper at P:$1f00 (above payload B's code) runs NBLK blocks of the core's
four local tracks: each call fills X:0..$1f with the next words of a counter that crosses
$800000 (so negative words go through the accumulator moves), sets x:$420 to the absolute
track and calls sctap. Then all of internal Y and the shared window are dumped.

Checks:
  model  the keybus slot of each track (gen 0) holds its last block; the cross-core window
         slot (SBASE + (local*4 + gen)*$20) holds the last block of each generation; GSEED is
         the $10000 sentinel and GCNT the last generation; no other Y word differs from a run
         of the same wrapper with sctap's call left out.
  --ref REV  the same wrapper against sctap as assembled from REV's patch_sc_dsp3.asm (e.g.
         a commit before a change to sctap): every Y word equal, the keybus compared at each
         version's own address.
"""
import pathlib, struct, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import emu_sc_dsp3 as E                      # noqa: E402  (its assembler, paths and .mem I/O)

WRAP = 0x1f00
NBLK = 6
DONE = 0x6f00                                # a Y flag: the wrapper runs its sequence once
COREBASE, SBASE, GCNT, GSEED = 0, 0x3be00, 0x3bdff, 0x3bdfe
SEED = 0x7fff80


def keybus_base(src):
    if "@KEYB@" in src:                     # a build token (2026-10-16): emu_sc_dsp3's layout
        return E.KB_BASE
    import re
    m = re.search(r"slot\(track\) = \$([0-9a-f]+) \+ track\*\$40", src)
    return int(m.group(1), 16)


def assemble_sc(src):
    """sctap..moncommit as emu_sc_dsp3.assemble() builds it, from source text `src`."""
    orig = E.SRC.read_text
    E.SRC = type("S", (), {"read_text": staticmethod(lambda: src)})()
    try:
        return E.assemble()
    finally:
        E.SRC = pathlib.Path(ROOT / "tools/patch_sc_dsp3.asm")


def wrapper(call):
    txt = f"""
wrap:
        move    #>${DONE:x},r1
        move    y:(r1),a
        tst     a
        bne     wdone
        move    #>1,a
        move    a,y:(r1)
        move    #>${SEED:x},r5
        do      #{NBLK},wblk
        move    #0,r2
        do      #4,wtrk
        move    #0,r0
        do      #<$20,wfill
        move    r5,x:(r0)+
        move    (r5)+
wfill:
        move    r2,a
        add     #>{COREBASE},a
        move    a,x:>$420
        {"move    #>$%x,r3\n        jsr     (r3)" % E.CAVE_ORG if call else "nop\n        nop"}
        move    (r2)+
wtrk:
        nop
wblk:
        nop
wdone:
        rts
"""
    with tempfile.TemporaryDirectory() as td:
        a = pathlib.Path(td) / "w.asm"; a.write_text(txt)
        o = pathlib.Path(td) / "w.bin"
        E.sh(E.DSP_ASM, "-in", a, "-org", f"{WRAP:x}", "-out", o)
        raw = o.read_bytes()
    return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]


def run(words, call):
    mods = E.load_mem(E.MEM_B)
    mods.append([0, E.CAVE_ORG, list(words)])
    mods.append([0, WRAP, wrapper(call)])
    m = E.SCRATCH / "sctap_test.mem"
    E.save_mem(m, mods)
    out = {}
    for name, (sp, lo, hi) in {"y": ("y", 0, 0xc000), "w": ("y", 0x30000, 0x40000)}.items():
        df = E.SCRATCH / f"sctap_{name}.bin"
        E.sh(E.DSP_HOST, "-mem", m, "-init", f"{E.RTS_ADDR:x}", "-proc", f"{WRAP:x}",
             "-frames", "15", "-blocks", "1", "-dumpy", f"{df},{lo:x},{hi:x}")
        raw = df.read_bytes()
        out[name] = [int.from_bytes(raw[j:j + 4], "little") & 0xffffff for j in range(0, len(raw), 4)]
    return out


def model(kb):
    """{(space, addr): word} that sctap must leave after the wrapper."""
    exp, ctr, gen = {}, SEED, None
    for b in range(NBLK):
        for t in range(4):
            data = [(ctr + i) & 0xffffff for i in range(32)]
            ctr += 32
            if t == 0:
                gen = 0 if gen is None else (gen + 1) & 3
            for i, v in enumerate(data):
                exp[("y", kb + (COREBASE + t) * 0x40 + i)] = v
                exp[("w", SBASE + (t * 4 + gen) * 0x20 + i)] = v
    exp[("w", GSEED)] = 0x10000
    exp[("w", GCNT)] = gen
    return exp


def main():
    ok = True
    src = E.SRC.read_text()
    kb = keybus_base(src)
    words = assemble_sc(src)[0]
    got, base = run(words, True), run(words, False)
    exp = model(kb)
    bad = []
    for sp, lo in (("y", 0), ("w", 0x30000)):
        for i, (g, z) in enumerate(zip(got[sp], base[sp])):
            a = lo + i
            want = exp.get((sp, a), z)
            if g != want:
                bad.append((sp, a, g, want))
    print(f"sctap model, keybus ${kb:x}, {NBLK} blocks x 4 tracks: "
          f"{len(exp)} words expected, {len(bad)} wrong")
    for sp, a, g, w in bad[:10]:
        print(f"  {'Y' if sp == 'y' else 'Y(window)'}:${a:x} = {g:06x}, expected {w:06x}")
    ok &= not bad

    if "--ref" in sys.argv:
        rev = sys.argv[sys.argv.index("--ref") + 1]
        rsrc = subprocess.run(["git", "show", f"{rev}:tools/patch_sc_dsp3.asm"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
        rkb = keybus_base(rsrc) if "slot(track) = $" in rsrc else 0x800
        ref = run(assemble_sc(rsrc)[0], True)
        moved = {a for a in range(0x200)}
        diff = []
        for i in range(0xc000):
            if i - kb in moved or i - rkb in moved:
                continue
            if got["y"][i] != ref["y"][i]:
                diff.append(("y", i))
        for i in range(0x200):
            if got["y"][kb + i] != ref["y"][rkb + i]:
                diff.append(("keybus", i))
        diff += [("w", 0x30000 + i) for i in range(0x10000) if got["w"][i] != ref["w"][i]]
        print(f"against {rev}'s sctap (keybus ${rkb:x}): {len(diff)} Y words differ")
        for d in diff[:10]:
            print("  ", d)
        ok &= not diff

    print("ALL GOOD" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

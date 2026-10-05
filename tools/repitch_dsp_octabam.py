#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
REPITCH_REPEAT98_KYOTI's DSP kernel in octabam's form, generated from the
hardware-tested one (tools/patch_repitch_dsp.asm + tools/repitch_dsp_src.py).

    python3 tools/repitch_dsp_octabam.py          -> writes the two files below
    python3 tools/repitch_dsp_octabam.py --check  -> exit 1 if either is stale

Writes, in octabam-modules/repitch-repeat98-kyoti/:
  rpk_dsp.asm        the kernel, one source for both payloads
  rpk_dsp_ptable.py  PTABLE (145 words: render half-table, cutoff table) and PTABLE2
                     (448: the RPSP and RPS9 half-rows), DspSection.ptable / ptable2

What changes against the standalone kernel (each a text substitution asserted to
apply exactly once; nothing else moves):
  * every `equ` is resolved to a literal -- octabam's dsp_asm has no constants;
  * the tables are TWO blocks, octabam's ptable and ptable2 (sambanks/octabam#603),
    as the standalone splits them across SPRING REVERB's X data: block 1 = the
    render half-table + channel 1/2's cutoff table, block 2 = the RPSP half-rows +
    the RPS9 half-rows (zqinit's r1 runs on from one to the next, as before). The
    source names each base exactly once (octabam's two literals, at zqrp); every
    table read is `p:(rN)`, which octabam keeps in P or rewrites to `x:(rN)` when
    it places a block in the curve bank or a given-up effect's own X data;
  * zqrp loads both bases and runs zqinit when the table tag OR either stored base
    differs (the bases move between remixes; the tag only says the contents);
  * zqinit stores the bases (TABB, TABB2) and the cutoff table's address (TABG)
    in Y and reads its three tables from the blocks; zqsp's per-frame cutoff
    lookup adds TABG instead of an absolute X address.
The XY dual moves with an ALU op stay as the standalone has them: octabam's
assembler gains them (sambanks/octabam#561, Sam Banks, 4 Oct 2026).
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import repitch_dsp_src as dsrc           # noqa: E402

MOD = ROOT / "octabam-modules/repitch-repeat98-kyoti"
OUT_ASM = MOD / "rpk_dsp.asm"
OUT_TAB = MOD / "rpk_dsp_ptable.py"
MARK = "$" + "fab1e0"                   # octabam's ptable literal (kept out of this file's text)
MARK2 = "$" + "fab2e0"                  # ... and ptable2's

# Two Y words above the aux blocks (zqinit zeroes FBASE..FBASE+63), inside the module's
# Y:$A00-$FFF claim.
TABB, TABG, TABB2 = 0xFF0, 0xFF1, 0xFF2


def tables():
    """The two blocks, and each table's offset in its block."""
    sp, _ = dsrc.half_table(dsrc.m.MODE_RPSP)
    r9, _ = dsrc.half_table(dsrc.m.MODE_RPS9)
    bl = dsrc.render_half()
    gt = [w & 0xFFFFFF for w in dsrc.m.ch12_gtab_q23()]
    off = dict(XBL=0, GTAB=len(bl), XSP=0, XR9=len(sp))
    return bl + gt, sp + r9, off


def constants():
    a, b = dsrc.constants("A"), dsrc.constants("B")
    per = {"XSP", "XR9", "XBL", "GTAB"}
    diff = {k for k in a if a[k] != b[k]}
    assert diff == per, f"payload-dependent constants beyond the table addresses: {sorted(diff - per)}"
    c = {k: v for k, v in a.items() if k not in per}
    assert c["FBASE"] + 64 <= min(TABB, TABG, TABB2) and max(TABB, TABG, TABB2) < 0x1000, "TABB/TABG/TABB2 collide with the aux blocks"
    return c


SUBS = [
    # zqrp: the tag check also checks this image's table base
    ("""        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        beq     zqtok
        bsr     zqinit                  ; first use on this core (or a new build)
zqtok:
""",
     """        move    #>@MARK@,x0            ; this image's two table blocks (they move per remix)
        move    #>@MARK2@,x1
        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        bne     zqni
        move    y:>@TABB@,a
        cmp     x0,a
        bne     zqni
        move    y:>@TABB2@,a
        cmp     x1,a
        beq     zqtok
zqni:
        bsr     zqinit                  ; first use on this core, a new build, or a moved block
zqtok:
"""),
    # zqsp: the cutoff table's address comes from TABG
    ("""        and     #>$3e,b                 ; env x 32: one (G, D) pair per 1/8 octave
        add     #>GTAB,b
""",
     """        and     #>$3e,b                 ; env x 32: one (G, D) pair per 1/8 octave
        move    y:>@TABG@,x0            ; the cutoff table (zqinit stored it)
        add     x0,b
"""),
    ("        move    x:(r4)+,a               ; G\n",
     "        move    p:(r4)+,a               ; G\n"),
    ("        move    x:(r4),x0               ; D\n",
     "        move    p:(r4),x0               ; D\n"),
    # zqinit: the base arrives in x0
    ("""zqinit:
        move    r7,n2
        move    #>XSP,r1
""",
     """zqinit:
        move    r7,n2
        move    x0,y:>@TABB@             ; x0, x1 = the two blocks' bases (zqrp)
        move    x1,y:>@TABB2@
        move    x0,a
        add     #>@GTOFF@,a
        move    a1,y:>@TABG@             ; channel 1/2's cutoff table, for zqsp
        move    x1,r1                   ; block 2: the RPSP half-rows; the RPS9 rows follow
"""),
    ("""        do      #SPHALF,zqi1
        move    x:(r1)+,x0
""",
     """        do      #SPHALF,zqi1
        move    p:(r1)+,x0
"""),
    ("""        do      #R9HALF,zqi2
        move    x:(r1)+,x0
""",
     """        do      #R9HALF,zqi2
        move    p:(r1)+,x0
"""),
    ("""zqi2:
        move    #>XBL,r1
""",
     """zqi2:
        move    y:>@TABB@,r1             ; the render's half-table: block 1's start
"""),
    ("""        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    x:(r1)+,x0
""",
     """        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    p:(r1)+,x0
"""),
]


def generate():
    w1, w2, off = tables()
    assert off["XBL"] == 0 and off["XSP"] == 0, "zqinit reads each block from its start"
    c = constants()
    text = dsrc.ASM.read_text()
    assert MARK not in text and MARK2 not in text
    for old, new in SUBS:
        n = text.count(old)
        if n != 1:
            sys.exit(f"repitch_dsp_octabam: a substitution matched {n} times:\n{old}")
        new = (new.replace("@MARK@", MARK).replace("@MARK2@", MARK2)
                  .replace("@TABB@", f"${TABB:x}").replace("@TABB2@", f"${TABB2:x}")
                  .replace("@TABG@", f"${TABG:x}").replace("@GTOFF@", f"${off['GTAB']:x}"))
        text = text.replace(old, new)
    # resolve every equ, as tools/dsp_xasm.py does: the generated constants, then the
    # source's own (S_*, A_*), in order
    consts = dict(c)
    body = []
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+([^;]+)", line)
        if m:
            consts[m.group(1)] = int(eval(m.group(2).strip().replace("$", "0x"), {}, dict(consts)))
            continue
        body.append(line)
    out = []
    for line in body:
        code, sep, cmt = line.partition(";")
        for n in sorted(consts, key=len, reverse=True):
            code = re.sub(rf"\b{n}\b", f"${consts[n] & 0xffffff:x}", code)
        out.append(code + sep + cmt)
    # the comments still name the constants and the old X tables; say so once
    head = (f"; GENERATED by tools/repitch_dsp_octabam.py from tools/patch_repitch_dsp.asm -- do not edit.\n"
            f"; Constants resolved (TAGVAL ${c['TAGVAL']:06x}); the comments below are the standalone\n"
            f"; kernel's and still name them. Tables: two octabam blocks (rpk_dsp_ptable.py):\n"
            f";   ptable  ({len(w1)} words): render half-table +0, cutoff table +${off['GTAB']:x}\n"
            f";   ptable2 ({len(w2)} words): RPSP half-rows +0, RPS9 half-rows +${off['XR9']:x}\n"
            f"; TABB / TABB2 = Y:${TABB:x} / Y:${TABB2:x} (the blocks' bases), TABG = Y:${TABG:x} (the cutoff table).\n")
    src = head + "\n".join(out) + "\n"
    assert src.count(MARK) == 1 and src.count(MARK2) == 1, "each ptable literal must occur exactly once"
    for l in src.splitlines():
        code = l.split(";")[0]
        assert not re.search(r"\bequ\b", code), l
        assert not (re.search(r"\bp:", code) and "p:(" not in code), l
        assert not re.search(r"\b(XSP|XR9|XBL|GTAB)\b", code), l
    def block(name, words):
        return f"{name} = (\n" + "".join(f"    {', '.join(f'0x{w:06x}' for w in words[i:i + 8])},\n"
                                         for i in range(0, len(words), 8)) + ")\n"
    tab = ("# GENERATED by tools/repitch_dsp_octabam.py -- do not edit.\n"
           f"# REPITCH_REPEAT98_KYOTI's DSP tables, two blocks ({len(w1)} + {len(w2)} words).\n"
           f"# PTABLE: render half-table +0, cutoff table +0x{off['GTAB']:x}.\n"
           + block("PTABLE", w1)
           + f"# PTABLE2: RPSP half-rows +0, RPS9 half-rows +0x{off['XR9']:x}.\n"
           + block("PTABLE2", w2))
    return src, tab, (w1, w2), off, c


def main():
    src, tab, (w1, w2), off, _ = generate()
    if "--check" in sys.argv:
        stale = [p.name for p, t in ((OUT_ASM, src), (OUT_TAB, tab)) if not p.exists() or p.read_text() != t]
        if stale:
            sys.exit(f"repitch_dsp_octabam: stale {stale} -- run python3 tools/repitch_dsp_octabam.py")
        print("repitch_dsp_octabam: rpk_dsp.asm and rpk_dsp_ptable.py are current")
        return
    OUT_ASM.write_text(src)
    OUT_TAB.write_text(tab)
    print(f"wrote {OUT_ASM.relative_to(ROOT)} and {OUT_TAB.relative_to(ROOT)} ({len(w1)} + {len(w2)} table words)")


if __name__ == "__main__":
    main()

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
  rpk_dsp_ptable.py  PTABLE: the 593 table words, one block (DspSection.ptable)

What changes against the standalone kernel (each a text substitution asserted to
apply exactly once; nothing else moves):
  * every `equ` is resolved to a literal -- octabam's dsp_asm has no constants;
  * the tables are ONE block, octabam's ptable: render half-table, then channel
    1/2's cutoff table, then the RPSP and RPS9 half-rows (zqinit's r1 runs on
    from one to the next, as before). The source names its base exactly once
    (octabam's ptable literal, at zqrp); every table read is `p:(rN)`, which
    octabam keeps in P or rewrites to `x:(rN)` when it parks the block in the
    stock curve bank;
  * zqrp loads that base and runs zqinit when the table tag OR the stored base
    differs (the base moves between remixes; the tag only says the contents);
  * zqinit stores the base (TABB) and the cutoff table's address (TABG) in Y,
    and reads its three tables from the block; zqsp's per-frame cutoff lookup
    adds TABG instead of an absolute X address.
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

# Two Y words above the aux blocks (zqinit zeroes FBASE..FBASE+63), inside the module's
# Y:$A00-$FFF claim.
TABB, TABG = 0xFF0, 0xFF1


def tables():
    """The block, and each table's offset in it."""
    sp, _ = dsrc.half_table(dsrc.m.MODE_RPSP)
    r9, _ = dsrc.half_table(dsrc.m.MODE_RPS9)
    bl = dsrc.render_half()
    gt = [w & 0xFFFFFF for w in dsrc.m.ch12_gtab_q23()]
    off = dict(XBL=0, GTAB=len(bl), XSP=len(bl) + len(gt), XR9=len(bl) + len(gt) + len(sp))
    return bl + gt + sp + r9, off


def constants():
    a, b = dsrc.constants("A"), dsrc.constants("B")
    per = {"XSP", "XR9", "XBL", "GTAB"}
    diff = {k for k in a if a[k] != b[k]}
    assert diff == per, f"payload-dependent constants beyond the table addresses: {sorted(diff - per)}"
    c = {k: v for k, v in a.items() if k not in per}
    assert c["FBASE"] + 64 <= TABB and TABG < 0x1000, "TABB/TABG collide with the aux blocks"
    return c


SUBS = [
    # zqrp: the tag check also checks this image's table base
    ("""        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        beq     zqtok
        bsr     zqinit                  ; first use on this core (or a new build)
zqtok:
""",
     """        move    #>@MARK@,x0            ; this image's table block (the base moves per remix)
        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        bne     zqni
        move    y:>@TABB@,a
        cmp     x0,a
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
        move    x0,y:>@TABB@             ; x0 = the table block's base (zqrp)
        move    x0,a
        add     #>@GTOFF@,a
        move    a1,y:>@TABG@             ; channel 1/2's cutoff table, for zqsp
        move    x0,a
        add     #>@XSPOFF@,a
        move    a1,r1                   ; the RPSP half-rows; the RPS9 rows follow
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
        move    y:>@TABB@,r1             ; the render's half-table: the block's start
"""),
    ("""        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    x:(r1)+,x0
""",
     """        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    p:(r1)+,x0
"""),
]


def generate():
    words, off = tables()
    assert off["XBL"] == 0, "zqinit reads the render half-table from the block's start"
    c = constants()
    text = dsrc.ASM.read_text()
    assert MARK not in text
    for old, new in SUBS:
        n = text.count(old)
        if n != 1:
            sys.exit(f"repitch_dsp_octabam: a substitution matched {n} times:\n{old}")
        new = (new.replace("@MARK@", MARK).replace("@TABB@", f"${TABB:x}").replace("@TABG@", f"${TABG:x}")
                  .replace("@GTOFF@", f"${off['GTAB']:x}").replace("@XSPOFF@", f"${off['XSP']:x}"))
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
            f"; kernel's and still name them. Tables: one octabam ptable block ({len(words)} words, rpk_dsp_ptable.py):\n"
            f";   render half-table +0, cutoff table +${off['GTAB']:x}, RPSP rows +${off['XSP']:x}, RPS9 rows +${off['XR9']:x}.\n"
            f"; TABB = Y:${TABB:x} (the block's base), TABG = Y:${TABG:x} (the cutoff table).\n")
    src = head + "\n".join(out) + "\n"
    assert src.count(MARK) == 1, "the ptable literal must occur exactly once"
    for l in src.splitlines():
        code = l.split(";")[0]
        assert not re.search(r"\bequ\b", code), l
        assert not (re.search(r"\bp:", code) and "p:(" not in code), l
        assert not re.search(r"\b(XSP|XR9|XBL|GTAB)\b", code), l
    tab = ("# GENERATED by tools/repitch_dsp_octabam.py -- do not edit.\n"
           f"# REPITCH_REPEAT98_KYOTI's DSP tables, one block ({len(words)} words): render half-table +0,\n"
           f"# cutoff table +0x{off['GTAB']:x}, RPSP half-rows +0x{off['XSP']:x}, RPS9 half-rows +0x{off['XR9']:x}.\n"
           "PTABLE = (\n" + "".join(f"    {', '.join(f'0x{w:06x}' for w in words[i:i + 8])},\n"
                                    for i in range(0, len(words), 8)) + ")\n")
    return src, tab, words, off, c


def main():
    src, tab, words, off, _ = generate()
    if "--check" in sys.argv:
        stale = [p.name for p, t in ((OUT_ASM, src), (OUT_TAB, tab)) if not p.exists() or p.read_text() != t]
        if stale:
            sys.exit(f"repitch_dsp_octabam: stale {stale} -- run python3 tools/repitch_dsp_octabam.py")
        print("repitch_dsp_octabam: rpk_dsp.asm and rpk_dsp_ptable.py are current")
        return
    OUT_ASM.write_text(src)
    OUT_TAB.write_text(tab)
    print(f"wrote {OUT_ASM.relative_to(ROOT)} and {OUT_TAB.relative_to(ROOT)} ({len(words)} table words)")


if __name__ == "__main__":
    main()

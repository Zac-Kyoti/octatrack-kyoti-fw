#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 14: the complete DSP source = generated constants +
tools/patch_repitch_dsp.asm, and the table DATA that goes into X memory.
Everything numeric comes from tools/repitch_engine_model.py, so the DSP and
its reference model cannot drift apart. Used by tools/build_repitch_repeat98_kyoti.py
and the DSP harnesses.

Since rev 14 the tables are not in the P cave: they are written over SPRING
REVERB's own X data tables (five modules per payload that only SPRING's code
references -- the canary run of NOTES Session 112), and zqinit copies them to
Y. Run 1 (three adjacent 72-word modules) holds the render's half-table and
channel 1/2's cutoff table (read in place); run 2 (116 + 384 words) the RPSP
and RPS9 half-rows, in that order (zqinit's r1 runs on from one to the next).

    python3 tools/repitch_dsp_src.py [A|B] [ORG]   -> assembles, prints size + tag
"""
import os
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dsp_xasm                          # noqa: E402
import repitch_engine_model as m         # noqa: E402

ASM = HERE / "patch_repitch_dsp.asm"

# Y:$795..$FFF is free on stock (octabam, hardware); SIDECHAIN3 owns $800-$9FF.
# Per-track RPSP slots at STBASE + x:$418 ($20 words: the render's residual
# ring, modulo-addressed so it starts the slot, then the state); the tag in the
# last word of track 3's slot; the RPSP table (32 x 12 = $180 words), the RPS9
# table (32 x 16 = $200), the render's step table at $E00 (L*R (T, D) pairs +
# T[L*R], to $F40), and since rev 14 the per-track aux blocks at FBASE + x:$418/2.
STBASE, TABTAG, SPTAB, R9TAB, BTAB, FBASE, YEND = 0xA00, 0xA7F, 0xA80, 0xC00, 0xE00, 0xF50, 0x1000
TAGSP = 0x5A5A05                          # "this slot is rev 14's" (rev 11: ...02, 12: ...03, 13: ...04)

# SPRING REVERB's exclusive X data modules, per payload: (address, words), and
# the two contiguous runs they form. X:0x8cf0 / 0x87b0 (27 words) is shared
# with DARK REVERB and is never touched.
SPRING_X = {"A": ((0x89a4, 72), (0x89ec, 72), (0x8a34, 72), (0x8afc, 116), (0x8b70, 384)),
            "B": ((0x8464, 72), (0x84ac, 72), (0x84f4, 72), (0x85bc, 116), (0x8630, 384))}
XRUNS = {"A": ((0x89a4, 216), (0x8afc, 500)), "B": ((0x8464, 216), (0x85bc, 500))}

# P placement (rev 14). SPRING's module is A P:0x1252 / B P:0x1012, 1063 words;
# SIDECHAIN3 builds from its start (388 words, kept free for a merged build).
# DARK REVERB (the next module) CALLS a 35-word routine inside it -- A P:0x1586,
# B P:0x1346 (`jsr` x3 each, NOTES Session 112) -- which rev 10-13's tail-aligned
# cave overwrote. The cave now ends right below that routine.
SPRING_P = {"A": 0x1252, "B": 0x1012}
SC3_WORDS = 388
DARK_SUB = {"A": (0x1586, 35), "B": (0x1346, 35)}


def cave_org(payload, n):
    org = DARK_SUB[payload][0] - n
    if org < SPRING_P[payload] + SC3_WORDS:
        raise ValueError(f"payload {payload}: a {n}-word cave would reach into SIDECHAIN3's "
                         f"{SC3_WORDS} words (room: {DARK_SUB[payload][0] - SPRING_P[payload] - SC3_WORDS})")
    return org


# The 7/8 build switch: CH12=0 in the environment drops the ;+CH12 .. ;-CH12
# blocks (RPSP heard as the raw outputs 7/8, rev 13's sound + the trig fix).
CH12 = os.environ.get("RPK_CH12", "1") != "0"


def q23(v):
    i = int(round(v * (1 << 23)))
    if not -(1 << 23) <= i < (1 << 23):
        raise ValueError(f"coefficient {v} does not fit Q23")
    return i & 0xFFFFFF


def half_table(mode):
    """Rows 0..15 of the virtual-ADC table, row-major, Q23 (rows 16..31 are
    their mirrors and are rebuilt in Y by zqinit, rev 12's copy)."""
    q = m.fir_q23(mode)
    n = q.shape[1]
    for ph in range(16):
        assert np.array_equal(q[31 - ph], q[ph][::-1]), "table is not mirror-symmetric"
    return [int(v) & 0xFFFFFF for v in q[:16].reshape(-1)], n


def render_half():
    """The render's step table T[0..LR/2] (zqinit rebuilds the rest and D)."""
    T, _ = m.render_q23()
    n = m.RENDER["L"] * m.RENDER["R"]
    assert all(T[n - k] == -(1 << 22) - T[k] for k in range(n // 2 + 1)), "T is not antisymmetric"
    return [int(v) & 0xFFFFFF for v in T[:n // 2 + 1]]


def x_data(payload):
    """{X address: word} for one payload: run 1 = render half + cutoff table,
    run 2 = RPSP half-rows then RPS9 half-rows."""
    sp, _ = half_table(m.MODE_RPSP)
    r9, _ = half_table(m.MODE_RPS9)
    bl = render_half()
    gt = [w & 0xFFFFFF for w in m.ch12_gtab_q23()]
    (r1, n1), (r2, n2) = XRUNS[payload]
    run1, run2 = bl + gt, sp + r9
    assert len(run1) <= n1 and len(run2) <= n2, "the tables outgrow SPRING's X runs"
    data = {r1 + i: w for i, w in enumerate(run1)}
    data.update({r2 + i: w for i, w in enumerate(run2)})
    return data


def constants(payload="A"):
    sp, spn = half_table(m.MODE_RPSP)
    r9, r9n = half_table(m.MODE_RPS9)
    bl = render_half()
    gt = [w & 0xFFFFFF for w in m.ch12_gtab_q23()]
    L, R = m.RENDER["L"], m.RENDER["R"]
    # the asm computes the RPSP row as phase x 12 (x8 + x4) and the RPS9 row as
    # phase x 16; the render's fraction as (u << 4), i.e. R = 16; the cutoff
    # table's index as env >> 18 (32 steps)
    assert (spn, r9n, R, m.CH12_GSTEPS) == (12, 16, 16, 32), "patch_repitch_dsp.asm's arithmetic"
    tag = (sum((i + 1) * w for i, w in enumerate(sp + r9 + bl + gt)) * 2654435761) & 0xFFFFFF | 1
    (x1, _), (x2, _) = XRUNS[payload]
    c = dict(
        STBASE=STBASE, TABTAG=TABTAG, SPTAB=SPTAB, R9TAB=R9TAB, BTAB=BTAB, FBASE=FBASE,
        TAGVAL=tag, TAGSP=TAGSP,
        SPN=spn, SPNM1=spn - 1, SPHALF=16 * spn, SPEND=SPTAB + 32 * spn - 1,
        R9N=r9n, R9NM1=r9n - 1, R9HALF=16 * r9n, R9END=R9TAB + 32 * r9n - 1,
        R9SW=4 * (r9n // 2 - 1) + 2,                 # first tap: k_i - 2c - 1 frames, in words
        SPC2=2 * (spn // 2 - 1) + 1,                 # first tap: floor(pos) - 2c - 1 frames
        PSPQ20=int(round(m.PSP * (1 << 20))),        # SP tick period, output samples, Q20
        PSPM1=int(round(m.PSP * (1 << 20))) - (1 << 20),   # ... minus the interval it ticks in
        PSPH=q23(m.PSP / 2),                          # PSP/2, Q23 (the lag term)
        RINGW=2 * L, RINGM1=2 * L - 1,                # the residual ring: L frames, modulo 2L
        S_SIZE=2 * L + 8,                             # ring + the 8 state words (asm S_*)
        BL=L, BSTART=BTAB + 2 * (L - 1) * R,          # tap 0's segment
        BSTRIDE=(-(2 * R + 1)) & 0xFFFFFF,            # after reading (T, D): R pairs down
        BHALF=L * R // 2 + 1, BPAIRS=L * R, BEND=BTAB + 2 * L * R,
        XSP=x2, XR9=x2 + len(sp), XBL=x1, GTAB=x1 + len(bl),
        DEC16=q23(m.CH12_DEC16),
    )
    # modulo-2L addressing needs the ring at a multiple of the next power of two
    assert 2 * L <= 0x20 and STBASE % 0x20 == 0, "the ring must fit a 32-aligned slot"
    assert 0x60 + c["S_SIZE"] <= TABTAG - STBASE < 0x80, "slots overlap the table tag"
    assert TABTAG < SPTAB and SPTAB + 32 * spn <= R9TAB and R9TAB + 32 * r9n <= BTAB
    assert c["BEND"] < FBASE and FBASE + 0x30 + 12 <= YEND, "aux blocks: 12 words at FBASE + x:$418/2"
    # r6 (the aux pointer) runs under the stock m6 = $7f: no block may straddle 128 words
    assert all((FBASE + 0x10 * t) // 0x80 == (FBASE + 0x10 * t + 11) // 0x80 for t in range(4)), "aux block straddles"
    return c


def source(payload="A", ch12=None):
    ch12 = CH12 if ch12 is None else ch12
    c = constants(payload)
    head = "".join(f"{k:<8}equ     ${v & 0xFFFFFF:x}\n" for k, v in c.items())
    text = ASM.read_text()
    if not ch12:
        text = re.sub(r";\+CH12\n.*?;-CH12\n", "", text, flags=re.S)
    return head + text, c


def assemble(org, payload="A", ch12=None):
    src, c = source(payload, ch12)
    words, syms = dsp_xasm.assemble(src, org)
    return words, syms, c


if __name__ == "__main__":
    pl = sys.argv[1] if len(sys.argv) > 1 else "A"
    org = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x1400
    try:
        words, syms, c = assemble(org, pl)
    except dsp_xasm.AsmError as e:
        sys.exit(f"repitch DSP source: {e}")
    xd = x_data(pl)
    print(f"payload {pl}: {len(words)} P words at P:{org:05x} (code only; CH12 {'on' if CH12 else 'off'}); "
          f"{len(xd)} X words; TAGVAL {c['TAGVAL']:06x}")

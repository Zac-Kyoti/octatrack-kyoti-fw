#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
repitch-kyoti rev 17: the complete DSP source = generated constants +
tools/patch_repitch_dsp.asm, and the table DATA that goes into X memory.
Everything numeric comes from tools/repitch_engine_model.py, so the DSP and
its reference model cannot drift apart. Used by tools/build_repitch_repeat98_kyoti.py
and the DSP harnesses.

Since rev 14 the tables are not in the P cave: they are written over SPRING
REVERB's own X data tables (five modules per payload that only SPRING's code
references -- the canary run of NOTES Session 112), and zqinit copies them to
Y. Run 1 (three adjacent 72-word modules) holds the render's half-table; run
2 (116 + 384 words) the RPSP and RPS9 half-rows, in that order (zqinit's r1 runs
on from one to the next). RPSP is full stereo since 2026-10-15 (raw outputs 7/8, 8-tap
ADC per channel; reference/handoffs/VARISPEED_EMUS_SP12_STEREO.md); rev 17's mid/side
is at the tag ref/sp12-midside-vem7.

    python3 tools/repitch_dsp_src.py [A|B] [ORG]   -> assembles, prints size + tag
"""
import os
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dsp_xasm                          # noqa: E402
import repitch_engine_model as m         # noqa: E402

ASM = HERE / "patch_repitch_dsp.asm"

# Y:$795..$FFF is free on stock (octabam, hardware); SIDECHAIN3 owns $800-$9FF.
# Per-track RPSP slots at STBASE + x:$418 ($20 words: the render's stereo ring, 2L words
# with L and R interleaved, modulo-addressed so it starts the slot, then the state); the
# tag in the last word of track 3's slot; the RPSP table (32 x 8 = $100 words), the RPS9
# table (32 x 16 = $200), the render's step table at $E00 (R rows of BROW words: the L
# taps' (T', D) pairs, then padding, so a row starts at BTAB + BROW j; to $FFF). zqinit
# builds T' in a scratch run inside the RPS9 table's place before it copies that table.
STBASE, TABTAG, SPTAB, R9TAB, BTAB, YEND = 0xA00, 0xA7F, 0xA80, 0xC00, 0xE00, 0x1000
BROW = 32                                 # the render table's row stride (2L = 20 words used)
TTMP = R9TAB                              # zqinit's scratch run of the render's T (161 words)
# the tag says the Y tables' CONTENTS and LAYOUT are this build's: Y_LAYOUT moves it when the
# copy changes shape (2: rev 17's first cut, the cutoff table in Y; 3: no cutoff table; 4: the render's
# table transposed; 6: the VEM DSP optimisation, padded render rows, RPS9 transposed)
Y_LAYOUT = 7                              # 7: SP12 stereo (the render's table holds T' = T + 1/2)
TAGSP = 0x5A5A0A                          # "this slot is this layout's" (rev 11: ...02, 12: ...03, 13: ...04, 14: ...05, 17 first cut: ...06, aligned: ...07, VEM DSP optimisation: ...09, SP12 stereo: ...0A)

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


# Rev 14-16's channel 1/2 build switch (RPK_CH12) is gone with channel 1/2 itself (rev 17).
CH12 = False


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


def r9_stored():
    """RPS9's 16 stored half-rows in the order zqinit copies them: tap-major (the
    VEM DSP optimisation's table is transposed: tap t of phase p at R9TAB + 32 t + p, so
    a phase's taps are walked with a stride of 32 and its row base is R9TAB + phase)."""
    r9, n = half_table(m.MODE_RPS9)
    return [r9[n * p + t] for t in range(n) for p in range(16)], n


def render_tp():
    """T' = T + 1/2 (Q23) = (1 - Gc) / 2, the render's step response / 2, k = 0..LR: the
    stereo kernel's ring holds outputs, not residuals (repitch_engine_model.DspExact)."""
    T, _ = m.render_q23()
    return T + (1 << 22)


def render_half():
    """The render's step table T'[0..LR/2] (zqinit rebuilds the rest, T'[LR-k] = 1/2 - T'[k],
    and D)."""
    Tp = render_tp()
    n = m.RENDER["L"] * m.RENDER["R"]
    assert all(Tp[n - k] == (1 << 22) - Tp[k] for k in range(n // 2 + 1)), "T' is not antisymmetric"
    return [int(v) & 0xFFFFFF for v in Tp[:n // 2 + 1]]


def x_data(payload):
    """{X address: word} for one payload: run 1 = the render's half-table,
    run 2 = RPSP half-rows then RPS9 half-rows."""
    sp, _ = half_table(m.MODE_RPSP)
    r9, _ = r9_stored()
    bl = render_half()
    (r1, n1), (r2, n2) = XRUNS[payload]
    run1, run2 = bl, sp + r9
    assert len(run1) <= n1 and len(run2) <= n2, "the tables outgrow SPRING's X runs"
    data = {r1 + i: w for i, w in enumerate(run1)}
    data.update({r2 + i: w for i, w in enumerate(run2)})
    return data


def constants(payload="A"):
    sp, spn = half_table(m.MODE_RPSP)
    r9, r9n = r9_stored()
    bl = render_half()
    L, R = m.RENDER["L"], m.RENDER["R"]
    # the asm computes the RPSP row as phase x 8 and the RPS9 row as phase x 16; the
    # render's fraction as (u << 4), i.e. R = 16; RPS9's 15 taps after the first are unrolled
    assert (spn, r9n, R, L) == (8, 16, 16, 10), "patch_repitch_dsp.asm's arithmetic (and its unrolled render: L = 10)"
    tag = ((sum((i + 1) * w for i, w in enumerate(sp + r9 + bl)) + Y_LAYOUT) * 2654435761) & 0xFFFFFF | 1
    (x1, _), (x2, _) = XRUNS[payload]
    c = dict(
        STBASE=STBASE, TABTAG=TABTAG, SPTAB=SPTAB, R9TAB=R9TAB, BTAB=BTAB,
        TAGVAL=tag, TAGSP=TAGSP,
        SPN=spn, SPNM1=spn - 1, SPHALF=16 * spn, SPEND=SPTAB + 32 * spn - 1,
        R9N=r9n, R9NM1=r9n - 1, R9HALF=16 * r9n, R9END=R9TAB + 32 * r9n - 1, R9RUN=16,
        R9SW=4 * (r9n // 2 - 1) + 2,                 # first tap: k_i - 2c - 1 frames, in words
        SPC2=2 * (spn // 2 - 1) + 1,                 # first tap: floor(pos) - 2c - 1 frames
        PSPQ23=int(round(m.PSP * (1 << 20))) << 3,   # SP tick period, output samples, Q23 (Q20's value:
                                                      # the model's PSP_TICK; < 2^24 as the AGU adds it)
        PSPH=q23(m.PSP / 2),                          # PSP/2, Q23 (the lag term)
        RINGN=2 * L, RINGM1=2 * L - 1,                # the stereo ring: 2L words (L, R), modulo 2L
        BL=L, BR=R, BROW=BROW, BPAD=BROW - 2 * L, BHALF=L * R // 2 + 1, BPAIRS=L * R, BEND=BTAB + BROW * R,
        TTMP=TTMP, TTEND=TTMP + L * R,                # zqinit's scratch run of T[0..LR]
        BTSTEP=R - 1,                                 # after T'[k], T'[k+1]: on to T'[k+R]
        BRSH=BROW.bit_length() - 1,                   # x BROW as a shift
        XSP=x2, XR9=x2 + len(sp), XBL=x1,
    )
    assert (1 << 23) < c["PSPQ23"] < (1 << 24), "1 < PSP < 2, as a 24-bit AGU offset"
    # modulo-2L addressing needs the ring at a multiple of the next power of two (32)
    assert 2 * L <= 0x20 and STBASE % 0x20 == 0, "the stereo ring must fit a 32-aligned slot"
    assert TABTAG < SPTAB and SPTAB + 32 * spn <= R9TAB and R9TAB + 32 * r9n <= BTAB
    assert c["BEND"] <= YEND and 2 * L <= BROW and BROW & (BROW - 1) == 0
    # the tick finds row j as ((u - 1) >> 14) & $fe0 (patch_repitch_dsp.asm, RPSP): BTAB = $E00
    assert (BTAB, BROW, R) == (0xE00, 32, 16), "the render row's bit trick wants BTAB $E00, 32-word rows, R = 16"
    assert 2 * L == 0x14 and STBASE + 0x60 + 0x1B < TABTAG, "the slot's state starts at $14 and ends before TABTAG"
    assert R9TAB <= TTMP and TTMP + L * R + 1 <= R9TAB + 32 * r9n     # the scratch run, before R9TAB is copied
    return c


def source(payload="A", ch12=None):
    c = constants(payload)
    head = "".join(f"{k:<8}equ     ${v & 0xFFFFFF:x}\n" for k, v in c.items())
    return head + ASM.read_text(), c


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
    print(f"payload {pl}: {len(words)} P words at P:{org:05x} (code only); "
          f"{len(xd)} X words; TAGVAL {c['TAGVAL']:06x}")

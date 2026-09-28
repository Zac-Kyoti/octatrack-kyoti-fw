#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 13: the complete DSP source = generated constants +
tools/patch_repitch_dsp.asm + generated tables. Everything numeric comes from
tools/repitch_engine_model.py, so the DSP and its reference model cannot
drift apart. Used by tools/build_repitch_kyoti.py and the DSP harnesses.

    python3 tools/repitch_dsp_src.py [ORG]   -> assembles, prints size + tag
"""
import pathlib
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
# table (32 x 16 = $200), and since rev 13 the render's step table at $E00
# (L*R (T, D) pairs + T[L*R]).
STBASE, TABTAG, SPTAB, R9TAB, BTAB, YEND = 0xA00, 0xA7F, 0xA80, 0xC00, 0xE00, 0x1000
TAGSP = 0x5A5A04                          # "this slot is rev 13's" (rev 11: ...02, rev 12: ...03)


def q23(v):
    i = int(round(v * (1 << 23)))
    if not -(1 << 23) <= i < (1 << 23):
        raise ValueError(f"coefficient {v} does not fit Q23")
    return i & 0xFFFFFF


def packed_table(mode):
    """The rows the DSP stores (model.PACKED_ROWS = 0,2,..,14,15), row-major,
    Q23; zqexp rebuilds the other 23 rows exactly as model.fir_q23 does."""
    assert m.PACKED_ROWS == (0, 2, 4, 6, 8, 10, 12, 14, 15), "zqexp's row order"
    q = m.fir_q23(mode)
    n = q.shape[1]
    for ph in range(16):
        assert np.array_equal(q[31 - ph], q[ph][::-1]), "table is not mirror-symmetric"
    return [int(v) & 0xFFFFFF for v in m.fir_packed(mode).reshape(-1)], n


def render_half():
    """The render's step table T[0..LR/2] (zqinit rebuilds the rest and D)."""
    T, _ = m.render_q23()
    n = m.RENDER["L"] * m.RENDER["R"]
    assert all(T[n - k] == -(1 << 22) - T[k] for k in range(n // 2 + 1)), "T is not antisymmetric"
    return [int(v) & 0xFFFFFF for v in T[:n // 2 + 1]]


def constants():
    sp, spn = packed_table(m.MODE_RPSP)
    r9, r9n = packed_table(m.MODE_RPS9)
    bl = render_half()
    L, R = m.RENDER["L"], m.RENDER["R"]
    # the asm computes the RPSP row as phase x 12 (x8 + x4) and the RPS9 row as
    # phase x 16; the render's fraction as (u << 4), i.e. R = 16
    assert (spn, r9n, R) == (12, 16, 16), "patch_repitch_dsp.asm's arithmetic assumes 12/16 taps, R = 16"
    tag = (sum((i + 1) * w for i, w in enumerate(sp + r9 + bl)) * 2654435761) & 0xFFFFFF | 1
    c = dict(
        STBASE=STBASE, TABTAG=TABTAG, SPTAB=SPTAB, R9TAB=R9TAB, BTAB=BTAB,
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
    )
    # modulo-2L addressing needs the ring at a multiple of the next power of two
    assert 2 * L <= 0x20 and STBASE % 0x20 == 0, "the ring must fit a 32-aligned slot"
    assert 0x60 + c["S_SIZE"] <= TABTAG - STBASE < 0x80, "slots overlap the table tag"
    assert TABTAG < SPTAB and SPTAB + 32 * spn <= R9TAB and R9TAB + 32 * r9n <= BTAB
    assert c["BEND"] < YEND
    return c, sp, r9, bl


def source():
    c, sp, r9, bl = constants()
    head = "".join(f"{k:<8}equ     ${v & 0xFFFFFF:x}\n" for k, v in c.items())

    def dc(label, words):
        rows = [words[i:i + 8] for i in range(0, len(words), 8)]
        return f"{label}:\n" + "".join("        dc      " + ",".join(f"${w:06x}" for w in r) + "\n" for r in rows)
    tail = dc("zqdsp", sp) + dc("zqdr9", r9) + dc("zqdbl", bl)
    return head + ASM.read_text() + tail, c


def assemble(org):
    src, c = source()
    words, syms = dsp_xasm.assemble(src, org)
    return words, syms, c


if __name__ == "__main__":
    org = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x1400
    try:
        words, syms, c = assemble(org)
    except dsp_xasm.AsmError as e:
        sys.exit(f"repitch DSP source: {e}")
    code = syms["zqdsp"] - org
    print(f"{len(words)} words ({code} code + {len(words) - code} data) at P:{org:05x}; "
          f"TAGVAL {c['TAGVAL']:06x}; PSPQ20 {c['PSPQ20']:#x}")

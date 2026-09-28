#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 12: the complete DSP source = generated constants +
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

# Y:$795..$FFF is free on stock (octabam, hardware); SIDECHAIN3 owns $800-$9FF;
# rev 11/12 keep to $A00-$DFF. Per-track state at STBASE + x:$418 (slots of $20
# words, S_SIZE used); the tag in the last word of track 3's slot; then the
# RPSP table (32 x 12 = $180 words) and the RPS9 table (32 x 16 = $200).
STBASE, TABTAG, SPTAB, R9TAB, YEND = 0xA00, 0xA7F, 0xA80, 0xC00, 0xE00
TAGSP = 0x5A5A03                          # "this state block is rev 12's" (rev 11: ...02)


def q23(v):
    i = int(round(v * (1 << 23)))
    if not -(1 << 23) <= i < (1 << 23):
        raise ValueError(f"coefficient {v} does not fit Q23")
    return i & 0xFFFFFF


def state_words():
    """S_SIZE, read from the asm so the layout check cannot drift from it."""
    for line in ASM.read_text().splitlines():
        f = line.split()
        if len(f) == 3 and f[0] == "S_SIZE" and f[1] == "equ":
            return int(f[2])
    raise ValueError("S_SIZE not found in the asm")


def half_table(mode):
    """Rows 0..15 of the virtual-ADC table, row-major, Q23 (rows 16..31 are
    their mirrors and are rebuilt on the DSP)."""
    q = m.fir_q23(mode)
    n = q.shape[1]
    for ph in range(16):
        assert np.array_equal(q[31 - ph], q[ph][::-1]), "table is not mirror-symmetric"
    return [int(v) & 0xFFFFFF for v in q[:16].reshape(-1)], n


def constants():
    sp, spn = half_table(m.MODE_RPSP)
    r9, r9n = half_table(m.MODE_RPS9)
    # the asm computes the RPSP row as phase x 12 (x8 + x4) and the RPS9 row as phase x 16
    assert (spn, r9n) == (12, 16), "patch_repitch_dsp.asm's row arithmetic assumes 12 and 16 taps"
    tag = (sum((i + 1) * w for i, w in enumerate(sp + r9)) * 2654435761) & 0xFFFFFF | 1
    c = dict(
        STBASE=STBASE, TABTAG=TABTAG, SPTAB=SPTAB, R9TAB=R9TAB,
        TAGVAL=tag, TAGSP=TAGSP,
        SPN=spn, SPNM1=spn - 1, SPHALF=16 * spn, SPEND=SPTAB + 32 * spn - 1,
        R9N=r9n, R9NM1=r9n - 1, R9HALF=16 * r9n, R9END=R9TAB + 32 * r9n - 1,
        R9SW=4 * (r9n // 2 - 1) + 2,                 # first tap: k_i - 2c - 1 frames, in words
        SPC2=2 * (spn // 2 - 1) + 1,                 # first tap: floor(pos) - 2c - 1 frames
        PSPQ20=int(round(m.PSP * (1 << 20))),        # SP tick period, output samples, Q20
        PSPM1=int(round(m.PSP * (1 << 20))) - (1 << 20),   # ... minus the interval it ticks in
        PSPH=q23(m.PSP / 2),                          # PSP/2, Q23 (the lag term)
    )
    assert 0x60 + state_words() <= TABTAG - STBASE < 0x80, "state blocks overlap the table tag"
    assert TABTAG < SPTAB and SPTAB + 32 * spn <= R9TAB and R9TAB + 32 * r9n <= YEND
    return c, sp, r9


def source():
    c, sp, r9 = constants()
    head = "".join(f"{k:<8}equ     ${v & 0xFFFFFF:x}\n" for k, v in c.items())

    def dc(label, words):
        rows = [words[i:i + 8] for i in range(0, len(words), 8)]
        return f"{label}:\n" + "".join("        dc      " + ",".join(f"${w:06x}" for w in r) + "\n" for r in rows)
    tail = dc("zqdsp", sp) + dc("zqdr9", r9)
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

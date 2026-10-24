#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
SIDECHAIN_COMPRESSOR key filters (major version, reference/handoffs/SIDECHAIN_KEYFILT_MON_SCOPE.md
§2): the table the DSP code reads, and a bit-exact integer model of what it computes.

  A base-width pair (2026-10-21, the user's choice; Elektron's BASE/WDTH):
  KBAS  the HP, 18 dB/oct Butterworth: a TPT one-pole HP x a TPT state-variable HP (k = 1),
        both at fc. Knob 0 = OFF (runs at ~5 Hz: no code path switch), 1..127 = 20 Hz ..
        19.5 kHz, the full grid.
  KWID  the LP, 12 dB/oct Butterworth (a TPT state-variable LP, k = sqrt 2), set as a
        distance above KBAS: knob 0..126 = 1/2 .. ~10 octaves, 127 = OFF (runs at ~19.5
        kHz). With KBAS OFF the distance is counted from 20 Hz: a plain LP, ~28 Hz .. 19.5
        kHz. The two cannot cross, and every readout is what the DSP runs.
  One grid, 16 steps an octave: f(g) = 20 Hz * 2^(g/16). KBAS knob n -> g = (n - 1) *
  159/126 (OFF -32); KWID knob m -> width 8 + m * 151/126 grid steps; g_LP = (g_BASE, or 0
  with KBAS OFF) + width, at most 159 (OFF).

Fixed point (Q23 = signed 24-bit fraction), as the DSP does it:
  * Position V = (g + 32) * 2^15, so g -32..159 is 0..0.75. Each block V glides toward the
    target with a one-pole (GLIDE_MS) and snaps when within SNAP; first block after a reset:
    straight to the target.
  * GT[j] = tan(pi f(g)/fs) / 16 at g = -32 + 4j, j = 0..48 (49 words). G16 = linear
    interpolation at j = V >> 17, frac = (V & $1ffff) << 6.
  * A state-variable section's a1 = 1/D with D = 1 + G^2 + kG, computed as (1/256)/(D/256)
    by the DSP's `div` (floor(N * 2^23 / D) for 0 < N < D); a2 = G * a1; a3 = 1 - a1 - k*a2.
    The one-pole's g1 = G / (1 + G) = G16 / (1/16 + G16).
  * Coefficients are recomputed only in a block where V moved (or after a reset).
  * Per sample: u = (L + R) / 16 (18 dB of headroom: a full-scale square through an open
    LP drives a section state to ~0.97 at 12 dB), then one-pole HP -> SVF HP -> SVF LP;
    out = u-scale * 8, saturated, on both channels.
  * Both knobs at OFF with the positions settled: the filters do not run (bypass): out =
    8u; the HP sections are left at 0 and the LP's ic2 at the last u, so a knob turned
    away from OFF continues smoothly (2026-10-19 cycle pass).
  * Every multiply truncates (the DSP takes a1), as the code does.
"""
import math

FS = 44100.0
Q23 = 1 << 23
STEPS = 16                      # grid steps an octave
F0 = 20.0                       # g = 0
G_MIN, G_HP_OFF, G_LP_OFF = -32, -32, 159
GT_STEP = 4
GT_N = 49                       # g = -32 .. 160
GLIDE_MS = 5.0
BLOCK = 16
SNAP = 1 << 7                   # |target - V| below this: snap (1/256 of a grid step)
K_HP, K_LP = 1.0, math.sqrt(2.0)


def _q(x):
    v = int(math.floor(x * Q23 + 0.5))
    return max(-Q23, min(Q23 - 1, v))


def freq(g):
    return F0 * 2.0 ** (g / STEPS)


def gt_table():
    return [_q(math.tan(math.pi * freq(G_MIN + GT_STEP * j) / FS) / 16) for j in range(GT_N)]


GT = gt_table()
K16_HP, K16_LP = _q(K_HP / 16), _q(K_LP / 16)
KH_LP = _q(K_LP / 2)            # k/2 for the k*a2 term (k = 1 needs no multiply)
GLIDE_A = _q(1 - math.exp(-BLOCK / FS / (GLIDE_MS / 1000)))
N256 = Q23 >> 8                 # 1/256
N16 = Q23 >> 4                  # 1/16


# Knob steps on the grid, in V units (1 << 15 = one grid step = 0.75 semitone):
# KBAS 1..127 = g 0 .. 159 (20 Hz .. 19.5 kHz; 2026-10-21, full range by the user's choice);
# KWID 0..126 = 8 .. 159 grid steps above KBAS (1/2 .. ~9.9 octaves).
HSTEP = 41349                   # 159/126 grid steps
WSTEP = 39269                   # 151/126 grid steps
WMIN = 8 << 15                  # half an octave
HBASE = 32 << 15                # V of g 0 (20 Hz)
LP_OFF_V = (G_LP_OFF + 32) << 15
MAGIC = 0x3a5c61                # r7+$2a once the filter block is set up (scinit clears it)


def hp_g(n):
    return G_HP_OFF if n == 0 else (n - 1) * HSTEP / (1 << 15)


def lp_g(n, m):
    """the LP's grid position for KBAS n, KWID m"""
    return (targets(n, m)[1] >> 0) / (1 << 15) - 32


def width_oct(m):
    """KWID m in octaves (None = OFF)"""
    return None if m >= 127 else (WMIN + m * WSTEP) / (1 << 15) / STEPS


def targets(n_hp, m_w):
    """knob values (KBAS, KWID) -> (V_hp, V_lp) targets: the LP sits KWID above KBAS (above
    20 Hz with KBAS OFF), at most at OFF."""
    vh = 0 if n_hp == 0 else HBASE + (n_hp - 1) * HSTEP
    if m_w >= 127:
        return vh, LP_OFF_V
    return vh, min((vh or HBASE) + WMIN + m_w * WSTEP, LP_OFF_V)


def asm_tokens():
    """The build tokens patch_sc_dsp3.asm's key-filter block reads (builders and tests)."""
    return {"@KFHSTEP@": f"${HSTEP:x}", "@KFWSTEP@": f"${WSTEP:x}", "@KFWMIN@": f"${WMIN:x}",
            "@KFMAGIC@": f"${MAGIC:x}", "@KFK16H@": f"${K16_HP:x}",
            "@KFK16L@": f"${K16_LP:x}", "@KFKHL@": f"${KH_LP:x}", "@KFSNAP@": f"${SNAP:x}",
            "@KFGA@": f"${GLIDE_A:x}"}


def glide(v, t):
    d = t - v
    if abs(d) < SNAP:
        return t
    return v + ((GLIDE_A * d) >> 23)


def g16(v):
    j, fr = v >> 17, (v & 0x1ffff) << 6
    a, b = GT[j], GT[j + 1]
    return a + ((fr * (b - a)) >> 23)


def svf_coefs(G16, K16, kmul):
    """(a1, a2, a3) in Q23. kmul: None for k = 1, else the Q23 k/2 constant."""
    D = (2 * (G16 * G16 + K16 * G16) + (1 << 39)) >> 24
    a1 = (N256 << 23) // D
    a2 = (G16 * a1 * 16) >> 23
    ka2 = a2 if kmul is None else (kmul * a2) >> 22
    a3 = Q23 - a1 - ka2
    return a1, a2, a3


def onepole_g1(G16):
    return (G16 << 23) // (N16 + G16)


def coefs(vh, vl):
    gh, gl = g16(vh), g16(vl)
    return (onepole_g1(gh),) + svf_coefs(gh, K16_HP, None) + svf_coefs(gl, K16_LP, KH_LP)


def _s24(v):
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


def _sat(v):
    return max(-Q23, min(Q23 - 1, v))


class KeyFilter:
    """Per-instance state, as the r7 block holds it."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.s1 = self.h1 = self.h2 = self.l1 = self.l2 = 0
        self.vh = self.vl = None
        self.c = None

    def block(self, inter, n_hp, m_lp):
        """inter: 32 interleaved Q23 words (L, R); returns 32 words."""
        th, tl = targets(n_hp, m_lp)
        if self.vh is None:
            self.vh, self.vl = th, tl
            moved = True
        else:
            nh, nl = glide(self.vh, th), glide(self.vl, tl)
            moved = (nh, nl) != (self.vh, self.vl)
            self.vh, self.vl = nh, nl
        if moved or self.c is None:
            self.c = coefs(self.vh, self.vl)
        if self.vh == 0 and self.vl == LP_OFF_V:
            # both at OFF and settled: the filters would pass the key through, so they don't
            # run. The sections restart where running would leave them: the HP from 0 (its
            # output starts as the input), the LP holding the last input as its ic2 (its
            # output starts there too), so leaving bypass is continuous.
            out = []
            for k in range(0, 32, 2):
                u = (_s24(inter[k]) + _s24(inter[k + 1])) >> 4
                y = _sat(u << 3) & 0xFFFFFF
                out += [y, y]
            self.s1 = self.h1 = self.h2 = self.l1 = 0
            self.l2 = u
            return out
        g1, ha1, ha2, ha3, la1, la2, la3 = self.c
        out = []
        for k in range(0, 32, 2):
            u = (_s24(inter[k]) + _s24(inter[k + 1])) >> 4
            v = ((u - self.s1) * g1) >> 23
            lp1 = v + self.s1
            self.s1 = _sat(lp1 + v)
            w = u - lp1
            v3 = w - self.h2
            v1 = (ha1 * self.h1 + ha2 * v3) >> 23
            v2 = self.h2 + ((ha2 * self.h1 + ha3 * v3) >> 23)
            self.h1, self.h2 = _sat(2 * v1 - self.h1), _sat(2 * v2 - self.h2)
            z = w - v1 - v2
            v3 = z - self.l2
            v1 = (la1 * self.l1 + la2 * v3) >> 23
            v2 = self.l2 + ((la2 * self.l1 + la3 * v3) >> 23)
            self.l1, self.l2 = _sat(2 * v1 - self.l1), _sat(2 * v2 - self.l2)
            y = _sat(v2 << 3) & 0xFFFFFF
            out += [y, y]
        return out


if __name__ == "__main__":
    print("GT (G/16, Q23), g = -32 + 4j:")
    for j in range(0, GT_N, 6):
        g = G_MIN + GT_STEP * j
        print(f"  j {j:2d}  g {g:4d}  {freq(g):8.1f} Hz  0x{GT[j]:06x}")
    for n in (0, 1, 33, 65, 97, 127):
        print(f"KBAS {n:3d}: {freq(hp_g(n)):8.1f} Hz")
    for m in (0, 16, 64, 112, 126, 127):
        print(f"KWID {m:3d}: {width_oct(m)} oct; with KBAS OFF the LP at {freq(lp_g(0, m)):8.1f} Hz")
    print(f"GLIDE_A 0x{GLIDE_A:06x}  K16 HP 0x{K16_HP:06x} LP 0x{K16_LP:06x}  KH_LP 0x{KH_LP:06x}")

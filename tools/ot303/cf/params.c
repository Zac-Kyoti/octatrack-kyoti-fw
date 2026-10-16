/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti
 * SPDX-FileCopyrightText: 2009 Robin Schmidt (Open303, MIT: the algorithm and constants ported here; tools/ot303/LICENSE.Open303.txt)
 *
 * OT-303: the knobs -> the engine's host words (params.h). Open303's own formulas (rosic_Open303.cpp:
 * calculateEnvModScalerAndOffset, DecayEnvelope / LeakyIntegrator coefficients, triggerNote's accent
 * switch), evaluated in fixed point; the constants come from tools/ot303/params_check.cpp gen
 * (params_const.h). Held against the double-precision originals by params_check.cpp check.
 * Written for the ColdFire's size: 32-bit divides only (the 5407 has them in hardware), 64-bit
 * multiplies (libgcc's __muldi3), no 64-bit division, no floating point.
 */
#include "params.h"
#include "params_const.h"

static ot_w clamp24(int64_t v) {
    return v > 0x7fffff ? 0x7fffff : v < -0x800000 ? -0x800000 : (ot_w)v;
}
/* a Q`q` value -> a Q23 word, rounded half up */
static ot_w q23(int64_t v, unsigned q) {
    return clamp24((v + ((int64_t)1 << (q - 24))) >> (q - 23));
}
/* 2^(a / 2^24) as Q30, a <= 0 (the knob curves only need the falling side): 2^(j/64) from the table
 * times e^u, u = t ln2 / 2^24 < 0.011, to u^3 (relative error < 1e-9) */
static uint32_t exp2q(int32_t a) {
    int32_t i = a >> 24;                       /* floor */
    uint32_t f = (uint32_t)a & 0xffffff, j = f >> 18, t = f & 0x3ffff;
    int64_t u = ((int64_t)t * OT_LN2_Q38) >> 32;            /* Q30 */
    int64_t u2 = (u * u) >> 31;                             /* u^2 / 2 */
    int64_t u3 = (((u2 * u) >> 30) * OT_RCPN[3]) >> 32;     /* u^3 / 6 */
    int64_t v = ((int64_t)OT_EXP2[j] * (((int64_t)1 << 30) + u + u2 + u3) + ((int64_t)1 << 29)) >> 30;
    return -i >= 31 ? 0 : (uint32_t)(v >> -i);
}
/* 1 - e^-x (sign < 0) or e^x - 1 (sign > 0), x >= 0 in Q`q`, the series to x^5 (x < 0.08 here);
 * the 1/n by Q32 reciprocals */
static int64_t expm1q(int64_t x, unsigned q, int sign) {
    int64_t t = x, s = x;
    for (int n = 2; n <= 5; ++n) {
        t = (((t * x) >> q) * OT_RCPN[n]) >> 32;
        s += (sign < 0 && !(n & 1)) ? -t : t;
    }
    return s;
}
/* the main envelope for a decay rate x = 1 / (0.001 tau fs) (Q41): c, and 0.5 / c (Q47, hi/lo) */
static void meg(int64_t x, struct ot_note *n) {
    n->c_meg = q23(((int64_t)1 << 41) - expm1q(x, 41, -1), 41);
    int64_t m = (((int64_t)1 << 41) + expm1q(x, 41, 1)) << 5;     /* 0.5 e^x, Q47 */
    n->m48h = (ot_w)(m >> 24);
    n->m48l = (ot_w)(m & 0xffffff);
}

void ot_params_cont(const uint8_t k[12], struct ot_cont *c) {
    ot_params_cont_q8(k, (unsigned)k[OT_CUT] << 8, (unsigned)k[OT_ENV] << 8, c);
}

void ot_params_cont_q8(const uint8_t k[12], unsigned cut_q8, unsigned env_q8, struct ot_cont *c) {
    /* slide: the pitch slew limiter, tau = 0.2 * (1.5625 SLID) ms; SLID 0 = no slew.
     * x = 1 / (13.78125 SLID) = 2^39 / (1764 SLID) as Q32, by two 32-bit divides */
    unsigned s = k[OT_SLID];
    if (!s) c->cs = 0x7fffff;
    else {
        uint32_t d = 1764u * s, q1 = 0x80000000u / d, r = 0x80000000u % d;
        int64_t x = ((int64_t)q1 << 8) + (((r << 8) + d / 2) / d);
        c->cs = q23(expm1q(x, 32, -1), 32);
    }
    /* cutoff 200 * 50^f Hz and env mod: Open303's measured mapping (scaler and offset lines), Q28 */
    /* Q24; with an integer knob (cut_q8 = CUT << 8) the same words as before MT24 */
    int64_t fc = (((uint32_t)cut_q8 << 16) + 63) / 127, e = (((uint32_t)env_q8 << 16) + 63) / 127;
    int64_t cc = OT_A0 + ((OT_A1 * fc) >> 24);
    int64_t slo = ((OT_SLOF * e) >> 24) + OT_SLOC, shi = ((OT_SHIF * e) >> 24) + OT_SHIC;
    int64_t sc = slo + (((shi - slo) * cc) >> 28);
    int64_t off = ((OT_OF * cc) >> 28) + OT_OC;
    int64_t l = ((OT_LOG50 * fc) >> 24) - ((sc * off) >> 28);
    c->l0_16 = q23(l, 28 + 4);
    c->es8 = q23(sc, 28 + 3);
    /* resonance: rs = (1 - e^-3r) / (1 - e^-3) */
    int64_t y = exp2q(-(int32_t)(k[OT_RES] * OT_RES_ARG24));
    int64_t rs = ((((int64_t)1 << 30) - y) * OT_RES_K) >> 30;
    if (rs > ((int64_t)1 << 30)) rs = (int64_t)1 << 30;
    c->rs = q23(rs, 30);
    int64_t rs2 = (rs * rs) >> 30;
    c->ag_8 = q23(((int64_t)1 << 30) - rs2, 33);
    int64_t p = (rs * (((int64_t)1 << 30) + rs)) >> 30;    /* rs (1 + rs), Q30 */
    c->bg = q23((p * OT_RCP17X8) >> 32, 30);                /* * 8 / 17 */
    /* volume: (VOL / 127)^2 */
    /* MT13: VOL 0 silent, 1..64 -30 dB .. the top level, 65..127 the top level driven 0 .. +4.5 dB (the
     * output drive / 8; 0: none, the DSP skips it); the soft attack faded by RES (MT10) */
    c->sc = (ot_w)(((int64_t)OT_SC[k[OT_VOL] & 127] * OT_RTRIM[k[OT_RES] & 127] + 8192) >> 14);   /* MT34: the RES trim */
    c->gd8 = k[OT_VOL] > 64 ? OT_GD8[(k[OT_VOL] & 127) - 65] : 0;
    c->rc1 = k[OT_RES] >= 115 ? 0 : OT_RC1[k[OT_RES] > 100 ? k[OT_RES] - 100 : 0];
    /* waveform: blend b = WAVE / 127; osc/2 = G (-(1 - b)/2 saw + b/4 tanh(..) + b sqDC / 4); MT29: G the WAVE
     * gain (Q14), which holds the saw's loudness across the blend (Open303 has none: the blends sound up to
     * 2-3 dB quieter) */
    uint32_t w = k[OT_WAVE];
    int64_t g = OT_WGAIN[w & 127];
    c->w1 = -(ot_w)(((int64_t)((((127 - w) << 22) + 63) / 127) * g + 8192) >> 14);
    c->w2 = (ot_w)(((int64_t)(((w << 21) + 63) / 127) * g + 8192) >> 14);
    c->w3 = -(ot_w)(((int64_t)((((w * (uint32_t)OT_SQDC4_MAG_Q30 + 63) / 127 + 64) >> 7)) * g + 8192) >> 14);
    c->sq = w ? 1 : 0;
}

unsigned ot_note_number(unsigned ptch) {
    return 12 + (ptch > OT_PTCH_MAX ? OT_PTCH_MAX : ptch);   /* a semitone a value: 0 C0 .. 72 C6 */
}

unsigned ot_note_name(unsigned ptch, char out[4]) {
    static const char nm[12][2] = {{'C', 0}, {'C', '#'}, {'D', 0}, {'D', '#'}, {'E', 0}, {'F', 0},
                                   {'F', '#'}, {'G', 0}, {'G', '#'}, {'A', 0}, {'A', '#'}, {'B', 0}};
    unsigned n = ot_note_number(ptch) - 12, s = n % 12, i = 0;
    out[i++] = nm[s][0];
    if (nm[s][1]) out[i++] = nm[s][1];
    out[i++] = (char)('0' + n / 12);
    out[i] = 0;
    return i;
}

void ot_params_note(const uint8_t k[12], struct ot_note *n) {
    /* pitch: A4 = 440 + (TUNE - 64) 80 / 127 Hz, f = A4 2^((note - 69) / 12), inc = 2 f / (4 fs):
     * (127 A4) * OT_INC12[s] >> (31 - o), the semitone's 2^(s/12) 2^54 / (127 * 88200) */
    int d = (int)ot_note_number(k[OT_PTCH]) - 69;
    int o = d >= 0 ? d / 12 : -((11 - d) / 12), s = d - 12 * o;
    int64_t t127 = 440 * 127 + ((int)k[OT_TUNE] - 64) * 80;
    unsigned sh = (unsigned)(31 - o);
    n->inc_t = clamp24((t127 * (int64_t)OT_INC12[s] + ((int64_t)1 << (sh - 1))) >> sh);
    /* accent: on when ACC > 0, amount ACC / 127 (Open303 triggerNote / slideToNote) */
    uint32_t a = k[OT_ACC];
    if (a) {
        meg(OT_X_ACC, n);                                   /* accent decay 200 ms */
        n->m_amp_off = OT_M_AMP_OFF_A;                      /* accent release 50 ms */
        n->ag8 = (ot_w)(((a << 20) + 63) / 127);            /* accentGain / 8 */
        n->agf = 0xffffff;
        n->k8_on = clamp24(OT_K8_BASE + (ot_w)(((a << 22) + 63) / 127));   /* (0.45 + 4 acc) / 8 */
    } else {
        /* decay 50 * 40^f ms (MT25: 50 ms .. 2 s; MT16 had Open303 VST's 200 ms .. 2 s): x = X0 2^(-f log2 40) */
        int64_t e2 = exp2q(-(int32_t)(k[OT_DEC] * OT_DEC_ARG24));
        meg((OT_X0 * e2) >> 30, n);
        n->m_amp_off = OT_M_AMP_OFF_N;                      /* release 2 ms (MT9) */
        n->ag8 = 0;
        n->agf = 0;
        n->k8_on = OT_K8_BASE;                              /* 0.45 / 8 */
    }
    n->m_amp_on = OT_M_AMP_ON;
    n->amp2 = OT_AMP2;
}

uint32_t ot_gate_samples(unsigned gate, uint32_t steplen) {
    return (uint32_t)(((uint64_t)steplen * (gate + 1)) >> 7);
}

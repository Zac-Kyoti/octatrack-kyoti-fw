/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti
 *
 * OT-303: the control record (record.h).
 */
#include "record.h"
#include "body_tables.h"
extern uint32_t ot_body_res_q8, ot_body_acc_q8;

ot_w ot_ease(ot_w s, ot_w t) {
    int32_t d = t - s;
    if (d > -8 && d < 8) return t;
    return s + d / 6;
}
static uint32_t pk(ot_w v) {
    uint32_t u = (uint32_t)v & 0xffffffu;
    return ((u & 0xffff00u) << 8) | (u & 0xffu);
}

/* the knobs ot_params_cont reads: only a change in one of these makes the continuous words again
 * (a PTCH lock or LFO changes k every step or frame and leaves them as they were) */
#define OT_CONT_KNOBS ((1u << OT_CUT) | (1u << OT_RES) | (1u << OT_ENV) | (1u << OT_WAVE) | \
                       (1u << OT_SLID) | (1u << OT_VOL))

void ot_record(volatile uint32_t *rec, struct ot_voice *v, const uint8_t k_in[12], unsigned ev, uint32_t gl,
               unsigned cut_q8, unsigned env_q8) {
    /* body: the RES knob through its taper (evenly spaced by the resonance's boost); params.c reads the 8.8 value, and
     * every other RES use (the level trim, the soft attack) the rounded one */
    /* body: the CUT knob: the real 303's range on knob 0 .. OT_CUT_KNEE, evenly in octaves, then the extension (8.8,
     * the lane's fraction kept) */
    const unsigned cut_knob = cut_q8;
    cut_q8 = cut_q8 <= OT_CUT_KNEE_Q8
        ? OT_CUT_LO_Q8 + (cut_q8 * (OT_CUT_HI_Q8 - OT_CUT_LO_Q8) + OT_CUT_KNEE_Q8 / 2) / OT_CUT_KNEE_Q8
        : OT_CUT_HI_Q8 + ((cut_q8 - OT_CUT_KNEE_Q8) * OT_CUT_EXT_Q8 + (127u * 256u - OT_CUT_KNEE_Q8) / 2) / (127u * 256u - OT_CUT_KNEE_Q8);
    uint32_t rq8 = OT_RES_TAPER_Q8[k_in[OT_RES] & 127];
    /* the resonance guard: in the CUT extension, the RES knob's span above OT_RES_EASE_KNOB eases toward it as CUT
     * rises (x1 at the knee .. x OT_RES_EASE_MIN at CUT 127); RES up to OT_RES_EASE_KNOB and CUT up to the knee as
     * they are */
    if (cut_knob > OT_CUT_KNEE_Q8 && (k_in[OT_RES] & 127) > OT_RES_EASE_KNOB) {
        uint32_t base = OT_RES_TAPER_Q8[OT_RES_EASE_KNOB];
        uint32_t f = ((uint32_t)(cut_knob - OT_CUT_KNEE_Q8) << 16) / (127u * 256u - OT_CUT_KNEE_Q8);   /* 0 .. 1, Q16 */
        if (f > 65536u) f = 65536u;
        uint32_t m = 65536u - (((65536u - OT_RES_EASE_MIN_Q16) * f) >> 16);
        rq8 = base + (((rq8 - base) * m) >> 16);
    }
    uint8_t k[12];
    for (unsigned i = 0; i < 12; ++i) k[i] = k_in[i];
    k[OT_RES] = (uint8_t)((rq8 + 128) >> 8);
    k[OT_CUT] = (uint8_t)((cut_q8 + 128) >> 8);
    ot_body_res_q8 = rq8;
    /* the ACCENT knob (the step's lock x the ACC scale) through its taper the same way (evenly spaced by the lift) */
    uint32_t aq8 = OT_ACC_TAPER_Q8[k_in[OT_ACC] & 127];
    k[OT_ACC] = (uint8_t)(aq8 ? ((aq8 + 128) >> 8 ? (aq8 + 128) >> 8 : 1) : 0);
    ot_body_acc_q8 = aq8;
    unsigned same = v->have != 0 && v->cut_q8 == cut_q8 && v->env_q8 == env_q8;
    for (unsigned i = 0; i < 12; ++i)
        if (v->k[i] != k[i]) { if (OT_CONT_KNOBS & (1u << i)) same = 0; v->k[i] = k[i]; }
    v->cut_q8 = cut_q8; v->env_q8 = env_q8;
    if (!same) {
        ot_params_cont_q8(k, cut_q8, env_q8, &v->c);
        if (!v->have) { v->rs = v->c.rs; v->bg = v->c.bg; v->ag_8 = v->c.ag_8; v->sc = v->c.sc; }
        v->have = 1;
    }
    const struct ot_cont *c = &v->c;
    /* MT20: RES steps (and locks) ease in instead of jumping at the frame: each word moves 1/6 of
     * the way a frame (tau ~2 ms; the engine glides the cutoff and env amount itself, per sample) */
    v->rs = ot_ease(v->rs, c->rs); v->bg = ot_ease(v->bg, c->bg); v->ag_8 = ot_ease(v->ag_8, c->ag_8);
    v->sc = ot_ease(v->sc, c->sc);                       /* MT34: the level follows RES through the trim */
    /* body: crossing VOL 64 / 65 the DSP changes path: the clean output, or the soft drive (GD8) with the level a
     * quarter (the drive's x4 makes it up). Switched in one frame, the engine's output smoothing ahead of the drive
     * still held the old level: a spike through the x4 going up (a pop), a dip going down (a click). Here the two trade
     * over a few frames instead, their product held: the level sent is the target x split, the drive / split, split
     * easing to 1 (going up: from 4, the drive entering at unity; going down: from 1/4, the drive leaving at unity once
     * the level is back). */
    ot_w sc_out = v->sc, gd8_out = c->gd8;
    {
        const unsigned want = c->gd8 != 0;
        /* a path change (or a reversal mid-way): the level jumps to its new target and split takes up the difference,
         * so the level sent this frame is last frame's */
        if (want && v->drv != 1) {
            v->sc = c->sc; v->drv = 1;
            v->split = v->sco && c->sc > 0 ? (((uint32_t)v->sco << 8) / ((uint32_t)c->sc >> 8 ? (uint32_t)c->sc >> 8 : 1)) : 1u << 16;
        } else if (!want && v->drv == 1) {
            v->sc = c->sc; v->drv = 3;
            v->split = v->sco && c->sc > 0 ? (((uint32_t)v->sco << 8) / ((uint32_t)c->sc >> 8 ? (uint32_t)c->sc >> 8 : 1)) : 1u << 16;
        }
        if (!v->split) v->split = 1u << 16;
        if (v->split != 1u << 16) {                                     /* eases to 1, a quarter of the way a frame */
            int32_t d = (int32_t)(1u << 16) - (int32_t)v->split;
            v->split = (d > -64 && d < 64) ? 1u << 16 : (uint32_t)((int32_t)v->split + d / 4);
        }
        if (v->drv == 3 && v->split == 1u << 16) v->drv = 0;           /* the level is back: the drive leaves at unity */
        if (v->split == 1u << 16) {                                     /* settled (every frame but a hand-over's) */
            sc_out = v->sc; gd8_out = v->drv == 1 ? c->gd8 : 0;
        } else {
            int64_t so = ((int64_t)v->sc * v->split) >> 16;
            sc_out = (ot_w)(so > 0x7fffff ? 0x7fffff : so);
            uint32_t g = v->drv == 1 ? (((uint32_t)c->gd8 << 8) / (v->split >> 8))   /* its gain / split */
                       : (uint32_t)((0x100000u << 8) / (v->split >> 8));                                 /* leaving: unity / split */
            gd8_out = (ot_w)(g > 0x7fffffu ? 0x7fffffu : g);
        }
        v->sco = sc_out;
    }
    /* body: the 303's accent sweep capacitor (Whittle; service notes D24 / R46 / VR4b / C13), a frame at a time: it
     * charges from the accent envelope only above ACCENT's threshold, charge and discharge by RES, and moves the
     * cutoff by the direct path (1 - RES) and the capacitor path (RES) */
    int64_t lw;
    {
        v->wmeg = (int32_t)(((int64_t)v->wmeg * OT_WOW_DECAY) >> 30);
        int64_t vin = ((int64_t)v->wmeg * v->wamt) >> 16;   /* the envelope through the threshold, Q30 */
        /* the split and the timing follow the RES pot's position the engine value stands for (the 303's VR4b gangs with
         * the RES pot), by knob */
        unsigned ri = k_in[OT_RES] & 127;
        if (vin > v->wcap) v->wcap += (int32_t)(((vin - v->wcap) * OT_WOW_CH[ri]) >> 30);
        v->wcap -= (int32_t)(((int64_t)v->wcap * OT_WOW_DIS[ri]) >> 30);
        int64_t od = (OT_WOW_D_Q16 * vin) >> 16, oc = (OT_WOW_C_Q16 * (int64_t)v->wcap) >> 16;   /* octaves, Q30 */
        uint32_t r16 = OT_RES_POT_Q16[ri];                  /* the RES pot's position, Q16 */
        int64_t oct = (od * (int64_t)(65536 - r16) + oc * (int64_t)r16) >> 16;
        lw = c->l0_16 + (((oct >> 11) * OT_LT_SCALE_Q20) >> 20);   /* octaves / 16 as a Q23 word, the table's scale */
        if (lw > 0x7fffff) lw = 0x7fffff;
        if (lw < -0x800000) lw = -0x800000;
        if (ev & OT_EV_OFF) v->wgl = 0;
        if (ev & OT_EV_NOTE) {
            if (!(ev & OT_EV_SLIDE) || v->wgl <= 0) {        /* a new accent (a slide into an open gate keeps it) */
                /* the ACCENT pot's position above the threshold, (a - thr) / (1 - thr), Q16; at a note only */
                uint32_t aq = OT_ACC_POS_Q16[k_in[OT_ACC] & 127];    /* the ACCENT pot's position the value stands for */
                v->wamt = aq > (uint32_t)OT_WOW_THR_Q16 ? (int32_t)(((aq - (uint32_t)OT_WOW_THR_Q16) << 15) / ((65536u - (uint32_t)OT_WOW_THR_Q16) >> 1)) : 0;
                if (k[OT_ACC]) v->wmeg = 1 << 30;
            }
            v->wgl = gl >= OT_GL_HELD ? 0x7fffffff : (int32_t)gl;
        }
        if (v->wgl != 0x7fffffff) v->wgl = v->wgl > 16 ? v->wgl - 16 : 0;
    }
    const ot_w cw[14] = {c->cs, c->es8, v->rs, v->bg, sc_out, c->sq, c->w1, c->w1, c->w2, c->w3, c->rc1, gd8_out, (ot_w)lw, v->ag_8};
    rec[0] = 0x33030000u | (++v->seq & 0xffffu);
    rec[1] = 0x09090000u | (ev & 7u);
    for (unsigned i = 0; i < 14; ++i) rec[2 + i] = pk(cw[i]);
    if (ev & OT_EV_NOTE) {
        struct ot_note n;
        ot_params_note(k, &n);
        const ot_w nw[11] = {n.c_meg, n.ag8, n.agf, n.k8_on, n.m_amp_off, (ot_w)gl, n.m_amp_on, n.inc_t, n.m48h, n.m48l, n.amp2};
        for (unsigned i = 0; i < 11; ++i) rec[16 + i] = pk(nw[i]);
    } else {
        for (unsigned i = 0; i < 11; ++i) rec[16 + i] = 0;
    }
    uint32_t off = v->chunk * OT_CHUNK, cnt = ot_ylen - off;
    if (cnt > OT_CHUNK) cnt = OT_CHUNK;
    rec[27] = pk((ot_w)(ot_ybeg + off));
    rec[28] = pk((ot_w)cnt);
    const uint32_t *src = &ot_ytab_pk[off];             /* packed at build time: a plain copy */
    volatile uint32_t *dst = &rec[29];
    for (uint32_t i = cnt; i; --i) *dst++ = *src++;
    for (uint32_t i = OT_CHUNK - cnt; i; --i) *dst++ = 0;
    v->chunk = off + cnt >= ot_ylen ? 0 : v->chunk + 1;
}

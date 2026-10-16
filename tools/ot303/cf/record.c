/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti
 *
 * OT-303: the control record (record.h).
 */
#include "record.h"

ot_w ot_ease_by(ot_w s, ot_w t, int32_t div) {
    int32_t d = t - s;
    if (d > -8 && d < 8) return t;
    return s + d / div;
}
ot_w ot_ease(ot_w s, ot_w t) { return ot_ease_by(s, t, 6); }

/* MT24: a knob turned by hand moves CUT and ENV one value (of 128) at a time, about half a semitone of
 * cutoff, which the DSP's 1 ms glide (MT15) let through as audible steps. Such small steps (1 or 2
 * values, outside a note's start) are eased here, 1/16 a frame (tau ~6 ms), so a turn sweeps; a
 * bigger jump or any change at a note (a p-lock) is sent at once, for the DSP's own 1 ms glide. */
#define OT_TURN_STEP 2
#define OT_TURN_DIV 16
static unsigned small_step(unsigned a, unsigned b) {
    return (a > b ? a - b : b - a) <= OT_TURN_STEP;
}
static uint32_t pk(ot_w v) {
    uint32_t u = (uint32_t)v & 0xffffffu;
    return ((u & 0xffff00u) << 8) | (u & 0xffu);
}

/* the knobs ot_params_cont reads: only a change in one of these makes the continuous words again
 * (a PTCH lock or LFO changes k every step or frame and leaves them as they were) */
#define OT_CONT_KNOBS ((1u << OT_CUT) | (1u << OT_RES) | (1u << OT_ENV) | (1u << OT_WAVE) | \
                       (1u << OT_SLID) | (1u << OT_VOL))

void ot_record(volatile uint32_t *rec, struct ot_voice *v, const uint8_t k[12], unsigned ev, uint32_t gl) {
    unsigned turn = v->have && !(ev & OT_EV_NOTE) && small_step(k[OT_CUT], v->k[OT_CUT]) &&
                    small_step(k[OT_ENV], v->k[OT_ENV]);
    unsigned same = v->have != 0;
    for (unsigned i = 0; i < 12; ++i)
        if (v->k[i] != k[i]) { if (OT_CONT_KNOBS & (1u << i)) same = 0; v->k[i] = k[i]; }
    if (!same) {
        ot_params_cont(k, &v->c);
        if (!v->have) { v->rs = v->c.rs; v->bg = v->c.bg; v->ag_8 = v->c.ag_8; v->es8 = v->c.es8; v->l0_16 = v->c.l0_16; }
        v->have = 1;
    }
    const struct ot_cont *c = &v->c;
    /* MT20: RES steps (and locks) ease in instead of jumping at the frame: each word moves 1/6 of
     * the way a frame (tau ~2 ms; the engine glides the cutoff and env amount itself, per sample) */
    v->rs = ot_ease(v->rs, c->rs); v->bg = ot_ease(v->bg, c->bg); v->ag_8 = ot_ease(v->ag_8, c->ag_8);
    if (turn) { v->es8 = ot_ease_by(v->es8, c->es8, OT_TURN_DIV); v->l0_16 = ot_ease_by(v->l0_16, c->l0_16, OT_TURN_DIV); }
    else { v->es8 = c->es8; v->l0_16 = c->l0_16; }
    const ot_w cw[14] = {c->cs, v->es8, v->rs, v->bg, c->sc, c->sq, c->w1, c->w1, c->w2, c->w3, c->rc1, c->gd8, v->l0_16, v->ag_8};
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

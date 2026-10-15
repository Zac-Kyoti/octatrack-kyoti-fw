/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti
 *
 * OT-303: the control record (record.h).
 */
#include "record.h"

ot_w ot_ease(ot_w s, ot_w t) {
    int32_t d = t - s;
    if (d > -8 && d < 8) return t;
    return s + d / 6;
}
static uint32_t pk(ot_w v) {
    uint32_t u = (uint32_t)v & 0xffffffu;
    return ((u & 0xffff00u) << 8) | (u & 0xffu);
}

void ot_record(volatile uint32_t *rec, struct ot_voice *v, const uint8_t k[12], unsigned ev, uint32_t gl) {
    unsigned same = v->have != 0;
    for (unsigned i = 0; i < 12; ++i) if (v->k[i] != k[i]) { same = 0; v->k[i] = k[i]; }
    if (!same) {
        ot_params_cont(k, &v->c);
        if (!v->have) { v->rs = v->c.rs; v->bg = v->c.bg; v->ag_8 = v->c.ag_8; }
        v->have = 1;
    }
    const struct ot_cont *c = &v->c;
    /* MT20: RES steps (and locks) ease in instead of jumping at the frame: each word moves 1/6 of
     * the way a frame (tau ~2 ms; the engine glides the cutoff and env amount itself, per sample) */
    v->rs = ot_ease(v->rs, c->rs); v->bg = ot_ease(v->bg, c->bg); v->ag_8 = ot_ease(v->ag_8, c->ag_8);
    const ot_w cw[14] = {c->cs, c->es8, v->rs, v->bg, c->sc, c->sq, c->w1, c->w1, c->w2, c->w3, c->rc1, c->gd8, c->l0_16, v->ag_8};
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
    for (unsigned i = 0; i < OT_CHUNK; ++i) rec[29 + i] = i < cnt ? pk((ot_w)ot_ytab[off + i]) : 0;
    v->chunk = off + cnt >= ot_ylen ? 0 : v->chunk + 1;
}

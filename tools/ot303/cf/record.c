/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac-Kyoti
 *
 * OT-303: the control record (record.h).
 */
#include "record.h"

static uint32_t pk(ot_w v) {
    uint32_t u = (uint32_t)v & 0xffffffu;
    return ((u & 0xffff00u) << 8) | (u & 0xffu);
}

void ot_record(volatile uint32_t *rec, struct ot_voice *v, const uint8_t k[12], unsigned ev, uint32_t gl) {
    unsigned same = v->have != 0;
    for (unsigned i = 0; i < 12; ++i) if (v->k[i] != k[i]) { same = 0; v->k[i] = k[i]; }
    if (!same) { ot_params_cont(k, &v->c); v->have = 1; }
    const struct ot_cont *c = &v->c;
    const ot_w cw[12] = {c->cs, c->es8, c->rs, c->bg, c->sc, c->sq, c->w1, c->w1, c->w2, c->w3, c->l0_16, c->ag_8};
    rec[0] = 0x33030000u;
    rec[1] = 0x09090000u | (ev & 3u);
    for (unsigned i = 0; i < 12; ++i) rec[2 + i] = pk(cw[i]);
    if (ev & OT_EV_NOTE) {
        struct ot_note n;
        ot_params_note(k, &n);
        const ot_w nw[11] = {n.c_meg, n.ag8, n.agf, n.k8_on, n.m_amp_off, (ot_w)gl, n.m_amp_on, n.inc_t, n.m48h, n.m48l, n.amp2};
        for (unsigned i = 0; i < 11; ++i) rec[14 + i] = pk(nw[i]);
    } else {
        for (unsigned i = 0; i < 11; ++i) rec[14 + i] = 0;
    }
    uint32_t off = v->chunk * OT_CHUNK, cnt = ot_ylen - off;
    if (cnt > OT_CHUNK) cnt = OT_CHUNK;
    rec[25] = pk((ot_w)(ot_ybeg + off));
    rec[26] = pk((ot_w)cnt);
    for (unsigned i = 0; i < OT_CHUNK; ++i) rec[27 + i] = i < cnt ? pk((ot_w)ot_ytab[off + i]) : 0;
    v->chunk = off + cnt >= ot_ylen ? 0 : v->chunk + 1;
}

/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac-Kyoti
 *
 * OT-303: the twelve knobs -> the DSP engine's host words (tools/ot303/twin.h's Engine fields), in
 * integer fixed point. One source for the ColdFire (tools/ot303/cf/control.c sends them in the
 * control record) and the native bench (tools/ot303/params_check.cpp holds it against Open303's
 * double-precision formulas; tools/ot303/host_probe.cpp drives the DSP and the twin with it).
 *
 * Knobs (0..127): SRC page   0 PTCH (64 = C2; semitones)  1 CUT (200 Hz..10 kHz, exp)
 *                            2 RES (0..100 %)             3 ENV (0..100 %)
 *                            4 DEC (30 ms..3 s, exp)      5 ACC (0..100 %; 0 = no accent)
 *                 SETUP      6 WAVE (saw..square)         7 TUNE (A4 = 400..480 Hz, 64 = 440)
 *                            8 SLID (0..198 ms)           9 GATE ((k + 1) / 128 of a step)
 *                           10 VOL ((k / 127)^2)         11 -
 */
#ifndef OT303_PARAMS_H
#define OT303_PARAMS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum { OT_PTCH, OT_CUT, OT_RES, OT_ENV, OT_DEC, OT_ACC, OT_WAVE, OT_TUNE, OT_SLID, OT_GATE, OT_VOL };

/* a host word: 24 bits, sign-extended */
typedef int32_t ot_w;

/* read every frame (they act at once, as Open303's setters do) */
struct ot_cont {
    ot_w cs, l0_16, es8, rs, ag_8, bg, sc, w1, w2, w3, sq;
};
/* latched at a note (Open303 reads them when a note starts or slides) */
struct ot_note {
    ot_w inc_t, c_meg, m_amp_on, m_amp_off, ag8, agf, k8_on, m48h, m48l, amp2;
};

void ot_params_cont(const uint8_t k[12], struct ot_cont *c);
void ot_params_note(const uint8_t k[12], struct ot_note *n);
/* the note PTCH plays: 36 (C2) at 64, clamped to 0..127 */
unsigned ot_note_number(unsigned ptch);
/* the gate of one step of `steplen` samples: (GATE + 1) / 128 of it */
uint32_t ot_gate_samples(unsigned gate, uint32_t steplen);

#ifdef __cplusplus
}
#endif
#endif

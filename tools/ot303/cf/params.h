/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti
 *
 * OT-303: the twelve knobs -> the DSP engine's host words (tools/ot303/twin.h's Engine fields), in
 * integer fixed point. One source for the ColdFire (tools/ot303/cf/control.c sends them in the
 * control record) and the native bench (tools/ot303/params_check.cpp holds it against Open303's
 * double-precision formulas; tools/ot303/host_probe.cpp drives the DSP and the twin with it).
 *
 * Knobs (0..127): SRC page   0 PTCH (0..96 only: a semitone a value, 0 C0, 36 C3, 96 C8; shown as
 *                              note names)                1 CUT (200 Hz..10 kHz, exp)
 *                            2 RES (0..100 %)             3 ENV (0..100 %)
 *                            4 DEC (200 ms..2 s, exp)     5 ACC (0..100 %; 0 = no accent)
 *                 SETUP      6 WAVE (saw..square)         7 TUNE (A4 = 400..480 Hz, 64 = 440)
 *                            8 SLID (0..198 ms)           9 GATE ((k + 1) / 128 of a step)
 *                           10 VOL (0 off, 1..64 -30 dB .. 0 dB, 65..127 driven 0 .. +4.5 dB; 99 = +2.5 dB)
 *                           11 - (MT13's OSC test switch, removed in MT15)
 * MT10 (not Open303): RES fades the soft attack out (1 ms to RES 100, none from 115).
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
    ot_w cs, l0_16, es8, rs, ag_8, bg, sc, w1, w2, w3, sq, rc1, gd8;
};
/* latched at a note (Open303 reads them when a note starts or slides) */
struct ot_note {
    ot_w inc_t, c_meg, m_amp_on, m_amp_off, ag8, agf, k8_on, m48h, m48l, amp2;
};

void ot_params_cont(const uint8_t k[12], struct ot_cont *c);
/* the same with CUT and ENV in 8.8 (a fraction between knob values; MT24): k's CUT / ENV are ignored */
void ot_params_cont_q8(const uint8_t k[12], unsigned cut_q8, unsigned env_q8, struct ot_cont *c);
void ot_params_note(const uint8_t k[12], struct ot_note *n);
/* the note PTCH plays: MIDI 12 (C0) + PTCH, the knob 0..96 (C0 .. C8, a semitone a value; MT13, the
 * user's choice); a larger value (a CC, an old project) plays C8 */
#define OT_PTCH_MAX 96u
unsigned ot_note_number(unsigned ptch);
/* its name for the knob's display: "C3", "C#3" (NUL-terminated); returns the length */
unsigned ot_note_name(unsigned ptch, char out[4]);
/* the gate of one step of `steplen` samples: (GATE + 1) / 128 of it */
uint32_t ot_gate_samples(unsigned gate, uint32_t steplen);

#ifdef __cplusplus
}
#endif
#endif

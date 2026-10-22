#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# BLACKPYRAMIDS_303's voice: the ColdFire constants and tables, generated from the fitted version
# (tools/ot303/body/data/voice.json: fitted against Din Sync's recordings of a real TB-303 on the circuit's coupling;
# tools/ot303/body/data/knob_curves.json: the RES / ACCENT effect curves, evenknob.py) and the author's listening
# choices, into tools/ot303/cf/body_tables.h, and the DSP's X constants as a JSON for hwprobe_image
# (tools/ot303/cf/body_dsp.json). Every value traces to a fitted, measured or circuit number (reference/BLACKPYRAMIDS_303.md).
#   gen_body.py [VERSION.json]
import json, math, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'tools', 'ot303', 'body', 'data', 'voice.json')
FIX = {'hp1_hz': 0.7, 'acc_t20': 0.157, 'amp_tau': 1.35, 'env_r': 0.0, 'wow_rd': 1, 'wow_thr': 0.4}   # (K fits carry them in values)
# the level by cutoff (the author's B8 choice, option C): FINAL's loudness-vs-cutoff curve -- the CUT knob mainly
# changes the tone -- with the headroom margin kept at the bright end (SC x (fc / 1 kHz)^LG_P x SC_MULT; the fitted,
# 303-like exponent was +0.14 with x0.6: ~6 dB quieter at the bottom). A level change only: every note's tone and
# shape are the fit's (tools/ot303/body: the tone-only score is the same).
LG_P_BUILD, SC_MULT = -0.05, 0.93
CUT_KNEE, CUT_EXT_OCT = 100, 1.0                  # B9: the real 303's CUT range on knob 0..100, an octave more on 101..127
# the resonance guard in the CUT extension (the author's choice after B9): only RES above RES_EASE_KNOB, only with CUT
# above the knee; the RES knob's span above RES_EASE_KNOB scales from x1 at CUT 100 to x RES_EASE_MIN at CUT 127 (never
# flat: every RES step still moves)
RES_EASE_KNOB, RES_EASE_MIN = 100, float(os.environ.get('RES_EASE_MIN', 0.5))
# more level into the VOL drive (the author's choice after B10): VOL 65..127 run the level 12 dB down into the soft drive;
# this adds DRIVE_DB there, ramped in dB from 0 at VOL 65 to the whole of it at DRIVE_FULL_VOL (no jump at VOL 64 / 65),
# flat above. Measured: no hard clipping anywhere in the engine (the 1,440-accent sweep); against Din Sync at VOL 99
# the accent peaks stay as near the real 303's as without it (tools/ot303/body/drivecheck.py).
DRIVE_DB, DRIVE_FULL_VOL = float(os.environ.get('DRIVE_DB', 3.0)), 99
LT_BASE, LT_SPO = 70.0, 26.0                      # the cutoff table: floor 70 Hz (Din Sync: the 303 closes below 200 Hz;
                                                  # 70 and 50 score alike), 26 entries an octave -> 215 entries reach 21 kHz
FS = 44100.0

def q(v, b): return int(round(v * (1 << b)))

def main():
    J = json.load(open(SRC)); v = dict(FIX); v.update(J['values']); law = J['law']   # the fit's values win (K5: wow_thr 0.6)
    v['lg_p'] = float(os.environ.get('LG_P', LG_P_BUILD))                          # (LG_P: exploration)
    sc_mult = float(os.environ.get('SC_MULT', SC_MULT))
    # the RES and ACCENT knobs, spaced evenly by what they do (tools/ot303/body/evenknob.py: the resonance's boost, the
    # accent's lift, measured on this voice): equal turns, equal steps of effect, over the same range (0 .. the real
    # 303's top). Only where a sound sits on the knob changes: the parts of the accent sweep that hang on the 303's
    # pots (the split, the timing, the threshold) read the pot position the engine value stands for, through the
    # fitted laws, so every engine value sounds as before.
    res_law, acc_law = law['res'], law['acc']   # real-303 % 0/25/50/75/100 -> the engine's RES / ACCENT
    KC = json.load(open(os.path.join(ROOT, 'tools', 'ot303', 'body', 'data', 'knob_curves.json')))
    def even(curve, k0, k1, e0):
        e = np.array([c[0] for c in curve], float); v = np.maximum.accumulate(np.array([c[1] for c in curve], float))
        out = []
        for k in range(k0, 128):
            t = v[0] + (k - k0) / (127 - k0) * (v[-1] - v[0])
            out.append(max(e0, float(np.interp(t, v, e))) if t < v[-1] else float(e[-1]))
        return out
    pot = lambda E, lw: float(np.interp(E, lw, [0, 25, 50, 75, 100])) / 100.0
    res_e = even(KC['res'], 0, 127, 0.0)                         # engine RES by knob 0..127
    acc_e = [0.0] + even(KC['acc'], 1, 127, 1.0)                 # engine ACCENT by knob (0: no accent)
    if os.environ.get('KNOBS') == 'pot':                         # the check's reference: the knobs as the 303's pots (B8's)
        res_e = [float(np.interp(k / 127 * 100, [0, 25, 50, 75, 100], res_law)) for k in range(128)]
        acc_e = [0.0] + [max(1.0, float(np.interp(k / 127 * 100, [0, 25, 50, 75, 100], acc_law))) for k in range(1, 128)]
    taper = [int(round(256 * e)) for e in res_e]
    res_pot = [pot(e, res_law) for e in res_e]
    acc_taper = [0] + [max(256, int(round(256 * e))) for e in acc_e[1:]]
    acc_pot = [0.0] + [pot(e, acc_law) for e in acc_e[1:]]
    # the accent sweep capacitor: per-frame (16 samples) charge / discharge coefficients by the RES pot (the knob's)
    ch = [1 - math.exp(-16 / ((85.0 - 35.0 * r) * 44.1)) for r in res_pot]
    dis = [1 - math.exp(-16 / ((150.0 - 50.0 * r) * 44.1)) for r in res_pot]
    decay = math.exp(-math.log(10) * 16 / (v['acc_t20'] * FS))
    # level by cutoff and the ring law: factors by CUT knob (0..128, interpolated by the 8.8 fraction)
    fc = [200.0 * 50 ** (c / 127) for c in range(129)]
    lg = [(f / 1000.0) ** v['lg_p'] for f in fc]
    ring = [(f / 1000.0) ** v['ring_q'] for f in fc]
    L = []
    L.append('/* SPDX-License-Identifier: MIT\n * SPDX-FileCopyrightText: 2026 Zac Kyoti\n *')
    L.append(' * GENERATED by tools/ot303/body/gen_body.py from %s -- do not edit.' % os.path.relpath(SRC, ROOT))
    L.append(' * BLACKPYRAMIDS_303: the voice\'s ColdFire constants and tables (params.c, record.c). */')
    L.append('#ifndef OT_BODY_TABLES_H\n#define OT_BODY_TABLES_H\n#include <stdint.h>')
    L.append('/* the RES knob, evenly spaced by the resonance\'s boost (0 .. engine %g = the real 303\'s top), 8.8, and the RES pot\'s position each knob value stands for (Q16, the fitted law %s inverted) */' % (res_e[-1], res_law))
    L.append('static const uint16_t OT_RES_TAPER_Q8[128] = {%s};' % ', '.join(map(str, taper)))
    L.append('static const uint32_t OT_RES_POT_Q16[128] = {%s};' % ', '.join(str(q(x, 16)) for x in res_pot))
    L.append('/* the ACCENT knob, evenly spaced by the accent\'s lift (0 = no accent .. engine %g = the real 303\'s top), 8.8, and the ACCENT pot\'s position (Q16, the law %s inverted) */' % (acc_e[-1], acc_law))
    L.append('static const uint16_t OT_ACC_TAPER_Q8[128] = {%s};' % ', '.join(map(str, acc_taper)))
    L.append('static const uint32_t OT_ACC_POS_Q16[128] = {%s};' % ', '.join(str(q(x, 16)) for x in acc_pot))
    L.append('/* the accent sweep capacitor (Whittle / service notes): charge 85 -> 50 ms, discharge 150 -> 100 ms by the RES pot, Q30 a frame, by RES knob */')
    L.append('static const int32_t OT_WOW_CH[128] = {%s};' % ', '.join(str(q(x, 30)) for x in ch))
    L.append('static const int32_t OT_WOW_DIS[128] = {%s};' % ', '.join(str(q(x, 30)) for x in dis))
    L.append('#define OT_WOW_DECAY (%dLL)        /* the accent envelope a frame, Q30: -20 dB in %.3f s */' % (q(decay, 30), v['acc_t20']))
    L.append('#define OT_WOW_D_Q16 (%dLL)       /* the direct path, octaves at full accent, Q16: %.3f */' % (q(v['wow_d'], 16), v['wow_d']))
    L.append('#define OT_WOW_C_Q16 (%dLL)       /* the capacitor path: %.3f */' % (q(v['wow_c'], 16), v['wow_c']))
    L.append('#define OT_WOW_THR_Q16 (%dLL)     /* ACCENT below this fraction does not conduct: %.2f */' % (q(v['wow_thr'], 16), v['wow_thr']))
    L.append('/* level by cutoff (fc / 1 kHz)^%.3f and the ring law\'s (fc / 1 kHz)^%.3f, Q20, by CUT knob 0..128 */' % (v['lg_p'], v['ring_q']))
    L.append('static const int32_t OT_LG[129] = {%s};' % ', '.join(str(q(x, 20)) for x in lg))
    L.append('static const int32_t OT_RINGF[129] = {%s};' % ', '.join(str(q(x, 20)) for x in ring))
    L.append('#define OT_RING_D_Q20 (%dLL)      /* rs x (1 - ring_d RES/127 RINGF): ring_d %.3f */' % (q(v['ring_d'], 20), v['ring_d']))
    L.append('#define OT_G_MULT_Q20 (%dLL)      /* the make-up gain BG x %.3f */' % (q(v['g_mult'], 20), v['g_mult']))
    L.append('#define OT_K8_MULT_Q20 (%dLL)     /* the accent VCA K8 x %.3f */' % (q(v['k8_mult'], 20), v['k8_mult']))
    L.append('#define OT_SC_MULT_Q20 (%dLL)     /* the output scaler x %.2f */' % (q(sc_mult, 20), sc_mult))
    tau_acc = v['acc_t20'] / math.log(10)
    L.append('#define OT_X_ACC_BODY (%dLL)      /* accent MEG 1 / (tau fs), Q41: tau %.2f ms (the service notes: 68 ms) */' % (q(1 / (tau_acc * FS), 41), tau_acc * 1000))
    L.append('#define OT_M_AMP_ON_BODY (%d)     /* the VCA decay while held, Q23: tau %.2f s */' % (min(q(math.exp(-1 / (v['amp_tau'] * FS)), 23), 0x7fffff), v['amp_tau']))
    cut_law = law['cut']                          # real-303 % 0/25/50/75/100 -> the engine's CUT (8.8)
    ext_q8 = int(round(CUT_EXT_OCT * 127 * 256 / math.log2(50)))   # the engine's base cutoff: 127 / log2(50) a octave
    L.append('/* the CUT knob (the author\'s B9 choice): the real 303\'s range (engine %g .. %g, real 0 .. 100 %%) on knob 0 .. %d, evenly in octaves (the engine\'s base cutoff is log-linear in it), then %g octave more on %d .. 127 */' % (cut_law[0] / 256, cut_law[-1] / 256, CUT_KNEE, CUT_EXT_OCT, CUT_KNEE))
    L.append('#define OT_CUT_LO_Q8 %du' % int(round(cut_law[0])))
    L.append('#define OT_CUT_HI_Q8 %du' % int(round(cut_law[-1])))
    L.append('#define OT_CUT_KNEE_Q8 %du' % (CUT_KNEE * 256))
    L.append('#define OT_CUT_EXT_Q8 %du         /* the extension, engine 8.8 */' % ext_q8)
    drv = [10 ** (DRIVE_DB * min(1.0, (vol - 65) / (DRIVE_FULL_VOL - 65)) / 20) for vol in range(65, 128)]
    L.append('/* more level into the VOL drive, VOL 65..127, Q20: +%g dB ramped from VOL 65 to %d */' % (DRIVE_DB, DRIVE_FULL_VOL))
    L.append('static const int32_t OT_DRIVE_Q20[63] = {%s};' % ', '.join(str(q(x, 20)) for x in drv))
    L.append('#define OT_RES_EASE_KNOB %du      /* the resonance guard: RES knob above this, CUT knob above the knee ... */' % RES_EASE_KNOB)
    L.append('#define OT_RES_EASE_MIN_Q16 %du   /* ... the span above it x 1 -> x %g at CUT 127 */' % (q(RES_EASE_MIN, 16), RES_EASE_MIN))
    L.append('#define OT_LT_BASE_HZ %g          /* the cutoff table floor, entries an octave: %g */' % (LT_BASE, LT_SPO))
    L.append('#define OT_LT_OFF_Q23 (%dLL)      /* log2(200 / floor) / 16 */' % q(math.log2(200.0 / LT_BASE) / 16, 23))
    L.append('#define OT_LT_SCALE_Q20 (%dLL)    /* the cutoff words x entries an octave / 32 */' % q(LT_SPO / 32.0, 20))
    L.append('#endif')
    open(os.environ.get('BODY_TABLES', os.path.join(ROOT, 'tools', 'ot303', 'cf', 'body_tables.h')), 'w').write('\n'.join(L) + '\n')
    json.dump({'res_q8': taper, 'acc_q8': acc_taper, 'cut_lo_q8': cut_law[0], 'cut_hi_q8': cut_law[-1], 'cut_knee': CUT_KNEE}, open(os.environ.get('BODY_KNOBS', os.path.join(ROOT, 'out', 'body', 'body_knobs.json')), 'w'))
    kp = [[200, v['kp200']], [500, v['kp500']], [1200, v['kp1200']], [3000, v['kp3000']]]
    json.dump({'fb_hz': v['fb_hz'], 'hp1_hz': v['hp1_hz'], 'hp2_hz': v['hp2_hz'], 'c2_ms': v['c2_ms'], 'kp_pts': kp, 'ag_mult': v['ag_mult'],
               'lt_base': LT_BASE, 'lt_spo': LT_SPO, 'source': os.path.relpath(SRC, ROOT)}, open(os.environ.get('BODY_DSP', os.path.join(ROOT, 'tools', 'ot303', 'cf', 'body_dsp.json')), 'w'), indent=1)
    print('wrote cf/body_tables.h and cf/body_dsp.json from', os.path.relpath(SRC, ROOT))
    print({k: round(v[k], 3) for k in ('fb_hz', 'hp2_hz', 'c2_ms', 'g_mult', 'k8_mult', 'ag_mult', 'lg_p', 'ring_d', 'ring_q', 'wow_d', 'wow_c')})

if __name__ == '__main__':
    main()

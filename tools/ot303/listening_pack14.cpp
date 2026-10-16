// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 listening pack round 14 (tools/ot303/listening_pack14.py): WAVE loudness. The machine as MT28 plays
// it (params.c's words, the host's note rules, the integer twin with the engine's own drive), with WAVE moving
// through the clip; listening_pack14.py builds it twice, with MT28's params.c and with MT29's (the WAVE gain).
//   listening_pack14 OUT.f32 SCENE CUT RES VOL
// SCENE: sweep  WAVE 0 for a bar, then rising to 127 over three bars, then 127
//        alt64  bars alternate WAVE 0 and WAVE 64     alt127  WAVE 0 and 127     alt96  WAVE 0 and 96
// Writes mono float, 44.1 kHz.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "halfband4x.h"
#include "halfband2x.h"
#include "twin.h"
#include "params.h"

struct St { char kind; int dp; bool slide, acc; };   // N note, T tie, R rest; dp semitones from the root
static const St ACID[16] = {{'N', 0, false, true}, {'T', 0, false, false}, {'N', 12, true, false}, {'N', 0, false, false},
                            {'R', 0, false, false}, {'N', 3, true, false}, {'N', 7, false, true}, {'N', 0, false, false},
                            {'N', 0, false, true}, {'N', 10, true, false}, {'N', 0, false, false}, {'N', -2, false, false},
                            {'N', 0, true, true}, {'N', 12, false, false}, {'N', 0, false, false}, {'N', 5, true, false}};
static const long STEP = 5088;   // a 16th at 130 BPM
static const int BARS = 7;

int main(int argc, char** argv) {
    if (argc < 6) { std::printf("usage: listening_pack14 OUT.f32 SCENE CUT RES VOL\n"); return 2; }
    const std::string scene = argv[2];
    const int CUT = std::atoi(argv[3]), RES = std::atoi(argv[4]), VOL = std::atoi(argv[5]);
    const int other = scene == "alt64" ? 64 : scene == "alt96" ? 96 : 127;
    auto waveAt = [&](long step) -> int {          // WAVE for a step
        if (scene == "sweep") {
            if (step < 16) return 0;
            if (step >= 64) return 127;
            return int((step - 16) * 127 / 47);
        }
        return (step / 16) & 1 ? other : 0;
    };
    twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
    e.C2 = 0x7fce80;
    { double x = std::exp(-2.0 * M_PI * 350.0 / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
    const long N = BARS * 16 * STEP + 22050;
    std::vector<float> out(N);
    long evc = 0x7fffff; int half = 0; twin::W moff = 0;
    uint8_t k[12];
    auto knobs = [&](long step, uint8_t* kk) {
        const St& st = ACID[step & 15];
        const uint8_t base[12] = {(uint8_t)(36 + st.dp), (uint8_t)CUT, (uint8_t)RES, 70, 60, (uint8_t)(st.acc ? 100 : 0),
                                  (uint8_t)waveAt(step), 64, 38, 63, (uint8_t)VOL, 0};
        std::memcpy(kk, base, 12);
    };
    knobs(0, k);
    for (long t = 0; t < N; t++) {
        long step = t / STEP; bool onStep = t % STEP == 0 && step < BARS * 16;
        int s = int(step & 15);
        if (t % 16 == 0) {                            // the frame's continuous words; WAVE follows the step
            long st = (t + 15) / STEP;
            if (st * STEP < t + 16 && st < BARS * 16 && ACID[st & 15].kind == 'N') knobs(st, k);
            k[OT_WAVE] = uint8_t(waveAt(std::min<long>(st, BARS * 16 - 1)));
            ot_cont c; ot_params_cont(k, &c);
            e.CS = c.cs; e.BG = c.bg; e.SC = c.sc; e.SQ = c.sq != 0;
            e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3;
            e.RC1 = c.rc1; e.GD8 = c.gd8;
            e.L0_16 = c.l0_16; e.ES8 = c.es8; e.RS = c.rs; e.AG_8 = c.ag_8;
        }
        if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
        if (onStep && ACID[s].kind == 'N') {
            int count = 1, nx = s;
            for (int i = 1; i < 16; i++) { nx = (nx + 1) & 15; if (ACID[nx].kind != 'T') break; count++; }
            bool hold = ACID[nx].kind == 'N' && ACID[nx].slide;
            knobs(step, k);
            long gl = hold ? (count + 1) * STEP : (count - 1) * STEP + ot_gate_samples(k[OT_GATE], STEP);
            ot_note nn; ot_params_note(k, &nn);
            e.C_MEG = nn.c_meg; e.AG8 = nn.ag8; e.AGF = nn.agf != 0; e.K8 = nn.k8_on; moff = nn.m_amp_off; evc = gl;
            e.INC_T = nn.inc_t;
            if (!(ACID[s].slide && half)) {
                e.M_AMP = nn.m_amp_on; e.S48 = twin::acc(nn.inc_t);
                e.M48 = (twin::A(nn.m48h) << 24) | (uint32_t(nn.m48l) & 0xffffff); e.AMP2 = nn.amp2; half = 1;
            }
        }
        e.tick();
        out[t] = float(twin::f23(e.outW));
        evc--;
    }
    FILE* f = std::fopen(argv[1], "wb");
    std::fwrite(out.data(), sizeof(float), out.size(), f); std::fclose(f);
    return 0;
}

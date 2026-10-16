// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 listening pack round 15 (tools/ot303/listening_pack15.py): output headroom. The machine as MT32
// plays it (params.c's words, the host's note rules, the integer twin with the engine's own drive) on the acid
// line, as built or with the voice's output stage given K times the headroom: the amp scaler SC / K and the
// drive gain x K (at clean VOL the drive stage switched on at unity), so tanh(g y) sees what the hard clip
// before it used to chop.
//   listening_pack15 OUT.f32 CUT RES ENV VOL ACC K [KNEE]
// KNEE (round 16, clean VOL): the output stage gets K x headroom with the drive off, and the voice comes out
// through a soft knee instead, simulated in double after the engine: linear up to KNEE (of full scale), then
// KNEE + (1 - KNEE) tanh((|y| - KNEE) / (1 - KNEE)) toward the ceiling (slope 1 at the knee).
// ACC: the accented steps' amount (the knob x lock / 127, as the renderer sends it). Writes mono float, 44.1 kHz.
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
    if (argc < 8) { std::printf("usage: listening_pack15 OUT.f32 CUT RES ENV VOL ACC K\n"); return 2; }
    const std::string scene = "steady";
    const int CUT = std::atoi(argv[2]), RES = std::atoi(argv[3]), ENV = std::atoi(argv[4]), VOL = std::atoi(argv[5]),
              ACCV = std::atoi(argv[6]);
    const double K = std::atof(argv[7]);
    const double KNEE = argc > 8 ? std::atof(argv[8]) : 0.0;
    auto waveAt = [&](long) -> int { return 0; };
    twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
    e.C2 = 0x7fce80;
    { double x = std::exp(-2.0 * M_PI * 350.0 / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
    const long N = BARS * 16 * STEP + 22050;
    std::vector<float> out(N);
    long evc = 0x7fffff; int half = 0; twin::W moff = 0;
    uint8_t k[12];
    auto knobs = [&](long step, uint8_t* kk) {
        const St& st = ACID[step & 15];
        const uint8_t base[12] = {(uint8_t)(36 + st.dp), (uint8_t)CUT, (uint8_t)RES, (uint8_t)ENV, 60, (uint8_t)(st.acc ? ACCV : 0),
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
            if (KNEE > 0 && c.sc) {                   // round 16: K x headroom, no drive, the knee below
                e.SC = twin::W(std::lround(c.sc / K));
                e.GD8 = 0;
            } else if (K > 1 && c.sc) {               // the candidate: K x headroom, the soft clip always on
                e.SC = twin::W(std::lround(c.sc / K));
                e.GD8 = c.gd8 ? twin::W(std::lround(c.gd8 * K)) : twin::q23(K / 8.0);
            }
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
        double y = twin::f23(e.outW);
        if (KNEE > 0) {
            y *= K;
            double a = std::fabs(y);
            if (a > KNEE) y = (y < 0 ? -1 : 1) * (KNEE + (1 - KNEE) * std::tanh((a - KNEE) / (1 - KNEE)));
        }
        out[t] = float(y);
        evc--;
    }
    std::fprintf(stderr, "saturations %ld\n", twin::g_sat);
    FILE* f = std::fopen(argv[1], "wb");
    std::fwrite(out.data(), sizeof(float), out.size(), f); std::fclose(f);
    return 0;
}

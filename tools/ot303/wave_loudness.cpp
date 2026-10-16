// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// BLACKPYRAMIDS_303's loudness against WAVE (tools/ot303/wave_loudness.py): the machine's words (params.c),
// the host's note rules and the integer twin (bit-exact with the DSP engine; feedback high-pass 350 Hz,
// the engine's own output drive from VOL), one render per WAVE value 0..127 at one CUT / RES / VOL.
//   wave_loudness OUT.f32 SCENE CUT RES VOL PTCH [GAINS]
// SCENE: acid (the 16-step line with accents, slides, a rest and a tie) or held (a note every 4 steps,
// tied: steady tones). Writes 128 blocks of 0.5 s lead-in + 2 bars (mono float, 44.1 kHz), WAVE 0 first.
// GAINS: a text file of 128 dB values, a candidate WAVE gain applied to the oscillator words (W1..W3)
// here, before params.c carries one.
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
static const St HELD[16] = {{'N', 0, false, false}, {'T', 0, false, false}, {'T', 0, false, false}, {'T', 0, false, false},
                            {'N', 3, false, false}, {'T', 0, false, false}, {'T', 0, false, false}, {'T', 0, false, false},
                            {'N', -2, false, false}, {'T', 0, false, false}, {'T', 0, false, false}, {'T', 0, false, false},
                            {'N', 5, false, false}, {'T', 0, false, false}, {'T', 0, false, false}, {'T', 0, false, false}};
static const St ACID[16] = {{'N', 0, false, true}, {'T', 0, false, false}, {'N', 12, true, false}, {'N', 0, false, false},
                            {'R', 0, false, false}, {'N', 3, true, false}, {'N', 7, false, true}, {'N', 0, false, false},
                            {'N', 0, false, true}, {'N', 10, true, false}, {'N', 0, false, false}, {'N', -2, false, false},
                            {'N', 0, true, true}, {'N', 12, false, false}, {'N', 0, false, false}, {'N', 5, true, false}};
static const long STEP = 5088;   // a 16th at 130 BPM
static const long LEAD = 22050, BLOCK = LEAD + 2 * 16 * STEP;

int main(int argc, char** argv) {
    if (argc < 7) { std::printf("usage: wave_loudness OUT.f32 acid|held CUT RES VOL PTCH [GAINS]\n"); return 2; }
    const bool acid = !std::strcmp(argv[2], "acid");
    const St* L = acid ? ACID : HELD;
    const int CUT = std::atoi(argv[3]), RES = std::atoi(argv[4]), VOL = std::atoi(argv[5]), PTCH = std::atoi(argv[6]);
    double gdb[128] = {0};
    if (argc > 7) {
        FILE* g = std::fopen(argv[7], "r");
        for (int i = 0; i < 128; i++) if (!g || std::fscanf(g, "%lf", &gdb[i]) != 1) { std::printf("bad GAINS\n"); return 2; }
        std::fclose(g);
    }
    std::vector<float> out(128 * BLOCK);
    for (int wv = 0; wv < 128; wv++) {
        twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
        e.C2 = 0x7fce80;
        { double x = std::exp(-2.0 * M_PI * 350.0 / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
        const double g = std::pow(10.0, gdb[wv] / 20.0);
        long evc = 0x7fffff; int half = 0; twin::W moff = 0;
        uint8_t k[12];
        auto knobs = [&](int s, uint8_t* kk) {
            const St& st = L[s & 15];
            const uint8_t base[12] = {(uint8_t)(PTCH + st.dp), (uint8_t)CUT, (uint8_t)RES, 70, 60, (uint8_t)(st.acc ? 100 : 0),
                                      (uint8_t)wv, 64, 38, 63, (uint8_t)VOL, 0};
            std::memcpy(kk, base, 12);
        };
        knobs(0, k);
        // the line starts LEAD samples before the measured 2 bars, at step 0 (so the bars are steps 4.33..)
        for (long t = 0; t < BLOCK; t++) {
            long step = t / STEP; bool onStep = t % STEP == 0;
            int s = int(step & 15);
            if (t % 16 == 0) {                        // the frame's continuous words (the frame of a note: its knobs)
                long st = (t + 15) / STEP;
                if (st * STEP < t + 16 && L[st & 15].kind == 'N') knobs(int(st), k);
                ot_cont c; ot_params_cont(k, &c);
                e.CS = c.cs; e.BG = c.bg; e.SC = c.sc; e.SQ = c.sq != 0;
                e.W1 = twin::W(std::lround(c.w1 * g)); e.W2 = twin::W(std::lround(c.w2 * g)); e.W3 = twin::W(std::lround(c.w3 * g));
                e.RC1 = c.rc1; e.GD8 = c.gd8;
                e.L0_16 = c.l0_16; e.ES8 = c.es8; e.RS = c.rs; e.AG_8 = c.ag_8;
            }
            if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
            if (onStep && L[s].kind == 'N') {
                int count = 1, nx = s;
                for (int i = 1; i < 16; i++) { nx = (nx + 1) & 15; if (L[nx].kind != 'T') break; count++; }
                bool hold = L[nx].kind == 'N' && L[nx].slide;
                knobs(s, k);
                long gl = hold ? (count + 1) * STEP : (count - 1) * STEP + ot_gate_samples(k[OT_GATE], STEP);
                ot_note nn; ot_params_note(k, &nn);
                e.C_MEG = nn.c_meg; e.AG8 = nn.ag8; e.AGF = nn.agf != 0; e.K8 = nn.k8_on; moff = nn.m_amp_off; evc = gl;
                e.INC_T = nn.inc_t;
                if (!(L[s].slide && half)) {
                    e.M_AMP = nn.m_amp_on; e.S48 = twin::acc(nn.inc_t);
                    e.M48 = (twin::A(nn.m48h) << 24) | (uint32_t(nn.m48l) & 0xffffff); e.AMP2 = nn.amp2; half = 1;
                }
            }
            e.tick();
            out[wv * BLOCK + t] = float(twin::f23(e.outW));
            evc--;
        }
    }
    std::fprintf(stderr, "saturations %ld", twin::g_sat);
    for (auto& pk : twin::g_peak) if (pk.second >= 0.9) std::fprintf(stderr, "  %s %.3f", pk.first.c_str(), pk.second);
    std::fprintf(stderr, "\n");
    FILE* f = std::fopen(argv[1], "wb");
    std::fwrite(out.data(), sizeof(float), out.size(), f); std::fclose(f);
    return 0;
}

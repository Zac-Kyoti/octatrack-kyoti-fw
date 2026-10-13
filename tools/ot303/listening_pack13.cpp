// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 listening pack round 13 (tools/ot303/listening_pack13.py): the machine as MT13 plays it (params.c's
// words, the host's note rules, the integer twin; the saw free-running, VOL 99 = drive +2.5 dB) and
// candidates for two reports from MT12 on the unit:
//   bass lost as RES rises (scene "sweep": RES 0 -> 127 over the clip):
//     makeup   the output scaled up by RES to hold RES 0's loudness (the loss measured on the twin: -4.6 dB
//              at RES 8, about -10 dB from RES 64), before the drive
//     fb350    the resonance feedback's high-pass 150 -> 350 Hz (less bass fed back, so less cancelled)
//     gentle   the RES knob's curve gentler at the bottom (RES' = RES^2 / 127: RES 32 acts as 8 does now)
//   pops on big lock / LFO jumps inside held notes (scene "jumps": a note every 4 steps, tied; CUT, ENV and
//   RES jump on every step, as trigless locks or a square / random LFO do):
//     sm1, sm3 the cutoff, env amount and resonance words glide to each new value (a one-pole, 1 ms /
//              3 ms) instead of jumping at the frame
// The drive is applied here as tanh(G y) after the makeup (the engine's own drive gets GD8 0).
//   listening_pack13 OUTDIR   writes SCENE.VARIANT.f32 (mono, 44.1 kHz)
#include <cmath>
#include <cstdio>
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
static const int BARS = 6;

struct Var { const char* name; double fbhz; bool makeup, gentle; double smms; };
static const Var VARS[] = {
    {"base", 150, false, false, 0}, {"makeup", 150, true, false, 0}, {"fb350", 350, false, false, 0},
    {"gentle", 150, false, true, 0}, {"sm1", 150, false, false, 1.0}, {"sm3", 150, false, false, 3.0},
};
// the loss measured on the twin (the line, CUT 30 and 60, dB) at RES 0 8 16 32 64 96 127
static double makeupDb(double res) {
    static const double R[7] = {0, 8, 16, 32, 64, 96, 127}, D[7] = {0, 4.6, 6.9, 8.8, 9.9, 10.1, 9.9};
    for (int i = 1; i < 7; i++) if (res <= R[i]) return D[i - 1] + (D[i] - D[i - 1]) * (res - R[i - 1]) / (R[i] - R[i - 1]);
    return D[6];
}

int main(int argc, char** argv) {
    if (argc < 2) { std::printf("usage: listening_pack13 OUTDIR\n"); return 2; }
    const std::string dir = argv[1];
    int n = 0;
    for (const char* scene : {"sweep", "jumps"})
        for (const Var& v : VARS) {
            const bool sweep = scene[0] == 's';
            const St* L = sweep ? ACID : HELD;
            if (sweep ? v.smms > 0 : (v.makeup || v.fbhz != 150 || v.gentle)) continue;
            twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
            e.C2 = 0x7fce80;
            { double x = std::exp(-2.0 * M_PI * v.fbhz / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
            const long N = BARS * 16 * STEP + 22050;
            std::vector<float> out(N);
            long evc = 0x7fffff; int half = 0; twin::W moff = 0;
            uint8_t k[12];
            auto knobs = [&](int bar, int s, uint8_t* kk) {
                const St& st = L[s];
                const int idx = bar * 16 + s;
                uint8_t base[12] = {(uint8_t)(24 + st.dp), 45, 0, 70, 60, (uint8_t)(st.acc ? 100 : 0), 0, 64, 38, 63, 99, 0};
                for (int i = 0; i < 12; i++) kk[i] = base[i];
                if (sweep) kk[OT_RES] = uint8_t(idx * 127 / (BARS * 16 - 1));
                else {
                    unsigned h = unsigned(idx + 1) * 2654435761u;
                    kk[OT_CUT] = uint8_t(idx & 1 ? 15 + (h >> 8) % 30 : 85 + (h >> 8) % 35);   // a big jump every step
                    kk[OT_ENV] = uint8_t((h >> 15) % 128); kk[OT_RES] = uint8_t(70 + (h >> 22) % 50);
                }
                if (v.gentle) kk[OT_RES] = uint8_t(kk[OT_RES] * kk[OT_RES] / 127);
            };
            knobs(0, 0, k);
            double resNow = 0, gd = 0;
            double sm[5] = {0, 0, 0, 0, 0}; bool smInit = false;
            const double a = v.smms > 0 ? std::exp(-1.0 / (0.001 * v.smms * 44100.0)) : 0;
            twin::W tg[5] = {0, 0, 0, 0, 0};
            for (long t = 0; t < N; t++) {
                long step = t / STEP; bool onStep = t % STEP == 0 && step < BARS * 16;
                int bar = int(step / 16), s = int(step % 16);
                if (t % 16 == 0) {                        // the frame's continuous words (the frame of a note: its knobs)
                    long st = (t + 15) / STEP;
                    if (st * STEP < t + 16 && st < BARS * 16 && (L[st % 16].kind == 'N' || !sweep)) knobs(int(st / 16), int(st % 16), k);
                    ot_cont c; ot_params_cont(k, &c);
                    e.CS = c.cs; e.BG = c.bg; e.SC = c.sc; e.SQ = c.sq != 0;
                    e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3; e.RC1 = c.rc1; e.GD8 = 0;
                    tg[0] = c.l0_16; tg[1] = c.es8; tg[2] = c.rs; tg[3] = c.bg; tg[4] = c.ag_8;
                    if (!smInit) { for (int i = 0; i < 5; i++) sm[i] = tg[i]; smInit = true; }
                    resNow = k[OT_RES]; gd = c.gd8 / 8388608.0 * 8.0;
                }
                for (int i = 0; i < 5; i++) sm[i] = a > 0 ? tg[i] + a * (sm[i] - tg[i]) : tg[i];
                e.L0_16 = twin::W(std::lround(sm[0])); e.ES8 = twin::W(std::lround(sm[1])); e.RS = twin::W(std::lround(sm[2]));
                e.BG = twin::W(std::lround(sm[3])); e.AG_8 = twin::W(std::lround(sm[4]));
                if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
                if (onStep && L[s].kind == 'N') {
                    int count = 1, nx = s;
                    for (int i = 1; i < 16; i++) { nx = (nx + 1) & 15; if (L[nx].kind != 'T') break; count++; }
                    bool hold = L[nx].kind == 'N' && L[nx].slide;
                    knobs(bar, s, k);
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
                double y = twin::f23(e.outW);
                if (v.makeup) y *= std::pow(10.0, makeupDb(resNow) / 20.0);
                if (gd > 0) y = std::tanh(gd * y);
                out[t] = float(y);
                evc--;
            }
            FILE* f = std::fopen((dir + "/" + scene + "." + v.name + ".f32").c_str(), "wb");
            std::fwrite(out.data(), sizeof(float), out.size(), f); std::fclose(f);
            n++;
        }
    std::printf("rendered %d clips\n", n);
    return 0;
}

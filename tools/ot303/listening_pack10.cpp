// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 listening pack round 10 (tools/ot303/listening_pack10.py): the machine as MT9 plays it (the
// ColdFire's params.c words, the DSP host's note rules -- tools/ot303/chain_check.cpp's "ours" path --
// on the integer twin) and candidate changes, one at a time, for a blind preference test:
// Each variant: the oscillator free-running or restarted from silence (MT7), an output soft clip
// tanh(G x) (G 0: none), the main envelope's soft attack (rc1, ms; 0: none) and the normal release
// (ms; 0: Open303's 1 ms), the square's shaper drive (dB; 0: Open303's 36.9).
//   listening_pack10 OUTDIR   writes SCENE.VARIANT.f32 (mono, 44.1 kHz)
#include <cmath>
#include <cstdio>
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
static const int BARS = 6;

struct Scene { const char* name; int root, cut, res, env, dec, acc, wave; bool locks, sweep; };
// PTCH as MT9 maps it: a semitone a step, 0 = C0, 12 = C1, 24 = C2, 36 = C3
static const Scene SCENES[] = {
    {"line", 24, 45, 90, 70, 60, 100, 0, false, false},     // a classic acid line around C2
    {"hot", 24, 80, 115, 110, 80, 110, 0, false, false},    // env, resonance and accent near the top
    {"locks", 24, 45, 100, 70, 60, 100, 0, true, false},    // CUT ENV DEC locked to new values every step
    {"square", 24, 20, 90, 60, 60, 100, 127, false, true},  // WAVE square, the cutoff sweeping up
    {"low", 14, 50, 80, 60, 60, 100, 0, false, false},      // the same line an octave lower, from D1 (37 Hz)
};
struct Var { const char* name; bool free; double drive, rc1ms, relms, sqdb; };
static const Var VARS[] = {
    {"mt8", false, 0, 0, 0, 0},                 // MT8's voice
    {"mt9", false, 1.68, 1.0, 2.0, 0},          // MT9's: drive +4.5 dB, soft attack 1 ms, release 2 ms
    {"mt9free", true, 1.68, 1.0, 2.0, 0},       // MT9's with the oscillator free-running
};

static double sqDC(double driveDb) {               // TwinVoice::init: the square's DC for a shaper drive
    double a = 0; const int NN = 1 << 16;
    for (int i = 0; i < NN; i++) { double q = (i + 0.5) / NN; a += -std::tanh(std::pow(10.0, driveDb / 20.0) * (2 * q - 1) + 4.37); }
    return a / NN;
}

int main(int argc, char** argv) {
    if (argc < 2) { std::printf("usage: listening_pack10 OUTDIR\n"); return 2; }
    const std::string dir = argv[1];
    for (const Scene& sc : SCENES)
        for (const Var& v : VARS) {
            twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
            e.C2 = 0x7fce80;                              // Open303's rc2 (hwprobe_image.py HOST)
            if (v.rc1ms > 0) e.RC1 = twin::q23(std::exp(-1.0 / (0.001 * v.rc1ms * 44100.0)));
            if (v.sqdb > 0) e.S70 = twin::q23(std::pow(10.0, v.sqdb / 20.0) / 128.0);
            const twin::W relEdges = v.relms > 0 ? twin::q23(std::exp(-1.0 / (0.001 * v.relms * 44100.0))) : 0;
            const long N = BARS * 16 * STEP + 22050;
            std::vector<float> out(N);
            long evc = 0x7fffff; int half = 0; twin::W moff = 0;
            uint8_t k[12];
            auto knobs = [&](int bar, int s, uint8_t* kk) {
                const St& st = ACID[s];
                uint8_t base[12] = {(uint8_t)(sc.root + st.dp), (uint8_t)sc.cut, (uint8_t)sc.res, (uint8_t)sc.env, (uint8_t)sc.dec,
                                    (uint8_t)(st.acc ? sc.acc : 0), (uint8_t)sc.wave, 64, 38, 63, 119, 0};
                for (int i = 0; i < 12; i++) kk[i] = base[i];
                if (sc.sweep) kk[OT_CUT] = uint8_t(sc.cut + (bar * 16 + s) * 90 / (BARS * 16));
                if (sc.locks) {
                    unsigned h = unsigned(bar * 16 + s + 1) * 2654435761u;
                    kk[OT_CUT] = uint8_t(20 + (h >> 8) % 90); kk[OT_ENV] = uint8_t((h >> 15) % 128); kk[OT_DEC] = uint8_t((h >> 22) % 128);
                }
            };
            knobs(0, 0, k);
            int nextStep = 0;
            for (long t = 0; t < N; t++) {
                long step = t / STEP; bool onStep = t % STEP == 0 && step < BARS * 16;
                int bar = int(step / 16), s = int(step % 16);
                if (t % 16 == 0) {                        // the frame's continuous words (the frame of a note: its knobs)
                    long st = (t + 15) / STEP;
                    if (st * STEP < t + 16 && st < BARS * 16 && ACID[st % 16].kind == 'N') knobs(int(st / 16), int(st % 16), k);
                    ot_cont c; ot_params_cont(k, &c);
                    e.CS = c.cs; e.ES8 = c.es8; e.RS = c.rs; e.BG = c.bg; e.SC = c.sc; e.SQ = c.sq != 0;
                    e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3; e.L0_16 = c.l0_16; e.AG_8 = c.ag_8;
                    if (v.sqdb > 0 && c.sq) e.W3 = twin::q23(k[OT_WAVE] / 127.0 * sqDC(v.sqdb) / 4.0);
                }
                if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
                if (onStep && ACID[s].kind == 'N') {
                    (void)nextStep;
                    int count = 1, n = s;
                    for (int i = 1; i < 16; i++) { n = (n + 1) & 15; if (ACID[n].kind != 'T') break; count++; }
                    bool hold = ACID[n].kind == 'N' && ACID[n].slide;
                    knobs(bar, s, k);
                    long gl = hold ? (count + 1) * STEP : (count - 1) * STEP + ot_gate_samples(k[OT_GATE], STEP);
                    ot_note nn; ot_params_note(k, &nn);
                    if (relEdges && !k[OT_ACC]) nn.m_amp_off = relEdges;
                    e.C_MEG = nn.c_meg; e.AG8 = nn.ag8; e.AGF = nn.agf != 0; e.K8 = nn.k8_on; moff = nn.m_amp_off; evc = gl;
                    e.INC_T = nn.inc_t;
                    if (!(ACID[s].slide && half)) {
                        if (!v.free && e.AMP2 < 0x400) e.P = twin::wrap(twin::acc(0x7fffff) - twin::acc(88 * nn.inc_t));
                        e.M_AMP = nn.m_amp_on; e.S48 = twin::acc(nn.inc_t);
                        e.M48 = (twin::A(nn.m48h) << 24) | (uint32_t(nn.m48l) & 0xffffff); e.AMP2 = nn.amp2; half = 1;
                    }
                }
                e.tick();
                double y = twin::f23(e.outW);
                if (v.drive > 0) y = std::tanh(v.drive * y);
                out[t] = float(y);
                evc--;
            }
            FILE* f = std::fopen((dir + "/" + sc.name + "." + v.name + ".f32").c_str(), "wb");
            std::fwrite(out.data(), sizeof(float), out.size(), f); std::fclose(f);
        }
    std::printf("rendered %zu scenes x %zu variants\n", sizeof SCENES / sizeof *SCENES, sizeof VARS / sizeof *VARS);
    return 0;
}

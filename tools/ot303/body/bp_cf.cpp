// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// BLACKPYRAMIDS_303 body: the new voice as the ColdFire plays it. bp_render.cpp's score format, but every word
// comes from the ColdFire's own code (record.c + params.c, compiled -DOT_BODY): the record is made each frame and
// the twin takes its words from the record itself (the continuous words, the note words), with the host's note
// rules (host_probe.cpp); build it -DOT_BODY like them (struct ot_voice). Only the DSP's constants come from PARAMS (fb_hz, hp1_hz, hp2_hz, c2_ms, kp_pts, lt_base / lt_spo: the
// X data and the Y image). The res column is the RES knob (the ColdFire tapers it).
//   bp_cf SCORE.txt OUT.f32 [PARAMS.txt]
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include "halfband4x.h"
#include "halfband2x.h"
#include "twin.h"
extern "C" {
#include "record.h"
}

struct St { char kind; int ptch, acc, slide; };
struct Fr { unsigned cut, env; int res, dec, wave; };
static twin::W clampW(double v) { if (v > 8388607) v = 8388607; if (v < -8388608) v = -8388608; return twin::W(std::lround(v)); }
static twin::W up(uint32_t u) { return twin::W(int32_t((((u >> 8) & 0xffff00u) | (u & 0xffu)) << 8) >> 8); }

int main(int argc, char** argv) {
    if (argc < 3) { std::fprintf(stderr, "usage: bp_cf SCORE.txt OUT.f32 [PARAMS.txt]\n"); return 2; }
    double fb_hz = 350, hp1_hz = 44.486, hp2_hz = 24.167, c2_ms = 0, lt_base = 0, lt_spo = 32; std::vector<double> kf, km;
    if (argc > 3) {
        FILE* q = std::fopen(argv[3], "r"); if (!q) { std::perror(argv[3]); return 1; }
        char key[64];
        while (std::fscanf(q, " %63s", key) == 1) {
            if (key[0] == '#') { int c; while ((c = std::fgetc(q)) != '\n' && c != EOF) {} continue; }
            std::string k = key; double v;
            if (k == "kp_pts") { int n; if (std::fscanf(q, "%d", &n) != 1) return 6;
                for (int i = 0; i < n; i++) { double f, m; if (std::fscanf(q, "%lf %lf", &f, &m) != 2) return 6; kf.push_back(f); km.push_back(m); } continue; }
            if (std::fscanf(q, "%lf", &v) != 1) return 6;
            if (k == "fb_hz") fb_hz = v; else if (k == "hp1_hz") hp1_hz = v; else if (k == "hp2_hz") hp2_hz = v;
            else if (k == "c2_ms") c2_ms = v; else if (k == "lt_base") lt_base = v; else if (k == "lt_spo") lt_spo = v;
            else { std::fprintf(stderr, "bp_cf: %s is not a DSP constant (the ColdFire makes it)\n", key); return 6; }
        }
        std::fclose(q);
    }
    FILE* f = std::fopen(argv[1], "r"); if (!f) { std::perror(argv[1]); return 1; }
    long STEP, NS; int GATE, SLID, VOL, TUNE;
    if (std::fscanf(f, "%ld %ld %d %d %d %d", &STEP, &NS, &GATE, &SLID, &VOL, &TUNE) != 6) return 3;
    std::vector<St> S(NS);
    for (long i = 0; i < NS; i++) { char c; if (std::fscanf(f, " %c %d %d %d", &c, &S[i].ptch, &S[i].acc, &S[i].slide) != 4) return 4; S[i].kind = c; }
    const long NF = NS * STEP / 16;
    std::vector<Fr> F(NF);
    for (long i = 0; i < NF; i++) if (std::fscanf(f, "%u %u %d %d %d", &F[i].cut, &F[i].env, &F[i].res, &F[i].dec, &F[i].wave) != 5) return 5;
    std::fclose(f);

    twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
    e.C2 = c2_ms > 0 ? twin::q23(std::exp(-1.0 / (c2_ms * 44.1))) : 0x7fce80;
    { double x = std::exp(-2.0 * M_PI * fb_hz / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
    { double x = std::exp(-2.0 * M_PI * hp1_hz / 176400.0); e.HP1_B = twin::q23(0.5 * (1 + x)); e.HP1_A = twin::q23(x); }
    { double x = std::exp(-2.0 * M_PI * hp2_hz / 44100.0); e.HP2_B = twin::q23(0.5 * (1 + x)); e.HP2_A = twin::q23(x); }
    if (lt_base > 0) twin::set_lt(lt_base, lt_spo);            // the cutoff table (the ColdFire scales its words to it)
    if (!kf.empty()) {
        auto mult = [&](double hz) {
            double l = std::log(hz);
            if (l <= std::log(kf.front())) return km.front();
            if (l >= std::log(kf.back())) return km.back();
            for (size_t i = 1; i < kf.size(); i++)
                if (l <= std::log(kf[i])) { double a = std::log(kf[i - 1]), b = std::log(kf[i]); return km[i - 1] + (km[i] - km[i - 1]) * (l - a) / (b - a); }
            return 1.0;
        };
        for (int i = 0; i <= twin::LT_N; i++) twin::T.kp[i] = clampW(twin::T.kp[i] * mult(twin::LT_BASE * std::pow(2.0, (double)i / twin::LT_SPO)));
        for (int i = 0; i < twin::LT_N; i++) twin::T.dkp[i] = twin::T.kp[i + 1] - twin::T.kp[i];
        twin::T.dkp[twin::LT_N] = 0;
    }
    e.glide = true; e.GLD = twin::q23(1.0 - std::exp(-1.0 / 44.1));
    const long N = NS * STEP;
    std::vector<float> out(N);
    long evc = 0x7fffff; int half = 0; twin::W moff = 0; bool first = true;
    ot_voice v{}; uint32_t rec[OT_REC_LONGS];
    uint8_t k[12] = {36, 30, 64, 32, 72, 0, 0, (uint8_t)TUNE, (uint8_t)SLID, (uint8_t)GATE, (uint8_t)VOL, 0};
    if (NS && S[0].kind == 'N') { k[OT_PTCH] = uint8_t(S[0].ptch); k[OT_ACC] = uint8_t(S[0].acc); }
    // BP_VOL_FRAMES=FILE: the VOL knob a frame (one value a line), for VOL moves while a note plays
    std::vector<int> volf;
    if (const char* vf = std::getenv("BP_VOL_FRAMES")) { FILE* q = std::fopen(vf, "r"); int v; while (q && std::fscanf(q, "%d", &v) == 1) volf.push_back(v); if (q) std::fclose(q); }
    for (long fr = 0; fr < NF; fr++) {
        const Fr& x = F[fr];
        if (fr < (long)volf.size()) k[OT_VOL] = uint8_t(volf[fr]);
        k[OT_CUT] = uint8_t(x.cut >> 8); k[OT_ENV] = uint8_t(x.env >> 8); k[OT_RES] = uint8_t(x.res);
        k[OT_DEC] = uint8_t(x.dec); k[OT_WAVE] = uint8_t(x.wave);
        // a step that starts in this frame (the ColdFire's look-ahead: ties extend, a note before a slide is held)
        unsigned ev = 0; uint32_t gl = 0; long off = 0;
        long t0 = fr * 16, step = (t0 + STEP - 1) / STEP;
        if (step < NS && step * STEP < t0 + 16 && S[step].kind == 'N') {
            long count = 1, nx = step;
            for (;;) { nx++; if (nx >= NS || S[nx].kind != 'T') break; count++; }
            bool hold = nx < NS && S[nx].kind == 'N' && S[nx].slide;
            k[OT_PTCH] = uint8_t(S[step].ptch); k[OT_ACC] = uint8_t(S[step].acc);
            gl = uint32_t(hold ? (count + 1) * STEP : (count - 1) * STEP + ot_gate_samples(k[OT_GATE], STEP));
            ev = OT_EV_NOTE | (S[step].slide ? OT_EV_SLIDE : 0); off = step * STEP - t0;
        }
        ot_record(rec, &v, k, ev, gl, x.cut, x.env);
        const twin::W cs = up(rec[2]), es8 = up(rec[3]), rs = up(rec[4]), bg = up(rec[5]), sc = up(rec[6]), sq = up(rec[7]);
        const twin::W w1 = up(rec[8]), w2 = up(rec[10]), w3 = up(rec[11]), rc1 = up(rec[12]), gd8 = up(rec[13]);
        const twin::W l016 = up(rec[14]), ag_8 = up(rec[15]);
        if (first) { e.ES8 = es8; e.L0_16 = l016; first = false; }
        e.CS = cs; e.ES8T = es8; e.RS = rs; e.BG = bg; e.SC = sc; e.SQ = sq != 0; e.W1 = w1; e.W2 = w2; e.W3 = w3;
        e.L016T = l016; e.AG_8 = ag_8; e.RC1 = rc1; e.GD8 = gd8;
        long trg = (ev & OT_EV_NOTE) ? off : 0x7fffff;
        for (int j = 0; j < 16; j++) {
            if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
            if (trg == 0) {
                e.C_MEG = up(rec[16]); e.AG8 = up(rec[17]); e.AGF = up(rec[18]) != 0; e.K8 = up(rec[19]); moff = up(rec[20]);
                evc = long(up(rec[21]) & 0xffffff); e.INC_T = up(rec[23]);
                if (!((ev & OT_EV_SLIDE) && half)) {
                    e.M_AMP = up(rec[22]); e.S48 = twin::acc(up(rec[23]));
                    e.M48 = (twin::A(up(rec[24])) << 24) | (uint32_t(up(rec[25])) & 0xffffff); e.AMP2 = up(rec[26]); half = 1;
                }
            }
            e.tick(); evc--; trg--;
            out[t0 + j] = float(twin::f23(e.outW));
        }
    }
    FILE* o = std::fopen(argv[2], "wb");
    std::fwrite(out.data(), sizeof(float), out.size(), o); std::fclose(o);
    if (std::getenv("BP_PEAKS"))                                // each named store's peak, re full scale
        for (auto& kv : twin::g_peak) std::fprintf(stderr, "peak %-8s %.3f\n", kv.first.c_str(), kv.second);
    std::fprintf(stderr, "saturations %ld\n", twin::g_sat);
    return 0;
}

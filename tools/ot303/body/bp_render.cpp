// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// BLACKPYRAMIDS_303 "body" study renderer. The machine as the FINAL build plays it -- params.c's words,
// record.c's easing of RS/BG/AG_8/SC, the cutoff/env glide (MT15, tau 1 ms), the host's note rules
// (listening_pack17.cpp), the integer twin (bit-exact to the DSP engine) -- plus CANDIDATE overrides that
// change only data the ColdFire already sends the DSP (X constants, the Y tables, the record's words).
// No candidate changes the engine's instructions.
//   bp_render SCORE.txt OUT.f32 [PARAMS.txt]
// SCORE.txt:
//   STEP NSTEPS GATE SLID VOL TUNE
//   NSTEPS lines: kind(N/T/R) ptch(0..96) acc(0..127, 0 = none) slide(0/1)
//   NSTEPS*STEP/16 lines (one a frame): cut_q8 env_q8 res dec wave
// PARAMS.txt (any subset; "key value" lines, '#' comments):
//   fb_hz F        resonance-loop high-pass (FINAL: 350; Open303: 150)
//   hp1_hz F       pre-filter high-pass (44.486)
//   hp2_hz F       post high-pass (24.167)
//   kp_pts N  f1 m1 ... fN mN   resonance-law multiplier by cutoff (Hz, factor; log-f interpolation)
//   es_mult F      envelope depth (ES8 x F)
//   l0_oct F       base cutoff shift, octaves (L0_16 + F/16)
//   envoff F       env offset: L0_16 + F * ES8 (moves the cutoff the envelope's floor sits at)
//   g_mult F       output gain-compensation scale (BG x F: the resonance's passband make-up)
//   ag_mult F      accent sweep (AG8 x F)       k8_mult F   accent VCA (K8 x F)
//   sc_mult F      output scaler (SC x F)       meg_t20 F   override the MEG -20 dB time, seconds (0 = knob)
//   sat F          ladder-input drive (osc words x F)
//   decl_hz F      Open303's amp declicker low-pass (200)    rc1 F   the soft attack's coefficient (0 = none; -1 = params.c)
//   acc_t20 F      the accented notes' MEG -20 dB time, s (0 = params.c: Open303's 200 ms time constant)
//   amp_tau F      the VCA's decay time constant while the gate is on, s (0 = params.c: Open303's 1.23 s)
//   wow_d F, wow_c F   the accent sweep capacitor (the 303's circuit: Roland's service notes, Whittle), run at the ColdFire's frame
//                  rate and added to the cutoff word L0_16: direct path wow_d x (1 - RES/127) and capacitor path
//                  wow_c x RES/127, octaves at full accent; wow_ch / wow_dis the capacitor's charge / discharge time
//                  constants, ms (60 / 126); wow_acc the accent envelope's -20 dB time, s (0 = acc_t20 or 0.2);
//                  wow_pot the ACCENT pot in the discharge path (0 = fixed; 1 = 100 k pot + 100 k fixed: ACC 0..127 spans 2x)
//   wow_rd 1       the capacitor's charge / discharge from RES as the 303's circuit (85 -> 50 / 150 -> 100 ms); wow_thr F
//                  the ACCENT level below which the sweep does not conduct (0..1; the circuit ~0.4)
//   vp_g F         PROTOTYPE (not DSP-exact): the 303's VCA-input pair (service notes R121/C21, R122/C20): the filter
//                  output through a vp_f1 (72 Hz) high-pass plus vp_g x RES/127 of it through a vp_f2 (156 Hz) high-pass,
//                  divided by (1 + vp_g); applied after the twin's VCA, before the VOL drive (the twin's drive is moved here)
//   sat_d F        PROTOTYPE (needs DSP code): ladder-input soft clip tanh(D v)/D inside the resonance loop
//   gcomp_off 1    Open303's resonance make-up gain off (g = 1): with vp_g the 303's VCA-input pair raises the level
//                  with RES instead, as in the circuit
//   ring_d F, ring_q F   the ring-out law (per frame, from RES and the base cutoff fc): rs x (1 - ring_d x RES/127 x
//                  (fc / 1 kHz)^ring_q), the make-up gain (AG_8, BG) recomputed from it (Open303's formulas)
//   env_r F        the envelope depth grows with RES: ES8 x (1 + env_r x RES/127)
//   lg_p F         the level by cutoff: SC x (fc / 1 kHz)^lg_p
//   wow_knob 1 + res_law R0 R25 R50 R75 R100   the accent sweep's split and timing from the RES pot's position (the RES
//                  law inverted: the real-303 %), not the engine's resonance (the 303's VR4b gangs with the RES pot);
//                  + acc_law A0 .. A100: its threshold from the ACCENT pot's position the same way
//   lt_base F, lt_top F   the cutoff table's floor and top, Hz (200 / 20 kHz: the DSP's); L0_16 follows the floor
//   drive_db F     more level into the output drive (VOL 65..127: SC x 10^(F/20)); VOL 1..64 unchanged
//   ext_f F, ext_lg F, ext_res F   the CUT extension above the real 303's top ext_f (Hz): level x (fc / ext_f)^-ext_lg,
//                  resonance x ext_res an octave above it (eased in linearly per octave)
//   c2_ms F        the accent RC's time constant, ms (0 = 0x7fce80, ~15 ms)
//   noglide 1      the pack renderer's behaviour (host words used as they are)
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

static ot_w ot_ease(ot_w s, ot_w t) {          // record.c ot_ease
    int32_t d = t - s;
    if (d > -8 && d < 8) return t;
    return s + d / 6;
}
static twin::W clampW(double v) { if (v > 8388607) v = 8388607; if (v < -8388608) v = -8388608; return twin::W(std::lround(v)); }

struct St { char kind; int ptch, acc, slide; };
struct Fr { unsigned cut, env; int res, dec, wave; };
struct P {
    double fb_hz = 350, hp1_hz = 44.486, hp2_hz = 24.167, es_mult = 1, l0_oct = 0, envoff = 0, g_mult = 1;
    double ag_mult = 1, k8_mult = 1, sc_mult = 1, meg_t20 = 0, sat = 1, decl_hz = 200, rc1 = -1, acc_t20 = 0, c2_ms = 0, amp_tau = 0, wow_d = 0, wow_c = 0, wow_ch = 60, wow_dis = 126, wow_acc = 0, wow_pot = 0, ring_d = 0, ring_q = 0, env_r = 0, lg_p = 0, wow_rd = 0, wow_thr = 0, vp_g = 0, vp_f1 = 72, vp_f2 = 156, gcomp_off = 0, sat_d = 0, lt_base = 200, lt_top = 0, wow_knob = 0, ext_f = 0, ext_lg = 0, ext_res = 1, drive_db = 0; int noglide = 0;
    std::vector<double> res_law, acc_law;
    std::vector<double> kf, km;
};
static double kpMult(const P& p, double hz) {
    if (p.kf.empty()) return 1.0;
    double l = std::log(hz);
    if (l <= std::log(p.kf.front())) return p.km.front();
    if (l >= std::log(p.kf.back())) return p.km.back();
    for (size_t i = 1; i < p.kf.size(); i++)
        if (l <= std::log(p.kf[i])) {
            double a = std::log(p.kf[i - 1]), b = std::log(p.kf[i]);
            return p.km[i - 1] + (p.km[i] - p.km[i - 1]) * (l - a) / (b - a);
        }
    return 1.0;
}

int main(int argc, char** argv) {
    if (argc < 3) { std::fprintf(stderr, "usage: bp_render SCORE.txt OUT.f32 [PARAMS.txt]\n"); return 2; }
    P p;
    if (argc > 3) {
        FILE* q = std::fopen(argv[3], "r"); if (!q) { std::perror(argv[3]); return 1; }
        char key[64];
        while (std::fscanf(q, " %63s", key) == 1) {
            if (key[0] == '#') { int c; while ((c = std::fgetc(q)) != '\n' && c != EOF) {} continue; }
            std::string k = key; double v;
            if (k == "acc_law") { for (int i = 0; i < 5; i++) { double r; if (std::fscanf(q, "%lf", &r) != 1) return 6; p.acc_law.push_back(r); } continue; }
            if (k == "res_law") { for (int i = 0; i < 5; i++) { double r; if (std::fscanf(q, "%lf", &r) != 1) return 6; p.res_law.push_back(r); } continue; }
            if (k == "kp_pts") { int n; if (std::fscanf(q, "%d", &n) != 1) return 6;
                for (int i = 0; i < n; i++) { double f, m; if (std::fscanf(q, "%lf %lf", &f, &m) != 2) return 6; p.kf.push_back(f); p.km.push_back(m); } continue; }
            if (std::fscanf(q, "%lf", &v) != 1) return 6;
            if (k == "fb_hz") p.fb_hz = v; else if (k == "hp1_hz") p.hp1_hz = v; else if (k == "hp2_hz") p.hp2_hz = v;
            else if (k == "es_mult") p.es_mult = v; else if (k == "l0_oct") p.l0_oct = v; else if (k == "envoff") p.envoff = v;
            else if (k == "g_mult") p.g_mult = v; else if (k == "ag_mult") p.ag_mult = v; else if (k == "k8_mult") p.k8_mult = v;
            else if (k == "sc_mult") p.sc_mult = v; else if (k == "meg_t20") p.meg_t20 = v; else if (k == "sat") p.sat = v;
            else if (k == "noglide") p.noglide = int(v); else if (k == "decl_hz") p.decl_hz = v; else if (k == "rc1") p.rc1 = v;
            else if (k == "acc_t20") p.acc_t20 = v; else if (k == "c2_ms") p.c2_ms = v; else if (k == "amp_tau") p.amp_tau = v;
            else if (k == "wow_d") p.wow_d = v; else if (k == "wow_c") p.wow_c = v; else if (k == "wow_ch") p.wow_ch = v;
            else if (k == "wow_dis") p.wow_dis = v; else if (k == "wow_acc") p.wow_acc = v; else if (k == "wow_pot") p.wow_pot = v;
            else if (k == "ring_d") p.ring_d = v; else if (k == "ring_q") p.ring_q = v;
            else if (k == "env_r") p.env_r = v; else if (k == "lg_p") p.lg_p = v;
            else if (k == "wow_rd") p.wow_rd = v; else if (k == "wow_thr") p.wow_thr = v;
            else if (k == "drive_db") p.drive_db = v;
            else if (k == "ext_f") p.ext_f = v; else if (k == "ext_lg") p.ext_lg = v; else if (k == "ext_res") p.ext_res = v;
            else if (k == "lt_base") p.lt_base = v; else if (k == "lt_top") p.lt_top = v; else if (k == "wow_knob") p.wow_knob = v;
            else if (k == "gcomp_off") p.gcomp_off = v; else if (k == "sat_d") p.sat_d = v; else if (k == "vp_g") p.vp_g = v; else if (k == "vp_f1") p.vp_f1 = v; else if (k == "vp_f2") p.vp_f2 = v;
            else { std::fprintf(stderr, "unknown key %s\n", key); return 6; }
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
    e.C2 = p.c2_ms > 0 ? twin::q23(std::exp(-1.0 / (p.c2_ms * 44.1))) : 0x7fce80;   // the accent RC (rc2), X data
    { double x = std::exp(-2.0 * M_PI * p.fb_hz / 176400.0); e.FB_B = twin::q23(0.5 * (1 + x)); e.FB_A = twin::q23(x); }
    { double x = std::exp(-2.0 * M_PI * p.hp1_hz / 176400.0); e.HP1_B = twin::q23(0.5 * (1 + x)); e.HP1_A = twin::q23(x); }
    { double x = std::exp(-2.0 * M_PI * p.hp2_hz / 44100.0); e.HP2_B = twin::q23(0.5 * (1 + x)); e.HP2_A = twin::q23(x); }
    if (p.lt_base != 200 || p.lt_top > 0) {                     // the cutoff table's floor and top (Y data; L0_16 follows)
        twin::LT_BASE = p.lt_base;
        twin::LT_TOP = std::log2((p.lt_top > 0 ? p.lt_top : 20000.0) / p.lt_base);
        twin::LT_NN = int(std::ceil(twin::LT_TOP * twin::LT_STEPS)) + 1;
        if (twin::LT_NN > twin::LT_NMAX) { std::fprintf(stderr, "table too long\n"); return 7; }
        twin::T.build();
        p.l0_oct += std::log2(200.0 / p.lt_base);
    }
    if (!p.kf.empty()) {                                         // the resonance law: the kp table (Y data) x m(fc)
        for (int i = 0; i <= twin::LT_NN; i++) {
            double fc = twin::LT_BASE * std::pow(2.0, (double)i / twin::LT_STEPS);
            twin::T.kp[i] = clampW(twin::T.kp[i] * kpMult(p, fc));
        }
        for (int i = 0; i < twin::LT_NN; i++) twin::T.dkp[i] = twin::T.kp[i + 1] - twin::T.kp[i];
        twin::T.dkp[twin::LT_NN] = 0;
    }
    if (p.decl_hz != 200) e.decl.design(p.decl_hz, 44100.0, 1.0 / std::sqrt(0.5), 0, 8, 1);   // the amp declicker (X data)
    e.satD = p.sat_d;                                           // PROTOTYPE: ladder-input saturation (needs DSP code)
    e.glide = !p.noglide; e.GLD = twin::q23(1.0 - std::exp(-1.0 / 44.1));
    const long N = NS * STEP;
    std::vector<float> out(N);
    long evc = 0x7fffff; int half = 0; twin::W moff = 0;
    bool have = false; ot_w rs = 0, bg = 0, ag = 0, sc = 0;
    double wmeg = 0, wcap = 0, wamt = 0; bool wacc = false;   // the accent sweep capacitor's state
    double vh1 = 0, vh2 = 0, vx = 0, vgd = 0;                   // the VCA-input pair prototype's state
    uint8_t k[12] = {36, 30, 64, 32, 72, 0, 0, (uint8_t)TUNE, (uint8_t)SLID, (uint8_t)GATE, (uint8_t)VOL, 0};
    if (NS && S[0].kind == 'N') { k[OT_PTCH] = uint8_t(S[0].ptch); k[OT_ACC] = uint8_t(S[0].acc); }   // as listening_pack17
    auto frameKnobs = [&](long fr) {
        const Fr& x = F[fr];
        k[OT_CUT] = uint8_t(x.cut >> 8); k[OT_ENV] = uint8_t(x.env >> 8); k[OT_RES] = uint8_t(x.res);
        k[OT_DEC] = uint8_t(x.dec); k[OT_WAVE] = uint8_t(x.wave);
    };
    for (long t = 0; t < N; t++) {
        long step = t / STEP; bool onStep = t % STEP == 0;
        if (t % 16 == 0) {
            long fr = t / 16; frameKnobs(fr);
            ot_cont c; ot_params_cont_q8(k, F[fr].cut, F[fr].env, &c);
            if (p.wow_d > 0 || p.wow_c > 0) {                   // the accent sweep capacitor, per 16-sample frame
                double ta = p.wow_acc > 0 ? p.wow_acc : (p.acc_t20 > 0 ? p.acc_t20 : 0.2);
                wmeg *= std::exp(-std::log(10.0) * 16.0 / (ta * 44100.0));
                // the 303's sweep (service notes, x0xb0x): it conducts only above the threshold (D24 against the
                // expo node, ~40 % ACCENT), and with wow_rd its charge / discharge follow RES through VR4b:
                // charge 85 -> 50 ms, discharge 150 -> 100 ms from RES min to max (the ACCENT pot is not in the path)
                double a = wamt > p.wow_thr ? (wamt - p.wow_thr) / (1.0 - p.wow_thr) : 0.0;
                // wow_knob: the split and the timing follow the RES pot's position (the 303's VR4b is a gang of the RES
                // pot), not the engine's resonance: the knob is the real-303 position, from the RES law inverted
                double rk = k[OT_RES] / 127.0;
                if (p.wow_knob > 0 && p.res_law.size() == 5) {
                    const double P[5] = {0, 25, 50, 75, 100}; double e = k[OT_RES];
                    rk = 1.0;
                    for (int i = 1; i < 5; i++)
                        if (e <= p.res_law[i]) { double d = p.res_law[i] - p.res_law[i - 1];
                            rk = (P[i - 1] + (d > 0 ? (e - p.res_law[i - 1]) / d : 0.0) * 25.0) / 100.0; break; }
                }
                double vin = wacc ? wmeg * a : 0.0, rr0 = rk;
                double chm = p.wow_rd > 0 ? 85.0 - 35.0 * rr0 : p.wow_ch, dism = p.wow_rd > 0 ? 150.0 - 50.0 * rr0 : -1.0;
                if (vin > wcap) wcap += (vin - wcap) * (1.0 - std::exp(-16.0 / (chm * 44.1)));
                // the discharge runs through the ACCENT pot + a fixed 100 k (Whittle): wow_pot > 0 makes it
                // wow_dis x (1 + wow_pot x ACC/127) / (1 + wow_pot / 2), equal to wow_dis at mid ACCENT
                double dis = dism > 0 ? dism : (p.wow_pot > 0 ? p.wow_dis * (1.0 + p.wow_pot * wamt) / (1.0 + p.wow_pot / 2.0) : p.wow_dis);
                wcap -= wcap * (1.0 - std::exp(-16.0 / (dis * 44.1)));
                double r = rk, oct = p.wow_d * (1.0 - r) * vin + p.wow_c * r * wcap;
                c.l0_16 = clampW(c.l0_16 + oct / 16.0 * 8388608.0);
            }
            {   // body study: ring-out law, envelope depth by RES, level by cutoff (ColdFire words, per frame)
                double fcb = 200.0 * std::pow(50.0, F[fr].cut / 256.0 / 127.0), rr = k[OT_RES] / 127.0;
                if (p.ring_d != 0) {
                    double rs1 = twin::f23(c.rs) * (1.0 - p.ring_d * rr * std::pow(fcb / 1000.0, p.ring_q));
                    rs1 = std::min(std::max(rs1, 0.0), 0.999999);
                    c.rs = twin::q23(rs1); c.ag_8 = twin::q23((1.0 - rs1 * rs1) / 8.0); c.bg = twin::q23(rs1 * (1.0 + rs1) * 8.0 / 17.0);
                }
                if (p.gcomp_off > 0) { c.ag_8 = twin::q23(1.0 / 8.0); c.bg = 0; }   // Open303's make-up gain off: g = 1
                if (p.env_r != 0) c.es8 = clampW(c.es8 * (1.0 + p.env_r * rr));
                if (p.lg_p != 0) c.sc = clampW(c.sc * std::pow(fcb / 1000.0, p.lg_p));
                // the CUT extension (above the real 303's top ext_f, Hz): the level x (fc / ext_f)^-ext_lg (no accent
                // peaks above the top's), the resonance eased to x ext_res an octave above it (no piercing sustain)
                if (p.ext_f > 0 && fcb > p.ext_f) {
                    double oc = std::log2(fcb / p.ext_f);
                    c.sc = clampW(c.sc * std::pow(fcb / p.ext_f, -p.ext_lg));
                    if (p.ext_res != 1) {
                        double m = 1.0 + (p.ext_res - 1.0) * std::min(oc, 1.0), rs1 = twin::f23(c.rs) * m;
                        c.rs = twin::q23(rs1); c.ag_8 = twin::q23((1.0 - rs1 * rs1) / 8.0); c.bg = twin::q23(rs1 * (1.0 + rs1) * 8.0 / 17.0);   // (x g_mult below)
                    }
                }
            }
            c.es8 = clampW(c.es8 * p.es_mult);
            c.l0_16 = clampW(c.l0_16 + twin::q23(p.l0_oct / 16.0) + p.envoff * c.es8 * 8.0 / 16.0 * 1.0);
            c.bg = clampW(c.bg * p.g_mult); c.sc = clampW(c.sc * p.sc_mult);
            c.w1 = clampW(c.w1 * p.sat); c.w2 = clampW(c.w2 * p.sat); c.w3 = clampW(c.w3 * p.sat);
            // drive_db: more level into the VOL drive (VOL 65..127 run the level 12 dB down into it, the drive's x4 back)
            if (p.drive_db != 0 && c.gd8) c.sc = clampW(c.sc * std::pow(10.0, p.drive_db / 20.0));
            if (!have) { rs = c.rs; bg = c.bg; ag = c.ag_8; sc = c.sc; have = true; e.ES8 = c.es8; e.L0_16 = c.l0_16; }
            rs = ot_ease(rs, c.rs); bg = ot_ease(bg, c.bg); ag = ot_ease(ag, c.ag_8); sc = ot_ease(sc, c.sc);
            e.CS = c.cs; e.BG = bg; e.SC = sc; e.SQ = c.sq != 0;
            e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3; e.RC1 = p.rc1 >= 0 ? twin::q23(p.rc1) : c.rc1; e.GD8 = c.gd8;
            if (e.glide) { e.ES8T = c.es8; e.L016T = c.l0_16; } else { e.L0_16 = c.l0_16; e.ES8 = c.es8; }
            e.RS = rs; e.AG_8 = ag;
        }
        if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
        if (onStep && S[step].kind == 'N') {
            long count = 1, nx = step;
            for (;;) { nx++; if (nx >= NS || S[nx].kind != 'T') break; count++; }
            bool hold = nx < NS && S[nx].kind == 'N' && S[nx].slide;
            k[OT_PTCH] = uint8_t(S[step].ptch); k[OT_ACC] = uint8_t(S[step].acc);
            long gl = hold ? (count + 1) * STEP : (count - 1) * STEP + ot_gate_samples(k[OT_GATE], STEP);
            ot_note nn; ot_params_note(k, &nn);
            if (!(S[step].slide && half)) {
                wacc = k[OT_ACC] != 0; wamt = k[OT_ACC] / 127.0;
                // wow_knob + acc_law: the sweep's threshold sits on the ACCENT pot's position (the real-303 %, the law
                // inverted), as the circuit's D24 does, not on the engine's accent amount
                if (wacc && p.wow_knob > 0 && p.acc_law.size() == 5) {
                    const double P[5] = {0, 25, 50, 75, 100}; double e = k[OT_ACC];
                    wamt = 1.0;
                    for (int i = 1; i < 5; i++)
                        if (e <= p.acc_law[i]) { double d = p.acc_law[i] - p.acc_law[i - 1];
                            wamt = (P[i - 1] + (d > 0 ? (e - p.acc_law[i - 1]) / d : 0.0) * 25.0) / 100.0; break; }
                }
                if (wacc) wmeg = 1.0;
            }
            if (p.meg_t20 > 0 && !k[OT_ACC]) nn.c_meg = twin::q23(std::exp(-std::log(10.0) / (p.meg_t20 * 44100.0)));
            if (p.acc_t20 > 0 && k[OT_ACC]) nn.c_meg = twin::q23(std::exp(-std::log(10.0) / (p.acc_t20 * 44100.0)));
            e.C_MEG = nn.c_meg; e.AG8 = clampW(nn.ag8 * p.ag_mult); e.AGF = nn.agf != 0; e.K8 = clampW(nn.k8_on * p.k8_mult);
            moff = nn.m_amp_off; evc = gl;
            e.INC_T = nn.inc_t;
            if (p.amp_tau > 0) nn.m_amp_on = twin::q23(std::exp(-1.0 / (p.amp_tau * 44100.0)));   // the VCA's decay while held
            if (!(S[step].slide && half)) {
                e.M_AMP = nn.m_amp_on; e.S48 = twin::acc(nn.inc_t);
                e.M48 = (twin::A(nn.m48h) << 24) | (uint32_t(nn.m48l) & 0xffffff); e.AMP2 = nn.amp2; half = 1;
            }
        }
        if (p.vp_g > 0 && t == 0) { vgd = twin::f23(e.GD8); }
        if (p.vp_g > 0) e.GD8 = 0;                                 // the drive after the pair
        e.tick();
        if (p.vp_g > 0) {
            double y = twin::f23(e.outW);
            double a1 = std::exp(-2 * M_PI * p.vp_f1 / 44100.0), a2 = std::exp(-2 * M_PI * p.vp_f2 / 44100.0);
            vh1 = 0.5 * (1 + a1) * (y - vx) + a1 * vh1; vh2 = 0.5 * (1 + a2) * (y - vx) + a2 * vh2; vx = y;
            double w = p.vp_g * k[OT_RES] / 127.0, z = (vh1 + w * vh2) / (1.0 + p.vp_g);
            if (vgd > 0) z = std::tanh(8.0 * vgd * z);
            out[t] = float(z);
        } else
        out[t] = float(twin::f23(e.outW));
        evc--;
    }
    FILE* o = std::fopen(argv[2], "wb");
    std::fwrite(out.data(), sizeof(float), out.size(), o); std::fclose(o);
    std::fprintf(stderr, "saturations %ld\n", twin::g_sat);
    return 0;
}

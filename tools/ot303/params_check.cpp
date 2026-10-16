// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 knob -> host-word compiler (tools/ot303/cf/params.c) against Open303 (pinned 313bf0d9, MIT).
//   params_check gen OUT.h   writes the constants params.c uses (params_const.h), from Open303's own
//                            double-precision code and the knob ranges in params.h
//   params_check check       every knob value (and the CUT x ENV plane) through params.c and through
//                            Open303 objects, the words compared as TwinVoice::host() makes them
//                            (tools/ot303/voice_study.cpp); prints the worst error per word in LSBs
// Built by tools/ot303/params_check.py (clang++, Open303's sources, params.c compiled as C).
#define protected public
#define private public
#include "rosic_Open303.h"
#undef private
#undef protected
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#ifndef OT_GEN_ONLY
extern "C" {
#include "params.h"
}
#endif
using namespace rosic;

static const double FS = 44100.0;
// the normal (unaccented) amp release: Open303 ships 1 ms; MT9 2 ms (the user's pick, listening round 9)
static const double NORMAL_RELEASE_MS = 2.0;
static int32_t q23(double v) {                    // twin.h's q23: nearest, clamped
    double x = std::nearbyint(v * 8388608.0);
    if (x > 8388607.0) x = 8388607.0;
    if (x < -8388608.0) x = -8388608.0;
    return (int32_t)x;
}
static int64_t qn(double v, int q) { return (int64_t)std::llround(v * std::ldexp(1.0, q)); }
static double sqDC() {                           // TwinVoice::init: the square's DC, as OscBlep
    double a = 0; const int NN = 1 << 16;
    for (int i = 0; i < NN; i++) { double q = (i + 0.5) / NN; a += -std::tanh(dB2amp(36.9) * (2 * q - 1) + 4.37); }
    return a / NN;
}
// the knob ranges (params.h)
static double cutoffHz(int k) { return 200.0 * std::pow(50.0, k / 127.0); }
static double decayMs(int k) { return 50.0 * std::pow(40.0, k / 127.0); }    // MT25: 50 ms .. 2 s (MT16: 200 ms .. 2 s)
static double slideMs(int k) { return 1.5625 * k; }
static double tuningHz(int k) { return 440.0 + (k - 64) * 80.0 / 127.0; }
// MT10's two additions (not Open303's; the user's listening rounds 11-12): the soft attack, 1 ms faded
// out by RES (full to RES 100, none from RES 115), and the output drive on VOL's top (none to VOL 109,
// then +4.5 dB at 127, linear in dB: VOL 119 = +2.5 dB); 0 = off for both
static int32_t rc1Word(int res) {
    double ms = std::fmin(1.0, std::fmax(0.0, (115.0 - res) / 15.0));
    return ms > 0 ? q23(std::exp(-1.0 / (0.001 * ms * FS))) : 0;
}
// MT13 (the user: most of VOL's travel useful, the drive over its top half): VOL 0 silent; 1..64 clean,
// -30 dB .. the top level (MT10's VOL 119, (119/127)^2); 65..127 the top level driven, 0 .. +4.5 dB
// linear in dB (99 = +2.5 dB, the default: MT10's sound at its default)
// MT33 (round 15, the driven half): VOL 65..127 runs the output stage DRIVE_ROOM times lower and the drive's
// gain DRIVE_ROOM times higher -- the same tanh(g y) below the old ceiling, but what used to hard-clip at the
// output stage (bright settings, accents) now reaches the soft clip instead of being chopped flat first.
// Clean VOL (1..64) is unchanged: linear, hard clip at the ceiling.
#define DRIVE_ROOM 4.0
static double volTop() { return std::pow(119.0 / 127.0, 2.0); }
static int32_t scWord(int vol) {
    return vol == 0 ? 0 : vol > 64 ? q23(volTop() / DRIVE_ROOM) : vol == 64 ? q23(volTop())
                                   : q23(volTop() * std::pow(10.0, -30.0 * (64 - vol) / 63.0 / 20.0));
}
static int32_t gd8Word(int vol) { return vol > 64 ? q23(DRIVE_ROOM * std::pow(10.0, 4.5 * (vol - 64) / 63.0 / 20.0) / 8.0) : 0; }

// MT29: the WAVE gain (dB, b = WAVE / 127), holding the loudness of the saw across the blend: fitted by
// tools/ot303/wave_loudness.py (ISO 532-1 N5 against WAVE 0, the mean over 21 CUT / RES / VOL settings, two
// passes); +2.66 dB at WAVE 87, +1.8 dB at 127. As Q14 (OT_WGAIN), which params.c and the reference apply.
static double waveGainDb(int w) {
    const double b = w / 127.0;
    return b * (6.0797 + b * (-3.5570 + b * (7.9781 + b * (-15.7193 + b * 7.0159))));
}
static unsigned wgainQ14(int w) { return (unsigned)std::llround(std::pow(10.0, waveGainDb(w) / 20.0) * 16384.0); }
// MT34 (round 17): a level trim at the bottom of RES. The voice is louder at low RES than from RES ~48 up (the
// boost below, measured on the twin: CUT 45, ENV 70, clean VOL 64, RMS dB over RES 127); RES_TRIM of it comes
// off, as a gain on SC by RES (OT_RTRIM, Q14): -1.4 dB at RES 0, -0.7 at 8, -0.2 at 32, none from ~96.
#define RES_TRIM 0.15
static double resBoostDb(int r) {
    static const double R[] = {0, 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 127};
    static const double D[] = {9.2, 7.6, 6.4, 5.5, 4.8, 3.7, 2.9, 2.3, 1.9, 1.3, 0.9, 0.6, 0.3, 0.1, 0.0, 0.0};
    for (int i = 1; i < 16; i++) if (r <= R[i]) return D[i - 1] + (D[i] - D[i - 1]) * (r - R[i - 1]) / (R[i] - R[i - 1]);
    return 0.0;
}
static unsigned rtrimQ14(int r) { return (unsigned)std::llround(std::pow(10.0, -RES_TRIM * resBoostDb(r) / 20.0) * 16384.0); }

static int gen(const char* path) {
    Open303 o; o.setSampleRate(FS);
    o.normalAmpRelease = NORMAL_RELEASE_MS;
    // amp envelope coefficients after a normal and an accented note (triggerNote's switch)
    o.noteOn(36, 64, 0.0);
    double decayC = o.ampEnv.decayCoeff, relN = o.ampEnv.releaseCoeff;
    o.noteOn(36, 0, 0.0);
    Open303 a; a.setSampleRate(FS); a.setAccent(100.0); a.noteOn(36, 127, 0.0);
    double relA = a.ampEnv.releaseCoeff;
    int32_t mOn = q23(1.0 - decayC);
    FILE* f = std::fopen(path, "w");
    if (!f) { std::perror(path); return 1; }
    std::fprintf(f, "/* Generated by tools/ot303/params_check.cpp gen (tools/ot303/params_check.py); do not edit.\n"
                    " * Open303 313bf0d9's constants for tools/ot303/cf/params.c. */\n#ifndef OT303_PARAMS_CONST_H\n#define OT303_PARAMS_CONST_H\n");
    // calculateEnvModScalerAndOffset (measured mapping) in Q28, c over CUT's range
    const double c0 = 3.138152786059267e+002, c1 = 2.394411986817546e+003;
    double L = std::log(c1 / c0);
    std::fprintf(f, "#define OT_A0 (%lldLL)\n#define OT_A1 (%lldLL)\n", (long long)qn(std::log(200.0 / c0) / L, 28),
                 (long long)qn(std::log(50.0) / L, 28));
    std::fprintf(f, "#define OT_SLOF (%lldLL)\n#define OT_SLOC (%lldLL)\n#define OT_SHIF (%lldLL)\n#define OT_SHIC (%lldLL)\n",
                 (long long)qn(3.773996325111173, 28), (long long)qn(0.736965594166206, 28),
                 (long long)qn(4.194548788411135, 28), (long long)qn(0.864344900642434, 28));
    std::fprintf(f, "#define OT_OF (%lldLL)\n#define OT_OC (%lldLL)\n#define OT_LOG50 (%lldLL)\n",
                 (long long)qn(0.048292930943553, 28), (long long)qn(0.294391201442418, 28), (long long)qn(std::log2(50.0), 28));
    // resonance skew and the exponent steps (Q24 per knob step)
    std::fprintf(f, "#define OT_RES_ARG24 (%lldLL)\n#define OT_RES_K (%lldLL)\n", (long long)qn(3.0 * std::log2(std::exp(1.0)) / 127.0, 24),
                 (long long)qn(1.0 / (1.0 - std::exp(-3.0)), 30));
    std::fprintf(f, "#define OT_DEC_ARG24 (%lldLL)\n", (long long)qn(std::log2(40.0) / 127.0, 24));
    // decay rates x = 1 / (0.001 tau fs), Q41: tau 50 ms (DEC 0) and the accent's 200 ms
    std::fprintf(f, "#define OT_X0 (%lldLL)\n#define OT_X_ACC (%lldLL)\n", (long long)qn(1.0 / (0.001 * 50.0 * FS), 41),
                 (long long)qn(1.0 / (0.001 * o.accentDecay * FS), 41));
    std::fprintf(f, "#define OT_SQDC4_MAG_Q30 (%lldLL)\n", (long long)qn(-sqDC() / 4.0, 30));
    std::fprintf(f, "#define OT_RCP17X8 (%lldLL)\n#define OT_SC_PER_K2 (%lldLL)\n", (long long)qn(8.0 / 17.0, 32),
                 (long long)qn(8388608.0 / 16129.0, 16));
    std::fprintf(f, "static const int64_t OT_RCPN[6] = {0, 0");
    for (int n = 2; n <= 5; n++) std::fprintf(f, ", %lldLL", (long long)qn(1.0 / n, 32));
    std::fprintf(f, "};\nstatic const uint32_t OT_INC12[12] = {");
    for (int s = 0; s < 12; s++) std::fprintf(f, "%s%s%uu", s ? "," : "", s % 6 ? " " : "\n    ",
                                             (unsigned)std::llround(std::exp2(s / 12.0) * std::ldexp(1.0, 54) / (127.0 * 88200.0)));
    std::fprintf(f, "};\n");
    std::fprintf(f, "#define OT_K8_BASE (%d)\n", q23(0.45 / 8.0));
    std::fprintf(f, "#define OT_M_AMP_ON (%d)\n#define OT_M_AMP_OFF_N (%d)\n#define OT_M_AMP_OFF_A (%d)\n", mOn,
                 q23(1.0 - relN), q23(1.0 - relA));
    std::fprintf(f, "#define OT_AMP2 (%d)\n", q23(0.5 / (mOn / 8388608.0)));
    std::fprintf(f, "#define OT_LN2_Q38 (%lldLL)\n", (long long)qn(std::log(2.0), 38));   // u = t ln2 2^6, t of 2^18
    std::fprintf(f, "static const uint32_t OT_EXP2[65] = {");
    for (int j = 0; j <= 64; j++) std::fprintf(f, "%s%s%uu", j ? "," : "", j % 6 ? " " : "\n    ", (unsigned)std::llround(std::ldexp(std::exp2(j / 64.0), 30)));
    std::fprintf(f, "};\n/* MT10: the soft attack for RES 100..114 (below: [0], from 115: none) */\n");
    std::fprintf(f, "static const int32_t OT_RC1[15] = {");
    for (int j = 0; j < 15; j++) std::fprintf(f, "%s%s%d", j ? "," : "", j % 8 ? " " : "\n    ", rc1Word(100 + j));
    std::fprintf(f, "};\n/* MT13: VOL -> the level (0 silent, 1..64 -30 dB .. top) and the drive / 8 for VOL 65..127 */\n");
    std::fprintf(f, "static const int32_t OT_SC[128] = {");
    for (int j = 0; j < 128; j++) std::fprintf(f, "%s%s%d", j ? "," : "", j % 8 ? " " : "\n    ", scWord(j));
    std::fprintf(f, "};\nstatic const int32_t OT_GD8[63] = {");
    for (int j = 0; j < 63; j++) std::fprintf(f, "%s%s%d", j ? "," : "", j % 8 ? " " : "\n    ", gd8Word(65 + j));
    std::fprintf(f, "};\n/* MT34: the RES level trim, Q14 (round 17: 15 %% of the low-RES boost) */\nstatic const uint16_t OT_RTRIM[128] = {");
    for (int j = 0; j < 128; j++) std::fprintf(f, "%s%s%u", j ? "," : "", j % 8 ? " " : "\n    ", rtrimQ14(j));
    std::fprintf(f, "};\n/* MT29: the WAVE gain, Q14 (tools/ot303/wave_loudness.py) */\nstatic const uint16_t OT_WGAIN[128] = {");
    for (int j = 0; j < 128; j++) std::fprintf(f, "%s%s%u", j ? "," : "", j % 8 ? " " : "\n    ", wgainQ14(j));
    std::fprintf(f, "};\n#endif\n");
    std::fclose(f);
    std::printf("wrote %s\n", path);
    return 0;
}

#ifndef OT_GEN_ONLY
// the words as TwinVoice::host() makes them from an Open303 set to knobs k
struct Ref { ot_cont c; ot_note n; };
static Ref reference(const uint8_t k[12]) {
    Open303 o; o.setSampleRate(FS);
    o.normalAmpRelease = NORMAL_RELEASE_MS;
    o.setCutoff(cutoffHz(k[OT_CUT]));
    o.setEnvMod(100.0 * k[OT_ENV] / 127.0);
    o.setResonance(100.0 * k[OT_RES] / 127.0);
    o.setDecay(decayMs(k[OT_DEC]));
    o.setAccent(100.0 * k[OT_ACC] / 127.0);
    o.setSlideTime(slideMs(k[OT_SLID]));
    o.setTuning(tuningHz(k[OT_TUNE]));
    o.setWaveform(k[OT_WAVE] / 127.0);
    o.noteOn((int)ot_note_number(k[OT_PTCH]), k[OT_ACC] ? 127 : 64, 0.0);
    Ref r{};
    double rr = 0.01 * (100.0 * k[OT_RES] / 127.0), rs = (1.0 - std::exp(-3.0 * rr)) / (1.0 - std::exp(-3.0));
    r.c.cs = q23(1.0 - o.pitchSlewLimiter.coeff);
    r.c.l0_16 = q23((std::log2(o.cutoff / 200.0) - o.envScaler * o.envOffset) / 16.0);
    r.c.es8 = q23(o.envScaler / 8.0);
    r.c.rs = q23(rs);
    r.c.ag_8 = q23((1.0 - rs * rs) / 8.0);
    r.c.bg = q23(rs * (1.0 + rs) * 8.0 / 17.0);
    r.c.sc = (int32_t)(((int64_t)scWord(k[OT_VOL]) * rtrimQ14(k[OT_RES]) + 8192) >> 14);   // MT34: the RES trim
    r.c.rc1 = rc1Word(k[OT_RES]); r.c.gd8 = gd8Word(k[OT_VOL]);
    double b = o.oscillator.blend;
    const double G = wgainQ14(k[OT_WAVE]) / 16384.0;   // MT29: not Open303's -- the WAVE gain
    r.c.w1 = q23(-(1.0 - b) / 2.0 * G); r.c.w2 = q23(b / 4.0 * G); r.c.w3 = q23(b * sqDC() / 4.0 * G); r.c.sq = b > 0.0;
    r.n.inc_t = q23(2.0 * o.oscFreq * o.pitchWheelFactor / (4 * FS));
    r.n.c_meg = q23(o.mainEnv.c);
    int64_t m48 = (int64_t)std::nearbyint(0.5 / o.mainEnv.c * 140737488355328.0);
    r.n.m48h = (ot_w)(m48 >> 24); r.n.m48l = (ot_w)(m48 & 0xffffff);
    r.n.m_amp_on = q23(1.0 - o.ampEnv.decayCoeff);
    r.n.m_amp_off = q23(1.0 - o.ampEnv.releaseCoeff);
    r.n.ag8 = q23(o.accentGain * o.n2 / 8.0);
    r.n.agf = o.accentGain > 0.0 ? 0xffffff : 0;
    r.n.k8_on = q23((0.45 + 4.0 * o.accentGain) / 8.0);
    r.n.amp2 = q23(0.5 / (r.n.m_amp_on / 8388608.0));
    return r;
}

static int check() {
    static const char* cn[] = {"CS", "L0_16", "ES8", "RS", "AG_8", "BG", "SC", "W1", "W2", "W3", "SQ", "RC1", "GD8"};
    static const char* nn[] = {"INC_T", "C_MEG", "M_AMP_on", "M_AMP_off", "AG8", "AGF", "K8_on", "M48 hi", "M48 lo", "AMP2"};
    const uint8_t D[12] = {36, 30, 64, 32, 38, 0, 0, 64, 38, 63, 99, 0};   // control.c's defaults
    long worstC[13] = {0}, worstN[10] = {0}; int atC[13] = {0}, atN[10] = {0};
    double m48rel = 0;
    auto cmp = [&](const uint8_t* k, int knob) {
        ot_cont c; ot_note n; ot_params_cont(k, &c); ot_params_note(k, &n);
        Ref r = reference(k);
        const ot_w* a = &c.cs; const ot_w* b = &r.c.cs;
        for (int i = 0; i < 13; i++) { long d = std::labs((long)a[i] - b[i]); if (d > worstC[i]) { worstC[i] = d; atC[i] = knob; } }
        a = &n.inc_t; b = &r.n.inc_t;
        for (int i = 0; i < 10; i++) {
            if (i == 7 || i == 8) continue;
            long d = std::labs((long)a[i] - b[i]); if (d > worstN[i]) { worstN[i] = d; atN[i] = knob; }
        }
        int64_t m = ((int64_t)n.m48h << 24) | (n.m48l & 0xffffff), rm = ((int64_t)r.n.m48h << 24) | (r.n.m48l & 0xffffff);
        m48rel = std::fmax(m48rel, std::fabs((double)(m - rm)) / (double)rm);
    };
    for (int knob = 0; knob < 11; knob++)
        for (int v = 0; v < 128; v++) {
            uint8_t k[12]; std::memcpy(k, D, 12); k[knob] = (uint8_t)v;
            cmp(k, knob * 1000 + v);
            if (knob == OT_DEC || knob == OT_TUNE) { k[OT_ACC] = 100; cmp(k, knob * 1000 + v); }     // accented notes too
        }
    for (int cu = 0; cu < 128; cu++) for (int en = 0; en < 128; en++) {        // CUT x ENV
        uint8_t k[12]; std::memcpy(k, D, 12); k[OT_CUT] = (uint8_t)cu; k[OT_ENV] = (uint8_t)en;
        cmp(k, 100000 + cu * 1000 + en);
    }
    int bad = 0;
    std::printf("continuous words, worst |params.c - Open303| in LSBs of 2^-23 (where):\n");
    for (int i = 0; i < 13; i++) { std::printf("  %-6s %6ld  (%d)\n", cn[i], worstC[i], atC[i]); bad += worstC[i] > 8; }
    std::printf("note words:\n");
    for (int i = 0; i < 10; i++) if (i != 7 && i != 8) { std::printf("  %-9s %6ld  (%d)\n", nn[i], worstN[i], atN[i]); bad += worstN[i] > 8; }
    std::printf("  M48       relative %.2e\n", m48rel);
    bad += m48rel > 1e-6;
    // PTCH: C0 .. C8 on the knob's 97 values, a semitone each (above 96: C8), named as the display shows it
    {
        static const char* NM[12] = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
        int per[97] = {0}, pbad = 0, prev = -1;
        for (int v = 0; v < 128; v++) {
            int n = (int)ot_note_number(v) - 12;
            char got[4], want[8]; unsigned len = ot_note_name(v, got);
            std::snprintf(want, sizeof want, "%s%d", NM[n % 12], n / 12);
            pbad += n < 0 || n > 96 || n < prev || std::strcmp(got, want) != 0 || len != std::strlen(want);
            if (n >= 0 && n <= 96) per[n]++;
            prev = n;
        }
        for (int n = 0; n < 96; n++) pbad += per[n] != 1;
        for (int v = 0; v <= 96; v++) pbad += (int)ot_note_number(v) != 12 + v;
        char a0[4], a36[4], a96[4]; ot_note_name(0, a0); ot_note_name(36, a36); ot_note_name(96, a96);
        pbad += std::strcmp(a0, "C0") || std::strcmp(a36, "C3") || std::strcmp(a96, "C8");
        std::printf("PTCH: 0 %s, 36 %s, 96 %s (97..127: C8); a semitone a value: %s\n", a0, a36, a96, pbad ? "BAD" : "ok");
        bad += pbad;
    }
    std::printf(bad ? "%d words beyond 8 LSB\n" : "ALL WITHIN 8 LSB (2^-20)\n", bad);
    return bad ? 1 : 0;
}

#endif

int main(int argc, char** argv) {
    if (argc == 3 && !std::strcmp(argv[1], "gen")) return gen(argv[2]);
#ifndef OT_GEN_ONLY
    if (argc == 2 && !std::strcmp(argv[1], "check")) return check();
#endif
    std::fprintf(stderr, "usage: params_check gen OUT.h | check\n");
    return 2;
}

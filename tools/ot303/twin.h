// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 Phase 2b: the integer twin. The final voice (OT303_SCOPE.md §11, "VOICING FINAL") in the
// DSP56300's own arithmetic, step for step: 24-bit words (Q23), 56-bit accumulators, fractional
// multiplies, stores that saturate and truncate (A1, no rounding: independent of the SR rounding
// mode). The DSP assembly must match this bit for bit; this must match the approved voice by ear
// and by measurement.
//
// The lean engine (option 3, user 2026-10-06):
//   * Open303's per-sample coefficient formulas (pow 2^x, the b0 rational, the k polynomial, g)
//     become two tables over log2(cutoff), 1/32 octave apart, linearly interpolated. The cutoff
//     never leaves the log domain, so there is no exp2 and no division.
//   * the square is only computed when WAVE is not pure saw (the host selects the loop);
//   * the second decimator stage is switchable (HB2_*).
// Everything that changes only at a note event or a knob move is a HOST word (the ColdFire's job,
// modelled here in double and rounded to Q23). Everything per sample is the DSP's.
//
// Included by voice_study.cpp after rosic_Open303.h: the twin borrows Open303 for its note logic
// (the note list, slide/accent decisions), never for audio.
#pragma once
#include <cstdint>
#include <cmath>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace twin {

using W = int32_t;      // a 24-bit data word, sign-extended
using A = int64_t;      // an accumulator: LSB = 2^-47 (A1 = bits 24..47, A2 = the extension)

static long g_sat = 0;                          // saturations on store (should stay 0)
static std::map<std::string, double> g_peak;    // |value| / full scale, before saturation

static inline W q23(double v) {                 // a host word: round to Q23, clamp
    double x = std::nearbyint(v * 8388608.0);
    if (x > 8388607.0) x = 8388607.0;
    if (x < -8388608.0) x = -8388608.0;
    return (W)x;
}
static inline double f23(W w) { return w / 8388608.0; }
static inline A acc(W w) { return (A)w << 24; }            // move w,a
static inline A mpy(W x, W y) { return ((A)x * (A)y) << 1; } // fractional multiply, exact
static inline A sh(A a, int n) { return n >= 0 ? a << n : a >> (-n); }   // asl / asr #n (exact here)
static inline W st(A a, const char* probe = nullptr) {    // move a,x:  (limit, then A1)
    A hi = a >> 24;
    if (probe) { double p = std::fabs((double)hi) / 8388608.0; double& m = g_peak[probe]; if (p > m) m = p; }
    if (hi > 0x7FFFFF) { g_sat++; return 0x7FFFFF; }
    if (hi < -0x800000) { g_sat++; return -0x800000; }
    return (W)hi;
}
static inline A rnd(A a) {                                  // rnd a: convergent (SR RM = 0, the reset default)
    A lo = a & 0xFFFFFF, hi = a >> 24;
    if (lo > 0x800000 || (lo == 0x800000 && (hi & 1))) hi += 1;
    return hi << 24;
}
static inline W str(A a, const char* probe = nullptr) { return st(rnd(a), probe); }   // macr/mpyr + move
static inline W wrap(A a) {                                 // move a1,x: no limiting (phase)
    W v = (W)((a >> 24) & 0xFFFFFF);
    return (v & 0x800000) ? v - 0x1000000 : v;
}
static inline W divq(W num, W den) {                        // 24-step div: floor(num/den), 0<=num<den
    return (W)(((A)num << 23) / den);
}

// ---------------------------------------------------------------------------------------------
// Tables (Y/X data on the DSP: value in X, slope in Y, one L: fetch per lookup)
static const int LT_STEPS = 32;                             // per octave
static const double LT_OCT = 6.6438561897747253;            // log2(20000/200)
static const int LT_N = 214;                                // entries 0..213 (212.6 needed)
struct Tables {
    W b0[LT_N + 1], db0[LT_N + 1], kp[LT_N + 1], dkp[LT_N + 1];   // b0 (fs 1), kpoly/64
    W th[513], dth[513];                                           // tanh over [-8, 8), 1/32 step
    void build() {
        for (int i = 0; i <= LT_N; i++) {
            double fc = 200.0 * std::pow(2.0, (double)i / LT_STEPS);
            double fx = fc / (176400.0 * std::sqrt(2.0));
            double b = (0.00045522346 + 6.1922189 * fx) / (1.0 + 12.358354 * fx + 4.4156345 * (fx * fx));
            double k = fx*(fx*(fx*(fx*(fx*(fx+7198.6997)-5837.7917)-476.47308)+614.95611)+213.87126)+16.998792;
            b0[i] = q23(b); kp[i] = q23(k / 64.0);
        }
        for (int i = 0; i < LT_N; i++) { db0[i] = b0[i + 1] - b0[i]; dkp[i] = kp[i + 1] - kp[i]; }
        db0[LT_N] = dkp[LT_N] = 0;
        for (int i = 0; i <= 512; i++) th[i] = q23(std::tanh(-8.0 + i / 32.0));
        for (int i = 0; i < 512; i++) dth[i] = th[i + 1] - th[i];
        dth[512] = 0;
    }
};
static Tables T;

// one interpolated lookup: v[i] + f * dv[i], f = the low bits of the index word as Q23
static inline A lerp(const W* v, const W* dv, int i, W f) { return acc(v[i]) + mpy(f, dv[i]); }

// ---------------------------------------------------------------------------------------------
// A half-band decimator: odd taps + centre 0.5, newest sample first. Exact accumulation.
struct HB {
    std::vector<W> c, buf; int n = 0, pos = 0;
    void init(const double* odd, int nOdd) {
        n = 2 * nOdd - 1;                                  // odd taps sit at offsets 1, 3, .. from the centre
        c.resize(nOdd); for (int i = 0; i < nOdd; i++) c[i] = q23(odd[i]);
        buf.assign(n, 0); pos = 0;
    }
    void reset() { std::fill(buf.begin(), buf.end(), 0); pos = 0; }
    void push(W x) { buf[pos] = x; pos = (pos + 1) % n; }
    W out(const char* probe) const {
        A a = 0; int ci = 0;
        for (int i = 0; i < n; i++) {
            int d = i - (n - 1) / 2;
            W x = buf[(pos - 1 - i + 2 * n) % n];
            if (d == 0) a += mpy(0x400000, x);
            else if (d % 2 != 0) a += mpy(c[ci++], x);
        }
        return st(a, probe);
    }
};

// A TPT state-variable filter (Zavalishin / Cytomic), a1 = 1/(1+g(g+k)), a2 = g a1, a3 = g a2.
// a2 and a3 are stored scaled up (2^s2, 2^s3) so tiny g keeps its precision.
struct SVF {
    W a1 = 0, a2 = 0, a3 = 0, kk = 0; int s2 = 0, s3 = 0, sk = 0; W ic1 = 0, ic2 = 0;
    void design(double f, double fs, double k, int s2_, int s3_, int sk_) {
        double g = std::tan(M_PI * f / fs), A1 = 1.0 / (1.0 + g * (g + k)), A2 = g * A1, A3 = g * A2;
        s2 = s2_; s3 = s3_; sk = sk_;
        a1 = q23(A1); a2 = q23(A2 * std::ldexp(1.0, s2)); a3 = q23(A3 * std::ldexp(1.0, s3));
        kk = q23(k / std::ldexp(1.0, sk));
    }
    void reset() { ic1 = ic2 = 0; }
    // returns v1 (band) and v2 (low); updates the states
    void tick(W x, W& v1, W& v2, const char* p1, const char* p2) {
        W v3 = st(acc(x) - acc(ic2), p1);
        v1 = str(mpy(a1, ic1) + sh(mpy(a2, v3), -s2), p1);
        v2 = str(acc(ic2) + sh(mpy(a2, ic1), -s2) + sh(mpy(a3, v3), -s3), p2);
        ic1 = st(acc(v1) + acc(v1) - acc(ic1), p1);
        ic2 = st(acc(v2) + acc(v2) - acc(ic2), p2);
    }
};

// ---------------------------------------------------------------------------------------------
struct Engine {
    // ---- HOST words (ColdFire contract; scales in the names: X8 = X/8 etc.)
    W INC_T = 0;     // target phase increment per 4x sample (phase spans 2.0 per cycle)
    A INC_T48 = 0;   // the same, 48 bits (inc48)
    W CS = 0;        // 1 - slew coefficient
    W C_MEG = 0;     // main envelope decay multiplier
    W C2 = 0;        // rc2 (accent attack) coefficient
    W M_AMP = 0;     // amp envelope multiplier (decay while held, release after)
    W L0_16 = 0;     // (log2(cutoff/200) - envScaler*envOffset) / 16
    W ES8 = 0;       // envScaler / 8
    W AG8 = 0;       // accentGain / 8
    bool AGF = false;// accent active (rc2 is fed by the MEG)
    W RS = 0;        // resonance, skewed
    W AG_8 = 0;      // (1 - rs^2) / 8           g = (1-rs^2) + rs(1+rs)/17 * kpoly
    W BG = 0;        // rs (1+rs) * 8 / 17       (times kpoly/64 gives the rest of g/8)
    W K8 = 0;        // (0.45 + 4 accentGain) / 8 while the note is on, else 0
    W SC = 0;        // ampScaler
    W W1 = 0, W2 = 0, W3 = 0;   // osc/2 = W1 saw + W2 tanh(..) + W3
    bool SQ = false; // WAVE > 0: the square loop
    // ---- constants (built once)
    W HP1_B = 0, HP1_A = 0;     // pre-filter high-pass 44.486 Hz @ 176.4 kHz (fs 2)
    W FB_B = 0, FB_A = 0;       // feedback high-pass 150 Hz @ 176.4 kHz
    W AP_B = 0, AP_A = 0;       // allpass 14.008 Hz @ 44.1 kHz
    W HP2_B = 0, HP2_A = 0;     // high-pass 24.167 Hz @ 44.1 kHz
    W TOP_A = 0;                // top rounding one-pole (bilinear) 16 kHz @ 44.1 kHz
    W S70 = 0, C437 = 0;        // square shaper: x/128 = S70 * s + C437
    SVF notch, decl;
    HB hb4, hb2;
    // ---- DSP state
    A S48 = 0;                  // slewed increment, 48-bit (L memory)
    W MEG2 = 0, RC2 = 0, AMP2 = 0;
    A M48 = 0;                  // meg48: the main envelope as 48 bits (MEG2 = its top word)
    W P = 0;
    A PH = 0;                   // inc48: the phase as 48 bits (P = its top word)
    W hpx = 0, hpy = 0;
    W fbx = 0, fby = 0, Y1 = 0, Y2 = 0, Y3 = 0, Y4 = 0;
    W apx = 0, apy = 0, h2x = 0, h2y = 0, tops = 0;
    // ---- options
    int FBS = 4;                // feedback words are fbin / 2^FBS
    bool topOn = true;
    bool inc48 = false;         // 48-bit phase and increment (else 24-bit)
    bool meg48 = false;         // 48-bit main envelope (else 24-bit, truncating)
    int dlyN = 0; std::vector<W> dly; int dlyP = 0;   // test only: restore the 79-tap stage's latency
    long sqClamp = 0;           // the shaper's deliberate clamps (not errors)
    // diagnostic: the oscillator from outside (the reference's, in double); returns osc (not /2)
    double (*oscHook)(void*) = nullptr; void* oscCtx = nullptr;
    bool exactCoef = false;     // diagnostic: b0/kpoly from the formulas (double) instead of tables

    void init(const double* hb2odd, int hb2n, double topHz, const double* hb1odd = nullptr, int hb1n = 0) {
        T.build();
        const double fo = 176400.0, fb = 44100.0;
        double x = std::exp(-2.0 * M_PI * 44.486 / fo);
        HP1_B = q23(0.5 * (1 + x)); HP1_A = q23(x);
        x = std::exp(-2.0 * M_PI * 150.0 / fo);
        FB_B = q23(0.5 * (1 + x)); FB_A = q23(x);
        double t = std::tan(M_PI * 14.008 / fb); x = (t - 1.0) / (t + 1.0);
        AP_B = q23(x); AP_A = q23(-x);
        x = std::exp(-2.0 * M_PI * 24.167 / fb);
        HP2_B = q23(0.5 * (1 + x)); HP2_A = q23(x);
        topOn = topHz > 0;
        if (topOn) { double K = std::tan(M_PI * topHz / fb); TOP_A = q23(K / (1 + K)); }
        S70 = q23(std::pow(10.0, 36.9 / 20.0) / 128.0); C437 = q23(4.37 / 128.0);
        // Open303's notch: RBJ band-reject 7.5164 Hz, 4.7 octaves = the bilinear SVF notch
        double w = 2 * M_PI * 7.5164 / fb;
        double kn = 2.0 * std::sinh(0.5 * std::log(2.0) * 4.7 * w / std::sin(w));
        notch.design(7.5164, fb, kn, 8, 16, 3);
        // Open303's amp declicker: RBJ low-pass 200 Hz, Q = sqrt(0.5) = the bilinear SVF low-pass
        decl.design(200.0, fb, 1.0 / std::sqrt(0.5), 0, 8, 1);
        if (hb1odd) hb4.init(hb1odd, hb1n); else hb4.init(HB4_ODD, 12);
        hb2.init(hb2odd, hb2n);
    }
    void resetAudio() {
        P = 0; PH = 0; hpx = hpy = 0; fbx = fby = Y1 = Y2 = Y3 = Y4 = 0;
        apx = apy = h2x = h2y = tops = 0;
        notch.reset(); decl.reset(); hb4.reset(); hb2.reset();
    }

    // the saw at phase word p with its polyBLEP: the discontinuity (+1 -> -1) sits at the wrap
    inline W blep(W p, W inc) const {
        A d1 = acc(p) + acc(0x7FFFFF) + (A(1) << 24);          // p + 1 (just after the wrap)
        W dA = (W)(d1 >> 24);
        if (dA < inc) {                                        // w = (inc - d)/inc, saw = p + w^2
            W w = divq(inc - dA, inc);
            return st(acc(p) + mpy(w, w), "osc");
        }
        W dB = 0x7FFFFF - p + 1;                               // 1 - p (just before the wrap)
        if (dB <= inc) {                                       // saw = p - w^2
            W w = divq(inc - dB, inc);
            return st(acc(p) - mpy(w, w), "osc");
        }
        return p;
    }

    // allpass 14 Hz, high-pass 24 Hz, notch 7.5 Hz (Open303's post-filter voicing), fs 8
    W post(W x) {
        apy = str(mpy(AP_B, x) + acc(apx) + mpy(AP_A, apy), "ap"); apx = x; x = apy;
        h2y = str(mpy(HP2_B, x) - mpy(HP2_B, h2x) + mpy(HP2_A, h2y), "hp2"); h2x = x; x = h2y;
        W nv1, nv2;
        notch.tick(x, nv1, nv2, "n1", "n2");
        return st(acc(x) - sh(mpy(notch.kk, nv1), notch.sk), "notch");
    }

    // one 44.1 kHz output sample
    double tick() {
        // pitch slew, 48-bit state
        if (inc48) {                 // d = T - S (acc), asl #8 -> word, mpy CS, asr #8, add
            W d = st((INC_T48 - S48) << 8, "slew");
            S48 += mpy(CS, d) >> 8;
        } else {
            W shi = (W)(S48 >> 24);
            S48 += mpy(CS, INC_T - shi);
        }
        W INC = (W)(S48 >> 24);
        // main envelope, accent attack
        if (meg48) {                 // mpysu c,lo,a ; asr #24,a,a ; mac c,hi,a  (both products truncated)
            W hi = (W)(M48 >> 24); A lo = M48 & 0xFFFFFF;
            M48 = mpy(C_MEG, hi) + ((((A)C_MEG * lo) << 1) >> 24);
            MEG2 = (W)(M48 >> 24);
        } else
            MEG2 = st(mpy(MEG2, C_MEG), "meg");
        W in2 = AGF ? MEG2 : 0;
        RC2 = str(acc(in2) + mpy(C2, RC2 - in2), "rc2");
        // log cutoff, clamped to 200 Hz .. 20 kHz, then the coefficient tables
        A l = acc(L0_16) + mpy(ES8, MEG2) + mpy(AG8, RC2);
        W L16 = st(l, "L16");
        const W LMAX = q23(LT_OCT / 16.0);
        if (L16 < 0) L16 = 0;
        if (L16 > LMAX) L16 = LMAX;
        int i = L16 >> 14;                                     // 1/32 octave per entry
        W f = (L16 & 0x3FFF) << 9;
        W B0 = st(lerp(T.b0, T.db0, i, f), "b0");
        W KP = st(lerp(T.kp, T.dkp, i, f), "kp64");
        if (exactCoef) {
            double fc = 200.0 * std::pow(2.0, f23(L16) * 16.0), fx = fc / (176400.0 * std::sqrt(2.0));
            B0 = q23((0.00045522346 + 6.1922189 * fx) / (1.0 + 12.358354 * fx + 4.4156345 * (fx * fx)));
            KP = q23((fx*(fx*(fx*(fx*(fx*(fx+7198.6997)-5837.7917)-476.47308)+614.95611)+213.87126)+16.998792) / 64.0);
        }
        W B2 = B0 * 2;                                          // asl: b0 <= 0.25
        W K64 = st(mpy(KP, RS), "k64");
        W G8 = st(acc(AG_8) + mpy(BG, KP), "g8");
        // amp envelope + MEG into the declicker (amp / 16)
        AMP2 = st(mpy(AMP2, M_AMP), "amp");
        W u = st(mpy(AMP2, 0x100000) + mpy(K8, MEG2), "amp16");
        W dv1, AD16;
        decl.tick(u, dv1, AD16, "decl1", "decl2");
        W ADS = st(mpy(AD16, SC), "ads");

        for (int n = 0; n < 4; n++) {
            if (inc48) {                                         // add x,a ; move a10,l: (no limiting)
                PH = (PH + (S48 & ((A(1) << 48) - 1))) & ((A(1) << 48) - 1);
                P = (W)(PH >> 24); if (P & 0x800000) P -= 0x1000000;
            } else P = wrap(acc(P) + acc(INC));
            W saw = blep(P, INC);
            A o = mpy(W1, saw);
            if (SQ) {
                W s = blep(P >= 0 ? P - 0x800000 : P + 0x800000, INC);   // half a cycle on (eor #$800000)
                long sv = g_sat;
                W x8 = st(sh(mpy(S70, s) + acc(C437), 4), "sqx");       // x/8, saturating at +-8 (on purpose)
                sqClamp += g_sat - sv; g_sat = sv;
                int ti = (x8 >> 15) + 256;                      // 256 entries per unit of x/8
                W tf = (x8 & 0x7FFF) << 8;
                W th = st(lerp(T.th, T.dth, ti, tf), nullptr);
                o += mpy(W2, th) + acc(W3);
            }
            W osc = oscHook ? q23(-0.5 * oscHook(oscCtx)) : st(o, "osc2");
            // pre-filter high-pass (fs 2)
            hpy = str(mpy(HP1_B, osc) - mpy(HP1_B, hpx) + mpy(HP1_A, hpy), "hp1");
            hpx = osc;
            // TB-303 filter (Open303's TeeBeeFilter, TB_303 mode), states / 8
            W fbin = st(sh(mpy(K64, Y4), 9 - FBS), "fbin");   // (k/64)(y4/8) = k y4/512 -> k y4 / 2^FBS
            fby = str(mpy(FB_B, fbin) - mpy(FB_B, fbx) + mpy(FB_A, fby), "fby");
            fbx = fbin;
            W y0 = st(sh(acc(hpy), -2) - sh(acc(fby), FBS - 3), "y0");
            Y1 = str(acc(Y1) + mpy(B2, y0) - mpy(B2, Y1) + mpy(B2, Y2), "y1");
            Y2 = str(acc(Y2) + mpy(B0, Y1) - mpy(B2, Y2) + mpy(B0, Y3), "y2");
            Y3 = str(acc(Y3) + mpy(B0, Y2) - mpy(B2, Y3) + mpy(B0, Y4), "y3");
            Y4 = str(acc(Y4) + mpy(B0, Y3) - mpy(B2, Y4), "y4");
            W fo = st(sh(mpy(G8, Y4), 4), "fout");             // 2 g y4 / 8
            hb4.push(fo);
            if (n & 1) hb2.push(hb4.out("hb4"));
        }
        W x = hb2.out("hb2");                                     // fs 8 from here
        if (dlyN) { if ((int)dly.size() != dlyN) dly.assign(dlyN, 0); W d = dly[dlyP]; dly[dlyP] = x; dlyP = (dlyP + 1) % dlyN; x = d; }
        x = post(x);
        W y = st(sh(mpy(x, ADS), 5), "out4");                     // x amp scaler / 4
        if (topOn) {                                              // v = (x - s) a; y = v + s; s = y + v
            W v = str(mpy(TOP_A, st(acc(y) - acc(tops), "top")), "top");
            W yy = st(acc(v) + acc(tops), "top");
            tops = st(acc(yy) + acc(v), "top");
            y = yy;
        }
        return f23(y) * 4.0;
    }
};

} // namespace twin

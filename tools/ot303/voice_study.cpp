// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 Phase 1, time-domain half: render Open303's voice with the filter and the
// oversampling factor swapped, everything else (oscillator tables, envelopes, slide, accent,
// pre/post voicing) Open303's own code. reference/handoffs/OT303_SCOPE.md §9.
//
// Open303 (c) 2009 Robin Schmidt, MIT (pinned 313bf0d9, fetched by build_voice_study.sh).
// This harness reaches into Open303's protected members (#define below): a test rig only,
// never shipped code.
//
//   voice_study validate                 o303 @4x through this harness == rosic::Open303, bit for bit
//   voice_study render SCENE FILTER N DEC DRIVE HEUN OUT.f32
//       SCENE  sweep | hot | squelch | square
//       FILTER o303 (TeeBeeFilter, TB_303) | zdf (linear TPT) | zdfnl (nonlinear, cheap ZDF)
//              | ref (linear, RK4 x16 substeps) | refnl (nonlinear, RK4 x16 substeps)
//       N      oversampling factor 1..8
//       DEC    ell (Open303's quarter-band elliptic, N=4 only) | fir (Kaiser, 100 dB)
//       DRIVE  nonlinear drive D: the ladder sees tanh(D v)/D (D -> 0 is linear)
//       HEUN   0/1: one corrector pass for the nonlinear gain factors
//   output: raw float32 mono at 44.1 kHz
#define protected public
#define private public
#include "rosic_Open303.h"
#undef private
#undef protected

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "halfband79.h"
#include "ktab.h"
#include "halfband4x.h"

using namespace rosic;
static const double FS = 44100.0;

// ------------------------------------------------------------------------------------------
// the analog-limit parameter mapping of Open303's TB_303 mode (filter_linear.py documents it)
static double KMAX = 0;            // 0: Open303's 16.998792; else the RES-100 feedback gain
static double FMAX = 20000.0;      // the cutoff ceiling (Open303: 20 kHz)
static int KCAPMODE = 0;           // 0: k = KMAX r (rounds 3-4); 1: k = min(16.998792 r, KMAX)
static int KTSEL = 0;              // 0 off; 15/30/45: k(RES, fc) toward Open303's peaks - 1.5/3/4.5 dB
static double ktab(double knob, double fc) {
    const double (*T)[15] = KTSEL == 15 ? KT_15 : KTSEL == 30 ? KT_30 : KT_45;
    double x = (log2(fc) - log2(200.0)) / (log2(20000.0) - log2(200.0)) * (KT_NF - 1);
    x = x < 0 ? 0 : (x > KT_NF - 1 ? KT_NF - 1 : x);
    int j = (int)x; if (j > KT_NF - 2) j = KT_NF - 2; double fx = x - j;
    int i = 0; while (i < 3 && knob > KT_KNOB[i + 1]) i++;
    double fy = (knob - KT_KNOB[i]) / (KT_KNOB[i + 1] - KT_KNOB[i]); fy = fy < 0 ? 0 : (fy > 1 ? 1 : fy);
    auto at = [&](int r, int c) { return T[r][c]; };
    double a = at(i, j) + fx * (at(i, j + 1) - at(i, j)), b = at(i + 1, j) + fx * (at(i + 1, j + 1) - at(i + 1, j));
    return a + fy * (b - a);
}
struct Mapping {
    double fc = 1000.0, r = 0.0, wc = 0, k = 0, g = 1;
    static double skew(double pct) {
        double rr = 0.01 * pct;
        return (1.0 - exp(-3.0 * rr)) / (1.0 - exp(-3.0));
    }
    void update() {
        double f = fc < 200.0 ? 200.0 : (fc > FMAX ? FMAX : fc);
        double w = 0.00045522346 * 176400.0 + 6.1922189 * f / sqrt(2.0);
        wc = 2.0 * w;
        // Open303's resonance curve, clipped at the ceiling: only RES above ~92% (where 16.998792 r
        // would exceed KMAX) is held down. (Until 2026-10-06 this scaled every RES by KMAX/16.998792.)
        k = 16.998792 * r;
        if (KCAPMODE == 0 && KMAX > 0) k = KMAX * r;
        else if (KMAX > 0 && k > KMAX) k = KMAX;
        if (KTSEL && r > 0) {          // only ever adds resonance, only above ~1.4-2.8 kHz
            double knob = -log(1.0 - r * (1.0 - exp(-3.0))) / 3.0;
            if (knob >= 0.25) {
                double w = (log2(f) - log2(1400.0)) / (log2(2800.0) - log2(1400.0));
                w = w < 0 ? 0 : (w > 1 ? 1 : w);
                double kt = ktab(knob, f);
                if (kt > k) k = k + w * (kt - k);
                if (k > KTAB_CAP) k = KTAB_CAP;
            }
        }
        g = ((16.998792 / 17.0 - 1.0) * r + 1.0) * (1.0 + r);
    }
};

struct Filt {
    virtual ~Filt() {}
    virtual void setSampleRate(double fs) = 0;
    virtual void setCutoff(double fc) = 0;
    virtual void setResonance(double pct) = 0;
    virtual double tick(double in) = 0;
    virtual void reset() = 0;
};

struct FO303 : Filt {
    TeeBeeFilter f;
    void setSampleRate(double fs) override { f.setSampleRate(fs); }
    void setCutoff(double fc) override { f.setCutoff(fc); }
    void setResonance(double pct) override { f.setResonance(pct); }
    double tick(double in) override { return f.getSample(in); }
    void reset() override { f.reset(); }
};

static inline double Tfac(double v, double D) {      // tanh(Dv)/(Dv), -> 1 at 0
    double x = D * v;
    if (fabs(x) < 1e-5) return 1.0 - x * x / 3.0;
    return tanh(x) / x;
}

// derivative of the diode ladder (Zavalishin VA Filter Design 2.1.0 §6.9 nonlinear form,
// linear when D == 0), state z = [y1 y2 y3 y4 l], HP out = k y4 - l
static inline void deriv(const double* z, double u, const Mapping& m, double wc, double wh,
                         double D, double* dz, double Dst = -1, double Dfb = 0) {
    // D: the input pair (and the stages too when Dst < 0, FZdf's uniform form); Dst: stages;
    // Dfb: the feedback path only
    if (Dst < 0) Dst = D;
    auto N = [](double v, double d) { return d > 0 ? tanh(d * v) / d : v; };
    double fb = N(m.k * z[3] - z[4], Dfb);
    double x = u - fb;
    double n0 = N(x, D), n12 = N(z[0] - z[1], Dst), n23 = N(z[1] - z[2], Dst), n34 = N(z[2] - z[3], Dst),
           n4 = N(z[3], Dst);
    dz[0] = wc * (n0 - n12);
    dz[1] = 0.5 * wc * (n12 - n23);
    dz[2] = 0.5 * wc * (n23 - n34);
    dz[3] = 0.5 * wc * (n34 - n4);
    dz[4] = wh * (m.k * z[3] - z[4]);
}

// ground truth: RK4 with S substeps per tick, input linearly interpolated
struct FRef : Filt {
    Mapping m; double fs = FS, D = 0, Dst = -1, Dfb = 0; int S = 16; double z[5] = {0}, uprev = 0;
    explicit FRef(double D_) : D(D_) {}
    void setSampleRate(double f) override { fs = f; }
    void setCutoff(double fc) override { m.fc = fc; m.update(); }
    void setResonance(double pct) override { m.r = Mapping::skew(pct); m.update(); }
    void reset() override { memset(z, 0, sizeof z); uprev = 0; }
    double tick(double in) override {
        double h = 1.0 / (fs * S), wh = 2 * M_PI * 150.0;
        for (int s = 0; s < S; s++) {
            double u0 = uprev + (in - uprev) * s / S, u1 = uprev + (in - uprev) * (s + 1) / S,
                   um = 0.5 * (u0 + u1);
            double k1[5], k2[5], k3[5], k4[5], t[5];
            deriv(z, u0, m, m.wc, wh, D, k1, Dst, Dfb);
            for (int i = 0; i < 5; i++) t[i] = z[i] + 0.5 * h * k1[i];
            deriv(t, um, m, m.wc, wh, D, k2, Dst, Dfb);
            for (int i = 0; i < 5; i++) t[i] = z[i] + 0.5 * h * k2[i];
            deriv(t, um, m, m.wc, wh, D, k3, Dst, Dfb);
            for (int i = 0; i < 5; i++) t[i] = z[i] + h * k3[i];
            deriv(t, u1, m, m.wc, wh, D, k4, Dst, Dfb);
            for (int i = 0; i < 5; i++) z[i] += h / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]);
        }
        uprev = in;
        return 2 * m.g * z[3];
    }
};

static void solve5(double A[5][5], double* b) {       // Gaussian elimination, partial pivot
    for (int c = 0; c < 5; c++) {
        int p = c;
        for (int r = c + 1; r < 5; r++) if (fabs(A[r][c]) > fabs(A[p][c])) p = r;
        if (p != c) { for (int j = 0; j < 5; j++) std::swap(A[c][j], A[p][j]); std::swap(b[c], b[p]); }
        for (int r = c + 1; r < 5; r++) {
            double f = A[r][c] / A[c][c];
            for (int j = c; j < 5; j++) A[r][j] -= f * A[c][j];
            b[r] -= f * b[c];
        }
    }
    for (int c = 4; c >= 0; c--) {
        for (int j = c + 1; j < 5; j++) b[c] -= A[c][j] * b[j];
        b[c] /= A[c][c];
    }
}

// the candidate: trapezoidal (TPT) diode ladder, omega_c prewarped at the resonance;
// nonlinear gains by mystran's "cheap non-linear zero-delay" method (tanh(v)/v evaluated at
// a state estimate, then the linear zero-delay solve), optional Heun corrector
struct FZdf : Filt {
    Mapping m; double fs = FS, D = 0; bool heun = false; double z[5] = {0}, uprev = 0;
    FZdf(double D_, bool h_) : D(D_), heun(h_) {}
    void setSampleRate(double f) override { fs = f; }
    void setCutoff(double fc) override { m.fc = fc; m.update(); }
    void setResonance(double pct) override { m.r = Mapping::skew(pct); m.update(); }
    void reset() override { memset(z, 0, sizeof z); uprev = 0; }
    void step(const double* z0, const double* est, double uest, double in, double* z1) {
        double h = 1.0 / fs;
        double wres = m.wc / sqrt(2.0), arg = wres * h / 2;
        if (arg > 0.98 * M_PI / 2) arg = 0.98 * M_PI / 2;
        double wc = m.wc * tan(arg) / (wres * h / 2);
        double wh = (2 / h) * tan(M_PI * 150.0 * h);
        double a = 1, b12 = 1, b23 = 1, b34 = 1, b4 = 1;
        if (D > 0) {
            a = Tfac(uest - (m.k * est[3] - est[4]), D);
            b12 = Tfac(est[0] - est[1], D); b23 = Tfac(est[1] - est[2], D);
            b34 = Tfac(est[2] - est[3], D); b4 = Tfac(est[3], D);
        }
        double A[5][5] = {{0}}, B[5] = {0};
        A[0][0] = -wc * b12; A[0][1] = wc * b12; A[0][3] = -wc * a * m.k; A[0][4] = wc * a;
        B[0] = wc * a;
        A[1][0] = 0.5 * wc * b12; A[1][1] = -0.5 * wc * (b12 + b23); A[1][2] = 0.5 * wc * b23;
        A[2][1] = 0.5 * wc * b23; A[2][2] = -0.5 * wc * (b23 + b34); A[2][3] = 0.5 * wc * b34;
        A[3][2] = 0.5 * wc * b34; A[3][3] = -0.5 * wc * (b34 + b4);
        A[4][3] = wh * m.k; A[4][4] = -wh;
        double M[5][5], rhs[5];
        for (int i = 0; i < 5; i++) {
            rhs[i] = z0[i] + 0.5 * h * B[i] * (uprev + in);
            for (int j = 0; j < 5; j++) {
                rhs[i] += 0.5 * h * A[i][j] * z0[j];
                M[i][j] = (i == j ? 1.0 : 0.0) - 0.5 * h * A[i][j];
            }
        }
        solve5(M, rhs);
        memcpy(z1, rhs, sizeof rhs);
    }
    double tick(double in) override {
        double z1[5];
        step(z, z, 0.5 * (uprev + in), in, z1);
        if (heun && D > 0) {
            double mid[5];
            for (int i = 0; i < 5; i++) mid[i] = 0.5 * (z[i] + z1[i]);
            step(z, mid, 0.5 * (uprev + in), in, z1);
        }
        memcpy(z, z1, sizeof z1);
        uprev = in;
        return 2 * m.g * z[3];
    }
};

// Voicing variant of FZdf (Phase 1c): the diode ladder's nonlinearities placed separately.
//   Din  the input pair: tanh on u = in - feedback (the bottom transistor pair of the ladder)
//   Dst  the stage differences (FZdf's D): adds harmonics AND lowers the effective cutoff at level
//   Dfb  the feedback path only: tanh on the high-passed k*y4 (tames the resonance peak)
//   comp undo the SLOW part of the stages' cutoff loss: omega_c / (mean stage gain, smoothed at
//        ~50 Hz), so the level-dependent darkening goes while the audio-rate nonlinearity stays
struct FZdf2 : Filt {
    Mapping m; double fs = FS, Din = 0, Dst = 0, Dfb = 0; bool comp = false, heun = true;
    double z[5] = {0}, uprev = 0, gsm = 1.0;
    void setSampleRate(double f) override { fs = f; }
    void setCutoff(double fc) override { m.fc = fc; m.update(); }
    void setResonance(double pct) override { m.r = Mapping::skew(pct); m.update(); }
    void reset() override { memset(z, 0, sizeof z); uprev = 0; gsm = 1.0; }
    double meanStage = 1.0;
    void step(const double* z0, const double* est, double uest, double in, double* z1) {
        double h = 1.0 / fs;
        double wres = m.wc / sqrt(2.0), arg = wres * h / 2;
        if (arg > 0.98 * M_PI / 2) arg = 0.98 * M_PI / 2;
        double wc = m.wc * tan(arg) / (wres * h / 2);
        if (comp) wc /= gsm;
        double wh = (2 / h) * tan(M_PI * 150.0 * h);
        double hpE = m.k * est[3] - est[4];
        double c = Dfb > 0 ? Tfac(hpE, Dfb) : 1.0;
        double a = Din > 0 ? Tfac(uest - c * hpE, Din) : 1.0;
        double b12 = 1, b23 = 1, b34 = 1, b4 = 1;
        if (Dst > 0) {
            b12 = Tfac(est[0] - est[1], Dst); b23 = Tfac(est[1] - est[2], Dst);
            b34 = Tfac(est[2] - est[3], Dst); b4 = Tfac(est[3], Dst);
        }
        meanStage = 0.25 * (b12 + b23 + b34 + b4);
        double A[5][5] = {{0}}, B[5] = {0};
        A[0][0] = -wc * b12; A[0][1] = wc * b12; A[0][3] = -wc * a * c * m.k; A[0][4] = wc * a * c;
        B[0] = wc * a;
        A[1][0] = 0.5 * wc * b12; A[1][1] = -0.5 * wc * (b12 + b23); A[1][2] = 0.5 * wc * b23;
        A[2][1] = 0.5 * wc * b23; A[2][2] = -0.5 * wc * (b23 + b34); A[2][3] = 0.5 * wc * b34;
        A[3][2] = 0.5 * wc * b34; A[3][3] = -0.5 * wc * (b34 + b4);
        A[4][3] = wh * m.k; A[4][4] = -wh;
        double M[5][5], rhs[5];
        for (int i = 0; i < 5; i++) {
            rhs[i] = z0[i] + 0.5 * h * B[i] * (uprev + in);
            for (int j = 0; j < 5; j++) {
                rhs[i] += 0.5 * h * A[i][j] * z0[j];
                M[i][j] = (i == j ? 1.0 : 0.0) - 0.5 * h * A[i][j];
            }
        }
        solve5(M, rhs);
        memcpy(z1, rhs, sizeof rhs);
    }
    double tick(double in) override {
        double z1[5];
        bool nl = Din > 0 || Dst > 0 || Dfb > 0;
        step(z, z, 0.5 * (uprev + in), in, z1);
        if (heun && nl) {
            double mid[5];
            for (int i = 0; i < 5; i++) mid[i] = 0.5 * (z[i] + z1[i]);
            step(z, mid, 0.5 * (uprev + in), in, z1);
        }
        if (comp) gsm += (meanStage - gsm) * (1.0 - exp(-2 * M_PI * 50.0 / fs));
        memcpy(z, z1, sizeof z1);
        uprev = in;
        return 2 * m.g * z[3];
    }
};

// Kaiser-windowed sinc decimator: pass 0-20 kHz, stop from 24.1 kHz (folds onto 20 kHz), 100 dB
struct Fir {
    std::vector<double> h, buf; int pos = 0;
    static double i0(double x) {
        double s = 1, t = 1;
        for (int k = 1; k < 50; k++) { t *= (x / (2 * k)) * (x / (2 * k)); s += t; }
        return s;
    }
    void design(double fs) {
        double A = 100, beta = 0.1102 * (A - 8.7), dw = 2 * M_PI * 4100.0 / fs;
        int n = (int)ceil((A - 7.95) / (2.285 * dw)) | 1;
        double fcut = 22050.0 / fs;
        h.assign(n, 0); double sum = 0;
        for (int i = 0; i < n; i++) {
            double t = i - (n - 1) / 2.0;
            double sinc = t == 0 ? 2 * fcut : sin(2 * M_PI * fcut * t) / (M_PI * t);
            double w = i0(beta * sqrt(1 - pow(2 * i / (double)(n - 1) - 1, 2))) / i0(beta);
            h[i] = sinc * w; sum += h[i];
        }
        for (auto& v : h) v /= sum;
        buf.assign(n, 0); pos = 0;
    }
    void reset() { std::fill(buf.begin(), buf.end(), 0.0); pos = 0; }
    void push(double x) { buf[pos] = x; pos = (pos + 1) % buf.size(); }
    double out() const {
        double s = 0; size_t n = h.size();
        for (size_t i = 0; i < n; i++) s += h[i] * buf[(pos + n - 1 - i) % n];
        return s;
    }
};

// ==========================================================================================
// Phase 2: the DSP-shaped voice. Every block below is written the way the DSP56300 will run it:
// closed-form solves, table lookups instead of tanh / division, a half-band decimator, a
// band-limited oscillator. QUANT models 24-bit storage (Q23 with a per-signal full scale),
// so the same code answers "what does the algorithm cost" and "what does 24 bits cost".
struct Quant {
    bool on = false; int stateBits = 24;
    double q(double v, double fs) const {                 // store v in Q23 of full scale fs
        if (!on) return v;
        double l = ldexp(1.0, 23), x = std::nearbyint(v / fs * l);
        if (x > l - 1) x = l - 1; if (x < -l) x = -l;
        return x / l * fs;
    }
    double qs(double v, double fs) const {                // a filter state (24 or 48 bit)
        if (!on) return v;
        if (stateBits >= 48) { double l = ldexp(1.0, 47); return std::nearbyint(v / fs * l) / l * fs; }
        return q(v, fs);
    }
};
static Quant QNT;

struct Tables {                                           // built once, in double, then stored
    bool use = false;                                     // false: exact functions
    static const int NT = 256; double TX = 8.0; double tnl[NT + 2];
    static const int NR = 64; double rc[NR + 2];
    static const int NS = 512; double SX = 8.0; double th[NS + 2];
    void build() {
        for (int i = 0; i <= NT + 1; i++) { double x = TX * i / NT; tnl[i] = QNT.q(x < 1e-9 ? 1.0 : tanh(x) / x, 1.0); }
        for (int i = 0; i <= NR + 1; i++) { double d = 1.0 + (double)i / NR; rc[i] = QNT.q(1.0 / d, 1.0); }
        for (int i = 0; i <= NS + 1; i++) { double x = -SX + 2 * SX * i / NS; th[i] = QNT.q(tanh(x), 1.0); }
    }
    double T(double x) const {                            // tanh(x)/x, even
        x = fabs(x);
        if (!use) return x < 1e-5 ? 1.0 - x * x / 3 : tanh(x) / x;
        double p = x / TX * NT; if (p >= NT) return QNT.q(tanh(x) / x, 1.0);
        int i = (int)p; double f = p - i;
        return QNT.q(tnl[i] + f * (tnl[i + 1] - tnl[i]), 1.0);
    }
    double recip(double d) const {                        // 1/d, d >= 1 (normalise, table, Newton)
        if (!use) return 1.0 / d;
        int e = 0; double m = frexp(d, &e); m *= 2; e -= 1;      // d = m 2^e, m in [1,2)
        double p = (m - 1.0) * NR; int i = (int)p; double f = p - i;
        double r = QNT.q(rc[i] + f * (rc[i + 1] - rc[i]), 1.0);
        r = QNT.q(r * (2.0 - QNT.q(m * r, 2.0)), 1.0);         // one Newton step
        return ldexp(r, -e);
    }
    double tanh_(double x) const {
        if (!use) return tanh(x);
        double p = (x + SX) / (2 * SX) * NS; if (p <= 0) return -1.0; if (p >= NS) return 1.0;
        int i = (int)p; double f = p - i;
        return QNT.q(th[i] + f * (th[i + 1] - th[i]), 1.0);
    }
};
static Tables TAB;

// the diode ladder (Zavalishin 5.18 / 6.9) in TPT form, solved in closed form by back
// substitution: four stage divisions and one for the resonance loop. Nonlinear stage gains by
// the cheap method (tanh(v)/v at an estimate), one Heun pass optional. Stage saturation only
// (the round-2 voicing): input pair and feedback stay linear.
struct FNested : Filt {
    Mapping m; double fs = FS, D = 0.5; bool heun = true;
    double s[4] = {0}, sl = 0, yp[4] = {0}, lp = 0, uprev = 0;
    double g = 0, gh = 0, ih = 1;
    static constexpr double SS = 8.0;                     // full scale of the ladder's signals
    void setSampleRate(double f) override { fs = f; gh = tan(M_PI * 150.0 / fs); ih = 1.0 / (1.0 + gh); }
    void coef() {
        double h = 1.0 / fs, wres = m.wc / sqrt(2.0), arg = wres * h / 2;
        if (arg > 0.98 * M_PI / 2) arg = 0.98 * M_PI / 2;
        g = QNT.q(m.wc * h / 2 * tan(arg) / arg, 2.0);
    }
    void setCutoff(double fc) override { m.fc = fc; m.update(); coef(); }
    void setResonance(double pct) override { m.r = Mapping::skew(pct); m.update(); coef(); }
    void reset() override { memset(s, 0, sizeof s); memset(yp, 0, sizeof yp); sl = lp = uprev = 0; }
    void solve(const double* est, double in, double* y, double& l) {
        double b12 = 1, b23 = 1, b34 = 1, b4 = 1;
        if (D > 0) {
            b12 = TAB.T(D * (est[0] - est[1])); b23 = TAB.T(D * (est[1] - est[2]));
            b34 = TAB.T(D * (est[2] - est[3])); b4 = TAB.T(D * est[3]);
        }
        double h2 = 0.5 * g, k = m.k;
        double d4 = 1 + h2 * (b34 + b4), r4 = TAB.recip(d4);
        double A4 = QNT.q(h2 * b34 * r4, 1.0), B4 = QNT.q(s[3] * r4, SS);
        double d3 = 1 + h2 * (b23 + b34 - b34 * A4), r3 = TAB.recip(d3);
        double A3 = QNT.q(h2 * b23 * r3, 1.0), B3 = QNT.q((s[2] + h2 * b34 * B4) * r3, SS);
        double d2 = 1 + h2 * (b12 + b23 - b23 * A3), r2 = TAB.recip(d2);
        double A2 = QNT.q(h2 * b12 * r2, 1.0), B2 = QNT.q((s[1] + h2 * b23 * B3) * r2, SS);
        double d1 = 1 + g * b12 * (1 - A2), r1 = TAB.recip(d1);
        double P1 = QNT.q(g * r1, 2.0), Q1 = QNT.q((s[0] + g * b12 * B2) * r1, SS);
        double P4 = QNT.q(A4 * A3 * A2 * P1, 2.0);
        double Q4 = QNT.q(A4 * (A3 * (A2 * Q1 + B2) + B3) + B4, SS);
        double dx = 1 + ih * k * P4, rx = TAB.recip(dx);
        double x = QNT.q((in + ih * (sl - k * Q4)) * rx, SS);
        y[0] = QNT.q(P1 * x + Q1, SS);
        y[1] = QNT.q(A2 * y[0] + B2, SS);
        y[2] = QNT.q(A3 * y[1] + B3, SS);
        y[3] = QNT.q(A4 * y[2] + B4, SS);
        l = QNT.q((gh * k * y[3] + sl) * ih, SS);
    }
    double tick(double in) override {
        double y[4], l;
        solve(yp, in, y, l);
        if (heun && D > 0) {
            double mid[4];
            for (int i = 0; i < 4; i++) mid[i] = 0.5 * (yp[i] + y[i]);
            solve(mid, in, y, l);
        }
        for (int i = 0; i < 4; i++) { s[i] = QNT.qs(2 * y[i] - s[i], SS); yp[i] = y[i]; }
        sl = QNT.qs(2 * l - sl, SS); lp = l;
        uprev = in;
        return 2 * m.g * y[3];
    }
};

// Open303's 303 saw and square, computed: a polyBLEP saw (one 2-sample residual per reset) and
// the square as -tanh(70.0 s + 4.37) of the saw half a cycle on, minus its DC (Open303 plays
// DC-free mip-map tables). Blend as Open303: (1-b) saw + b * 0.5 * square.
struct OscBlep {
    double p = 0, sqDC = 0;
    static double blep(double t, double dt) {            // polyBLEP residual for a unit step
        if (t < dt) { t /= dt; return t + t - t * t - 1.0; }
        if (t > 1.0 - dt) { t = (t - 1.0) / dt; return t * t + t + t + 1.0; }
        return 0.0;
    }
    static double sawAt(double q, double dt) {            // standard saw 2q-1 with the drop at q=1
        return 2 * q - 1 - blep(q, dt);
    }
    void init() {                                          // square's DC over one cycle (fine grid)
        double a = 0; const int N = 1 << 16;
        for (int i = 0; i < N; i++) { double q = (i + 0.5) / N; a += -tanh(dB2amp(36.9) * (2 * q - 1) + 4.37); }
        sqDC = a / N;
    }
    void reset() { p = 0; }
    double tick(double inc, double blend) {
        // Open303's saw table: 0..1 over the first half, -1..0 over the second = 2q-1 with q = p+0.5
        double q = p + 0.5; if (q >= 1) q -= 1;
        double saw = sawAt(q, inc);
        double sq = 0;
        if (blend > 0) {                                   // the square table is shifted 180 deg
            double s2 = sawAt(p, inc);
            sq = -TAB.tanh_(dB2amp(36.9) * s2 + 4.37) - sqDC;
        }
        p += inc; if (p >= 1) p -= 1;
        return QNT.q((1 - blend) * saw + blend * 0.5 * sq, 2.0);
    }
};

struct HalfBand {                                          // 79-tap, 40 odd taps + centre 0.5
    double buf[HB_N] = {0}; int pos = 0; double c[40];
    void init() { for (int i = 0; i < 40; i++) c[i] = QNT.q(HB_ODD[i], 1.0); }
    void reset() { memset(buf, 0, sizeof buf); pos = 0; }
    void push(double x) { buf[pos] = x; pos = (pos + 1) % HB_N; }
    double out() const {                                   // newest sample at pos-1
        double acc = 0; int ci = 0;
        for (int i = 0; i < HB_N; i++) {
            int d = i - (HB_N - 1) / 2;                    // tap offset from centre
            double x = buf[(pos - 1 - i + 2 * HB_N) % HB_N];
            if (d == 0) acc += 0.5 * x;
            else if (d % 2 != 0) acc += c[ci++] * x;
        }
        return QNT.q(acc, 2.0);
    }
};

// Open303's TB_303 filter, transcribed for the DSP (rosic_TeeBeeFilter.h @ 313bf0d9, MIT): the
// explicit 4x update, the fitted b0/k/g, the 150 Hz one-pole high-pass in the feedback. With QNT
// off and no ceiling it is bit-exact to rosic::TeeBeeFilter (checked by `validate`). RCAP holds
// resonanceSkewed at the ceiling (k <= KMAX at fx -> 0): the round-5 decision.
static double RCAP = 1.0;
struct FO303Q : Filt {
    double fs = 176400, twoPiOverFs = 0, cutoff = 1000.0, rs = 0, b0 = 0, k = 0, g = 1;
    double y1 = 0, y2 = 0, y3 = 0, y4 = 0, hx1 = 0, hy1 = 0, hb0 = 0, hb1 = 0, ha1 = 0;
    static constexpr double SS = 8.0;
    void setSampleRate(double f) override {
        fs = f; twoPiOverFs = 2.0 * PI / fs;
        double x = exp(-2.0 * PI * 150.0 * (1.0 / fs));
        hb0 = QNT.q(0.5 * (1 + x), 1.0); hb1 = QNT.q(-0.5 * (1 + x), 1.0); ha1 = QNT.q(x, 1.0);
        calc();
    }
    void setCutoff(double c) override {
        if (c != cutoff) { cutoff = c < 200.0 ? 200.0 : (c > 20000.0 ? 20000.0 : c); calc(); }
    }
    void setResonance(double pct) override {
        double rr = 0.01 * pct; rs = (1.0 - exp(-3.0 * rr)) / (1.0 - exp(-3.0));
        if (rs > RCAP) rs = RCAP;
        calc();
    }
    void calc() {
        double wc = twoPiOverFs * cutoff, r = rs;
        double fx = wc * ONE_OVER_SQRT2 / (2 * PI);
        b0 = (0.00045522346 + 6.1922189 * fx) / (1.0 + 12.358354 * fx + 4.4156345 * (fx * fx));
        k = fx*(fx*(fx*(fx*(fx*(fx+7198.6997)-5837.7917)-476.47308)+614.95611)+213.87126)+16.998792;
        g = k * 0.058823529411764705882352941176471;
        g = (g - 1.0) * r + 1.0;
        g = (g * (1.0 + r));
        k = k * r;
        b0 = QNT.q(b0, 1.0); k = QNT.q(k, 64.0); g = QNT.q(g, 4.0);
    }
    void reset() override { y1 = y2 = y3 = y4 = hx1 = hy1 = 0; }
    double tick(double in) override {
        double fbin = QNT.q(k * y4, SS);
        hy1 = QNT.qs(hb0 * fbin + hb1 * hx1 + ha1 * hy1 + (QNT.on ? 0.0 : TINY), SS);
        hx1 = fbin;
        double y0 = in - hy1;
        y1 = QNT.qs(y1 + 2 * b0 * (y0 - y1 + y2), SS);
        y2 = QNT.qs(y2 + b0 * (y1 - 2 * y2 + y3), SS);
        y3 = QNT.qs(y3 + b0 * (y2 - 2 * y3 + y4), SS);
        y4 = QNT.qs(y4 + b0 * (y3 - 2 * y4), SS);
        return 2 * g * y4;
    }
};

struct HalfBand4 {                                         // 23-tap, 12 odd taps + centre 0.5
    double buf[HB4_N] = {0}; int pos = 0; double c[12];
    void init() { for (int i = 0; i < 12; i++) c[i] = QNT.q(HB4_ODD[i], 1.0); }
    void reset() { memset(buf, 0, sizeof buf); pos = 0; }
    void push(double x) { buf[pos] = x; pos = (pos + 1) % HB4_N; }
    double out() const {
        double acc = 0; int ci = 0;
        for (int i = 0; i < HB4_N; i++) {
            int d = i - (HB4_N - 1) / 2;
            double x = buf[(pos - 1 - i + 2 * HB4_N) % HB4_N];
            if (d == 0) acc += 0.5 * x; else if (d % 2 != 0) acc += c[ci++] * x;
        }
        return QNT.q(acc, 2.0);
    }
};

// Open303::getSample with a pluggable filter and oversampling factor
struct Voice {
    Open303 o;
    std::unique_ptr<Filt> flt;
    int N = 4, oscOffset = 2;
    bool ell = true;
    EllipticQuarterBandFilter el;
    Fir fir;
    bool blepOsc = false, hb = false; OscBlep ob; HalfBand hbd;
    double topHz = 0, topS = 0;
    bool hb2 = false; HalfBand4 hb4;               // 4x: 23-tap stage to 2x, then the 79-tap stage
    void init(std::unique_ptr<Filt> f, int n, bool useEll) {
        flt = std::move(f); N = n; ell = useEll;
        // table k carries harmonics up to fs/8..fs/4 at offset k: keep >= 22 kHz without aliasing,
        // and the same ~22-44 kHz band at N = 2, 4, 8 (N = 3: 33-66 kHz)
        oscOffset = (N >= 8) ? 3 : (N >= 4) ? 2 : 1;
        o.setSampleRate(FS);
        o.oscillator.setSampleRate(N * FS);
        o.highpass1.setSampleRate(N * FS);
        flt->setSampleRate(N * FS);
        flt->setResonance(o.filter.getResonance());
        if (!ell && !hb && !hb2) fir.design(N * FS);
        ob.init(); hbd.init(); hb4.init();
    }
    void setResonance(double pct) { o.setResonance(pct); flt->setResonance(pct); }
    void noteOn(int note, int vel) {
        bool wasIdle = o.idle;
        o.noteOn(note, vel, 0.0);
        if (wasIdle && vel > 0) { flt->reset(); el.reset(); fir.reset(); ob.reset(); hbd.reset(); hb4.reset(); }
    }
    double osc() {
        BlendOscillator& b = o.oscillator;
        if (b.waveTable1 == NULL || b.waveTable2 == NULL) return 0.0;
        int tableNumber = ((int)EXPOFDBL(b.increment)) + oscOffset;
        while (b.phaseIndex >= b.tableLengthDbl) b.phaseIndex -= b.tableLengthDbl;
        int intIndex = floorInt(b.phaseIndex);
        double frac = b.phaseIndex - (double)intIndex;
        double out1 = (1.0 - b.blend) * b.waveTable1->getValueLinear(intIndex, frac, tableNumber);
        double out2 = b.blend * b.waveTable2->getValueLinear(intIndex, frac, tableNumber);
        out2 *= 0.5;
        b.phaseIndex += b.increment;
        return out1 + out2;
    }
    // the stock 303's accent sweep (Whittle, Devil Fish notes): MEG -> diode + 47k -> 1 uF, bled
    // by the 100k ACCENT pot + 100k mixing resistor: fast charge, slow discharge, so consecutive
    // accents stack ("wow"). accTauD is the discharge (pot-dependent 100-200 ms; 150 here).
    bool accRC = false; double accS = 0, accN = 1, accTauC = 0.047, accTauD = 0.150;
    void calibrateAccent() {      // one isolated accent peaks where Open303's rc2 path peaks
        double T = 1.0 / FS, tauE = 0.200, y = 0, s = 0, py = 0, ps = 0;
        double ar = 1 - exp(-T / 0.015), ac = 1 - exp(-T / accTauC), ad = 1 - exp(-T / accTauD);
        for (int n = 0; n < (int)FS; n++) {
            double e = exp(-n * T / tauE);
            y += (e - y) * ar; py = fmax(py, y);
            if (e > s) s += (e - s) * ac;
            s -= s * ad; ps = fmax(ps, s);
        }
        accN = py / ps;           // Open303's n2 then scales both the same way
    }
    double accentPath(double mainEnvOut) {
        double e = o.accentGain > 0.0 ? mainEnvOut : 0.0;
        if (!accRC) return o.n2 * o.rc2.getSample(e);
        double T = 1.0 / FS;
        if (e > accS) accS += (e - accS) * (1 - exp(-T / accTauC));
        accS -= accS * (1 - exp(-T / accTauD));
        o.rc2.getSample(e);       // keep Open303's state moving identically (unused)
        return o.n2 * accN * accS;
    }
    double getSample() {
        if (o.idle) return 0.0;
        double instFreq = o.pitchSlewLimiter.getSample(o.oscFreq);
        o.oscillator.setFrequency(instFreq * o.pitchWheelFactor);
        o.oscillator.calculateIncrement();
        double mainEnvOut = o.mainEnv.getSample();
        double tmp1 = o.n1 * o.rc1.getSample(mainEnvOut);
        double tmp2 = accentPath(mainEnvOut);
        tmp1 = o.envScaler * (tmp1 - o.envOffset);
        tmp2 = o.accentGain * tmp2;
        double instCutoff = o.cutoff * pow(2.0, tmp1 + tmp2);
        flt->setCutoff(instCutoff);
        double ampEnvOut = o.ampEnv.getSample();
        if (o.ampEnv.isNoteOn()) ampEnvOut += 0.45 * mainEnvOut + o.accentGain * 4.0 * mainEnvOut;
        ampEnvOut = o.ampDeClicker.getSample(ampEnvOut);
        double tmp = 0;
        double inc = o.oscillator.increment / o.oscillator.tableLengthDbl;   // cycles per OS sample
        for (int i = 1; i <= N; i++) {
            tmp = blepOsc ? -ob.tick(inc, o.oscillator.blend) : -osc();
            tmp = QNT.q(o.highpass1.getSample(tmp), 2.0);
            tmp = flt->tick(tmp);
            if (hb2) { hb4.push(tmp); if (i % 2 == 0) hbd.push(hb4.out()); }
            else if (hb) hbd.push(tmp); else if (ell) tmp = el.getSample(tmp); else fir.push(tmp);
        }
        if (hb || hb2) tmp = hbd.out(); else if (!ell) tmp = fir.out();
        tmp = o.allpass.getSample(tmp);
        tmp = o.highpass2.getSample(tmp);
        tmp = o.notch.getSample(tmp);
        tmp *= ampEnvOut;
        tmp *= o.ampScaler;
        if (topHz > 0) {                       // gentle rounding of the very top (one pole, bilinear)
            double K = tan(M_PI * topHz / FS), a = K / (1 + K);
            double v = (tmp - topS) * a, y = v + topS; topS = y + v; tmp = y;
        }
        return QNT.q(tmp, 4.0);
    }
};

// ------------------------------------------------------------------------------------------
// Phase 2b: the integer twin (twin.h) driven like the voice above. Open303 keeps the note logic
// (note list, slide/accent decisions, its parameter values); host() turns its state into the
// twin's HOST words, as the ColdFire will.
#include "twin.h"
#include "halfband2x.h"
struct TwinVoice {
    Open303 o;
    twin::Engine e;
    double rs = 0, sqDC = 0;
    int frame = 1, n = 0;           // knob words refreshed every `frame` samples (events: at once)
    double pendCut = -1;
    void init(const double* hb2odd, int hb2n, double topHz, const double* hb1odd = nullptr, int hb1n = 0) {
        o.setSampleRate(FS);
        e.init(hb2odd, hb2n, topHz, hb1odd, hb1n);
        double a = 0; const int NN = 1 << 16;     // the square's DC, as OscBlep
        for (int i = 0; i < NN; i++) { double q = (i + 0.5) / NN; a += -tanh(dB2amp(36.9) * (2 * q - 1) + 4.37); }
        sqDC = a / NN;
    }
    void setResonance(double pct) {
        o.setResonance(pct);
        double rr = 0.01 * pct; rs = (1.0 - exp(-3.0 * rr)) / (1.0 - exp(-3.0));
        host();
    }
    void setCutoff(double c) {
        if (frame <= 1) { o.setCutoff(c); host(); }
        else pendCut = c;
    }
    void host() {
        using twin::q23;
        e.INC_T = q23(2.0 * o.oscFreq * o.pitchWheelFactor / (4 * FS));
        e.INC_T48 = (twin::A)std::nearbyint(2.0 * o.oscFreq * o.pitchWheelFactor / (4 * FS) * 140737488355328.0);
        e.CS = q23(1.0 - o.pitchSlewLimiter.coeff);
        e.C_MEG = q23(o.mainEnv.c);
        e.C2 = q23(o.rc2.coeff);
        e.M_AMP = q23(1.0 - (o.ampEnv.noteIsOn ? o.ampEnv.decayCoeff : o.ampEnv.releaseCoeff));
        e.L0_16 = q23((log2(o.cutoff / 200.0) - o.envScaler * o.envOffset) / 16.0);
        e.ES8 = q23(o.envScaler / 8.0);
        e.AG8 = q23(o.accentGain * o.n2 / 8.0);
        e.AGF = o.accentGain > 0.0;
        e.RS = q23(rs);
        e.AG_8 = q23((1.0 - rs * rs) / 8.0);
        e.BG = q23(rs * (1.0 + rs) * 8.0 / 17.0);
        e.K8 = q23(o.ampEnv.noteIsOn ? (0.45 + 4.0 * o.accentGain) / 8.0 : 0.0);
        e.SC = q23(o.ampScaler);
        double b = o.oscillator.blend;
        e.W1 = q23(-(1.0 - b) / 2.0); e.W2 = q23(b / 4.0); e.W3 = q23(b * sqDC / 4.0);
        e.SQ = b > 0.0;
    }
    void noteOn(int note, int vel) {
        bool trig = vel > 0 && o.noteList.empty(), wasIdle = o.idle;
        o.noteOn(note, vel, 0.0);
        host();
        if (trig) {
            if (wasIdle) { e.resetAudio(); ob.reset(); }
            e.S48 = e.inc48 ? e.INC_T48 : twin::acc(e.INC_T);
            e.MEG2 = twin::q23(0.5 / o.mainEnv.c);                 // first output = 1
            e.M48 = (twin::A)std::nearbyint(0.5 / o.mainEnv.c * 140737488355328.0);
            e.AMP2 = twin::q23(0.5 / f23m(e.M_AMP));
        }
    }
    static double f23m(twin::W w) { return twin::f23(w); }
    // diagnostic refosc: the reference's oscillator (OscBlep, Open303's slew in double)
    OscBlep ob; double rinc = 0;
    static double oscCb(void* p) { auto* t = (TwinVoice*)p; return t->ob.tick(t->rinc, t->o.oscillator.blend); }
    void useRefOsc() { QNT.on = true; TAB.use = true; TAB.build(); ob.init(); e.oscHook = oscCb; e.oscCtx = this; }
    double getSample() {
        if (o.idle) return 0.0;
        if (e.oscHook) rinc = o.pitchSlewLimiter.getSample(o.oscFreq) * o.pitchWheelFactor / (4 * FS);
        if (frame > 1 && n % frame == 0 && pendCut >= 0) { o.setCutoff(pendCut); pendCut = -1; host(); }
        n++;
        return e.tick();
    }
};

// ------------------------------------------------------------------------------------------
// scenes: one 16-step acid line, 8 bars at 130 BPM, 303-style gates (half step, slides held)
struct Step { int note; bool acc, slide; };
static const Step LINE[16] = {
    {36, true, false}, {-1, false, false}, {48, false, true}, {36, false, false},
    {39, true, false}, {36, false, true}, {43, false, false}, {36, false, false},
    {36, true, false}, {46, false, true}, {36, false, false}, {34, false, false},
    {36, true, true}, {48, false, false}, {36, false, false}, {41, true, false}};

static const Step ACCLINE[16] = {   // runs of consecutive accents: where the 303's accent stacks
    {36, true, false}, {36, true, false}, {48, true, true}, {36, true, false},
    {-1, false, false}, {39, false, false}, {36, true, false}, {36, true, false},
    {43, true, false}, {36, false, false}, {46, true, true}, {36, true, false},
    {34, true, false}, {36, false, false}, {48, true, false}, {36, true, false}};
struct Scene { double cut0, cut1, res, env, dec, acc, wave; const Step* line = LINE; };
static bool scene(const std::string& s, Scene& sc) {
    // cut0/cut1: Open303's cutoff knob 0..1 (314..2394 Hz, exponential), swept linearly over the take
    if (s == "sweep")   { sc = {0.0, 1.0, 85, 60, 400, 70, 0}; return true; }
    if (s == "hot")     { sc = {0.7, 0.7, 100, 100, 1500, 100, 0}; return true; }
    if (s == "squelch") { sc = {0.10, 0.30, 95, 80, 200, 80, 0}; return true; }
    if (s == "square")  { sc = {0.0, 1.0, 85, 60, 400, 70, 1}; return true; }
    if (s == "accents") { sc = {0.30, 0.30, 85, 70, 400, 85, 0, ACCLINE}; return true; }
    return false;
}

template <class V>
static std::vector<float> run(V& v, const Scene& sc, std::function<void(double)> setCut) {
    const int bars = 8, steps = bars * 16;
    const double stepLen = 60.0 / 130.0 / 4.0 * FS;
    const int total = (int)(steps * stepLen + FS);
    std::vector<float> out(total);
    int held = -1, k = 0;
    for (int n = 0; n < total; n++) {
        double t = (double)n / total;
        double knob = sc.cut0 + (sc.cut1 - sc.cut0) * t;
        setCut(314.0 * pow(2394.0 / 314.0, knob));
        // events at step boundaries and half steps
        double pos = n / stepLen;
        int si = (int)pos;
        if (si < steps && n == (int)ceil(si * stepLen)) {
            const Step& st = sc.line[si % 16];
            if (st.note >= 0) {
                v.noteOn(st.note, st.acc ? 127 : 80);            // held note -> Open303 slides
                if (held >= 0 && held != st.note) v.noteOn(held, 0);
                held = st.note;
            }
        }
        if (si < steps && n == (int)ceil((si + 0.5) * stepLen)) {
            const Step& st = sc.line[si % 16];
            const Step& nx = sc.line[(si + 1) % 16];
            bool hold = st.note >= 0 && st.slide && nx.note >= 0 && si + 1 < steps;
            if (held >= 0 && !hold) { v.noteOn(held, 0); held = -1; }
        }
        out[n] = (float)v.getSample();
        k++;
    }
    return out;
}

template <class O>
static void params(O& o, const Scene& sc) {
    o.setWaveform(sc.wave);
    o.setEnvMod(sc.env);
    o.setDecay(sc.dec);
    o.setAccent(sc.acc);
    o.setVolume(-6.0);
}

struct Plain {      // rosic::Open303 as shipped
    Open303 o;
    void noteOn(int n, int v) { o.noteOn(n, v, 0.0); }
    double getSample() { return o.getSample(); }
};

int main(int argc, char** argv) {
    if (argc >= 2 && !strcmp(argv[1], "validate")) {
        int fails = 0;
        const char* names[] = {"sweep", "hot", "squelch", "square"};
        for (auto nm : names) {
            Scene sc; scene(nm, sc);
            Plain p; p.o.setSampleRate(FS); params(p.o, sc); p.o.setResonance(sc.res);
            auto a = run(p, sc, [&](double c) { p.o.setCutoff(c); });
            Voice v; params(v.o, sc);
            v.init(std::make_unique<FO303>(), 4, true);
            v.setResonance(sc.res);
            auto b = run(v, sc, [&](double c) { v.o.setCutoff(c); });
            double md = 0, pk = 0;
            for (size_t i = 0; i < a.size(); i++) { md = fmax(md, fabs(a[i] - b[i])); pk = fmax(pk, fabs(a[i])); }
            printf("%-8s samples %zu  peak %.4f  max|diff| %.3g  %s\n", nm, a.size(), pk, md,
                   md == 0 ? "BIT-EXACT" : "DIFFERS");
            fails += md != 0;
        }
        for (auto nm : names) {          // FO303Q (QNT off, no ceiling) == TeeBeeFilter through the voice
            Scene sc; scene(nm, sc);
            Voice a; params(a.o, sc); a.init(std::make_unique<FO303>(), 4, true); a.setResonance(sc.res);
            auto xa = run(a, sc, [&](double c) { a.o.setCutoff(c); });
            Voice b; params(b.o, sc); b.init(std::make_unique<FO303Q>(), 4, true); b.setResonance(sc.res);
            auto xb = run(b, sc, [&](double c) { b.o.setCutoff(c); });
            double md = 0; for (size_t i = 0; i < xa.size(); i++) md = fmax(md, fabs(xa[i] - xb[i]));
            printf("%-8s FO303Q vs TeeBeeFilter  max|diff| %.3g  %s\n", nm, md, md == 0 ? "BIT-EXACT" : "DIFFERS");
            fails += md != 0;
        }
        return fails;
    }
    if (argc == 2 && !strcmp(argv[1], "twinunit")) {    // each twin block vs its Open303 counterpart
        TwinVoice tv; tv.init(HB_ODD, 40, 16000);
        twin::Engine& e = tv.e;
        Open303 o; o.setSampleRate(FS);
        const int N = 4 * 44100; std::vector<double> x(N);
        unsigned s = 1; for (auto& v : x) { s = s * 1664525u + 1013904223u; v = ((s >> 8) / 16777216.0 - 0.5) * 0.4; }
        auto rep = [](const char* nm, const std::vector<double>& a, const std::vector<double>& b) {
            double e2 = 0, r2 = 0; for (size_t i = 0; i < a.size(); i++) { e2 += (a[i] - b[i]) * (a[i] - b[i]); r2 += b[i] * b[i]; }
            printf("%-28s null %7.1f dB\n", nm, 10 * log10(e2 / r2 + 1e-30));
        };
        // post chain (fs 8 words)
        std::vector<double> a(N), b(N);
        for (int i = 0; i < N; i++) {
            double t = o.notch.getSample(o.highpass2.getSample(o.allpass.getSample(x[i])));
            b[i] = t; a[i] = twin::f23(e.post(twin::q23(x[i] / 8.0))) * 8.0;
        }
        rep("post: allpass+hp2+notch", a, b);
        // each post stage alone
        Open303 o2; o2.setSampleRate(FS); twin::Engine e2; e2.init(HB_ODD, 40, 16000);
        for (int i = 0; i < N; i++) { b[i] = o2.allpass.getSample(x[i]);
            twin::W w = twin::q23(x[i] / 8.0); e2.apy = twin::str(twin::mpy(e2.AP_B, w) + twin::acc(e2.apx) + twin::mpy(e2.AP_A, e2.apy)); e2.apx = w; a[i] = twin::f23(e2.apy) * 8; }
        rep("  allpass", a, b);
        for (int i = 0; i < N; i++) { b[i] = o2.highpass2.getSample(x[i]);
            twin::W w = twin::q23(x[i] / 8.0); e2.h2y = twin::str(twin::mpy(e2.HP2_B, w) - twin::mpy(e2.HP2_B, e2.h2x) + twin::mpy(e2.HP2_A, e2.h2y)); e2.h2x = w; a[i] = twin::f23(e2.h2y) * 8; }
        rep("  hp2", a, b);
        for (int i = 0; i < N; i++) { b[i] = o2.notch.getSample(x[i]);
            twin::W w = twin::q23(x[i] / 8.0), v1, v2; e2.notch.tick(w, v1, v2, nullptr, nullptr);
            a[i] = twin::f23(twin::st(twin::acc(w) - twin::sh(twin::mpy(e2.notch.kk, v1), e2.notch.sk))) * 8; }
        rep("  notch", a, b);
        // declicker (amp / 16), a step train like the amp envelope
        for (int i = 0; i < N; i++) { double u = ((i / 3000) % 2) ? 0.0 : 5.0 * fabs(x[i]) + 0.2;
            b[i] = o2.ampDeClicker.getSample(u); twin::W v1, v2; e2.decl.tick(twin::q23(u / 16.0), v1, v2, nullptr, nullptr); a[i] = twin::f23(v2) * 16; }
        rep("declicker", a, b);
        // decimators: 4x noise in, 1x out
        HalfBand4 rh4; HalfBand rh2; rh4.init(); rh2.init(); twin::HB th4, th2; th4.init(HB4_ODD, 12); th2.init(HB_ODD, 40);
        std::vector<double> da(N / 4), db(N / 4);
        for (int i = 0; i < N; i++) {
            rh4.push(x[i]); th4.push(twin::q23(x[i] / 8.0));
            if (i % 2 == 1) { rh2.push(rh4.out()); th2.push(th4.out(nullptr)); }
            if (i % 4 == 3) { db[i / 4] = rh2.out(); da[i / 4] = twin::f23(th2.out(nullptr)) * 8; }
        }
        rep("decimators 23+79", da, db);
        return 0;
    }
    if (argc == 5 && !strcmp(argv[1], "twin")) {        // voice_study twin SCENE OPTS OUT.f32
        Scene sc;
        if (!scene(argv[2], sc)) { fprintf(stderr, "unknown scene %s\n", argv[2]); return 2; }
        int hb2 = 79, hbfp = 0, hb1 = 23, hb1fp = 0, frame = 1, fbs = 4; bool hbdelay = false; double top = 16000; bool inc48 = false, refosc = false, exactcoef = false, meg48 = false;
        for (std::string opt = argv[3]; !opt.empty();) {
            auto cm = opt.find(','); std::string kv = opt.substr(0, cm); auto co = kv.find(':');
            if (co != std::string::npos) {
                std::string k = kv.substr(0, co); double v = atof(kv.c_str() + co + 1);
                if (k == "hb2") hb2 = (int)v; else if (k == "frame") frame = (int)v;
                else if (k == "fbs") fbs = (int)v; else if (k == "top") top = v;
                else if (k == "inc48") inc48 = v != 0;
                else if (k == "refosc") refosc = v != 0;
                else if (k == "exactcoef") exactcoef = v != 0;
                else if (k == "meg48") meg48 = v != 0;
                else if (k == "hbfp") hbfp = (int)v;
                else if (k == "hbdelay") hbdelay = v != 0;
                else if (k == "hb1") hb1 = (int)v; else if (k == "hb1fp") hb1fp = (int)v;
                else { fprintf(stderr, "unknown option %s\n", k.c_str()); return 2; }
            }
            opt = cm == std::string::npos ? "" : opt.substr(cm + 1);
        }
        const double* odd = nullptr; int nodd = 0;
        if (hb2 == 79) { odd = HB_ODD; nodd = 40; }        // the approved stage (halfband79.h)
        else for (auto& d : HB2_DESIGNS)                       // lean candidates: hb2:N,hbfp:kHz
            if (d.n == hb2 && (int)lround(d.fp / 1000) == hbfp) { odd = d.odd; nodd = d.nodd; }
        if (!odd) { fprintf(stderr, "hb2:%d hbfp:%d not built in\n", hb2, hbfp); return 2; }
        const double* odd1 = nullptr; int nodd1 = 0;
        if (hb1 != 23) {
            for (auto& d : HB1_DESIGNS) if (d.n == hb1 && (int)lround(d.fp / 1000) == hb1fp) { odd1 = d.odd; nodd1 = d.nodd; }
            if (!odd1) { fprintf(stderr, "hb1:%d hb1fp:%d not built in\n", hb1, hb1fp); return 2; }
        }
        TwinVoice v; params(v.o, sc);
        v.frame = frame; v.e.FBS = fbs; v.e.inc48 = inc48;
        v.init(odd, nodd, top, odd1, nodd1);
        if (refosc) v.useRefOsc();
        v.e.exactCoef = exactcoef; v.e.meg48 = meg48;
        if (hbdelay) v.e.dlyN = (79 - hb2) / 4 + (23 - hb1) / 8;
        v.setResonance(sc.res);
        auto out = run(v, sc, [&](double c) { v.setCutoff(c); });
        FILE* fh = fopen(argv[4], "wb");
        if (!fh) { perror(argv[4]); return 1; }
        fwrite(out.data(), sizeof(float), out.size(), fh); fclose(fh);
        double pk = 0; for (float x : out) pk = fmax(pk, fabs(x));
        printf("twin %s %s -> %s (peak %.4f, saturations %ld, shaper clamps %ld)\n", argv[2], argv[3], argv[4], pk, twin::g_sat, v.e.sqClamp);
        for (auto& kv : twin::g_peak) printf("  %-6s %.3f\n", kv.first.c_str(), kv.second);
        return 0;
    }
    if (argc != 9 || strcmp(argv[1], "render")) {
        fprintf(stderr, "usage: voice_study validate | render SCENE FILTER N DEC DRIVE HEUN OUT.f32\n");
        return 2;
    }
    Scene sc;
    if (!scene(argv[2], sc)) { fprintf(stderr, "unknown scene %s\n", argv[2]); return 2; }
    std::string fname = argv[3];
    int N = atoi(argv[4]);
    bool useEll = !strcmp(argv[5], "ell"), useHB = !strcmp(argv[5], "hb"), useHB2 = !strcmp(argv[5], "hb2");
    double D = atof(argv[6]);
    double otune = 440.0; double oin = 0, ost = 0, ofb = 0, ores = -1, okmax = 0, ofmax = 20000, otop = 0, oacctc = 47; int oktab = 0, okcap = 0; bool ocomp = false, oacc = false, oblep = false;
    for (std::string opt = argv[6]; !opt.empty();) {          // "k:v,k:v" (or a bare number = D)
        auto cm = opt.find(','); std::string kv = opt.substr(0, cm);
        auto co = kv.find(':');
        if (co != std::string::npos) {
            std::string k = kv.substr(0, co); double v = atof(kv.c_str() + co + 1);
            if (k == "in") oin = v; else if (k == "st") ost = v; else if (k == "fb") ofb = v;
            else if (k == "comp") ocomp = v != 0; else if (k == "acc") oacc = v != 0;
            else if (k == "blep") oblep = v != 0; else if (k == "tab") TAB.use = v != 0;
            else if (k == "q") QNT.on = v != 0; else if (k == "stbits") QNT.stateBits = (int)v;
            else if (k == "res") ores = v; else if (k == "kmax") okmax = v;
            else if (k == "fmax") ofmax = v; else if (k == "top") otop = v;
            else if (k == "ktab") oktab = (int)lround(v * 10);
            else if (k == "acctc") oacctc = v; else if (k == "kcap") okcap = (int)v;
            else if (k == "tune") otune = v;
            else { fprintf(stderr, "unknown option %s\n", k.c_str()); return 2; }
        }
        opt = cm == std::string::npos ? "" : opt.substr(cm + 1);
    }
    bool heun = atoi(argv[7]) != 0;
    if (useEll && N != 4) { fprintf(stderr, "ell decimator is quarter-band: N must be 4\n"); return 2; }
    TAB.build();                     // every filter path uses the tables when tab:1 (built after q:)
    std::unique_ptr<Filt> f;
    if (fname == "o303") f = std::make_unique<FO303>();
    else if (fname == "zdf") f = std::make_unique<FZdf>(0.0, false);
    else if (fname == "zdfnl") f = std::make_unique<FZdf>(D, heun);
    else if (fname == "zdf2") {
        auto z2 = std::make_unique<FZdf2>();
        z2->Din = oin; z2->Dst = ost; z2->Dfb = ofb; z2->comp = ocomp; z2->heun = heun;
        f = std::move(z2);
    }
    else if (fname == "nest") {
        auto fn = std::make_unique<FNested>(); fn->D = ost; fn->heun = heun;
        f = std::move(fn);
    }
    else if (fname == "ref2") {                       // the reference with zdf2's separate placements
        auto r = std::make_unique<FRef>(oin); r->Dst = ost; r->Dfb = ofb; f = std::move(r);
    }
    else if (fname == "o303q") f = std::make_unique<FO303Q>();
    else if (fname == "ref") f = std::make_unique<FRef>(0.0);
    else if (fname == "refnl") f = std::make_unique<FRef>(D);
    else { fprintf(stderr, "unknown filter %s\n", fname.c_str()); return 2; }
    Voice v; params(v.o, sc); v.o.pitchWheelFactor = otune / 440.0;   // tune: a clean global pitch factor
    v.accRC = oacc; v.accTauC = oacctc * 0.001; v.calibrateAccent();
    v.blepOsc = oblep; v.hb = useHB; v.hb2 = useHB2;
    if (useHB2 && N != 4) { fprintf(stderr, "hb2 decimator is two half-bands: N must be 4\n"); return 2; }
    if (useHB && N != 2) { fprintf(stderr, "hb decimator is half-band: N must be 2\n"); return 2; }
    v.init(std::move(f), N, useEll);
    if (ores >= 0) sc.res = ores;
    RCAP = (fname == "o303q" && okmax > 0) ? okmax / 16.998792 : 1.0;
    KMAX = okmax; FMAX = ofmax; v.topHz = otop; KTSEL = oktab; KCAPMODE = okcap;
    v.setResonance(sc.res);
    auto out = run(v, sc, [&](double c) { v.o.setCutoff(c); });
    FILE* fh = fopen(argv[8], "wb");
    if (!fh) { perror(argv[8]); return 1; }
    fwrite(out.data(), sizeof(float), out.size(), fh);
    fclose(fh);
    double pk = 0;
    for (float x : out) pk = fmax(pk, fabs(x));
    printf("%s %s N=%d %s D=%g heun=%d -> %s (%zu samples, peak %.4f)\n", argv[2], argv[3], N,
           argv[5], D, heun, argv[8], out.size(), pk);
    return 0;
}

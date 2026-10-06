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

using namespace rosic;
static const double FS = 44100.0;

// ------------------------------------------------------------------------------------------
// the analog-limit parameter mapping of Open303's TB_303 mode (filter_linear.py documents it)
struct Mapping {
    double fc = 1000.0, r = 0.0, wc = 0, k = 0, g = 1;
    static double skew(double pct) {
        double rr = 0.01 * pct;
        return (1.0 - exp(-3.0 * rr)) / (1.0 - exp(-3.0));
    }
    void update() {
        double f = fc < 200.0 ? 200.0 : (fc > 20000.0 ? 20000.0 : fc);
        double w = 0.00045522346 * 176400.0 + 6.1922189 * f / sqrt(2.0);
        wc = 2.0 * w;
        k = 16.998792 * r;
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
                         double D, double* dz) {
    auto N = [&](double v) { return D > 0 ? tanh(D * v) / D : v; };
    double x = u - (m.k * z[3] - z[4]);
    double n0 = N(x), n12 = N(z[0] - z[1]), n23 = N(z[1] - z[2]), n34 = N(z[2] - z[3]),
           n4 = N(z[3]);
    dz[0] = wc * (n0 - n12);
    dz[1] = 0.5 * wc * (n12 - n23);
    dz[2] = 0.5 * wc * (n23 - n34);
    dz[3] = 0.5 * wc * (n34 - n4);
    dz[4] = wh * (m.k * z[3] - z[4]);
}

// ground truth: RK4 with S substeps per tick, input linearly interpolated
struct FRef : Filt {
    Mapping m; double fs = FS, D = 0; int S = 16; double z[5] = {0}, uprev = 0;
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
            deriv(z, u0, m, m.wc, wh, D, k1);
            for (int i = 0; i < 5; i++) t[i] = z[i] + 0.5 * h * k1[i];
            deriv(t, um, m, m.wc, wh, D, k2);
            for (int i = 0; i < 5; i++) t[i] = z[i] + 0.5 * h * k2[i];
            deriv(t, um, m, m.wc, wh, D, k3);
            for (int i = 0; i < 5; i++) t[i] = z[i] + h * k3[i];
            deriv(t, u1, m, m.wc, wh, D, k4);
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

// Open303::getSample with a pluggable filter and oversampling factor
struct Voice {
    Open303 o;
    std::unique_ptr<Filt> flt;
    int N = 4, oscOffset = 2;
    bool ell = true;
    EllipticQuarterBandFilter el;
    Fir fir;
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
        if (!ell) fir.design(N * FS);
    }
    void setResonance(double pct) { o.setResonance(pct); flt->setResonance(pct); }
    void noteOn(int note, int vel) {
        bool wasIdle = o.idle;
        o.noteOn(note, vel, 0.0);
        if (wasIdle && vel > 0) { flt->reset(); el.reset(); fir.reset(); }
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
        for (int i = 1; i <= N; i++) {
            tmp = -osc();
            tmp = o.highpass1.getSample(tmp);
            tmp = flt->tick(tmp);
            if (ell) tmp = el.getSample(tmp); else fir.push(tmp);
        }
        if (!ell) tmp = fir.out();
        tmp = o.allpass.getSample(tmp);
        tmp = o.highpass2.getSample(tmp);
        tmp = o.notch.getSample(tmp);
        tmp *= ampEnvOut;
        tmp *= o.ampScaler;
        return tmp;
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
        return fails;
    }
    if (argc != 9 || strcmp(argv[1], "render")) {
        fprintf(stderr, "usage: voice_study validate | render SCENE FILTER N DEC DRIVE HEUN OUT.f32\n");
        return 2;
    }
    Scene sc;
    if (!scene(argv[2], sc)) { fprintf(stderr, "unknown scene %s\n", argv[2]); return 2; }
    std::string fname = argv[3];
    int N = atoi(argv[4]);
    bool useEll = !strcmp(argv[5], "ell");
    double D = atof(argv[6]);
    double oin = 0, ost = 0, ofb = 0; bool ocomp = false, oacc = false;
    for (std::string opt = argv[6]; !opt.empty();) {          // "k:v,k:v" (or a bare number = D)
        auto cm = opt.find(','); std::string kv = opt.substr(0, cm);
        auto co = kv.find(':');
        if (co != std::string::npos) {
            std::string k = kv.substr(0, co); double v = atof(kv.c_str() + co + 1);
            if (k == "in") oin = v; else if (k == "st") ost = v; else if (k == "fb") ofb = v;
            else if (k == "comp") ocomp = v != 0; else if (k == "acc") oacc = v != 0;
            else { fprintf(stderr, "unknown option %s\n", k.c_str()); return 2; }
        }
        opt = cm == std::string::npos ? "" : opt.substr(cm + 1);
    }
    bool heun = atoi(argv[7]) != 0;
    if (useEll && N != 4) { fprintf(stderr, "ell decimator is quarter-band: N must be 4\n"); return 2; }
    std::unique_ptr<Filt> f;
    if (fname == "o303") f = std::make_unique<FO303>();
    else if (fname == "zdf") f = std::make_unique<FZdf>(0.0, false);
    else if (fname == "zdfnl") f = std::make_unique<FZdf>(D, heun);
    else if (fname == "zdf2") {
        auto z2 = std::make_unique<FZdf2>();
        z2->Din = oin; z2->Dst = ost; z2->Dfb = ofb; z2->comp = ocomp; z2->heun = heun;
        f = std::move(z2);
    }
    else if (fname == "ref") f = std::make_unique<FRef>(0.0);
    else if (fname == "refnl") f = std::make_unique<FRef>(D);
    else { fprintf(stderr, "unknown filter %s\n", fname.c_str()); return 2; }
    Voice v; params(v.o, sc);
    v.accRC = oacc; v.calibrateAccent();
    v.init(std::move(f), N, useEll);
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

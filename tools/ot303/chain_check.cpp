// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 item 2, the whole chain against Open303 (pinned 313bf0d9, MIT): one acid line (notes, ties,
// rests, slides into held and into closed gates, accents by an ACC lock, the square) three ways:
//   open303  Open303 itself (double precision), the line as MIDI: a note's off GL samples after its
//            on; a slide's on before the previous note's off (Open303's slideToNote)
//   twinv    the approved voice: the integer twin with Open303's note logic, its words made from
//            Open303's state at each event (voice_study.cpp TwinVoice, without its idle reset)
//   ours     the machine: the twin driven as the DSP host drives the engine (tools/ot303/host.asm:
//            a note's words at its sample, a slide into an open gate without a retrigger, the gate's
//            end), the words from tools/ot303/cf/params.c, the gates as control.c ot_step makes them
// ours against twinv says whether the ColdFire's words and the DSP's event rules reproduce Open303's
// note logic (they differ only by params.c's <= 3 LSB words); ours against open303 is the voice's
// own distance from Open303 (the lean engine, accepted by ear in round 7).
//   chain_check OUTDIR   writes open303.f32, twinv.f32, ours.f32 (mono, 44.1 kHz); compared by
//   tools/ot303/chain_check.py
#define protected public
#define private public
#include "rosic_Open303.h"
#undef private
#undef protected
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include "halfband4x.h"
#include "halfband2x.h"
#include "twin.h"
#include "params.h"
using namespace rosic;

static const double FS = 44100.0;
static double cutoffHz(int k) { return 200.0 * std::pow(50.0, k / 127.0); }
static double decayMs(int k) { return 30.0 * std::pow(100.0, k / 127.0); }
static double slideMs(int k) { return 1.5625 * k; }
static double tuningHz(int k) { return 440.0 + (k - 64) * 80.0 / 127.0; }
static double sqDCv() {
    double a = 0; const int NN = 1 << 16;
    for (int i = 0; i < NN; i++) { double q = (i + 0.5) / NN; a += -std::tanh(dB2amp(36.9) * (2 * q - 1) + 4.37); }
    return a / NN;
}
static void set303(Open303& o, const uint8_t* k) {
    o.setCutoff(cutoffHz(k[OT_CUT])); o.setEnvMod(100.0 * k[OT_ENV] / 127.0); o.setResonance(100.0 * k[OT_RES] / 127.0);
    o.setDecay(decayMs(k[OT_DEC])); o.setAccent(100.0 * k[OT_ACC] / 127.0); o.setSlideTime(slideMs(k[OT_SLID]));
    o.setTuning(tuningHz(k[OT_TUNE])); o.setWaveform(k[OT_WAVE] / 127.0);
    o.setVolume(20.0 * std::log10(std::max(1e-9, std::pow(k[OT_VOL] / 127.0, 2.0))));
}

struct St { char kind; int ptch; bool slide; int acc; };
// N note, T tie (trigless), R rest; slide on a note slides into it
static const St LINE[16] = {{'N', 64, false, 100}, {'T', 0, false, 0}, {'N', 76, true, 0}, {'N', 64, false, 0},
                            {'R', 0, false, 0}, {'N', 67, true, 0}, {'N', 71, false, 110}, {'T', 0, false, 0},
                            {'T', 0, false, 0}, {'N', 74, true, 90}, {'N', 62, false, 0}, {'N', 64, true, 0},
                            {'N', 76, false, 127}, {'R', 0, false, 0}, {'N', 64, false, 0}, {'N', 69, true, 0}};
static const long STEPS = 5088;     // a 16th at 130 BPM

struct Ev { long at; int kind; int note, vel; uint8_t k[12]; unsigned ev; uint32_t gl; };   // kind 1 on, 0 off

int main(int argc, char** argv) {
    if (argc < 2) { std::printf("usage: chain_check OUTDIR\n"); return 2; }
    const std::string dir = argv[1];
    const std::string mode = argc > 2 ? argv[2] : "";
    const bool locks = mode.rfind("locks", 0) == 0;                     // every step locks CUT ENV DEC (random); locks-cut etc: one
    const int gateK = argc > 3 ? std::atoi(argv[3]) : 63;
    const int BARS = 6;
    // the knobs of each bar (WAVE: saw, saw, square, square, half, saw)
    auto knobs = [&](int bar, const St& s, uint8_t* k) {
        static const uint8_t base[12] = {64, 30, 100, 80, 60, 0, 0, 64, 38, 63, 119, 0};
        for (int i = 0; i < 12; i++) k[i] = base[i];
        k[OT_CUT] = uint8_t(20 + 15 * bar);
        k[OT_WAVE] = bar == 2 || bar == 3 ? 127 : bar == 4 ? 64 : 0;
        k[OT_PTCH] = uint8_t(s.kind == 'N' ? s.ptch : 64);
        k[OT_ACC] = uint8_t(s.acc);
        k[OT_GATE] = uint8_t(gateK);
        if (locks) {
            unsigned h = unsigned(bar * 16 + (&s - LINE)) * 2654435761u;
            if (mode == "locks" || mode == "locks-cut") k[OT_CUT] = uint8_t((h >> 8) % 128);
            if (mode == "locks" || mode == "locks-env") k[OT_ENV] = uint8_t((h >> 15) % 128);
            if (mode == "locks" || mode == "locks-dec") k[OT_DEC] = uint8_t((h >> 22) % 128);
        }
    };
    std::vector<Ev> evs;
    for (int bar = 0; bar < BARS; bar++)
        for (int s = 0; s < 16; s++) {
            const St& st = LINE[s];
            if (st.kind != 'N') continue;
            int count = 1, n = s;
            for (int i = 1; i < 16; i++) { n = (n + 1) & 15; if (LINE[n].kind != 'T') break; count++; }
            bool hold = LINE[n].kind == 'N' && LINE[n].slide;
            Ev e{}; e.at = (bar * 16 + s) * STEPS; e.kind = 1; knobs(bar, st, e.k);
            e.note = int(ot_note_number(e.k[OT_PTCH])); e.vel = st.acc ? 127 : 64;
            e.ev = 1 | (st.slide ? 2 : 0);
            e.gl = hold ? uint32_t((count + 1) * STEPS) : uint32_t((count - 1) * STEPS + ot_gate_samples(e.k[OT_GATE], STEPS));
            evs.push_back(e);
        }
    const long N = BARS * 16 * STEPS + 20000;

    // ---- open303 and twinv: the line as MIDI (offs at on + GL, or just after the next note's on)
    std::vector<std::pair<long, std::pair<int, int>>> midi;    // (sample, (note, vel)); vel 0 = off; ordered on before off at a tie
    for (size_t i = 0; i < evs.size(); i++) {
        const Ev& e = evs[i];
        long off = e.at + e.gl;
        if (i + 1 < evs.size() && evs[i + 1].at < off) off = evs[i + 1].at;   // held into the next note (a slide)
        midi.push_back({e.at, {e.note, e.vel}});
        midi.push_back({off, {e.note, 0}});
    }
    // at the same sample: a slide's on comes before the previous off (held); a plain off before an on
    std::stable_sort(midi.begin(), midi.end(), [&](const auto& a, const auto& b) { return a.first < b.first; });
    for (size_t i = 0; i + 1 < midi.size(); i++)
        if (midi[i].first == midi[i + 1].first && midi[i].second.second == 0 && midi[i + 1].second.second > 0) {
            // which kind of event is the on: a held note's slide (on first) or a retrigger (off first)
            bool slideOn = false;
            for (const Ev& e : evs) if (e.at == midi[i + 1].first) slideOn = (e.ev & 2) != 0;
            if (slideOn) std::swap(midi[i], midi[i + 1]);
        }
    auto evAt = [&](long at) -> const Ev* { for (const Ev& e : evs) if (e.at == at) return &e; return nullptr; };

    std::vector<float> ref(N), tv(N), ours(N);
    {
        Open303 o; o.setSampleRate(FS);
        size_t mi = 0;
        for (long t = 0; t < N; t++) {
            while (mi < midi.size() && midi[mi].first == t) {
                auto [note, vel] = midi[mi].second;
                if (vel) { const Ev* e = evAt(t); set303(o, e->k); }
                o.noteOn(note, vel, 0.0);
                mi++;
            }
            ref[t] = float(o.getSample());
        }
    }
    const double SQDC = sqDCv();
    {   // twinv: TwinVoice's host() and noteOn
        Open303 o; o.setSampleRate(FS);
        twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
        const uint8_t* curk = evs[0].k;
        auto host = [&]() {
            using twin::q23;
            double rr = 0.01 * (100.0 * curk[OT_RES] / 127.0), rs = (1.0 - std::exp(-3.0 * rr)) / (1.0 - std::exp(-3.0));
            e.INC_T = q23(2.0 * o.oscFreq * o.pitchWheelFactor / (4 * FS));
            e.CS = q23(1.0 - o.pitchSlewLimiter.coeff); e.C_MEG = q23(o.mainEnv.c); e.C2 = q23(o.rc2.coeff);
            e.M_AMP = q23(1.0 - (o.ampEnv.noteIsOn ? o.ampEnv.decayCoeff : o.ampEnv.releaseCoeff));
            e.L0_16 = q23((std::log2(o.cutoff / 200.0) - o.envScaler * o.envOffset) / 16.0);
            e.ES8 = q23(o.envScaler / 8.0); e.AG8 = q23(o.accentGain * o.n2 / 8.0); e.AGF = o.accentGain > 0.0;
            e.RS = q23(rs); e.AG_8 = q23((1.0 - rs * rs) / 8.0); e.BG = q23(rs * (1.0 + rs) * 8.0 / 17.0);
            e.K8 = q23(o.ampEnv.noteIsOn ? (0.45 + 4.0 * o.accentGain) / 8.0 : 0.0);
            e.SC = q23(o.ampScaler);
            double b = o.oscillator.blend;
            e.W1 = q23(-(1.0 - b) / 2.0); e.W2 = q23(b / 4.0); e.W3 = q23(b * SQDC / 4.0); e.SQ = b > 0.0;
        };
        size_t mi = 0;
        for (long t = 0; t < N; t++) {
            while (mi < midi.size() && midi[mi].first == t) {
                auto [note, vel] = midi[mi].second;
                bool trig = vel > 0 && o.noteList.empty();
                if (vel) { const Ev* ev = evAt(t); set303(o, ev->k); curk = ev->k; }
                o.noteOn(note, vel, 0.0);
                host();
                if (trig) {
                    e.S48 = twin::acc(e.INC_T);
                    e.M48 = (twin::A)std::nearbyint(0.5 / o.mainEnv.c * 140737488355328.0);
                    e.AMP2 = twin::q23(0.5 / twin::f23(e.M_AMP));
                }
                mi++;
            }
            tv[t] = float(e.tick());
        }
    }
    {   // ours: params.c's words, the DSP host's rules
        twin::Engine e; e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8); e.meg48 = true; e.inc48 = false; e.FBS = 4;
        Open303 o; o.setSampleRate(FS); e.C2 = twin::q23(o.rc2.coeff);
        long evc = 0x7fffff; int half = 0; twin::W moff = 0;
        size_t ei = 0;
        uint8_t k[12]; for (int i = 0; i < 12; i++) k[i] = evs[0].k[i];
        for (long t = 0; t < N; t++) {
            if (t % 16 == 0) {      // the frame's continuous words: the knobs of the frame's note, else the last note's
                if (ei < evs.size() && evs[ei].at < t + 16) for (int i = 0; i < 12; i++) k[i] = evs[ei].k[i];
                ot_cont c; ot_params_cont(k, &c);
                e.CS = c.cs; e.ES8 = c.es8; e.RS = c.rs; e.BG = c.bg; e.SC = c.sc; e.SQ = c.sq != 0;
                e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3; e.L0_16 = c.l0_16; e.AG_8 = c.ag_8;
            }
            if (evc == 0) { evc = 0x7fffff; if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; } }
            if (ei < evs.size() && evs[ei].at == t) {
                const Ev& v = evs[ei++];
                ot_note n; ot_params_note(v.k, &n);
                e.C_MEG = n.c_meg; e.AG8 = n.ag8; e.AGF = n.agf != 0; e.K8 = n.k8_on; moff = n.m_amp_off; evc = long(v.gl);
                e.INC_T = n.inc_t;
                if (!((v.ev & 2) && half)) {
                    e.M_AMP = n.m_amp_on; e.S48 = twin::acc(n.inc_t);
                    e.M48 = (twin::A(n.m48h) << 24) | (uint32_t(n.m48l) & 0xffffff); e.AMP2 = n.amp2; half = 1;
                }
            }
            ours[t] = float(e.tick());
            evc--;
        }
    }
    for (auto& [name, v] : {std::pair<const char*, std::vector<float>*>{"open303", &ref}, {"twinv", &tv}, {"ours", &ours}}) {
        std::ofstream f(dir + "/" + name + ".f32", std::ios::binary);
        f.write(reinterpret_cast<const char*>(v->data()), std::streamsize(v->size() * sizeof(float)));
    }
    std::printf("%zu notes, %ld samples (%d bars at %ld samples a step)\n", evs.size(), N, BARS, STEPS);
    return 0;
}

// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 hardware probe on dsp56kEmu: the wrapper (tools/ot303/hwprobe.asm + hwprobe_ev.asm) entered
// the way the stock dispatcher enters DJ EQ's process routine, against the integer twin.
//   hwprobe_probe DIR KNOB FRAMES [corrupt]
// DIR holds p1.bin (ORG in p1.org), p2.bin (p2.org), x.txt ("addr word"), syms.txt ("name hex X|Y"),
// djeq.txt (DJ EQ's proc address). KNOB: page-2 slot 7 (1..127): 1-15 TONE, 16-31 ENG+TONE, 32-47 RIFF,
// 48-63 WATCH, 64-127 SQUARE. Entered by a jsr from a stub; with 303 up it returns itself.
// m0-m5 and m7 are NOT linear on entry here (m6 is: the knob is read through r6), and must come back.
// `corrupt`: in WATCH, one table word is changed mid-run; the output must become the 880 Hz tone.
// Each frame is two calls, as the dispatcher makes them: n7 = k1 (skipped when 0), then 16 - k1
// (made even when 0), k1 varying. Checks: r0 r6 r7 n7 and m0-m7 kept; the track's audio untouched
// while the tables build; the built LT table and the cleared tanh table word for word; then every
// output sample (L and R) against the twin playing the same riff; cycles per sample (host-stepped).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <vector>
#include "dsp56kEmu/dsp.h"
#include "dsp56kEmu/memory.h"
#include "dsp56kEmu/peripherals.h"
#include "halfband4x.h"
#include "halfband2x.h"
#include "twin.h"
using namespace dsp56k;
struct AllowAll : IMemoryValidator { bool memValidateAccess(EMemArea, TWord, bool) const override { return true; } };
static std::vector<uint32_t> load24(const std::string& p) {
    std::ifstream in(p, std::ios::binary); std::vector<uint8_t> b((std::istreambuf_iterator<char>(in)), {});
    std::vector<uint32_t> w; for (size_t i = 0; i + 2 < b.size(); i += 3) w.push_back(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16));
    return w;
}
static int32_t sx(uint32_t w) { return int32_t(w << 8) >> 8; }
static uint32_t hx(const std::string& s) { return (uint32_t)std::stoul(s, nullptr, 16); }

int main(int argc, char** argv) {
    if (argc < 4) { std::printf("usage: hwprobe_probe DIR KNOB FRAMES [corrupt]\n"); return 2; }
    const bool corrupt = argc > 4;
    std::string dir = argv[1]; int knob = std::atoi(argv[2]); long frames = std::atol(argv[3]);
    auto rd = [&](const char* n) { std::ifstream f(dir + "/" + n); std::string s; f >> s; return hx(s); };
    auto p1 = load24(dir + "/p1.bin"), p2 = load24(dir + "/p2.bin");
    uint32_t o1 = rd("p1.org"), o2 = rd("p2.org"), djeq = rd("djeq.txt");
    std::map<std::string, uint32_t> S;
    { std::ifstream f(dir + "/syms.txt"); std::string n, v, sp; while (f >> n >> v >> sp) S[n] = hx(v); }
    auto sym = [&](const char* n) { auto it = S.find(n); if (it == S.end()) { std::printf("no symbol %s\n", n); std::exit(2); } return it->second; };

    AllowAll val; Memory mem(val, 0x080000, 0x800000, 0x200000);
    Peripherals56362 px; Peripherals56367 py; DSP dsp(mem, &px, &py);
    for (size_t i = 0; i < p1.size(); i++) dsp.memWriteP(o1 + TWord(i), p1[i]);
    for (size_t i = 0; i < p2.size(); i++) dsp.memWriteP(o2 + TWord(i), p2[i]);
    dsp.memWriteP(djeq, 0);                                       // a nop: with 303 at 0 the wrapper leaves here
    const uint32_t STUB = 0x100;                                  // jsr >hq_entry ; nop (the return lands on it)
    dsp.memWriteP(STUB, 0x0bf080); dsp.memWriteP(STUB + 1, sym("hq_entry")); dsp.memWriteP(STUB + 2, 0);
    { std::ifstream f(dir + "/x.txt"); std::string a, w; while (f >> a >> w) mem.set(MemArea_X, hx(a), hx(w)); }
    // the Y region the probe owns starts as noise on the unit: poison it here
    for (uint32_t a = 0x795; a < 0x1000; a++) mem.set(MemArea_Y, a, (a * 2654435761u) & 0xffffff);
    // DIAG12: a relocated run 1 (payload A, T6's FX1 block) starts as noise too; hq_reloc fills it on the first call
    if (sym("OLD1") != sym("PB")) {
        for (uint32_t a = sym("PB"); a < sym("PB") + 216; a++) mem.set(MemArea_X, a, (a * 2246822519u) & 0xffffff);
    }
    auto& R = dsp.regs();
    const uint32_t MIN[8] = {0xff, 0x3ff, 0x1f, 0x3, 0x7f, 0x5fb, 0xffffff, 0x9};    // entry modifiers
    for (int k = 0; k < 8; k++) R.m[k].var = MIN[k];
    dsp.setHostStepped(true);
    auto gx = [&](uint32_t a) { return sx(mem.get(MemArea_X, a)); };
    auto gy = [&](uint32_t a) { return sx(mem.get(MemArea_Y, a)); };

    const uint32_t PARB = 0x3000, AUD = 0x0000, R7V = 0x6200;
    const int burn = std::getenv("HWP_BURN") ? std::atoi(std::getenv("HWP_BURN")) : 0;    // page-2 slot 6
    mem.set(MemArea_X, PARB + 0xc, (uint32_t(burn & 0x7f) << 16) | (uint32_t(knob & 0x7f) << 8));
    const int pre = 0;                                                                     // DIAG8: no PRE
    const bool meter = false;                                            // DIAG10: 64-127 = STRESS + TONE
    std::vector<int32_t> mvals; std::vector<int> mlens;
    uint64_t totalCyc = 0, worstFrame = 0, worstInit = 0; long calls = 0;
    // one call; returns its cycles
    auto call = [&](int n7, uint32_t r0) -> uint64_t {
        R.r[0].var = r0; R.r[6].var = PARB; R.r[7].var = R7V; R.n[7].var = n7;
        for (int k = 0; k < 8; k++) R.m[k].var = MIN[k];
        dsp.setPC(STUB);
        uint64_t cyc = 0; unsigned steps = 0;
        while (dsp.getPC().toWord() != djeq && dsp.getPC().toWord() != STUB + 2 && steps++ < 3000000) {
            uint32_t pc = dsp.getPC().toWord();
            uint64_t c0 = dsp.getInstructionCounter();
            uint32_t cy = dsp.calcOpcodeCycles(pc);
            dsp.execInterpreter();
            uint64_t n = dsp.getInstructionCounter() - c0;
            if (n > 1) cy += uint32_t(n - 1) * dsp.calcOpcodeCycles(pc + 1);
            cyc += cy;
            dsp.doLoopEnd();
        }
        if (dsp.getPC().toWord() != STUB + 2) { std::printf("call %ld: did not return (pc %06x)\n", calls, dsp.getPC().toWord()); std::exit(1); }
        if ((R.r[0].var & 0xffffff) != r0 || (R.r[6].var & 0xffffff) != PARB || (R.r[7].var & 0xffffff) != R7V ||
            (R.n[7].var & 0xffffff) != uint32_t(n7)) {
            std::printf("call %ld: r0 %06x r6 %06x r7 %06x n7 %06x not kept\n", calls, R.r[0].var & 0xffffff,
                        R.r[6].var & 0xffffff, R.r[7].var & 0xffffff, R.n[7].var & 0xffffff); std::exit(1);
        }
        for (int m = 0; m < 8; m++) if ((R.m[m].var & 0xffffff) != MIN[m]) { std::printf("call %ld: m%d %06x, entered %06x\n", calls, m, R.m[m].var & 0xffffff, MIN[m]); std::exit(1); }
        calls++;
        return cyc;
    };
    const bool nosplit = std::getenv("HWP_NOSPLIT") != nullptr;          // one 16-sample call a frame (the firmware's usual)
    auto split = [&](long f) { return nosplit ? 0 : int((f * 7) % 16); };  // 0..15: the trig's offset (the second call is never empty)

    twin::Engine e;                                              // builds the twin's tables
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;
    // ---- the tables build: the track's audio passes untouched
    int initCalls = 0;
    for (long f = 0; gx(sym("STG")) != 2; f++) {
        for (int i = 0; i < 32; i++) mem.set(MemArea_X, AUD + i, 0x123400 + i);
        int k1 = split(f);
        uint64_t c = 0;
        if (k1) c += call(k1, AUD);
        c += call(16 - k1, AUD + 2 * k1);
        if (c > worstInit) worstInit = c;
        for (int i = 0; i < 32; i++) if ((mem.get(MemArea_X, AUD + i) & 0xffffff) != 0x123400u + i) { std::printf("init: audio touched\n"); return 1; }
        initCalls += (k1 ? 2 : 1);
        if (f > 200) { std::printf("init does not finish (STG %d CNK %d)\n", gx(sym("STG")), gx(sym("CNK"))); return 1; }
    }
    int bad = 0;
    for (int i = 0; i <= twin::LT_N; i++) {
        uint32_t a = sym("LT") + 4 * i;
        bad += gy(a) != twin::T.b0[i]; bad += gy(a + 1) != twin::T.db0[i]; bad += gy(a + 2) != twin::T.kp[i]; bad += gy(a + 3) != twin::T.dkp[i];
    }
    for (int i = 0; i < 1026; i++) bad += gy(sym("TH") + i) != 0;
    if (bad) { std::printf("tables: %d words differ\n", bad); return 1; }
    std::printf("tables built in %d calls (worst frame %.1f cycles/sample); LT matches the twin, tanh cleared\n",
                initCalls, worstInit / 16.0);

    // ---- the twin, playing the same riff (the square's tanh table cleared, as on the DSP)
    for (int i = 0; i <= 512; i++) { twin::T.th[i] = 0; twin::T.dth[i] = 0; }
    auto X = [&](const char* n) { return gx(sym(n)); };
    e.CS = X("CS"); e.C2 = X("C2"); e.ES8 = X("ES8"); e.RS = X("RS"); e.BG = X("BG"); e.SC = X("SC");
    e.L0_16 = sx(mem.get(MemArea_X, sym("L0C"))); e.AG_8 = sx(mem.get(MemArea_X, sym("AG8C")));
    const int band = knob >> 4;
    bool sq = false;
    uint32_t ww = sym(sq ? "SQRW" : "SAWW");
    e.W1 = gx(ww); e.W2 = gx(ww + 1); e.W3 = gx(ww + 2); e.SQ = gx(ww + 3) != 0;
    auto vars = [&](int v) { uint32_t a = sym("VARS") + 5 * v; e.C_MEG = gx(a); e.M_AMP = gx(a + 1); e.AG8 = gx(a + 2); e.AGF = gx(a + 3) != 0; e.K8 = gx(a + 4); };
    vars(3);
    e.INC_T = 0;
    long evc = 0; int half = 0, step = 0; int32_t curw = 0;
    auto event = [&]() {
        evc = 2544;
        if (!half) {
            half = 1; curw = gx(sym("PAT") + step);
            if (curw & 0x800000) return;
            bool acc = (curw & 0x400000) != 0;
            vars(acc ? 0 : 2);
            int32_t inc = curw & 0xffff;
            e.INC_T = inc; e.S48 = twin::A(inc) << 24;
            uint32_t t = sym("TRIG") + (acc ? 0 : 2);
            e.M48 = (twin::A(gx(t)) << 24) | (mem.get(MemArea_X, t + 1) & 0xffffff);
            e.AMP2 = gx(sym("AMPT"));
        } else {
            half = 0; step = (step + 1) & 15;
            if (curw & 0x800000) return;
            vars((curw & 0x400000) ? 1 : 3);
        }
    };
    std::vector<float> wav;
    long sample = 0;
    uint32_t tph = 0, tinc = 0xa3a3; bool alarm = false;
    const long corruptAt = frames / 2;
    for (long f = 0; f < frames; f++) {
        if (corrupt && f == corruptAt) { mem.set(MemArea_Y, sym("LT") + 300, (mem.get(MemArea_Y, sym("LT") + 300) + 1) & 0xffffff);
                                         alarm = true; tinc = 0x51d1c; }        // this frame's first call sees it
        int k1 = split(f);
        uint64_t c = 0;
        if (k1) c += call(k1, AUD);
        c += call(16 - k1, AUD + 2 * k1);
        totalCyc += c; if (c > worstFrame) worstFrame = c;
        for (int j = 0; j < 16; j++) {
            if (evc == 0) event();
            if (!alarm) { e.tick(); }
            evc--;
            int32_t want = e.outW;
            bool toneNow = knob < 32 || alarm;                               // DIAG13: 32-127 riff
            if (toneNow) { tph = (tph + tinc) & 0xffffff; want = sx(tph) >> 2; }
            int32_t l = gx(AUD + 2 * j), r = gx(AUD + 2 * j + 1);
            if (meter) {                                                 // ticks, then -KCNT for the rest of the render
                if (l != r) { std::printf("METER: L %06x != R %06x\n", l & 0xffffff, r & 0xffffff); return 1; }
                if (l >= 0) { mvals.push_back(l); mlens.push_back(1); }
                else if (!mlens.empty()) {
                    if ((-l) >> 16 != mlens.back() + 0 && (-l) & 0xffff) { std::printf("METER: marker %06x\n", l & 0xffffff); return 1; }
                    mlens.back()++;
                }
                sample++;
                continue;
            }
            if (l != want || r != want) {
                std::printf("MISMATCH frame %ld sample %ld (step %d): dsp L %06x R %06x want %06x\n", f, sample, step,
                            l & 0xffffff, r & 0xffffff, want & 0xffffff);
                return 1;
            }
            wav.push_back(float(l) / 8388608.0f);
            sample++;
        }
    }
    if (std::getenv("HWP_DUMP")) {                                      // the engine's memory after FRAMES riff frames
        uint32_t pb = sym("SAWW");
        std::printf("X:%05x:", pb); for (int i = 0; i < 216; i++) std::printf(" %06x", mem.get(MemArea_X, pb + i) & 0xffffff); std::printf("\n");
        std::printf("Y:%05x:", sym("YS")); for (int i = 0; i < 172; i++) std::printf(" %06x", mem.get(MemArea_Y, sym("YS") + i) & 0xffffff); std::printf("\n");
    }
    if (meter) {
        std::vector<double> per;
        for (size_t i = 1; i + 1 < mvals.size(); i++) per.push_back(2.0 * (mvals[i] >> 7) / mlens[i]);    // ticks are CLK/2
        std::sort(per.begin(), per.end());
        std::printf("METER mode %d (0 plain, else yielding): %zu renders; cycles/sample by the timer: min %.1f median %.1f max %.1f; "
                    "the bench's own count %.1f cycles/sample incl. the wrapper\n", (knob - 64) >> 3, per.size(),
                    per.empty() ? 0 : per.front(), per.empty() ? 0 : per[per.size() / 2], per.empty() ? 0 : per.back(),
                    double(totalCyc) / (frames * 16.0));
        return 0;
    }
    const char* what[] = {"TONE", "STRESS + TONE", "STRESS + TONE", "ENG + TONE", "ENG + TONE", "RIFF / 8", "RIFF", "X READS + TONE"};
    if (burn || pre) std::printf("BURN %d PRE %d: +%d cycles a sample expected (24 x each)\n", burn, pre, 24 * (burn + pre));
    std::printf("BIT-EXACT: %ld samples, %s%s, %ld calls; %.1f cycles/sample incl. the wrapper (worst frame %.1f)\n",
                sample, what[knob < 32 ? 0 : 6], corrupt ? " (a table word changed mid-run: the alarm tone followed)" : "",
                calls, double(totalCyc) / (frames * 16.0), worstFrame / 16.0);
    std::ofstream o(dir + "/out_" + std::to_string(knob) + (corrupt ? "c" : "") + ".f32", std::ios::binary);
    o.write(reinterpret_cast<const char*>(wav.data()), std::streamsize(wav.size() * sizeof(float)));
    return 0;
}

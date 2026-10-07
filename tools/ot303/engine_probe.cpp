// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 Phase 2b: the DSP engine (tools/ot303/ot303_engine.asm, assembled) on dsp56kEmu against its
// contract, the integer twin (tools/ot303/twin.h), word for word.
//   engine_probe CODE.bin ORG STUB.bin STUBORG SYMS.txt LOG.txt
// CODE: the engine at P:ORG. STUB: `jsr ot303` then a nop at P:STUBORG (the probe runs from STUBORG
// to the nop). SYMS: "name hex" for every equ and label. LOG: the segments voice_study's twin
// mode wrote (log:FILE): "n reset trig <18 host words> S48hi S48lo M48hi M48lo AMP2".
// Each segment: the host words are written to the DSP and to the twin, a reset/trigger poked into
// both, then the DSP renders n samples (one call, r7 = n) and the twin ticks n times. Any differing
// word stops the run with both sides' state. Prints instructions per sample (mean, worst 16-sample call).
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <map>
#include <set>
#include <sstream>
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
static std::vector<uint32_t> load24(const char* p) {
    std::ifstream in(p, std::ios::binary); std::vector<uint8_t> b((std::istreambuf_iterator<char>(in)), {});
    std::vector<uint32_t> w; for (size_t i = 0; i + 2 < b.size(); i += 3) w.push_back(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16));
    return w;
}
static int32_t sx(uint32_t w) { return int32_t(w << 8) >> 8; }

int main(int argc, char** argv) {
    if (argc != 7) { std::printf("usage: engine_probe CODE.bin ORG STUB.bin STUBORG SYMS.txt LOG.txt\n"); return 2; }
    auto hx = [](const std::string& s) { return (uint32_t)std::stoul(s, nullptr, 16); };
    auto code = load24(argv[1]); uint32_t org = hx(argv[2]);
    auto stub = load24(argv[3]); uint32_t sorg = hx(argv[4]);
    std::map<std::string, uint32_t> S;
    { std::ifstream f(argv[5]); std::string n, v; while (f >> n >> v) S[n] = hx(v); }
    auto sym = [&](const char* n) { auto it = S.find(n); if (it == S.end()) { std::printf("no symbol %s\n", n); std::exit(2); } return it->second; };

    // the contract: the lean engine
    twin::Engine e;
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;

    AllowAll val; Memory mem(val, 0x080000, 0x800000, 0x200000);
    Peripherals56362 px; Peripherals56367 py; DSP dsp(mem, &px, &py);
    for (size_t i = 0; i < code.size(); i++) dsp.memWriteP(org + TWord(i), code[i]);
    for (size_t i = 0; i < stub.size(); i++) dsp.memWriteP(sorg + TWord(i), stub[i]);
    auto& R = dsp.regs();
    for (int k = 0; k < 8; k++) R.m[k].var = 0xffffff;
#ifdef OT303_HOSTSTEP
    dsp.setHostStepped(true);
#endif
    const uint32_t stopA = sorg + uint32_t(stub.size()) - 1;    // the stub's last word (a nop)
    auto X = [&](uint32_t a, int32_t w) { mem.set(MemArea_X, a, uint32_t(w) & 0xffffff); };
    auto Y = [&](uint32_t a, int32_t w) { mem.set(MemArea_Y, a, uint32_t(w) & 0xffffff); };
    auto gx = [&](uint32_t a) { return sx(mem.get(MemArea_X, a)); };
    auto gy = [&](uint32_t a) { return sx(mem.get(MemArea_Y, a)); };
    // which memory each named word lives in (ot303_engine.asm: coefficients in X, data in Y)
    static const std::set<std::string> YN = {"INC_T", "RC2", "L0_16", "AG_8", "AMP2", "DIC1", "DIC2", "MEG2", "TOPS",
        "APX", "APY", "H2X", "H2Y", "NIC1", "NIC2", "HPX", "HPY", "FBX", "FBY", "YY1", "YY2", "YY3", "YY4"};
    auto isY = [](const std::string& n) { return YN.count(n) != 0; };
    auto gs = [&](const char* n) { return isY(n) ? gy(sym(n)) : gx(sym(n)); };
    auto ws = [&](const char* n, int32_t w) { if (isY(n)) Y(sym(n), w); else X(sym(n), w); };
    // constants and tables, from the twin
    X(sym("LMAX"), twin::q23(twin::LT_OCT / 16.0)); X(sym("S70"), e.S70); X(sym("C437"), e.C437);
    X(sym("HP1B"), e.HP1_B); X(sym("HP1A"), e.HP1_A); X(sym("FBB"), e.FB_B); X(sym("FBA"), e.FB_A);
    X(sym("APB"), e.AP_B); X(sym("APA"), e.AP_A); X(sym("HP2B"), e.HP2_B); X(sym("HP2A"), e.HP2_A);
    X(sym("TOPA"), e.TOP_A);
    X(sym("NA1"), e.notch.a1); X(sym("NA2"), e.notch.a2); X(sym("NA3"), e.notch.a3); X(sym("NKK"), e.notch.kk);
    X(sym("DA1"), e.decl.a1); X(sym("DA2"), e.decl.a2); X(sym("DA3"), e.decl.a3); X(sym("DA2B"), e.decl.a2);
    for (int i = 0; i <= twin::LT_N; i++) {
        uint32_t a = sym("LT") + 4 * i;
        Y(a, twin::T.b0[i]); Y(a + 1, twin::T.db0[i]); Y(a + 2, twin::T.kp[i]); Y(a + 3, twin::T.dkp[i]);
    }
    for (int i = 0; i <= 512; i++) { Y(sym("TH") + 2 * i, twin::T.th[i]); Y(sym("TH") + 2 * i + 1, twin::T.dth[i]); }
    for (int i = 0; i < 8; i++) Y(sym("HB1C") + i, e.hb4.c[i]);
    for (int i = 0; i < 22; i++) Y(sym("HB2C") + i, e.hb2.c[i]);
    if (sym("THM") != sym("TH") + 512) { std::printf("THM != TH + 512\n"); return 2; }

    const char* zeroed[] = {"PH", "APX", "APY", "H2X", "H2Y", "TOPS", "NIC1", "NIC2", "DIC1", "DIC2"};
    auto resetDsp = [&]() {
        for (auto n : zeroed) ws(n, 0);
        for (int i = 0; i < 16; i++) Y(sym("PP") + i, 0);
        for (int i = 0; i < 16; i++) X(sym("HB1B") + i, 0);
        for (int i = 0; i < 64; i++) X(sym("HB2B") + i, 0);
        X(sym("HB1P"), sym("HB1B")); X(sym("HB2P"), sym("HB2B"));
    };
    resetDsp();
    for (auto n : {"S48", "M48"}) { X(sym(n), 0); Y(sym(n), 0); }
    ws("RC2", 0); ws("AMP2", 0);

    const char* hostNames[] = {"INC_T", "CS", "C_MEG", "C2", "M_AMP", "L0_16", "ES8", "AG8", "AGFM", "RS", "AG_8", "BG",
                               "K8", "SC", "W1", "W2", "W3", "SQ"};
    const uint32_t OUTB = 0x3000;
    const bool prof = std::getenv("OT303_PROF") != nullptr;      // instructions per code region (labels)
    std::map<uint32_t, uint64_t> pcHist;
    std::ifstream lf(argv[6]); std::string line;
    long seg = 0, samples = 0; uint64_t instr = 0, worst16 = 0, cycles = 0, worstCyc16 = 0;
    while (std::getline(lf, line)) {
        std::istringstream s(line); int n, rst, trg; s >> n >> rst >> trg;
        uint32_t h[18]; for (auto& v : h) { std::string t; s >> t; v = hx(t); }
        std::string t; uint32_t s48h, s48l, m48h, m48l, amp;
        s >> t; s48h = hx(t); s >> t; s48l = hx(t); s >> t; m48h = hx(t); s >> t; m48l = hx(t); s >> t; amp = hx(t);
        // twin
        e.INC_T = sx(h[0]); e.CS = sx(h[1]); e.C_MEG = sx(h[2]); e.C2 = sx(h[3]); e.M_AMP = sx(h[4]); e.L0_16 = sx(h[5]);
        e.ES8 = sx(h[6]); e.AG8 = sx(h[7]); e.AGF = h[8] != 0; e.RS = sx(h[9]); e.AG_8 = sx(h[10]); e.BG = sx(h[11]);
        e.K8 = sx(h[12]); e.SC = sx(h[13]); e.W1 = sx(h[14]); e.W2 = sx(h[15]); e.W3 = sx(h[16]); e.SQ = h[17] != 0;
        for (int i = 0; i < 18; i++) ws(hostNames[i], sx(h[i]));
        if (rst) { e.resetAudio(); resetDsp(); }
        if (trg) {
            e.S48 = (twin::A(s48h) << 24) | s48l; e.M48 = (twin::A(m48h) << 24) | m48l; e.AMP2 = sx(amp);
            X(sym("S48"), s48h); Y(sym("S48"), s48l); X(sym("M48"), m48h); Y(sym("M48"), m48l); ws("AMP2", sx(amp));
        }
        // DSP: one call per segment, in calls of at most 16 (a frame)
        for (int done = 0; done < n;) {
            int k = std::min(16, n - done);
            R.r[7].var = k; R.r[3].var = OUTB;
            dsp.setPC(sorg);
            uint64_t i0 = dsp.getInstructionCounter(); unsigned steps = 0; uint64_t callCycles = 0;
#ifdef OT303_HOSTSTEP
            // octabam's host-stepped interpreter: one instruction per step (a DO loop returns after
            // each instruction; doLoopEnd() applies the loop's end test). Cycles from the emulator's
            // own table (dsp56k::calcCycles: internal P, no interlocks), a REP's repeats priced as
            // the repeated instruction.
            while (dsp.getPC().toWord() != stopA && steps++ < 4000000) {
                uint32_t pc = dsp.getPC().toWord();
                uint64_t c0 = dsp.getInstructionCounter();
                uint32_t cy = dsp.calcOpcodeCycles(pc);
                dsp.execInterpreter();
                uint64_t n = dsp.getInstructionCounter() - c0;
                if (n > 1) cy += uint32_t(n - 1) * dsp.calcOpcodeCycles(pc + 1);
                cycles += cy; callCycles += cy;
                if (prof) pcHist[pc] += cy;
                dsp.doLoopEnd();
            }
#else
            while (dsp.getPC().toWord() != stopA && steps++ < 2000000) {
                if (prof) pcHist[dsp.getPC().toWord()]++;
                dsp.execInterpreter();
            }
#endif
            if (dsp.getPC().toWord() != stopA) { std::printf("segment %ld: did not return (pc %06x)\n", seg, dsp.getPC().toWord()); return 1; }
            uint64_t ni = dsp.getInstructionCounter() - i0; instr += ni; if (k == 16 && ni > worst16) worst16 = ni;
            if (k == 16 && callCycles > worstCyc16) worstCyc16 = callCycles;
            if ((R.r[3].var & 0xffffff) != OUTB + uint32_t(k)) { std::printf("r3 = %06x after %d samples\n", R.r[3].var & 0xffffff, k); return 1; }
            for (int m = 0; m < 8; m++) if ((R.m[m].var & 0xffffff) != 0xffffff) { std::printf("m%d left at %06x\n", m, R.m[m].var & 0xffffff); return 1; }
            for (int j = 0; j < k; j++) {
                e.tick();
                int32_t d = gx(OUTB + j);
                if (d != e.outW) {
                    std::printf("MISMATCH segment %ld (line %ld) sample %ld: dsp %06x twin %06x\n", seg, seg + 1, samples, d & 0xffffff, e.outW & 0xffffff);
                    if (j + 1 < k) std::printf("  (the twin is mid-call: state below is the DSP's after %d samples, the twin's after %d)\n", k, j + 1);
                    struct { const char* n; twin::W t; } st[] = {{"PH", e.P}, {"HPY", e.hpy}, {"FBY", e.fby}, {"YY1", e.Y1}, {"YY2", e.Y2},
                        {"YY3", e.Y3}, {"YY4", e.Y4}, {"RC2", e.RC2}, {"AMP2", e.AMP2}, {"APY", e.apy}, {"H2Y", e.h2y}, {"TOPS", e.tops},
                        {"NIC1", e.notch.ic1}, {"NIC2", e.notch.ic2}, {"DIC1", e.decl.ic1}, {"DIC2", e.decl.ic2}};
                    for (auto& q : st) std::printf("  %-5s dsp %06x twin %06x%s\n", q.n, gs(q.n) & 0xffffff, q.t & 0xffffff, gs(q.n) == q.t ? "" : "  <--");
                    std::printf("  M48 dsp %06x%06x twin %012llx; S48 dsp %06x%06x twin %012llx\n", gx(sym("M48")) & 0xffffff, gy(sym("M48")) & 0xffffff,
                                (unsigned long long)e.M48, gx(sym("S48")) & 0xffffff, gy(sym("S48")) & 0xffffff, (unsigned long long)e.S48);
                    return 1;
                }
                samples++;
            }
            done += k;
        }
        seg++;
    }
#ifdef OT303_HOSTSTEP
    std::printf("CYCLES (emulator table, internal P, no interlocks): %.1f/sample (worst 16-sample call %.1f/sample)\n",
                samples ? double(cycles) / samples : 0.0, worstCyc16 / 16.0);
#endif
    if (prof) {                                 // attribute each PC to the nearest label at or below it
        std::map<uint32_t, std::string> labs;
        for (auto& kv : S) if (kv.first.size() > 1 && kv.first[0] == 'z' && kv.second >= org && kv.second < org + code.size()) labs[kv.second] = kv.first;
        labs[org] = "ot303";
        std::map<std::string, uint64_t> per;
        for (auto& kv : pcHist) { auto it = labs.upper_bound(kv.first); --it; per[it->second] += kv.second; }
        for (auto& kv : per) std::printf("  %-8s %7.1f per sample\n", kv.first.c_str(), double(kv.second) / samples);
        if (std::string(std::getenv("OT303_PROF")) == "2")       // per PC (cycles with OT303_HOSTSTEP)
            for (auto& kv : pcHist) std::printf("  PC %05x %8.3f\n", kv.first, double(kv.second) / samples);
    }
    std::printf("BIT-EXACT: %ld samples in %ld segments; %.1f instructions/sample (worst 16-sample call %.1f/sample)\n",
                samples, seg, samples ? double(instr) / samples : 0.0, worst16 / 16.0);
    return 0;
}

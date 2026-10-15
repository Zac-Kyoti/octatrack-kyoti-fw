// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 hardware probe (DIAG14) on dsp56kEmu: the source-seam glue and the DJ EQ remote
// (tools/ot303/hwprobe.asm) entered the way the firmware enters them, against the integer twin.
//   hwprobe_probe DIR KNOB FRAMES
// DIR holds p1.bin (ORG in p1.org), x.txt ("addr word"), syms.txt ("name hex X|Y"), djeq.txt (DJ EQ's
// proc address), cont.txt (the stock code after the source), rawp.txt (1: payload A's raw path).
// KNOB: DJ EQ page-2 slot 7 (1-31 TONE, 32-127 RIFF); HWP_BURN = slot 6; HWP_RAW=1 sets bit 18 of
// the claimed track's word (payload A: the raw path, the ring base must stay).
// Each frame runs three tracks of one core in the firmware's order, each: the seam (jsr from a stub,
// as the stock `move a,x:>$20e` now is), then its FX1 DJ EQ as two dispatcher calls (n7 = k1, skipped
// when 0, then 16 - k1). Track $00: no DJ EQ. Track $20 (OWNER): 303 = KNOB until 3/4 of the run,
// then 0. Track $40 (RIVAL): 303 = 0, then KNOB from half the run: it must wait while the owner
// holds the voice, and take it over (the same engine, continuing) once the owner's claim lapses.
// A model of the claim (OWN, LIVE) predicts which track renders each frame. Checks, every call:
//   seam, stock path: returns (rts) with only b, x0 and the CCR changed; X:0 untouched
//   seam, voice: never returns (continues at CONT, the return dropped, SP as before the jsr); X:0..31
//     = the twin's next 16 samples, L = R; x:$20e = a; x:$20b + $80 (not on payload A's raw path);
//     m0-m7 as found
//   DJ EQ: leaves through DJ EQ's stock proc with r0 r6 r7 n7 and m0-m7 kept
// and the built LT table and the cleared tanh table word for word; cycles (host-stepped).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <map>
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
    if (argc < 4) { std::printf("usage: hwprobe_probe DIR KNOB FRAMES\n"); return 2; }
    std::string dir = argv[1]; int knob = std::atoi(argv[2]); long frames = std::atol(argv[3]);
    auto rd = [&](const char* n) { std::ifstream f(dir + "/" + n); std::string s; f >> s; return hx(s); };
    auto p1 = load24(dir + "/p1.bin");
    uint32_t o1 = rd("p1.org"), djeq = rd("djeq.txt"), cont = rd("cont.txt"), rawp = rd("rawp.txt");
    std::map<std::string, uint32_t> S;
    { std::ifstream f(dir + "/syms.txt"); std::string n, v, sp; while (f >> n >> v >> sp) S[n] = hx(v); }
    auto sym = [&](const char* n) { auto it = S.find(n); if (it == S.end()) { std::printf("no symbol %s\n", n); std::exit(2); } return it->second; };

    AllowAll val; Memory mem(val, 0x080000, 0x800000, 0x200000);
    Peripherals56362 px; Peripherals56367 py; DSP dsp(mem, &px, &py);
    for (size_t i = 0; i < p1.size(); i++) dsp.memWriteP(o1 + TWord(i), p1[i]);
    dsp.memWriteP(djeq, 0);                                       // DJ EQ's stock proc: the run stops here
    dsp.memWriteP(cont, 0);                                       // the stock code after the source: likewise
    const uint32_t STUBS = 0x100, STUBD = 0x110;                  // jsr >entry ; nop (an rts lands on the nop)
    dsp.memWriteP(STUBS, 0x0bf080); dsp.memWriteP(STUBS + 1, sym("sg_entry")); dsp.memWriteP(STUBS + 2, 0);
    dsp.memWriteP(STUBD, 0x0bf080); dsp.memWriteP(STUBD + 1, sym("hq_entry")); dsp.memWriteP(STUBD + 2, 0);
    { std::ifstream f(dir + "/x.txt"); std::string a, w; while (f >> a >> w) mem.set(MemArea_X, hx(a), hx(w)); }
    // the Y region the probe owns starts as noise on the unit: poison it here; run 1's place and the
    // claim words too (hq_reloc fills them on the first claim)
    for (uint32_t a = 0x795; a < 0x1000; a++) mem.set(MemArea_Y, a, (a * 2654435761u) & 0xffffff);
    for (uint32_t a = sym("SIGA"); a < sym("PB") + 216; a++) mem.set(MemArea_X, a, (a * 2246822519u) & 0xffffff);
    auto& R = dsp.regs();
    const uint32_t MIN[8] = {0xff, 0x3ff, 0x1f, 0x3, 0x7f, 0x5fb, 0xffffff, 0x9};    // entry modifiers (m6: the DJ EQ knob is read through r6)
    dsp.setHostStepped(true);
    auto gx = [&](uint32_t a) { return sx(mem.get(MemArea_X, a)); };
    auto gy = [&](uint32_t a) { return sx(mem.get(MemArea_Y, a)); };

    const uint32_t PARB = 0x3000, TRKW = 0x3100, AUD = 0x0040, R7V = 0x6200;
    const bool raw = std::getenv("HWP_RAW") != nullptr;
    const int burn = std::getenv("HWP_BURN") ? std::atoi(std::getenv("HWP_BURN")) : 0;
    auto setKnob = [&](int k) { mem.set(MemArea_X, PARB + 0xc, (uint32_t(burn & 0x7f) << 16) | (uint32_t(k & 0x7f) << 8)); };
    long calls = 0;
    auto run = [&](uint32_t stub, uint32_t stop2, uint64_t& cyc) -> uint32_t {     // -> where it stopped
        dsp.setPC(stub);
        cyc = 0; unsigned steps = 0;
        for (;;) {
            uint32_t pc = dsp.getPC().toWord();
            if (pc == stub + 2 || pc == stop2) break;
            if (steps++ > 3000000) { std::printf("call %ld: runaway (pc %06x)\n", calls, pc); std::exit(1); }
            uint64_t c0 = dsp.getInstructionCounter();
            uint32_t cy = dsp.calcOpcodeCycles(pc);
            dsp.execInterpreter();
            uint64_t n = dsp.getInstructionCounter() - c0;
            if (n > 1) cy += uint32_t(n - 1) * dsp.calcOpcodeCycles(pc + 1);
            cyc += cy;
            dsp.doLoopEnd();
        }
        calls++;
        return dsp.getPC().toWord();
    };
    // the seam for track t; -> true when the voice rendered
    uint64_t seamCyc = 0, seamCalls = 0, voiceCyc = 0, voiceWorst = 0, voiceFrames = 0, stockCyc = 0, stockCalls = 0, initWorst = 0;
    auto seam = [&](uint32_t t, bool expectVoice, bool building) -> bool {
        mem.set(MemArea_X, 0x418, t);
        mem.set(MemArea_X, TRKW + 0x1e, (raw && t == 0x20) ? 0x040000 : 0x000300);
        const uint32_t rb = 0x1e00 + t * 4;
        mem.set(MemArea_X, 0x20b, rb);
        for (int i = 0; i < 32; i++) mem.set(MemArea_X, i, 0x5a0000 + i);
        const uint32_t A1 = 0x123456 ^ t;
        const int64_t AV = ((int64_t(A1) << 24) | 0x000777) << 8;   // dsp56kEmu keeps accumulators left-aligned (DSP::g_aluShift, private)
        R.a.var = AV; R.r[2].var = TRKW;
        for (int k = 0; k < 8; k++) { R.m[k].var = MIN[k]; if (k != 2) R.r[k].var = 0x111 * (k + 1); R.n[k].var = 0x222 + k; }
        R.x.var = 0x0abcde0fedcbull; R.y.var = 0x0135790246800ull;
        const uint32_t sp0 = R.sp.var;
        uint64_t cyc;
        uint32_t at = run(STUBS, cont, cyc);
        seamCyc += cyc; seamCalls++;
        if ((mem.get(MemArea_X, 0x20e) & 0xffffff) != A1) { std::printf("seam %ld: x:$20e %06x, a was %06x\n", calls, mem.get(MemArea_X, 0x20e) & 0xffffff, A1); std::exit(1); }
        if (R.sp.var != sp0) { std::printf("seam %ld: SP %x, entered %x\n", calls, R.sp.var, sp0); std::exit(1); }
        for (int m = 0; m < 8; m++) if ((R.m[m].var & 0xffffff) != MIN[m]) { std::printf("seam %ld: m%d %06x, entered %06x\n", calls, m, R.m[m].var & 0xffffff, MIN[m]); std::exit(1); }
        if (at == cont) {
            if (!expectVoice) { std::printf("seam %ld (track $%02x): the voice rendered, not expected\n", calls, t); std::exit(1); }
            bool keep = rawp && raw && t == 0x20;
            uint32_t want = keep ? rb : rb + 0x80;
            if ((mem.get(MemArea_X, 0x20b) & 0xffffff) != want) { std::printf("seam %ld: ring base %06x, want %06x\n", calls, mem.get(MemArea_X, 0x20b) & 0xffffff, want); std::exit(1); }
            voiceCyc += cyc; voiceFrames++; voiceWorst = std::max(voiceWorst, cyc);
            return true;
        }
        if (expectVoice) { std::printf("seam %ld (track $%02x): returned to the stock source, the voice was expected\n", calls, t); std::exit(1); }
        if ((R.r[2].var & 0xffffff) != TRKW) { std::printf("seam %ld: r2 not kept\n", calls); std::exit(1); }
        if ((mem.get(MemArea_X, 0x20b) & 0xffffff) != rb) { std::printf("seam %ld: ring base moved on the stock path\n", calls); std::exit(1); }
        for (int i = 0; i < 32; i++) if ((mem.get(MemArea_X, i) & 0xffffff) != 0x5a0000u + i) { std::printf("seam %ld: X:0 touched on the stock path\n", calls); std::exit(1); }
        if (building) { initWorst = std::max(initWorst, cyc); return false; }      // a table chunk: r2 and m0-m7 are the contract
        if (R.a.var != AV) { std::printf("seam %ld: a not kept\n", calls); std::exit(1); }
        if ((R.x.var & 0xffffff000000ull) != (0x0abcde0fedcbull & 0xffffff000000ull) || R.y.var != 0x0135790246800ull) { std::printf("seam %ld: x1/y not kept\n", calls); std::exit(1); }
        for (int k = 0; k < 8; k++) {
            if (k != 2 && (R.r[k].var & 0xffffff) != 0x111u * (k + 1)) { std::printf("seam %ld: r%d not kept\n", calls, k); std::exit(1); }
            if ((R.n[k].var & 0xffffff) != 0x222u + k) { std::printf("seam %ld: n%d not kept\n", calls, k); std::exit(1); }
        }
        stockCyc += cyc; stockCalls++;
        return false;
    };
    uint64_t djCyc = 0, djCalls = 0;
    auto djeqCall = [&](uint32_t t, int k, int n7, uint32_t r0) {
        setKnob(k);
        mem.set(MemArea_X, 0x418, t);
        R.r[0].var = r0; R.r[6].var = PARB; R.r[7].var = R7V; R.n[7].var = n7;
        for (int m = 0; m < 8; m++) R.m[m].var = MIN[m];
        for (int i = 0; i < 32; i++) mem.set(MemArea_X, AUD + i, 0x6b0000 + i);
        uint64_t cyc;
        if (run(STUBD, djeq, cyc) != djeq) { std::printf("DJ EQ call %ld returned itself\n", calls); std::exit(1); }
        if ((R.r[0].var & 0xffffff) != r0 || (R.r[6].var & 0xffffff) != PARB || (R.r[7].var & 0xffffff) != R7V ||
            (R.n[7].var & 0xffffff) != uint32_t(n7)) { std::printf("DJ EQ call %ld: r0 r6 r7 n7 not kept\n", calls); std::exit(1); }
        for (int m = 0; m < 8; m++) if ((R.m[m].var & 0xffffff) != MIN[m]) { std::printf("DJ EQ call %ld: m%d %06x\n", calls, m, R.m[m].var & 0xffffff); std::exit(1); }
        for (int i = 0; i < 32; i++) if ((mem.get(MemArea_X, AUD + i) & 0xffffff) != 0x6b0000u + i) { std::printf("DJ EQ call %ld: audio touched\n", calls); std::exit(1); }
        djCyc += cyc; djCalls++;
    };
    auto split = [&](long f) { return int((f * 7) % 16); };

    twin::Engine e;                                              // builds the twin's tables
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;
    for (int i = 0; i <= 512; i++) { twin::T.th[i] = 0; twin::T.dth[i] = 0; }   // the square's tanh table: cleared, as on the DSP
    bool twinSet = false;
    long evc = 0; int half = 0, step = 0; int32_t curw = 0;
    auto vars = [&](int v) { uint32_t a = sym("VARS") + 5 * v; e.C_MEG = gx(a); e.M_AMP = gx(a + 1); e.AG8 = gx(a + 2); e.AGF = gx(a + 3) != 0; e.K8 = gx(a + 4); };
    auto event = [&]() {
        evc = 2544;
        if (!half) {
            half = 1; curw = gx(sym("PAT") + step);
            if (curw & 0x800000) return;
            bool acc = (curw & 0x400000) != 0;
            vars(acc ? 0 : 2);
            int32_t inc = curw & 0xffff;
            e.INC_T = inc; e.S48 = twin::A(inc) << 24;
            uint32_t tr = sym("TRIG") + (acc ? 0 : 2);
            e.M48 = (twin::A(gx(tr)) << 24) | (mem.get(MemArea_X, tr + 1) & 0xffffff);
            e.AMP2 = gx(sym("AMPT"));
        } else {
            half = 0; step = (step + 1) & 15;
            if (curw & 0x800000) return;
            vars((curw & 0x400000) ? 1 : 3);
        }
    };
    auto setupTwin = [&]() {                                     // from run 1 as the DSP holds it after the copy
        auto X = [&](const char* n) { return gx(sym(n)); };
        e.CS = X("CS"); e.C2 = X("C2"); e.ES8 = X("ES8"); e.RS = X("RS"); e.BG = X("BG"); e.SC = X("SC");
        e.L0_16 = gx(sym("L0C")); e.AG_8 = gx(sym("AG8C"));
        uint32_t ww = sym("SAWW");
        e.W1 = gx(ww); e.W2 = gx(ww + 1); e.W3 = gx(ww + 2); e.SQ = gx(ww + 3) != 0;
        vars(3); e.INC_T = 0;
        twinSet = true;
    };
    uint32_t tph = 0, tinc = 0xa3a3;
    std::vector<float> wav;
    long sample = 0;

    // the claim model
    uint32_t own = 0; int live = 0; bool tablesChecked = false;
    long ownerFrames = 0, rivalFrames = 0, initFrames = 0, handover = -1;
    const uint32_t TR[3] = {0x00, 0x20, 0x40};
    for (long f = 0; f < frames; f++) {
        const int kOwner = f < frames * 3 / 4 ? knob : 0;
        const int kRival = f >= frames / 2 ? knob : 0;
        for (uint32_t t : TR) {
            // the seam: the model says whether this track renders
            bool ready = gx(sym("STG")) == 2 && (mem.get(MemArea_X, sym("SIGA")) & 0xffffff) == 0x5a5a5a;
            bool mine = own == t + 1 && (mem.get(MemArea_X, sym("SIGA")) & 0xffffff) == 0x5a5a5a;
            bool voice = false, building = false;
            if (mine) {
                if (live == 0) own = 0;
                else { live--; voice = ready; building = !ready; if (!ready) initFrames++; }
            }
            if (voice && !tablesChecked) {
                int bad = 0;
                for (int i = 0; i <= twin::LT_N; i++) {
                    uint32_t a = sym("LT") + 4 * i;
                    bad += gy(a) != twin::T.b0[i]; bad += gy(a + 1) != twin::T.db0[i]; bad += gy(a + 2) != twin::T.kp[i]; bad += gy(a + 3) != twin::T.dkp[i];
                }
                for (int i = 0; i < 1026; i++) bad += gy(sym("TH") + i) != 0;
                if (bad) { std::printf("tables: %d words differ\n", bad); return 1; }
                std::printf("tables built at the seam in %ld frames (the track's source heard meanwhile; worst %.1f cycles/sample); "
                            "LT matches the twin, tanh cleared\n", initFrames, initWorst / 16.0);
                tablesChecked = true;
                setupTwin();
            }
            bool rendered = seam(t, voice, building);
            if (rendered) {
                (t == 0x20 ? ownerFrames : rivalFrames)++;
                if (t == 0x40 && handover < 0) handover = f;
                for (int j = 0; j < 16; j++) {
                    int32_t want;
                    if (knob < 32) { tph = (tph + tinc) & 0xffffff; want = sx(tph) >> 2; }
                    else { if (evc == 0) event(); e.tick(); evc--; want = e.outW; }
                    int32_t l = gx(2 * j), r = gx(2 * j + 1);
                    if (l != want || r != want) {
                        std::printf("MISMATCH frame %ld track $%02x sample %ld (step %d): dsp L %06x R %06x want %06x\n", f, t, sample, step,
                                    l & 0xffffff, r & 0xffffff, want & 0xffffff);
                        return 1;
                    }
                    wav.push_back(float(l) / 8388608.0f);
                    sample++;
                }
            }
            // its FX1: DJ EQ (not on track $00)
            if (t == 0x00) continue;
            const int k = t == 0x20 ? kOwner : kRival;
            if (k > 0 && (own == 0 || own == t + 1)) { own = t + 1; live = 2; }
            int k1 = split(f);
            if (k1) djeqCall(t, k, k1, AUD);
            djeqCall(t, k, 16 - k1, AUD + 2 * k1);
            if ((mem.get(MemArea_X, sym("OWN")) & 0xffffff) != own || gx(sym("LIVE")) != live) {
                std::printf("frame %ld track $%02x: OWN %06x LIVE %d, the model says %06x %d\n", f, t,
                            mem.get(MemArea_X, sym("OWN")) & 0xffffff, gx(sym("LIVE")), own, live);
                return 1;
            }
        }
    }
    if (!tablesChecked || !ownerFrames || !rivalFrames) { std::printf("the voice did not run on both tracks (owner %ld, rival %ld frames)\n", ownerFrames, rivalFrames); return 1; }
    std::printf("claims: owner $20 rendered %ld frames, rival $40 waited, then took over at frame %ld (owner released at %ld) "
                "and rendered %ld; track $00 always stock\n", ownerFrames, handover, frames * 3 / 4, rivalFrames);
    if (burn) std::printf("BURN %d: +%d cycles a sample in each DJ EQ call (24 x BURN)\n", burn, 24 * burn);
    std::printf("BIT-EXACT: %ld samples, %s%s; seam with the voice %.1f cycles/sample (worst frame %.1f); "
                "seam on other tracks %.1f cycles/call; DJ EQ remote %.1f cycles/call incl. BURN\n",
                sample, knob < 32 ? "TONE" : "RIFF", (raw && rawp) ? " (raw path: ring base kept)" : "",
                double(voiceCyc) / (voiceFrames * 16.0), voiceWorst / 16.0,
                double(stockCyc) / std::max<uint64_t>(stockCalls, 1), double(djCyc) / std::max<uint64_t>(djCalls, 1));
    std::ofstream o(dir + "/out_" + std::to_string(knob) + ".f32", std::ios::binary);
    o.write(reinterpret_cast<const char*>(wav.data()), std::streamsize(wav.size() * sizeof(float)));
    return 0;
}

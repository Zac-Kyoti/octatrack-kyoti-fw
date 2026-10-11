// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// OT-303 machine host (tools/ot303/host.asm) on dsp56kEmu, entered the way the firmware enters the
// source seam, against the integer twin.
//   host_probe DIR FRAMES
// DIR holds p1.bin (ORG in p1.org), x.txt ("addr word"), syms.txt ("name hex X|Y"), cont.txt (the
// stock code after the source), rawp.txt.
// Each frame runs one core's four tracks in order, each a seam call (jsr from a stub, as the stock
// `move a,x:>$20e` now is) with its record at x:$209 and its frame offset at x:$20c:
//   $00, $60  stock records (never the signature)
//   $20 (A)   an OT-303 record (w0 $3303, w2 $0909, w3 = trig) until 3/4 of the run, then stock
//   $40 (B)   stock, then an OT-303 record from half the run: silent while A holds the voice, then
//             it takes the voice over (the same engine, continuing) once A's claim has aged out
// Trigs reach the OT-303 tracks at varying offsets, mostly a bar's 16th apart (318 frames), every
// fourth one sooner than the gate (100 frames: the open gate closes first).
// A model of the claim (OWN, LIVE) predicts each call. Checks:
//   stock record: returns (rts) with only b, x0, r4 and the CCR changed; X:0 and the ring base kept
//   OT-303 record: never returns (on at CONT, the return dropped, SP as before the jsr); ring base
//     + $80; m0-m7 as found; x:$20e = a; X:0..31 = the twin's next 16 samples L = R when it holds the
//     voice and the tables are built, else silence
// and the built LT table and the cleared tanh table word for word; cycles (host-stepped).
#include <algorithm>
#include <cmath>
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
    if (argc < 3) { std::printf("usage: host_probe DIR FRAMES\n"); return 2; }
    std::string dir = argv[1]; long frames = std::atol(argv[2]);
    auto rd = [&](const char* n) { std::ifstream f(dir + "/" + n); std::string s; f >> s; return hx(s); };
    auto p1 = load24(dir + "/p1.bin");
    uint32_t o1 = rd("p1.org"), cont = rd("cont.txt");
    std::map<std::string, uint32_t> S;
    { std::ifstream f(dir + "/syms.txt"); std::string n, v, sp; while (f >> n >> v >> sp) S[n] = hx(v); }
    auto sym = [&](const char* n) { auto it = S.find(n); if (it == S.end()) { std::printf("no symbol %s\n", n); std::exit(2); } return it->second; };

    AllowAll val; Memory mem(val, 0x080000, 0x800000, 0x200000);
    Peripherals56362 px; Peripherals56367 py; DSP dsp(mem, &px, &py);
    for (size_t i = 0; i < p1.size(); i++) dsp.memWriteP(o1 + TWord(i), p1[i]);
    dsp.memWriteP(cont, 0);
    const uint32_t STUB = 0x100;
    dsp.memWriteP(STUB, 0x0bf080); dsp.memWriteP(STUB + 1, sym("sg_entry")); dsp.memWriteP(STUB + 2, 0);
    { std::ifstream f(dir + "/x.txt"); std::string a, w; while (f >> a >> w) mem.set(MemArea_X, hx(a), hx(w)); }
    for (uint32_t a = 0x795; a < 0x1000; a++) mem.set(MemArea_Y, a, (a * 2654435761u) & 0xffffff);
    for (uint32_t a = sym("SIGA"); a < sym("PB") + 216; a++) mem.set(MemArea_X, a, (a * 2246822519u) & 0xffffff);
    auto& R = dsp.regs();
    const uint32_t MIN[8] = {0xff, 0x3ff, 0x1f, 0x3, 0x7f, 0x5fb, 0xffffff, 0x9};
    dsp.setHostStepped(true);
    auto gx = [&](uint32_t a) { return sx(mem.get(MemArea_X, a)); };
    auto gyy = [&](uint32_t a) { return sx(mem.get(MemArea_Y, a)); };

    const uint32_t REC = 0x2a00, TRKW = 0x3100;
    long calls = 0;
    auto run = [&](uint64_t& cyc) -> uint32_t {
        dsp.setPC(STUB);
        cyc = 0; unsigned steps = 0;
        for (;;) {
            uint32_t pc = dsp.getPC().toWord();
            if (pc == STUB + 2 || pc == cont) break;
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
    enum Want { STOCK, SILENT, VOICE };
    uint64_t voiceCyc = 0, voiceWorst = 0, voiceFrames = 0, stockCyc = 0, stockCalls = 0, silentWorst = 0;
    // one seam call; X:0..31 after it are returned through `out` for a VOICE call
    auto seam = [&](uint32_t t, bool sig, int trig, int offset, Want want) {
        mem.set(MemArea_X, 0x418, t);
        mem.set(MemArea_X, 0x209, REC);
        mem.set(MemArea_X, 0x20c, offset);
        for (int i = 0; i < 24; i++) mem.set(MemArea_X, REC + i, (0x4100 + 0x11 * i + t) & 0xffff);   // a stock-looking record
        if (sig) { mem.set(MemArea_X, REC, 0x3303); mem.set(MemArea_X, REC + 2, 0x0909); mem.set(MemArea_X, REC + 3, trig); }
        else mem.set(MemArea_X, REC, 0x0000);                       // stock w0: the high half of a source count
        mem.set(MemArea_X, TRKW + 0x1e, 0x000300);
        const uint32_t rb = 0x1e00 + t * 4;
        mem.set(MemArea_X, 0x20b, rb);
        for (int i = 0; i < 32; i++) mem.set(MemArea_X, i, 0x5a0000 + i);
        const uint32_t A1 = 0x123456 ^ t;
        const int64_t AV = ((int64_t(A1) << 24) | 0x000777) << 8;   // dsp56kEmu keeps accumulators left-aligned
        R.a.var = AV; R.r[2].var = TRKW;
        for (int k = 0; k < 8; k++) { R.m[k].var = MIN[k]; if (k != 2) R.r[k].var = 0x111 * (k + 1); R.n[k].var = 0x222 + k; }
        R.x.var = 0x0abcde0fedcbull; R.y.var = 0x0135790246800ull;
        const uint32_t sp0 = R.sp.var;
        uint64_t cyc;
        uint32_t at = run(cyc);
        auto fail = [&](const char* what) { std::printf("seam %ld (track $%02x, %s): %s\n", calls, t, want == STOCK ? "stock" : want == SILENT ? "silent" : "voice", what); std::exit(1); };
        if ((mem.get(MemArea_X, 0x20e) & 0xffffff) != A1) fail("x:$20e is not a");
        if (R.sp.var != sp0) fail("SP moved");
        for (int m = 0; m < 8; m++) if ((R.m[m].var & 0xffffff) != MIN[m]) fail("m register changed");
        if (want == STOCK) {
            if (at != STUB + 2) fail("did not return to the stock source");
            if ((R.r[2].var & 0xffffff) != TRKW || R.a.var != AV) fail("r2/a not kept");
            if ((mem.get(MemArea_X, 0x20b) & 0xffffff) != rb) fail("ring base moved");
            for (int i = 0; i < 32; i++) if ((mem.get(MemArea_X, i) & 0xffffff) != 0x5a0000u + i) fail("X:0 touched");
            if ((R.x.var & 0xffffff000000ull) != (0x0abcde0fedcbull & 0xffffff000000ull) || R.y.var != 0x0135790246800ull) fail("x1/y not kept");
            for (int k = 0; k < 8; k++) {
                if (k != 2 && k != 4 && (R.r[k].var & 0xffffff) != 0x111u * (k + 1)) fail("an r register changed");
                if ((R.n[k].var & 0xffffff) != 0x222u + k) fail("an n register changed");
            }
            stockCyc += cyc; stockCalls++;
            return;
        }
        if (at != cont) fail("returned to the stock source");
        if ((mem.get(MemArea_X, 0x20b) & 0xffffff) != rb + 0x80) fail("ring base not advanced");
        if (want == SILENT) {
            for (int i = 0; i < 32; i++) if (mem.get(MemArea_X, i) & 0xffffff) fail("not silent");
            silentWorst = std::max(silentWorst, cyc);
        } else { voiceCyc += cyc; voiceFrames++; voiceWorst = std::max(voiceWorst, cyc); }
    };

    twin::Engine e;
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;
    for (int i = 0; i <= 512; i++) { twin::T.th[i] = 0; twin::T.dth[i] = 0; }
    const long BIG = 0x7fffff;
    long evc = 0; int half = 0, step = 0; int32_t curw = 0;
    auto vars = [&](int v) { uint32_t a = sym("VARS") + 5 * v; e.C_MEG = gx(a); e.M_AMP = gx(a + 1); e.AG8 = gx(a + 2); e.AGF = gx(a + 3) != 0; e.K8 = gx(a + 4); };
    auto gateoff = [&]() {
        evc = BIG;
        if (!half) return;
        half = 0; step = (step + 1) & 15;
        if (curw & 0x800000) return;
        vars((curw & 0x400000) ? 1 : 3);
    };
    auto start = [&]() {
        if (half) gateoff();
        evc = 2544; half = 1; curw = gx(sym("PAT") + step);
        if (curw & 0x800000) return;
        bool acc = (curw & 0x400000) != 0;
        vars(acc ? 0 : 2);
        int32_t inc = curw & 0xffff;
        e.INC_T = inc; e.S48 = twin::A(inc) << 24;
        uint32_t tr = sym("TRIG") + (acc ? 0 : 2);
        e.M48 = (twin::A(gx(tr)) << 24) | (mem.get(MemArea_X, tr + 1) & 0xffffff);
        e.AMP2 = gx(sym("AMPT"));
    };
    bool twinSet = false;
    auto setupTwin = [&]() {
        auto X = [&](const char* n) { return gx(sym(n)); };
        e.CS = X("CS"); e.C2 = X("C2"); e.ES8 = X("ES8"); e.RS = X("RS"); e.BG = X("BG"); e.SC = X("SC");
        e.L0_16 = gx(sym("L0C")); e.AG_8 = gx(sym("AG8C"));
        uint32_t ww = sym("SAWW");
        e.W1 = gx(ww); e.W2 = gx(ww + 1); e.W3 = gx(ww + 2); e.SQ = gx(ww + 3) != 0;
        vars(3); e.INC_T = 0;
        twinSet = true;
    };
    // the trig frames: mostly 318 apart, every fourth 100 after the one before
    std::set<long> trigs;
    for (long f = 3, i = 0; f < frames; f += (++i % 4) ? 318 : 100) trigs.insert(f);
    std::vector<float> wav;
    long sample = 0, aFrames = 0, bFrames = 0, takeover = -1, trigsHeard = 0;
    uint32_t own = 0; int live = 0; bool tablesChecked = false, relocated = false; long initFrames = 0;
    for (long f = 0; f < frames; f++) {
        const bool sigA = f < frames * 3 / 4, sigB = f >= frames / 2;
        const int trig = trigs.count(f) ? 1 : 0;
        const int offset = int((f * 5) % 16);
        for (uint32_t t : {0x00u, 0x20u, 0x40u, 0x60u}) {
            const bool sig = (t == 0x20 && sigA) || (t == 0x40 && sigB);
            if (t == 0 && live > 0 && --live == 0) own = 0;
            Want want = STOCK;
            bool voice = false;
            if (sig) {
                if (!relocated) { own = 0; live = 0; relocated = true; }    // the first frame copies run 1 and frees the voice
                if (own == 0 || own == t + 1) {
                    own = t + 1; live = 2;
                    voice = gx(sym("STG")) == 2;
                    if (!voice) initFrames++;
                }
                want = voice ? VOICE : SILENT;
            }
            if (voice && !tablesChecked) {
                int bad = 0;
                for (int i = 0; i <= twin::LT_N; i++) {
                    uint32_t a = sym("LT") + 4 * i;
                    bad += gyy(a) != twin::T.b0[i]; bad += gyy(a + 1) != twin::T.db0[i]; bad += gyy(a + 2) != twin::T.kp[i]; bad += gyy(a + 3) != twin::T.dkp[i];
                }
                for (int i = 0; i < 1026; i++) bad += gyy(sym("TH") + i) != 0;
                if (bad) { std::printf("tables: %d words differ\n", bad); return 1; }
                std::printf("tables built in %ld silent frames (worst %.1f cycles/sample); LT matches the twin, tanh cleared\n",
                            initFrames, silentWorst / 16.0);
                tablesChecked = true;
                setupTwin();
            }
            seam(t, sig, trig, sig ? offset : int((f * 3) % 16), want);
            if (!voice) continue;
            (t == 0x20 ? aFrames : bFrames)++;
            if (t == 0x40 && takeover < 0) takeover = f;
            long trg = trig ? offset : BIG;
            trigsHeard += trig;
            for (int j = 0; j < 16; j++) {
                if (evc == 0) gateoff();
                if (trg == 0) { start(); trg = BIG; }
                e.tick(); evc--; trg--;
                int32_t want = e.outW;
                int32_t l = gx(2 * j), r = gx(2 * j + 1);
                if (l != want || r != want) {
                    std::printf("MISMATCH frame %ld track $%02x sample %ld (step %d): dsp L %06x R %06x want %06x\n", f, t, sample, step,
                                l & 0xffffff, r & 0xffffff, want & 0xffffff);
                    return 1;
                }
                wav.push_back(float(l) / 8388608.0f);
                sample++;
            }
            if ((mem.get(MemArea_X, sym("OWN")) & 0xffffff) != own || gx(sym("LIVE")) != live) {
                std::printf("frame %ld track $%02x: OWN %06x LIVE %d, the model says %06x %d\n", f, t,
                            mem.get(MemArea_X, sym("OWN")) & 0xffffff, gx(sym("LIVE")), own, live);
                return 1;
            }
        }
    }
    if (!tablesChecked || !aFrames || !bFrames) { std::printf("the voice did not run on both tracks (A %ld, B %ld frames)\n", aFrames, bFrames); return 1; }
    float pk = 0; for (float x : wav) pk = std::max(pk, std::fabs(x));
    std::printf("claims: A ($20) voiced %ld frames; B ($40) silent beside it, then took the voice at frame %ld "
                "(A stopped at %ld) and voiced %ld; $00/$60 always stock\n", aFrames, takeover, frames * 3 / 4, bFrames);
    std::printf("BIT-EXACT: %ld samples, %ld trigs heard (peak %.3f = %.1f dBFS); voice %.1f cycles/sample (worst frame %.1f); "
                "stock records %.1f cycles/call; a silent frame at most %.1f cycles/sample\n",
                sample, trigsHeard, pk, 20 * std::log10(pk), double(voiceCyc) / (voiceFrames * 16.0), voiceWorst / 16.0,
                double(stockCyc) / std::max<uint64_t>(stockCalls, 1), silentWorst / 16.0);
    std::ofstream o(dir + "/host_out.f32", std::ios::binary);
    o.write(reinterpret_cast<const char*>(wav.data()), std::streamsize(wav.size() * sizeof(float)));
    return 0;
}

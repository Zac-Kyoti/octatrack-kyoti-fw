// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 machine host (tools/ot303/host.asm) on dsp56kEmu, entered the way the firmware enters the
// source seam, against the integer twin; the records come from the ColdFire's own code
// (tools/ot303/cf/record.c + params.c, compiled natively).
//   host_probe DIR FRAMES
// DIR holds p1.bin (ORG in p1.org), x.txt ("addr word"), syms.txt ("name hex X|Y"), cont.txt (the
// stock code after the source), rawp.txt.
// Each frame runs one core's four tracks in order, each a seam call (jsr from a stub, as the stock
// `move a,x:>$20e` now is) with its record at x:$209 and its frame offset at x:$20c:
//   $00, $60  stock records (never the signature)
//   $20 (A)   an OT-303 track until 3/4 of the run, then stock
//   $40 (B)   stock, then an OT-303 track from half the run: silent while A holds the voice, then
//             it takes the voice over (the same engine, continuing) in the frame A's record turns stock
// Each OT-303 track plays its own 16-step line (notes, ties, rests, slides into open and into
// closed gates, accents by an ACC lock) at a step of 4,999 samples, so the notes land on every
// frame offset; its knobs move all the time (a CUT sweep, RES/ENV/DEC drifts, WAVE saw ->
// square -> half, SLID, GATE, TUNE). Gates as the ColdFire makes them: ties extend a note by
// whole steps, a note before a slide is held. The transport's top 8 bits carry junk. The tables
// arrive by the record's chunks, A's stream starting mid-cycle. Records ride two ping-pong slots per
// track, as on the unit; for 12 frames A's voice stops rendering and its slots keep their last two
// records (old numbers): silence, its claim lapses, no old note replays.
// A model of the claim (OWN, LIVE) predicts each call. Checks:
//   stock record: returns (rts) with only b, x0, r4 and the CCR changed; X:0 and the ring base kept;
//     the voice's own track's stock record frees the voice
//   OT-303 record: never returns (on at CONT, the return dropped, SP as before the jsr); ring base
//     + $80; m0-m7 as found; x:$20e = a; X:0..31 = the twin's next 16 samples L = R when it holds the
//     voice and the tables are complete, else silence
// the Y image word for word against the twin's tables, Y outside it untouched; cycles
// (host-stepped).
#include <algorithm>
#include <cmath>
#include <cstring>
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
#include "record.h"
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
    // OT_PCPROF=FILE: every executed instruction's cycles summed by its address, written as "pc cycles count"
    // lines at the end (a profiling aid; the checks below do not use it)
    const char* pcprof = std::getenv("OT_PCPROF");
    std::map<uint32_t, std::pair<uint64_t, uint64_t>> prof;
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
            // a step that ran more than one instruction (a DO and its loop's first): the extra one is
            // the instruction after this one, at pc + this one's length (pc + 1 decoded a DO's
            // loop-address operand as an opcode, which made the cost depend on where the loop ends)
            if (n > 1) cy += uint32_t(n - 1) * dsp.calcOpcodeCycles(pc + dsp.opcodes().getOpcodeLength(mem.get(MemArea_P, pc)));
            cyc += cy;
            if (pcprof) { auto& e = prof[pc]; e.first += cy; e.second += 1; }
            dsp.doLoopEnd();
        }
        calls++;
        return dsp.getPC().toWord();
    };
    enum Want { STOCK, SILENT, VOICE };
    uint64_t lastVoiceCyc = 0, stockCyc = 0, stockCalls = 0, silentWorst = 0;
    // one seam call; X:0..31 after it are returned through `out` for a VOICE call
    auto seam = [&](uint32_t t, bool sig, int trig, int offset, Want want) {
        mem.set(MemArea_X, 0x418, t);
        mem.set(MemArea_X, 0x209, REC);
        mem.set(MemArea_X, 0x20c, offset);
        if (!sig) {                                                 // a stock-looking record
            for (int i = 0; i < 24; i++) mem.set(MemArea_X, REC + i, (0x4100 + 0x11 * i + t) & 0xffff);
            mem.set(MemArea_X, REC, 0x0000);                        // stock w0: the high half of a source count
        }
        (void)trig;
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
        } else lastVoiceCyc = cyc;
    };

    twin::Engine e;
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;
    const long BIG = 0x7fffff;
    // the DSP host's note state, modelled
    long evc = BIG; int half = 0; twin::W moff = 0;
    const uint32_t YB = sym("YBEG"), YE = sym("YEND");
    if (YE - YB != ot_ylen || YB != ot_ybeg) { std::printf("the Y image's bounds differ from ytab.c\n"); return 1; }

    // ---- the two lines: kind N note, T tie, R rest; slide on a note slides into it
    struct St { char kind; int ptch; bool slide, acc; };
    const St LA[16] = {{'N', 64, false, true}, {'T', 0, false, false}, {'N', 76, true, false}, {'N', 64, false, false},
                       {'R', 0, false, false}, {'N', 67, true, false}, {'N', 71, false, true}, {'T', 0, false, false},
                       {'T', 0, false, false}, {'N', 74, true, true}, {'N', 62, false, false}, {'N', 64, true, false},
                       {'N', 76, false, true}, {'R', 0, false, false}, {'N', 64, false, false}, {'N', 69, true, false}};
    const St LB[16] = {{'N', 60, false, false}, {'N', 72, true, true}, {'N', 60, true, false}, {'T', 0, false, false},
                       {'N', 63, false, true}, {'R', 0, false, false}, {'R', 0, false, false}, {'N', 58, true, false},
                       {'N', 70, false, false}, {'T', 0, false, false}, {'N', 60, true, true}, {'N', 65, true, false},
                       {'N', 53, false, false}, {'N', 60, false, true}, {'T', 0, false, false}, {'R', 0, false, false}};
    const long STEPS = 4999;
    auto knobs = [&](const St* L, long f, int step, uint8_t k[12]) {
        long ph = f % 6000; int tri = int(ph < 3000 ? ph * 127 / 3000 : (6000 - ph) * 127 / 3000);
        const St& s = L[step & 15];
        k[OT_PTCH] = uint8_t(s.kind == 'N' ? s.ptch : 64);
        k[OT_CUT] = uint8_t(tri);
        k[OT_RES] = uint8_t(40 + (f / 700) % 88);
        k[OT_ENV] = uint8_t((f / 450) % 128);
        k[OT_DEC] = uint8_t((f / 1300 * 37) % 128);
        k[OT_ACC] = uint8_t(s.acc ? 90 + (f / 2000) % 38 : 0);
        k[OT_WAVE] = uint8_t(f < frames / 3 ? 0 : f < frames * 2 / 3 ? 127 : 64);
        k[OT_TUNE] = uint8_t(f < frames / 2 ? 64 : 70);
        k[OT_SLID] = uint8_t((f / 2500) & 1 ? 100 : 38);
        k[OT_GATE] = uint8_t(((f / 1800) * 41 + 20) % 128);
        k[OT_VOL] = uint8_t(119 - (f / 5000) % 4 * 30);       // driven (119, 89), clean (59, 29)
        k[11] = 0;
    };
    // the note a step starts (the ColdFire's look-ahead), or 0
    auto stepEvent = [&](const St* L, int s, unsigned gate, uint32_t& gl) -> unsigned {
        if (L[s].kind != 'N') return 0;
        int count = 1, n = s;
        for (int i = 1; i < 16; i++) { n = (n + 1) & 15; if (L[n].kind != 'T') break; count++; }
        bool hold = L[n].kind == 'N' && L[n].slide && n != s;
        uint64_t g = hold ? uint64_t(count + 1) * STEPS : uint64_t(count - 1) * STEPS + ot_gate_samples(gate, STEPS);
        gl = uint32_t(std::min<uint64_t>(std::max<uint64_t>(g, 1), 0x7ffffe));
        return OT_EV_NOTE | (L[s].slide ? OT_EV_SLIDE : 0);     // (OSC SYNC added by the caller)
    };
    ot_voice va{}, vb{};
    va.chunk = 11; vb.chunk = 23;
    uint32_t rec[OT_REC_LONGS];
    uint32_t slots[2][2][OT_REC_LONGS] = {};        // [track A/B][ping]: the transport's ping-pong slots
    uint32_t lseq[4] = {0, 0, 0, 0};                // the host's last record number taken, per track (modelled)
    // A's voice stops rendering for 12 frames right after one of its notes: its slots stay (one holds the note)
    long STALE0 = frames / 4;
    for (long st = frames / 4 * 16 / 4999 + 1;; st++)
        if (LA[st & 15].kind == 'N') { STALE0 = (st * 4999 + 15) / 16 + 1; break; }
    const long STALE1 = STALE0 + 12;
    long staleFrames = 0;
    long junk = 1;
    auto putRecord = [&]() {
        for (unsigned i = 0; i < OT_REC_LONGS; i++) {
            junk = junk * 1103515245 + 12345;
            uint32_t j1 = (junk >> 8) & 0xff, j2 = (junk >> 16) & 0xff;
            mem.set(MemArea_X, REC + 2 * i, (j1 << 16) | (rec[i] >> 16));
            mem.set(MemArea_X, REC + 2 * i + 1, (j2 << 16) | (rec[i] & 0xffff));
        }
    };
    bool twinSet = false;
    auto setupTwin = [&]() {
        auto X = [&](const char* n) { return gx(sym(n)); };
        e.C2 = X("C2"); e.C_MEG = X("C_MEG"); e.M_AMP = X("M_AMP"); e.AG8 = X("AG8"); e.AGF = X("AGFM") != 0; e.K8 = X("K8");
        e.MEGS = X("MEGS");                                         // the soft attack's state (RC1, GD8: the record's)
        e.FB_B = X("FBB"); e.FB_A = X("FBA");                       // the machine's feedback high-pass (MT14: 350 Hz)
        e.glide = true; e.GLD = X("GLD"); e.ES8 = X("ES8"); e.L0_16 = gyy(sym("L0_16"));   // MT15: the glide's state
        e.INC_T = 0;
        moff = gx(sym("XM") + sym("D_MOFF"));
        twinSet = true;
    };
    std::vector<float> wav;
    long sample = 0, aFrames = 0, bFrames = 0, takeover = -1, notesHeard = 0, slidesHeard = 0, retrigSlides = 0, fromSilence = 0, releases = 0;
    uint64_t sawCyc = 0, sawN = 0, sqCyc = 0, sqN = 0, evWorst = 0, evSawWorst = 0, offSawWorst = 0, sawWorst = 0, sqWorst = 0;
    uint32_t own = 0; int live = 0; bool tablesChecked = false, relocated = false; long initFrames = 0;
    for (long f = 0; f < frames; f++) {
        const bool sigA = f < frames * 3 / 4, sigB = f >= frames / 2;
        // this frame's notes: a step starts at sample STEPS * s (+ a little, B)
        unsigned evA = 0, evB = 0; uint32_t glA = 0, glB = 0; int offA = int((f * 5) % 16), offB = int((f * 3) % 16);
        uint8_t kA[12], kB[12];
        for (int w = 0; w < 2; w++) {
            const St* L = w ? LB : LA; long shift = w ? 1234 : 0;
            long s0 = f * 16 - shift, step = s0 >= 0 ? (s0 + STEPS - 1) / STEPS : -1;
            long at = step * STEPS + shift;
            uint8_t* k = w ? kB : kA;
            int cur = int(std::max<long>(0, (f * 16 - shift) / STEPS));
            knobs(L, f, cur, k);
            if (step >= 0 && at >= f * 16 && at < f * 16 + 16) {
                knobs(L, f, int(step), k);
                uint32_t gl = 0;
                unsigned ev = stepEvent(L, int(step & 15), k[OT_GATE], gl);
                (w ? evB : evA) = ev; (w ? glB : glA) = gl; (w ? offB : offA) = int(at - f * 16);
            }
        }
        // MT18: a live note's release now and then, in a frame with no note (an open gate closes at the
        // frame's start; a closed one is left alone)
        if (!evA && f % 997 == 500) evA = OT_EV_OFF;
        if (!evB && f % 1301 == 650) evB = OT_EV_OFF;
        for (uint32_t t : {0x00u, 0x20u, 0x40u, 0x60u}) {
            const bool sig = (t == 0x20 && sigA) || (t == 0x40 && sigB);
            if (t == 0 && live > 0 && --live == 0) own = 0;
            if (!sig && own == t + 1) { own = 0; live = 0; }                // the owner's own stock record frees it
            Want want = STOCK;
            bool voice = false;
            const bool isA0 = t == 0x20, isB0 = t == 0x40;
            bool old = false;
            if (sig) {
                uint32_t* slot = slots[isB0][f & 1];
                if (!(isA0 && f >= STALE0 && f < STALE1)) {
                    unsigned ev0 = isA0 ? evA : evB; uint32_t gl0 = isA0 ? glA : glB;
                    const uint8_t* kk = isA0 ? kA : kB;                       // MT24: a fraction half the time
                    const unsigned fr = (f >> 11) & 1 ? (f * 37u) & 0xffu : 0u;
                    const unsigned cq = kk[OT_CUT] < 127 ? (kk[OT_CUT] << 8) + fr : 0x7f00u;
                    const unsigned eq = kk[OT_ENV] < 127 ? (kk[OT_ENV] << 8) + fr : 0x7f00u;
                    ot_record(slot, isA0 ? &va : &vb, kk, ev0, gl0, cq, eq);
                } else staleFrames++;
                std::memcpy(rec, slot, sizeof rec);
                putRecord();
                const uint32_t sq = rec[0] & 0xffff, L = lseq[t >> 5];
                old = sq == L || ((sq + 1) & 0xffff) == L;
                if (!old) lseq[t >> 5] = sq;
            }
            if (sig && old) {
                if (!relocated) { own = 0; live = 0; relocated = true; }
                want = SILENT;
            } else if (sig) {
                if (!relocated) { own = 0; live = 0; relocated = true; }    // the first frame copies run 1 and frees the voice
                if (own == 0 || own == t + 1) {
                    own = t + 1; live = 2;
                    voice = gx(sym("XM") + sym("D_STG")) == 2;
                    if (!voice) initFrames++;
                }
                want = voice ? VOICE : SILENT;
            }
            if (voice && !tablesChecked) {
                int bad = 0;
                for (uint32_t i = 0; i < ot_ylen; i++) {
                    uint32_t a = YB + i, w = ((ot_ytab_pk[i] >> 8) & 0xffff00u) | (ot_ytab_pk[i] & 0xffu);   // unpacked
                    if (a >= sym("CB") && a < sym("CHH") + 2) { bad += w != 0; continue; }   // the host's Y scratch (zeros in the image)
                    bad += (mem.get(MemArea_Y, a) & 0xffffff) != w;
                }
                for (int i = 0; i <= 512; i++) { bad += gyy(sym("TH") + 2 * i) != twin::T.th[i]; bad += gyy(sym("TH") + 2 * i + 1) != twin::T.dth[i]; }
                for (int i = 0; i <= twin::LT_N; i++) {
                    uint32_t a = sym("LT") + 4 * i;
                    bad += gyy(a) != twin::T.b0[i]; bad += gyy(a + 1) != twin::T.db0[i]; bad += gyy(a + 2) != twin::T.kp[i]; bad += gyy(a + 3) != twin::T.dkp[i];
                }
                for (int i = 0; i < 16; i++) bad += gyy(sym("HB1C") + i) != e.hb4.c[7 - (i & 7)];
                for (uint32_t a = 0x795; a < 0x1000; a++)
                    if ((a < YB || a >= YE) && (mem.get(MemArea_Y, a) & 0xffffff) != ((a * 2654435761u) & 0xffffff)) bad++;
                if (bad) { std::printf("tables: %d words differ\n", bad); return 1; }
                std::printf("tables: the Y image arrived in %ld silent frames (A's stream from chunk 11): equal to the twin's "
                            "tanh, coefficient table and taps; Y outside it untouched\n", initFrames);
                tablesChecked = true;
                setupTwin();
            }
            const bool isA = t == 0x20, isB = t == 0x40;
            unsigned ev = isA ? evA : isB ? evB : 0; uint32_t gl = isA ? glA : glB; int off = isA ? offA : isB ? offB : int((f * 3) % 16);
            const uint8_t* k = isA ? kA : kB;
            if (old) ev = 0;                                                // the old record's bits are not read
            seam(t, sig, ev & 1, off, want);
            if (!voice) continue;
            (isA ? aFrames : bFrames)++;
            if (isB && takeover < 0) takeover = f;
            const ot_voice& vv = isA ? va : vb;                              // MT20: the eased resonance words, as sent
            const ot_cont& c = vv.c;                                         // MT24: made with CUT / ENV's fraction
            e.CS = c.cs; e.ES8T = c.es8; e.RS = vv.rs; e.BG = vv.bg; e.SC = vv.sc; e.SQ = c.sq != 0;
            e.W1 = c.w1; e.W2 = c.w2; e.W3 = c.w3; e.L016T = c.l0_16; e.AG_8 = vv.ag_8;
            e.RC1 = c.rc1; e.GD8 = c.gd8;                                   // MT10: from RES and VOL, every frame
            ot_note n{}; if (ev & 1) ot_params_note(k, &n);
            long trg = (ev & 1) ? off : BIG;
            if (ev & OT_EV_OFF) { evc = 0; releases++; }
            bool gateEnded = false;
            for (int j = 0; j < 16; j++) {
                if (evc == 0) {
                    gateEnded = true;
                    evc = BIG;
                    if (half) { half = 0; e.K8 = 0; e.M_AMP = moff; }
                }
                if (trg == 0) {
                    trg = BIG; notesHeard++;
                    e.C_MEG = n.c_meg; e.AG8 = n.ag8; e.AGF = n.agf != 0; e.K8 = n.k8_on; moff = n.m_amp_off; evc = long(gl);
                    e.INC_T = n.inc_t;
                    if ((ev & 2) && half) slidesHeard++;
                    else {
                        if (ev & 2) retrigSlides++;
                        if (e.AMP2 < 0x400) fromSilence++;                  // the saw runs free
                        e.M_AMP = n.m_amp_on; e.S48 = twin::acc(n.inc_t);
                        e.M48 = (twin::A(n.m48h) << 24) | (uint32_t(n.m48l) & 0xffffff); e.AMP2 = n.amp2; half = 1;
                    }
                }
                e.tick(); evc--; trg--;
                int32_t want = e.outW;
                int32_t l = gx(2 * j), r = gx(2 * j + 1);
                if (l != want || r != want) {
                    std::printf("MISMATCH frame %ld track $%02x sample %ld: dsp L %06x R %06x want %06x\n", f, t, sample,
                                l & 0xffffff, r & 0xffffff, want & 0xffffff);
                    return 1;
                }
                wav.push_back(float(l) / 8388608.0f);
                sample++;
            }
            uint64_t cy = lastVoiceCyc;
            if (c.sq) { sqCyc += cy; sqN++; } else { sawCyc += cy; sawN++; }
            if (ev & 1) (c.sq ? evWorst : evSawWorst) = std::max(c.sq ? evWorst : evSawWorst, cy);
            else if (gateEnded && !c.sq) offSawWorst = std::max(offSawWorst, cy);
            else if (!gateEnded) (c.sq ? sqWorst : sawWorst) = std::max(c.sq ? sqWorst : sawWorst, cy);
            if ((mem.get(MemArea_X, sym("OWN")) & 0xffffff) != own || gx(sym("LIVE")) != live) {
                std::printf("frame %ld track $%02x: OWN %06x LIVE %d, the model says %06x %d\n", f, t,
                            mem.get(MemArea_X, sym("OWN")) & 0xffffff, gx(sym("LIVE")), own, live);
                return 1;
            }
        }
    }
    if (!tablesChecked || !aFrames || !bFrames) { std::printf("the voice did not run on both tracks (A %ld, B %ld frames)\n", aFrames, bFrames); return 1; }
    float pk = 0; for (float x : wav) pk = std::max(pk, std::fabs(x));
    std::printf("claims: A ($20) voiced %ld frames (silent for its %ld old records, its claim lapsed); B ($40) silent beside it, "
                "then took the voice at frame %ld (A stopped at %ld) and voiced %ld; $00/$60 always stock\n", aFrames, staleFrames,
                takeover, frames * 3 / 4, bFrames);
    std::printf("BIT-EXACT: %ld samples, %ld notes (%ld slides into an open gate, %ld slides into a closed one retriggered, "
                "%ld from silence, the saw running free; cutoff and env amount gliding; %ld releases); peak %.3f = %.1f dBFS\n", sample, notesHeard, slidesHeard, retrigSlides,
                fromSilence, releases, pk, 20 * std::log10(pk));
    std::printf("cycles/sample: saw %.1f (worst plain frame %.1f, note %.1f, gate end %.1f), square %.1f (worst plain %.1f, note %.1f); "
                "stock records %.1f cycles/call; a silent frame at most %.1f\n",
                double(sawCyc) / std::max<uint64_t>(sawN * 16, 1), sawWorst / 16.0, evSawWorst / 16.0, offSawWorst / 16.0,
                double(sqCyc) / std::max<uint64_t>(sqN * 16, 1), sqWorst / 16.0, evWorst / 16.0,
                double(stockCyc) / std::max<uint64_t>(stockCalls, 1), silentWorst / 16.0);
    if (pcprof) {
        std::ofstream pf(pcprof);
        for (auto& [pc, e] : prof) pf << std::hex << pc << std::dec << ' ' << e.first << ' ' << e.second << '\n';
    }
    std::ofstream o(dir + "/host_out.f32", std::ios::binary);
    o.write(reinterpret_cast<const char*>(wav.data()), std::streamsize(wav.size() * sizeof(float)));
    return 0;
}

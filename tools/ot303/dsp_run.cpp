// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303 Phase 2b: a minimal DSP56300 runner on dsp56kEmu (vendor/dsp56300) for code snippets.
//   dsp_run CODE.bin ORG ENTRY STOP [INIT.txt]
// CODE.bin: 24-bit little-endian words loaded at P:ORG. INIT.txt lines: "x ADDR WORD", "y ADDR WORD",
// "p ADDR WORD", "r a VALUE" (a, b as 56-bit hex; x0 x1 y0 y1 r0..r7 n0..n7 m0..m7 as 24-bit hex),
// "dump x|y ADDR COUNT". Prints registers (and dumps) at STOP, plus instructions and cycles.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>
#include "dsp56kEmu/dsp.h"
#include "dsp56kEmu/memory.h"
#include "dsp56kEmu/peripherals.h"
using namespace dsp56k;
struct AllowAll : IMemoryValidator { bool memValidateAccess(EMemArea, TWord, bool) const override { return true; } };
static std::vector<uint32_t> load24(const char* p) {
    std::ifstream in(p, std::ios::binary); std::vector<uint8_t> b((std::istreambuf_iterator<char>(in)), {});
    std::vector<uint32_t> w; for (size_t i = 0; i + 2 < b.size(); i += 3) w.push_back(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16));
    return w;
}
int main(int argc, char** argv) {
    if (argc < 5) { std::printf("usage: dsp_run CODE.bin ORG ENTRY STOP [INIT.txt]\n"); return 2; }
    auto hx = [](const std::string& s) { return (uint64_t)std::stoull(s, nullptr, 16); };
    auto code = load24(argv[1]); uint32_t org = hx(argv[2]), entry = hx(argv[3]), stop = hx(argv[4]);
    AllowAll val; Memory mem(val, 0x080000, 0x800000, 0x200000);
    Peripherals56362 px; Peripherals56367 py; DSP dsp(mem, &px, &py);
    for (size_t i = 0; i < code.size(); i++) dsp.memWriteP(org + TWord(i), code[i]);
    auto& R = dsp.regs();
    for (int k = 0; k < 8; k++) R.m[k].var = 0xffffff;
    std::vector<std::tuple<char, uint32_t, uint32_t>> dumps;
    if (argc > 5) {
        std::ifstream f(argv[5]); std::string line;
        while (std::getline(f, line)) {
            std::istringstream s(line); std::string k, a, v; s >> k >> a >> v;
            if (k == "x") mem.set(MemArea_X, hx(a), hx(v) & 0xffffff);
            else if (k == "y") mem.set(MemArea_Y, hx(a), hx(v) & 0xffffff);
            else if (k == "p") dsp.memWriteP(hx(a), hx(v) & 0xffffff);
            else if (k == "dump") { std::string c; s >> c; dumps.push_back({a[0], (uint32_t)hx(v), (uint32_t)hx(c)}); }
            else if (k == "r") {
                uint64_t x = hx(v);
                if (a == "a") { R.a.var = (int64_t)(x << 8) >> 8; } else if (a == "b") { R.b.var = (int64_t)(x << 8) >> 8; }
                else if (a == "x0") R.x.var = (R.x.var & ~0xffffffull) | (x & 0xffffff);
                else if (a == "x1") R.x.var = (R.x.var & 0xffffffull) | ((x & 0xffffff) << 24);
                else if (a == "y0") R.y.var = (R.y.var & ~0xffffffull) | (x & 0xffffff);
                else if (a == "y1") R.y.var = (R.y.var & 0xffffffull) | ((x & 0xffffff) << 24);
                else if (a[0] == 'r') R.r[a[1] - '0'].var = x & 0xffffff;
                else if (a[0] == 'n') R.n[a[1] - '0'].var = x & 0xffffff;
                else if (a[0] == 'm') R.m[a[1] - '0'].var = x & 0xffffff;
            }
        }
    }
    dsp.setPC(entry);
    uint64_t i0 = dsp.getInstructionCounter(), c0 = dsp.getCycles(); unsigned steps = 0;
    while (dsp.getPC().toWord() != stop && steps++ < 50000000) dsp.execInterpreter();
    if (dsp.getPC().toWord() != stop) { std::printf("did not reach stop (pc %06x)\n", dsp.getPC().toWord()); return 1; }
    auto a56 = [](int64_t v) { return (unsigned long long)(v & 0xffffffffffffffull); };
    std::printf("a %014llx b %014llx x %012llx y %012llx\n", a56(R.a.var), a56(R.b.var),
                (unsigned long long)(R.x.var & 0xffffffffffffull), (unsigned long long)(R.y.var & 0xffffffffffffull));
    for (int k = 0; k < 8; k++) std::printf("r%d %06x n%d %06x m%d %06x\n", k, R.r[k].var & 0xffffff, k, R.n[k].var & 0xffffff, k, R.m[k].var & 0xffffff);
    std::printf("sr %06x instructions %llu cycles %llu\n", dsp.getSR().var & 0xffffff,
                (unsigned long long)(dsp.getInstructionCounter() - i0), (unsigned long long)(dsp.getCycles() - c0));
    for (auto& d : dumps) {
        std::printf("%c:%05x", std::get<0>(d), std::get<1>(d));
        for (uint32_t i = 0; i < std::get<2>(d); i++) std::printf(" %06x", mem.get(std::get<0>(d) == 'x' ? MemArea_X : MemArea_Y, std::get<1>(d) + i) & 0xffffff);
        std::printf("\n");
    }
    return 0;
}

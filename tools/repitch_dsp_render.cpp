// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// repitch-kyoti LISTENING render: streams a stereo source through the REAL
// stock voice-engine kernel on dsp56kEmu, block by block -- unpatched (stock
// = RPCH) or patched with the repitch cave and a mode -- and writes the
// output. Driven by tools/repitch_dsp_listen.py.
//
// What is real and what is modelled:
//   REAL      the kernel (P:0x40b..0x41b, both the stock 2-tap interpolator
//             and our cave), i.e. every sample value you hear
//   MODELLED  stock's pre-kernel stage -- the ring fill and the per-output
//             (offset, fraction) table -- rebuilt here per block from a
//             running phase, the same quantities P:0x3fc..0x40a computes
//
// usage: repitch_dsp_render MOD MODBASE HOOK STOP CAVE CAVEORG BSR0 BSR1
//                           PATCHED(0/1) MODE INC IN.raw OUT.raw
//   IN/OUT: interleaved stereo int32 holding 24-bit samples.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include "dsp56kEmu/dsp.h"
#include "dsp56kEmu/memory.h"
#include "dsp56kEmu/peripherals.h"

using namespace dsp56k;

namespace
{
struct AllowAll : IMemoryValidator
{
	bool memValidateAccess(EMemArea, TWord, bool) const override { return true; }
};

std::vector<uint32_t> load24(const char* path)
{
	std::ifstream in(path, std::ios::binary);
	std::vector<uint8_t> b((std::istreambuf_iterator<char>(in)), {});
	std::vector<uint32_t> w;
	for(size_t i = 0; i + 2 < b.size(); i += 3)
		w.push_back(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16));
	return w;
}

constexpr uint32_t RING = 0x2000, OUT = 0x3000, TAB = 0x80, PRELUDE = 0xf00;
constexpr uint32_t BLOCK = 24;          // (BLOCK-1)*2 + 1 frames must fit 64
}

int main(int argc, char** argv)
{
	if(argc != 14) { std::printf("usage: see header\n"); return 2; }
	auto hx = [](const char* s) { return uint32_t(std::stoul(s, nullptr, 16)); };
	const auto mod = load24(argv[1]);
	const uint32_t modBase = hx(argv[2]), hook = hx(argv[3]), stop = hx(argv[4]);
	const auto cave = load24(argv[5]);
	const uint32_t caveOrg = hx(argv[6]), bsr0 = hx(argv[7]), bsr1 = hx(argv[8]);
	const bool patched = std::stoi(argv[9]) != 0;
	const uint32_t mode = uint32_t(std::stoi(argv[10]));
	const double inc = std::stod(argv[11]);
	if(inc <= 0 || inc > 2.0) { std::printf("inc must be in (0, 2]\n"); return 2; }

	std::ifstream in(argv[12], std::ios::binary);
	std::vector<int32_t> src;
	int32_t v;
	while(in.read(reinterpret_cast<char*>(&v), 4)) src.push_back(v);
	const size_t frames = src.size() / 2;

	AllowAll val;
	Memory mem(val, 0x080000, 0x800000, 0x200000);
	Peripherals56362 px;
	Peripherals56367 py;
	DSP dsp(mem, &px, &py);
	for(size_t i = 0; i < mod.size(); ++i) dsp.memWriteP(modBase + TWord(i), mod[i]);
	if(patched) {
		dsp.memWriteP(hook, bsr0);
		dsp.memWriteP(hook + 1, bsr1);
		for(size_t i = 0; i < cave.size(); ++i) dsp.memWriteP(caveOrg + TWord(i), cave[i]);
	}
	dsp.memWriteP(PRELUDE, 0x057fa6);              // move #$7f,m6 (see the probe)
	dsp.memWriteP(PRELUDE + 1, 0x0c0000 | hook);   // jmp hook

	auto s24 = [&](size_t frame, int ch) -> uint32_t {
		if(frame >= frames) return 0;
		return uint32_t(src[2 * frame + ch]) & 0xffffff;
	};

	std::vector<int32_t> out;
	double pos = 0.0;
	while(true) {
		const size_t kb = size_t(std::floor(pos));
		if(kb + 2 >= frames) break;
		// ring: 64 consecutive stereo frames from kb
		for(uint32_t j = 0; j < 64; ++j) {
			mem.set(MemArea_X, RING + 2 * j, s24(kb + j, 0));
			mem.set(MemArea_X, RING + 2 * j + 1, s24(kb + j, 1));
		}
		// per-output table, as P:0x3fc..0x40a lays it out
		for(uint32_t i = 0; i < BLOCK; ++i) {
			const double p = pos + i * inc;
			const size_t k = size_t(std::floor(p));
			const double f = p - double(k);
			mem.set(MemArea_X, TAB + i, uint32_t(2 * (k - kb)) & 0x7e);
			mem.set(MemArea_Y, TAB + i, uint32_t(f * 16777216.0) & 0xffffff);
		}
		mem.set(MemArea_Y, 0x40, mode & 3);
		auto& R = dsp.regs();
		R.r[2].var = RING; R.r[6].var = RING;
		R.r[3].var = OUT; R.r[5].var = TAB; R.r[7].var = BLOCK;
		dsp.setPC(PRELUDE);
		unsigned steps = 0;
		while(dsp.getPC().toWord() != stop && steps++ < 200000) dsp.execInterpreter();
		if(dsp.getPC().toWord() != stop) { std::printf("block did not finish\n"); return 1; }
		for(uint32_t i = 0; i < 2 * BLOCK; ++i) {
			uint32_t w = mem.get(MemArea_X, OUT + i) & 0xffffff;
			out.push_back(int32_t(w << 8) >> 8);      // sign-extend 24 -> 32
		}
		pos += BLOCK * inc;
	}
	std::ofstream o(argv[13], std::ios::binary);
	o.write(reinterpret_cast<const char*>(out.data()), std::streamsize(out.size() * 4));
	std::printf("rendered %zu frames\n", out.size() / 2);
	return 0;
}

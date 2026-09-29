// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// repitch-kyoti rev 11 (rev 14: two visits per frame, the trig flag, the AMP
// level, X-memory tables): run the BUILT DSP cave (virtual sampler) inside the
// real stock voice-engine module on dsp56kEmu, frame after frame, the way the
// firmware drives it (measured in ot_emu, NOTES Sessions 110 and 112):
//   * a 64-frame stereo ring at X:RING (128-aligned), appended to, never reset
//   * per 16-sample frame one pass: table x/y:$80+i = (ring word offset,
//     fraction Q24), r7 = 16, l:$40 = the increment (mode in y:$40 bits 0-1),
//     x:$418 = the track offset
//   * Y persists across passes (the engine's state and tables live there)
//   * rev 14: each frame visits the hook TWICE (the voice module's do #2): k
//     outputs, then 16-k (k = the frame's split); x:$419 -> a record whose
//     word +$1E carries the trig flag (bit 12), x:$20a -> an AMP state block
//     whose +8 is the level. RK_SCHED = a file of per-frame "k flags level"
//     (hex); RK_XDATA = a file of "addr word" (hex) loaded into X (the tables)
// Driven by tools/repitch_dsp_engine_check.py, which compares the output with
// tools/repitch_engine_model.py.
//
// usage: repitch_dsp_engine_probe MOD MODBASE HOOK STOP CAVE CAVEORG BSR0 BSR1
//                                 MODE RINT RFRAC TRACKOFF IN.raw OUT.raw [COUNT.txt]
//   RINT/RFRAC: the increment's integer part and 24-bit fraction (hex)
//   IN/OUT: interleaved stereo int32 holding 24-bit samples.
//   COUNT.txt (optional): instructions per pass, one per line.
#include <cmath>
#include <cstdlib>
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

constexpr uint32_t RING = 0x1e00, OUT = 0x0000, TAB = 0x80, PRELUDE = 0xf00, REC = 0x25d, AMP = 0x6000;
constexpr uint32_t BLOCK = 16;
}

int main(int argc, char** argv)
{
	if(argc != 15 && argc != 16) { std::printf("usage: see header\n"); return 2; }
	auto hx = [](const char* s) { return uint32_t(std::stoul(s, nullptr, 16)); };
	const auto mod = load24(argv[1]);
	const uint32_t modBase = hx(argv[2]), hook = hx(argv[3]), stop = hx(argv[4]);
	const auto cave = load24(argv[5]);
	const uint32_t caveOrg = hx(argv[6]), bsr0 = hx(argv[7]), bsr1 = hx(argv[8]);
	const uint32_t mode = hx(argv[9]), rint = hx(argv[10]), rfrac = hx(argv[11]) & 0xffffff;
	const uint32_t trk = hx(argv[12]);

	std::ifstream in(argv[13], std::ios::binary);
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
	dsp.memWriteP(hook, bsr0);
	dsp.memWriteP(hook + 1, bsr1);
	for(size_t i = 0; i < cave.size(); ++i) dsp.memWriteP(caveOrg + TWord(i), cave[i]);
	dsp.memWriteP(PRELUDE, 0x057fa6);              // move #$7f,m6 (a poked m6 is ignored)
	dsp.memWriteP(PRELUDE + 1, 0x0c0000 | hook);   // jmp hook
	// Y starts dirty, as hardware's does after a reflash: the engine must not trust it
	uint32_t seed = 0x2545f491u;
	for(uint32_t a = 0x800; a < 0x1000; ++a) { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; mem.set(MemArea_Y, a, seed & 0xffffff); }

	if(const char* xd = std::getenv("RK_XDATA")) {
		std::ifstream xf(xd);
		unsigned a, w;
		while(xf >> std::hex >> a >> w) mem.set(MemArea_X, a, w & 0xffffff);
		if(std::getenv("RK_XPEEK")) { const uint32_t a0 = std::strtoul(std::getenv("RK_XPEEK"), nullptr, 16); std::printf("xpeek after load %05x: %06x %06x %06x\n", a0, mem.get(MemArea_X, a0) & 0xffffff, mem.get(MemArea_X, a0 + 1) & 0xffffff, mem.get(MemArea_X, a0 + 2) & 0xffffff); }
	}
	struct Sched { uint32_t k, flags, level; };
	std::vector<Sched> sched;
	if(const char* sp = std::getenv("RK_SCHED")) {
		std::ifstream sf(sp);
		unsigned k, f, l;
		while(sf >> std::hex >> k >> f >> l) sched.push_back({k, f, l});
	}

	// 24.24 with the mode in bits 0-1: the stock table builder accumulates exactly
	// this (l:$40 via `add x,a`), so the tag is part of the OT's own position
	const uint64_t incEff = (uint64_t(rint) << 24) | ((rfrac & ~3u) | (mode & 3));
	std::vector<int32_t> out;
	std::vector<uint64_t> counts;
	uint64_t pos = 0;                                       // source position, 24.24
	size_t written = 0;
	while(true) {
		// The firmware delivers frames up to floor(p_last), and the one after only
		// when that fraction is nonzero (measured). Deliver exactly that, and POISON
		// the next frames: any read of an undelivered frame shows up as noise.
		// (floor(p_last)+1 IS delivered when that fraction is nonzero: the stock
		// kernel weights it by the fraction. RPCH needs it; our engine never reads it.)
		const uint64_t last = pos + (BLOCK - 1) * incEff;
		const size_t need = size_t(last >> 24) + 1 + ((last & 0xffffff) ? 1 : 0);
		if(need + 1 > frames) break;
		for(; written < need; ++written) {
			mem.set(MemArea_X, RING + 2 * (written % 64), uint32_t(src[2 * written]) & 0xffffff);
			mem.set(MemArea_X, RING + 2 * (written % 64) + 1, uint32_t(src[2 * written + 1]) & 0xffffff);
		}
		for(size_t j = need; j < need + 8; ++j) {
			seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
			mem.set(MemArea_X, RING + 2 * (j % 64), seed & 0xffffff);
			mem.set(MemArea_X, RING + 2 * (j % 64) + 1, (seed >> 7) & 0xffffff);
		}
		const size_t fr = counts.size();
		const Sched sc = fr < sched.size() ? sched[fr] : Sched{0, 0, 0};
		// RK_MODE_SWITCH=N: frames N..2N-1 run in RPCH (mode 0), as a user switching away and back
		static const int sw = std::getenv("RK_MODE_SWITCH") ? std::atoi(std::getenv("RK_MODE_SWITCH")) : 0;
		const uint32_t pm = (sw && fr >= size_t(sw) && fr < size_t(2 * sw)) ? 0 : mode;
		uint64_t frameCount = 0;
		auto& R = dsp.regs();
		R.r[3].var = OUT;
		for(int visit = 0; visit < 2; ++visit) {
			const uint32_t i0 = visit ? sc.k : 0, i1 = visit ? BLOCK : sc.k;
			for(uint32_t i = i0; i < i1; ++i) {
				const uint64_t p = pos + i * incEff;
				mem.set(MemArea_X, TAB + i - i0, uint32_t(2 * ((p >> 24) % 64)));
				mem.set(MemArea_Y, TAB + i - i0, uint32_t(p & 0xffffff));
			}
			mem.set(MemArea_X, 0x40, rint | 0xc0);        // the unit's x:$40 carries $c0 above the integer part (measured)
			mem.set(MemArea_Y, 0x40, (rfrac & ~3u) | (pm & 3));
			mem.set(MemArea_X, 0x418, trk);
			mem.set(MemArea_X, 0x419, REC);
			mem.set(MemArea_X, REC + 0x1e, sc.flags & 0xffffff);
			mem.set(MemArea_X, 0x20a, AMP);
			mem.set(MemArea_X, AMP + 8, sc.level & 0xffffff);
			const uint32_t r3in = R.r[3].var & 0xffffff;
			R.r[2].var = RING; R.r[6].var = RING;
			R.r[5].var = TAB; R.r[7].var = i1 - i0;
			R.r[0].var = 0x5555;   // live in the firmware: must come back untouched
			dsp.setPC(PRELUDE);
			const uint64_t before = dsp.getInstructionCounter();
			unsigned steps = 0;
			while(dsp.getPC().toWord() != stop && steps++ < 400000) dsp.execInterpreter();
			if(dsp.getPC().toWord() != stop) { std::printf("pass did not finish (pc %06x)\n", dsp.getPC().toWord()); return 1; }
			frameCount += dsp.getInstructionCounter() - before;
			if((R.r[0].var & 0xffffff) != 0x5555) { std::printf("r0 clobbered\n"); return 1; }
			if((R.r[3].var & 0xffffff) != r3in + 2 * (i1 - i0)) { std::printf("r3 = %06x, want %06x\n", R.r[3].var & 0xffffff, r3in + 2 * (i1 - i0)); return 1; }
			if(std::getenv("RK_AUX")) {
				static FILE* af = std::fopen(std::getenv("RK_AUX"), "w");
				for(uint32_t k = 0; k < 12; ++k) std::fprintf(af, "%06x ", mem.get(MemArea_Y, 0xf50 + trk / 2 + k) & 0xffffff);
				std::fprintf(af, "\n");
			}
			for(int k = 0; k < 8; ++k)
				if(k != 6 && (R.m[k].var & 0xffffff) != 0xffffff) { std::printf("m%d left at %06x\n", k, R.m[k].var & 0xffffff); return 1; }
		}
		counts.push_back(frameCount);
		if(std::getenv("RK_STATE")) {
			static FILE* sf = std::fopen(std::getenv("RK_STATE"), "w");
			for(uint32_t k = 0; k < 10; ++k) std::fprintf(sf, "%06x ", mem.get(MemArea_Y, 0xa00 + trk + k) & 0xffffff);
			std::fprintf(sf, "\n");
		}
		for(uint32_t i = 0; i < 2 * BLOCK; ++i) {
			uint32_t w = mem.get(MemArea_X, OUT + i) & 0xffffff;
			out.push_back(int32_t(w << 8) >> 8);
		}
		pos += BLOCK * incEff;
	}
	if(std::getenv("RK_XPEEK")) { const uint32_t a0 = std::strtoul(std::getenv("RK_XPEEK"), nullptr, 16); std::printf("xpeek at end %05x: %06x %06x %06x\n", a0, mem.get(MemArea_X, a0) & 0xffffff, mem.get(MemArea_X, a0 + 1) & 0xffffff, mem.get(MemArea_X, a0 + 2) & 0xffffff); }
	std::ofstream o(argv[14], std::ios::binary);
	o.write(reinterpret_cast<const char*>(out.data()), std::streamsize(out.size() * 4));
	if(argc == 16) {
		std::ofstream c(argv[15]);
		for(auto n : counts) c << n << "\n";
	}
	std::printf("rendered %zu frames in %zu frames of two visits\n", out.size() / 2, counts.size());
	return 0;
}

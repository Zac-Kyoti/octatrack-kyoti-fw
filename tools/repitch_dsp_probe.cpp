// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// SUPERSEDED (Session 110, rev 11): tests rev 10's kernel contracts; the rev-11
// engine is checked by tools/repitch_dsp_engine_probe.cpp + _engine_check.py.
//
// repitch-kyoti DSP oracle: the REAL stock voice-engine kernel, run from its
// prologue hook site to the per-voice loop's closing NOP, unpatched and
// patched, on dsp56kEmu. Built and driven by tools/repitch_dsp_check.py.
//
// The reference is never a hand model of DSP arithmetic -- it is stock itself
// run on transformed input:
//   RPCH (mode 0)  patched                == stock
//   RPS9 (mode 1)  patched                == stock on the 12-bit ring
//   RPSP (mode 2)  patched                == stock on the 12-bit ring with
//                                            every fraction zeroed
//   RPSP, and independently of the kernel: out = q12(L0), q12(R0) per entry
// plus the side effects (ring, fraction table) and the registers the outer
// per-voice loop relies on afterwards (r0 r2 r3 r4 r5 r7 m6, and the stack).
//
// usage: repitch_dsp_probe MOD.bin MODBASE HOOK STOP CAVE.bin CAVEORG BSR0 BSR1
//        (all numbers hex). Exit 0 iff every case passes.
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

constexpr uint32_t RING = 0x2000, OUT = 0x3000, TAB = 0x80, MASK12 = 0xfff000;

struct Image
{
	std::vector<uint32_t> mod, cave;
	uint32_t modBase, hook, stop, caveOrg, bsr0, bsr1;
};

struct Case
{
	const char* name;
	uint32_t n;
	uint32_t incFrac;               // y:$40 -- mode in bits 0-1
	std::vector<uint32_t> ring, offs, fracs;
};

struct Result
{
	bool ran = false;
	std::vector<uint32_t> out, ring, fracs;
	uint32_t r[8]{}, m6 = 0, sp = 0;
};

Result run(const Image& im, bool patched, const Case& c)
{
	AllowAll v;
	Memory mem(v, 0x080000, 0x800000, 0x200000);
	Peripherals56362 px;
	Peripherals56367 py;
	DSP dsp(mem, &px, &py);

	for(size_t i = 0; i < im.mod.size(); ++i) dsp.memWriteP(im.modBase + TWord(i), im.mod[i]);
	if(patched) {
		dsp.memWriteP(im.hook, im.bsr0);
		dsp.memWriteP(im.hook + 1, im.bsr1);
		for(size_t i = 0; i < im.cave.size(); ++i) dsp.memWriteP(im.caveOrg + TWord(i), im.cave[i]);
	}
	for(uint32_t i = 0; i < 128; ++i) mem.set(MemArea_X, RING + i, c.ring[i]);
	for(uint32_t i = 0; i < c.n; ++i) {
		mem.set(MemArea_X, TAB + i, c.offs[i]);
		mem.set(MemArea_Y, TAB + i, c.fracs[i]);
	}
	mem.set(MemArea_X, 0x40, 0x000001);           // integer part: irrelevant here
	mem.set(MemArea_Y, 0x40, c.incFrac);
	for(uint32_t i = 0; i < 2 * c.n + 8; ++i) mem.set(MemArea_X, OUT + i, 0x5a5a5a);

	auto& R = dsp.regs();
	for(int k = 0; k < 8; ++k) R.n[k].var = 0;
	R.r[0].var = 0x000111; R.r[1].var = 0x000222; R.r[4].var = 0x000444;
	R.r[2].var = RING; R.r[6].var = RING;
	R.r[3].var = OUT; R.r[5].var = TAB; R.r[7].var = c.n;

	// m6 is set by EXECUTING stock's own `move #$7f,m6` (057fa6, P:0x3a9),
	// then a short jmp to the hook site: poking R.m[6] directly does not
	// reach the emulator's cached address-generation mode, and a ring that
	// silently stops wrapping fails RPS9/RPSP while RPCH still "passes"
	// (both sides read the same wrong words).
	constexpr TWord PRELUDE = 0xf00;
	dsp.memWriteP(PRELUDE, 0x057fa6);
	dsp.memWriteP(PRELUDE + 1, 0x0c0000 | im.hook);
	dsp.setPC(PRELUDE);
	for(unsigned steps = 0; steps < 200000; ++steps) {
		if(dsp.getPC().toWord() == im.stop) { break; }
		dsp.execInterpreter();
	}
	Result res;
	res.ran = dsp.getPC().toWord() == im.stop;
	for(uint32_t i = 0; i < 2 * c.n; ++i) res.out.push_back(mem.get(MemArea_X, OUT + i));
	for(uint32_t i = 0; i < 128; ++i) res.ring.push_back(mem.get(MemArea_X, RING + i));
	for(uint32_t i = 0; i < c.n; ++i) res.fracs.push_back(mem.get(MemArea_Y, TAB + i));
	for(int k = 0; k < 8; ++k) res.r[k] = R.r[k].var & 0xffffff;
	res.m6 = R.m[6].var & 0xffffff;
	res.sp = R.sp.var & 0xffffff;
	return res;
}

bool regsMatch(const Result& a, const Result& b)
{
	// r1 is scratch here (RPSP walks it; stock resets it at P:0x3f9 before
	// its next use), and r6 is set by the kernel's own last sample -- the
	// rest are what the outer per-voice loop carries into the next voice.
	for(int k : {0, 2, 3, 4, 5, 7})
		if(a.r[k] != b.r[k]) return false;
	return a.m6 == b.m6 && a.sp == b.sp;
}

int fails = 0;
void check(const char* what, bool ok)
{
	fails += !ok;
	std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", what);
}

uint32_t lcg = 0x1234567;
uint32_t rnd24() { lcg = lcg * 1103515245u + 12345u; return (lcg >> 4) & 0xffffff; }
}

int main(int argc, char** argv)
{
	if(argc != 9) { std::printf("usage: %s MOD MODBASE HOOK STOP CAVE CAVEORG BSR0 BSR1\n", argv[0]); return 2; }
	auto hx = [](const char* s) { return uint32_t(std::stoul(s, nullptr, 16)); };
	Image im;
	im.mod = load24(argv[1]);
	im.modBase = hx(argv[2]); im.hook = hx(argv[3]); im.stop = hx(argv[4]);
	im.cave = load24(argv[5]);
	im.caveOrg = hx(argv[6]); im.bsr0 = hx(argv[7]); im.bsr1 = hx(argv[8]);
	std::printf("module %zu words @P:%05x, hook %05x, stop %05x, cave %zu words @P:%05x\n",
	            im.mod.size(), im.modBase, im.hook, im.stop, im.cave.size(), im.caveOrg);

	// the hook site must hold exactly the displaced pair before patching
	const uint32_t hi = im.hook - im.modBase;
	check("hook site holds the displaced pair (move x:(r5),n6 / move y:(r5)+,a)",
	      im.mod[hi] == 0x76e500 && im.mod[hi + 1] == 0x5edd00);
	check("stop site is the per-voice loop's closing NOP", im.mod[im.stop - im.modBase] == 0x000000);

	std::vector<Case> cases;
	for(uint32_t n : {1u, 5u, 64u})
		for(uint32_t mode : {0u, 1u, 2u}) {
			Case c;
			c.n = n;
			// high fraction bits deliberately busy: only bits 0-1 may matter
			c.incFrac = (rnd24() & ~3u) | mode;
			for(int i = 0; i < 128; ++i) c.ring.push_back(rnd24());   // incl. negatives
			for(uint32_t i = 0; i < n; ++i) {
				// even word offsets; force a wrap case (0x7e -> reads 0x7e,0x7f,0x00,0x01)
				uint32_t off = (i == 0) ? 0x7e : (rnd24() & 0x7e);
				c.offs.push_back(off);
				c.fracs.push_back(rnd24());
			}
			static char names[9][48];
			static int k = 0;
			std::snprintf(names[k], sizeof names[k], "n=%-2u mode %u (%s)", n, mode,
			              mode == 0 ? "RPCH" : mode == 1 ? "RPS9" : "RPSP");
			c.name = names[k++];
			cases.push_back(c);
		}

	for(const auto& c : cases) {
		const Result stockRun = run(im, false, c);
		const Result pat = run(im, true, c);

		Case ref = c;                      // stock on the transformed input
		const uint32_t mode = c.incFrac & 3;
		if(mode) for(auto& s : ref.ring) s &= MASK12;
		if(mode == 2) for(auto& f : ref.fracs) f = 0;
		const Result want = mode ? run(im, false, ref) : stockRun;

		std::string why;
		auto need = [&](bool cond, const char* what) { if(!cond && why.empty()) why = what; };
		need(stockRun.ran && pat.ran && want.ran, "a run did not reach the stop NOP");
		need(pat.out == want.out, "output != stock on the transformed input");
		need(regsMatch(pat, want), "carried registers / stack differ");
		need(pat.ring == ref.ring, "ring not transformed as specified");
		need(pat.fracs == ref.fracs, "fraction table not transformed as specified");
		if(mode == 2)                      // exact ZOH of 12-bit samples, kernel-independent
			for(uint32_t i = 0; i < c.n; ++i) {
				const uint32_t o = c.offs[i];
				need(pat.out[2 * i] == (c.ring[o & 0x7f] & MASK12), "RPSP L != q12(L0)");
				need(pat.out[2 * i + 1] == (c.ring[(o + 1) & 0x7f] & MASK12), "RPSP R != q12(R0)");
			}
		if(mode == 0)                      // RPCH must BE stock, not just match a reference
			need(pat.out == stockRun.out && pat.ring == c.ring && pat.fracs == c.fracs, "RPCH != stock");
		if(mode == 1)
			need(pat.out != stockRun.out, "RPS9 changed nothing");
		if(!why.empty()) {
			std::printf("      %s -- r6 stock %06x patched %06x\n", why.c_str(), stockRun.r[6], pat.r[6]);
			if(!pat.out.empty())
				std::printf("      out[0..1] patched %06x %06x  want %06x %06x\n",
				            pat.out[0], pat.out.size() > 1 ? pat.out[1] : 0,
				            want.out[0], want.out.size() > 1 ? want.out[1] : 0);
		}
		check(c.name, why.empty());
	}

	std::printf("%d failure(s)\n", fails);
	return fails ? 1 : 0;
}

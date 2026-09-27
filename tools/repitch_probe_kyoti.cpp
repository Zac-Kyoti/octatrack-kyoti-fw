// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// repitch-kyoti gate-1 oracle: the patched image's increment builder and
// TSTR resolver run through the firmware's own code on ot::Machine, against
// (a) the STOCK image case-for-case for every non-repitch path, and (b) an
// independent C model of the QUANT/fold/tag semantics for the repitch paths.
//
// Scaffold ported from refs/octabam/tools/harness/repitch_probe.cpp (MIT,
// Sam Banks); the expectations are this module's own (RPS9/RPSP, QUANT,
// integer-domain octave fold, INC_MAX-4 ceiling, 2-bit mode tag).
//
// Build (links refs/octabam's PREBUILT libs; rebuilds nothing there):
//   c++ -std=c++17 -O1 -I refs/octabam/tools/emu/ot_emu -I refs/octabam/vendor \
//       -I refs/octabam/vendor/dsp56300/source tools/repitch_probe_kyoti.cpp \
//       refs/octabam/out/emu/libot_machine.a refs/octabam/out/emu/mc68k/lib68kEmu.a \
//       refs/octabam/out/emu/dsp56300/dsp56kEmu/libdsp56kEmu.a \
//       refs/octabam/out/emu/dsp56300/dsp56kBase/libdsp56kBase.a \
//       refs/octabam/out/emu/dsp56300/asmjit/libasmjit.a \
//       -o out/repitch_probe_kyoti
// Run from the repo root:
//   out/repitch_probe_kyoti out/raw/section_3_MAIN_OS.bin out/mainos_repitch_kyoti.bin \
//       [quant_widget_addr rp_ui_gate_addr]   (hex; from m68k-elf-nm, enables 6+7)
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include "machine.h"
#include "mc68k/Musashi/m68k.h"
#include "mc68k/cpuState.h"

namespace
{
constexpr uint32_t lanes = 0x80000510, voices = 0x800049d8, states = 0x80004898;
constexpr uint32_t curState = 0x800062a4, projectTempo = 0x8000181c;
constexpr uint32_t trampoline = 0x47000000, stack = 0x47100000, settings = 0x47200000;
constexpr uint32_t INC_MAX = 0x08000000;

struct Img
{
	std::vector<uint8_t> image;

	static bool runTo(ot::Machine& m, uint32_t site, uint32_t until, unsigned budget = 600)
	{
		const uint8_t code[] = {0xa9, 0x3c, 0x00, 0x00, 0x00, 0x20, 0x4e, 0xf9,
			uint8_t(site >> 24), uint8_t(site >> 16), uint8_t(site >> 8), uint8_t(site)};
		for(unsigned i = 0; i < sizeof(code); ++i)
			m.write8(trampoline + i, code[i]);
		m68k_set_reg(m.getCpuState(), M68K_REG_PC, trampoline);
		unsigned steps = 0;
		while(m.pc() != until && steps++ < budget)
			if(!m.step()) return false;
		return m.pc() == until;
	}

	struct Rate { unsigned track, tstr, tsmode, source, project; uint16_t ptch, rate; uint8_t machine = 1; };

	uint32_t increment(const Rate& r, bool& ok, uint32_t rkAddr = 0, unsigned idx = 0) const
	{
		ot::Machine m(image);
		auto* cpu = m.getCpuState();
		const uint32_t state = states + 40 * r.track, lane = lanes + 48 * r.track;
		if(rkAddr) m.write8(rkAddr, uint8_t(idx));
		m.write32(curState, state);
		m.write32(stack + 64, 0x10);
		m.write16(lane, r.ptch);
		m.write16(lane + 6, r.rate);
		m.write16(lane + 10, 0);
		m.write8(lane + 27, 0);
		m.write8(lane + 28, uint8_t(r.tstr));
		m.write32(voices + 168 * r.track + 8, settings);
		m.write8(voices + 168 * r.track + 20, r.machine);
		m.write32(settings + 0x110, r.tsmode);
		m.write32(settings + 0x114, r.source);
		m.write32(projectTempo, r.project);
		m68k_set_reg(cpu, M68K_REG_A3, state);
		m68k_set_reg(cpu, M68K_REG_A6, lane);
		m68k_set_reg(cpu, M68K_REG_D5, 26);
		m68k_set_reg(cpu, M68K_REG_SP, stack);
		ok &= runTo(m, 0x4000406a, 0x40004108) && m68k_get_reg(cpu, M68K_REG_SP) == stack;
		return m.read32(state + 36);
	}

	struct Resolved { uint8_t stored; uint32_t loopStart; uint32_t regs[16]; bool ok;
		bool operator==(const Resolved& o) const {
			if(stored != o.stored || loopStart != o.loopStart || ok != o.ok) return false;
			for(int i = 0; i < 16; ++i) if(regs[i] != o.regs[i]) return false;
			return true;
		} };
	Resolved resolve(uint32_t value, uint8_t machine, uint8_t previous) const
	{
		ot::Machine m(image);
		auto* cpu = m.getCpuState();
		constexpr uint32_t voice = 0x47006000, frame = 0x47008000;
		m.write8(voice + 20, machine);
		m.write8(voice + 24, previous);
		m.write32(voice + 64, 0x11111111);
		m.write32(voice + 68, 0x22222222);
		m68k_set_reg(cpu, M68K_REG_D1, value);
		m68k_set_reg(cpu, M68K_REG_D0, 0x89abcdef);
		m68k_set_reg(cpu, M68K_REG_D2, 0x13579bdf);
		m68k_set_reg(cpu, M68K_REG_D3, 0x2468ace0);
		m68k_set_reg(cpu, M68K_REG_A0, 0x47010000);
		m68k_set_reg(cpu, M68K_REG_A1, 0x47020000);
		m68k_set_reg(cpu, M68K_REG_A2, voice);
		m68k_set_reg(cpu, M68K_REG_A6, frame);
		m68k_set_reg(cpu, M68K_REG_SP, stack);
		m68k_set_reg(cpu, M68K_REG_PC, 0x40007d96);
		unsigned steps = 0;
		while(m.pc() != 0x40007dc0 && steps++ < 60)
			if(!m.step()) break;
		Resolved r{m.read8(voice + 24), m.read32(voice + 64), {}, m.pc() == 0x40007dc0};
		for(int i = 0; i < 16; ++i)
			r.regs[i] = m68k_get_reg(cpu, m68k_register_t(M68K_REG_D0 + i));
		return r;
	}
};

// ---- the independent model of gate 1's semantics --------------------------
const unsigned RP[8] = {1, 2, 3, 1, 5, 4, 3, 2}, RQ[8] = {2, 3, 4, 1, 4, 3, 2, 1};
unsigned bucket(unsigned ui) { unsigned d = ui > 12 ? ui - 12 : 0; d /= 15; return d > 7 ? 7 : d; }
uint32_t model(uint32_t neutralInc, unsigned proj, unsigned samp, unsigned idx, unsigned modeoff)
{
	uint64_t N = uint64_t(proj) * RP[idx], D = uint64_t(samp) * RQ[idx];
	while(N > 2 * D) D <<= 1;
	uint64_t inc = (neutralInc / D) * N + (neutralInc % D) * N / D;
	if(inc > INC_MAX - 4) inc = INC_MAX - 4;
	return uint32_t((inc & ~3ull) | modeoff);
}

int fails = 0;
void check(const char* what, bool ok, int detail = -1)
{
	fails += !ok;
	if(!ok && detail >= 0) std::printf("  [FAIL] %s (case %d)\n", what, detail);
	else std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", what);
}
}

int main(int argc, char** argv)
{
	if(argc != 3 && argc != 6) { std::printf("usage: %s STOCK PATCHED [quant_widget rp_ui_gate rk_quan]\n", argv[0]); return 2; }
	Img stock, pat;
	for(auto [img, path] : {std::pair{&stock, argv[1]}, {&pat, argv[2]}}) {
		std::ifstream in(path, std::ios::binary);
		if(!in) { std::printf("missing %s\n", path); return 2; }
		img->image.assign(std::istreambuf_iterator<char>(in), {});
	}
	std::printf("repitch-kyoti gate-1 contracts (%zu / %zu bytes):\n",
	            stock.image.size(), pat.image.size());

	const uint32_t rkQuan = argc == 6 ? uint32_t(std::stoul(argv[5], nullptr, 16)) : 0;
	if(!rkQuan) std::printf("  (no rk_quan address: contracts 2 and 5 need all three symbols)\n");
	const unsigned projects[] = {720, 2160, 2880, 3600, 7200};
	const unsigned sources[] = {720, 1440, 2880, 4320, 7200};
	const uint16_t ptchs[] = {0x0400, 0x2200, 0x3400, 0x4000, 0x4800, 0x5800, 0x7c00};
	const uint16_t rates[] = {0x7f00, 0x3f00};

	// 1) feature-off purity: TSTR 0..3, both machines, every PTCH/RATE --
	//    the patched builder must be bit-identical to stock.
	{
		int bad = -1, n = 0;
		bool ok = true;
		for(unsigned tstr = 0; tstr <= 3; ++tstr)
			for(uint8_t mac : {uint8_t(1), uint8_t(4)})
				for(auto ptch : ptchs) for(auto rate : rates)
					for(auto proj : projects) {
						Img::Rate r{unsigned(n) % 8, tstr, 2, 2880, proj, ptch, rate, mac};
						bool oks = true, okp = true;
						const auto a = stock.increment(r, oks), b = pat.increment(r, okp);
						if(!(oks && okp && a == b) && bad < 0) bad = n;
						ok &= oks && okp && a == b;
						++n;
					}
		check("feature off: TSTR 0..3 increments bit-identical to stock", ok, bad);
		std::printf("      (%d cases)\n", n);
	}

	// 2) repitch family: SETUP 4/5/6 and AUTO carrying the sample's mode,
	//    the QUAN index from rk_quan[track] -- and the PTCH word must be
	//    IRRELEVANT: two different words give bit-identical increments.
	{
		int bad = -1, n = 0;
		bool ok = true;
		struct Sel { unsigned tstr, tsmode, modeoff; };
		const Sel sels[] = {{4, 2, 0}, {5, 2, 1}, {6, 2, 2},
		                    {1, 4, 0}, {1, 5, 1}, {1, 6, 2}};
		for(auto sel : sels)
			for(auto proj : projects) for(auto samp : sources)
				for(unsigned idx = 0; idx < 8; ++idx) {
					Img::Rate rNeut{2, 0, 2, samp, proj, 0x4000, 0x7f00, 1};
					bool oks = true, okA = true, okB = true;
					const auto neutral = stock.increment(rNeut, oks);
					Img::Rate rT{2, sel.tstr, sel.tsmode, samp, proj, 0x4800, 0x7f00, 1};
					const auto a = pat.increment(rT, okA, rkQuan + 2, idx);
					rT.ptch = 0x2200;
					const auto b = pat.increment(rT, okB, rkQuan + 2, idx);
					const auto want = model(neutral, proj, samp, idx, sel.modeoff);
					if(!(oks && okA && okB && a == want && b == a) && bad < 0) {
						bad = n;
						std::printf("      first divergence: tstr%u idx%u proj%u samp%u: got %08x/%08x want %08x\n",
						            sel.tstr, idx, proj, samp, a, b, want);
					}
					ok &= oks && okA && okB && a == want && b == a;
					++n;
				}
		check("repitch family: rk_quan drives the ratio; the PTCH word is irrelevant", ok, bad);
		std::printf("      (%d cases x 2 words)\n", n);
	}

	// 3) the guards: PICKUP, out-of-range sample tempo, TSMODE 4 without AUTO
	//    -- all identical to stock.
	{
		bool ok = true;
		int bad = -1, n = 0;
		const Img::Rate guards[] = {
			{1, 4, 2, 2880, 2880, 0x4800, 0x7f00, 4},   // PICKUP keeps grains
			{1, 5, 2, 2880, 2880, 0x4800, 0x7f00, 4},
			{1, 4, 2, 600, 2880, 0x4800, 0x7f00, 1},    // sample tempo below range
			{1, 6, 2, 7300, 2880, 0x4800, 0x7f00, 1},   // above range
			{1, 0, 4, 2880, 2160, 0x4800, 0x7f00, 1},   // TSMODE 4 but SETUP OFF
			{1, 2, 4, 2880, 2160, 0x4800, 0x7f00, 1},   // ... NORM
			{1, 0, 5, 2880, 2160, 0x4800, 0x7f00, 1},   // TSMODE 5/6 without AUTO
			{1, 3, 6, 2880, 2160, 0x4800, 0x7f00, 1},   // ... BEAT
		};
		for(const auto& g : guards) {
			bool oks = true, okp = true;
			const auto a = stock.increment(g, oks), b = pat.increment(g, okp);
			if(!(oks && okp && a == b) && bad < 0) bad = n;
			ok &= oks && okp && a == b;
			++n;
		}
		check("guards: PICKUP / tempo out of range / TSMODE without AUTO stay stock", ok, bad);
	}

	// 4) the resolver: patched values 4/5/6 must equal stock GIVEN 0,
	//    register for register; 0..3 must equal stock given the same value.
	{
		bool ok = true;
		for(uint32_t v = 0; v <= 6; ++v)
			for(uint8_t mac : {uint8_t(1), uint8_t(4)})
				for(uint8_t prev : {uint8_t(0), uint8_t(2)}) {
					const auto want = stock.resolve(v >= 4 ? 0 : v, mac, prev);
					const auto got = pat.resolve(v, mac, prev);
					ok &= want.ok && got.ok && got == want;
				}
		check("resolver: 4/5/6 behave as OFF register-for-register; 0..3 untouched", ok);
	}

	// 5) quant_edit at 0x40055008: on the PLAYBACK page, slot 0, QUAN in
	//    force, the delta edits rk_quan (clamped) and stock's body is never
	//    entered; anything else falls through to the displaced frame.
	{
		bool ok = true;
		int bad = -1, n = 0;
		struct Ed { unsigned slot; int delta; unsigned setup; uint8_t q0, want; bool hook; };
		const Ed eds[] = {
			{0, +1, 4, 3, 4, true},
			{0, -1, 5, 4, 3, true},
			{0, +20, 6, 3, 7, true},
			{0, -20, 4, 5, 0, true},
			{1, +1, 4, 3, 3, false},   // another slot: stock
			{0, +1, 0, 3, 3, false},   // not a repitch mode: stock
		};
		for(const auto& e : eds) {
			ot::Machine m(pat.image);
			auto* cpu = m.getCpuState();
			const unsigned t = 2;
			m.write8(0x80000000, t);
			m.write32(0x80000012, 0);
			m.write32(0x800000e0, 0);
			m.write8(0x80000eb4 + t, 1);            // FLEX
			m.write8(0x8000082f + 72 * t, 5);       // slot 5
			const uint32_t set = 0x100b14f0 + 5 * 0x448;
			m.write32(set + 0x114, 2880);
			m.write32(set + 0x110, 2);
			m.write8(lanes + 48 * t + 28, uint8_t(e.setup));
			m.write8(rkQuan + t, e.q0);
			m.write8(0x80000810 + 72 * t, 0x55);    // live-byte canary
			m.write32(stack - 12, trampoline + 0x80);  // return sentinel
			m.write32(stack - 8, e.slot);
			m.write32(stack - 4, uint32_t(e.delta));
			for(unsigned i = 0; i < 8; i += 2) m.write16(trampoline + 0x80 + i, 0x4e71);
			m68k_set_reg(cpu, M68K_REG_SP, stack - 12);
			m68k_set_reg(cpu, M68K_REG_PC, 0x40055008);
			unsigned steps = 0;
			bool hooked = false, fell = false;
			while(steps++ < 400) {
				if(m.pc() == trampoline + 0x80) { hooked = true; break; }
				if(m.pc() == 0x40055010) { fell = true; break; }
				if(!m.step()) break;
			}
			bool good;
			if(e.hook)
				good = hooked && !fell && m.read8(rkQuan + t) == e.want &&
				       m.read8(0x80000810 + 72 * t) == 0x55 &&
				       m68k_get_reg(cpu, M68K_REG_SP) == stack - 8;   // rts popped the sentinel
			else
				good = fell && m.read8(rkQuan + t) == e.q0;
			if(!good && bad < 0) bad = n;
			ok &= good;
			++n;
		}
		check("quant_edit: hook edits rk_quan only; everything else reaches stock", ok, bad);
	}

	if(argc == 6) {
		const uint32_t quantWidget = uint32_t(std::stoul(argv[3], nullptr, 16));
		const uint32_t uiGate = uint32_t(std::stoul(argv[4], nullptr, 16));

		// 6) the four page-1 dial shims: resolve record+48 (knob when null),
		//    override with quant_widget exactly when record+0 is PTCH's
		//    formatter; d1..d7/a1..a6 preserved.
		{
			constexpr uint32_t PTCH_FMT = 0x4003b4b0, KNOB = 0x400479b4;
			struct Site { uint32_t at, ret; char rec; };
			const Site sitesTab[] = {{0x40036698, 0x400366a6, 4},
			                         {0x4003690c, 0x4003691a, 3},
			                         {0x4003786a, 0x40037878, 3},
			                         {0x40037c06, 0x40037c14, 3}};
			bool ok = true;
			int n = 0, bad = -1;
			for(const auto& st : sitesTab)
				for(uint32_t fmt : {PTCH_FMT, 0x4003b64cu})
					for(uint32_t wid : {0u, 0x12345678u}) {
						ot::Machine m(pat.image);
						auto* cpu = m.getCpuState();
						constexpr uint32_t rec = 0x47004000;
						m.write32(rec, fmt);
						m.write32(rec + 48, wid);
						const uint32_t seeds[8] = {0x11111111, 0x22222222, 0x33333333, 0x44444444,
						                           0x55555555, 0x66666666, 0x77777777, 0x88888888};
						for(int r = 1; r < 8; ++r) {
							m68k_set_reg(cpu, m68k_register_t(M68K_REG_D0 + r), seeds[r]);
							if(r != 7) m68k_set_reg(cpu, m68k_register_t(M68K_REG_A0 + r),
							                        r == st.rec ? rec : seeds[r]);
						}
						m68k_set_reg(cpu, M68K_REG_SP, stack);
						m68k_set_reg(cpu, M68K_REG_PC, st.at);
						unsigned steps = 0;
						while(m.pc() != st.ret && steps++ < 40)
							if(!m.step()) break;
						const uint32_t a0 = m68k_get_reg(cpu, M68K_REG_A0);
						const uint32_t wantA0 = fmt == PTCH_FMT ? quantWidget : (wid ? wid : KNOB);
						bool good = m.pc() == st.ret && a0 == wantA0 &&
						            m68k_get_reg(cpu, M68K_REG_SP) == stack;
						for(int r = 1; r < 8 && good; ++r) {
							good &= m68k_get_reg(cpu, m68k_register_t(M68K_REG_D0 + r)) == seeds[r];
							if(r != 7 && r != st.rec)
								good &= m68k_get_reg(cpu, m68k_register_t(M68K_REG_A0 + r)) == seeds[r];
						}
						if(!good && bad < 0) bad = n;
						ok &= good;
						++n;
					}
			check("dial shims: knob/record/quant resolution and register preservation", ok, bad);
			std::printf("      (%d cases across 4 sites)\n", n);
		}

		// 7) rp_ui_gate truth table -- resolved from the part/machine/slot
		//    tables and the settings arrays, no voice binding involved.
		{
			struct Case { uint8_t track, setup, machine, slot; uint32_t tsmode, bpm; int want; };
			const Case cases[] = {
				{2, 4, 0, 5, 2, 2880, 1},   // STATIC, RPCH, tempo fine
				{2, 5, 1, 7, 2, 2880, 1},   // FLEX, RPS9
				{2, 6, 1, 7, 2,  100, 0},   // tempo veto
				{2, 4, 4, 5, 2, 2880, 0},   // PICKUP machine never QUANTs
				{2, 4, 2, 5, 2, 2880, 0},   // THRU machine neither
				{2, 0, 1, 5, 2, 2880, 0},   // OFF
				{2, 2, 1, 5, 4, 2880, 0},   // NORM ignores TSMODE
				{2, 1, 1, 5, 4, 2880, 1},   // AUTO + sample REPITCH, IMMEDIATE
				{2, 1, 0, 5, 5, 2880, 1},   // AUTO + sample RPS9 on STATIC
				{2, 1, 1, 5, 6, 8000, 0},   // AUTO + RPSP, tempo out of range
				{2, 1, 1, 5, 2, 2880, 0},   // AUTO + NORMAL sample
				{9, 4, 0, 5, 2, 2880, 0},   // track out of range
			};
			bool ok = true;
			int n = 0, bad = -1;
			for(const auto& c : cases) {
				ot::Machine m(pat.image);
				auto* cpu = m.getCpuState();
				const uint32_t t = c.track & 7;
				m.write32(0x800000e0, 0);
				m.write8(0x80000eb4 + t, c.machine);
				m.write8(0x8000082f + 72 * t, c.slot);
				const uint32_t set = (c.machine == 0 ? 0x100d5b30u : 0x100b14f0u) + c.slot * 0x448;
				m.write32(set + 0x110, c.tsmode);
				m.write32(set + 0x114, c.bpm);
				if(m.read32(set + 0x114) != c.bpm) { std::printf("  [FAIL] settings region unmapped in the emu\n"); ok = false; break; }
				m.write8(lanes + 48 * t + 28, c.setup);
				m68k_set_reg(cpu, M68K_REG_D1, c.track);
				m.write32(stack - 4, trampoline + 0x80);
				for(unsigned i = 0; i < 8; i += 2) m.write16(trampoline + 0x80 + i, 0x4e71);
				m68k_set_reg(cpu, M68K_REG_SP, stack - 4);
				m68k_set_reg(cpu, M68K_REG_PC, uiGate);
				unsigned steps = 0;
				while(m.pc() != trampoline + 0x80 && steps++ < 160)
					if(!m.step()) break;
				const bool good = m.pc() == trampoline + 0x80 &&
				                  m68k_get_reg(cpu, M68K_REG_D0) == uint32_t(c.want) &&
				                  m68k_get_reg(cpu, M68K_REG_SP) == stack;
				if(!good && bad < 0) bad = n;
				ok &= good;
				++n;
			}
			std::printf("      (%d gate cases)\n", n);
			check("rp_ui_gate: slot-table display truth, binding-free", ok, bad);
		}
	}

	std::printf("%d failure(s)\n", fails);
	return fails ? 1 : 0;
}

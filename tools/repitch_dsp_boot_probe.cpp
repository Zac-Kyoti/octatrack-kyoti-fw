// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac-Kyoti
//
// repitch-kyoti rev 17: run one payload's boot path on dsp56kEmu -- from its
// entry P:0x40 (the one-time memory clear) to the head of its frame loop -- and
// dump memory, so tools/repitch_dsp_boot_check.py can compare a patched image
// (zqboot hooked into the clear) with stock word for word.
//
// usage: repitch_dsp_boot_probe PAYLOAD.mem STOP OUT.bin
//   PAYLOAD.mem: tools/dsp_modmap.py's --dumpmem format ([u8 space][u32 addr]
//   [u32 count] + count u32 words, space 0xff ends); STOP: the P address to stop
//   at (hex). Every data register, address register and memory word not loaded
//   by the payload starts from the same pseudo-random garbage on every run.
//   OUT.bin: u32 words -- P 0..0x1fff, X 0..0xffff, Y 0..0xffff, Y 0x30000..0x3ffff.
//   Prints the instructions executed.
#include <cstdint>
#include <cstdio>
#include <fstream>
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
}

int main(int argc, char** argv)
{
	if(argc != 4) { std::printf("usage: see header\n"); return 2; }
	const uint32_t stop = uint32_t(std::stoul(argv[2], nullptr, 16));

	AllowAll val;
	Memory mem(val, 0x080000, 0x800000, 0x200000);
	Peripherals56362 px;
	Peripherals56367 py;
	DSP dsp(mem, &px, &py);

	uint32_t seed = 0x2545f491u;
	auto rnd = [&]() { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return seed & 0xffffff; };
	for(uint32_t a = 0; a < 0x10000; ++a) { mem.set(MemArea_X, a, rnd()); mem.set(MemArea_Y, a, rnd()); }
	for(uint32_t a = 0x30000; a < 0x40000; ++a) { mem.set(MemArea_X, a, rnd()); mem.set(MemArea_Y, a, rnd()); }

	std::ifstream in(argv[1], std::ios::binary);
	for(;;) {
		uint8_t sp; uint32_t addr, cnt;
		if(!in.read(reinterpret_cast<char*>(&sp), 1) || sp == 0xff) break;
		in.read(reinterpret_cast<char*>(&addr), 4);
		in.read(reinterpret_cast<char*>(&cnt), 4);
		for(uint32_t i = 0; i < cnt; ++i) {
			uint32_t w;
			in.read(reinterpret_cast<char*>(&w), 4);
			if(sp == 0) dsp.memWriteP(addr + i, w & 0xffffff);
			else mem.set(sp == 1 ? MemArea_X : MemArea_Y, addr + i, w & 0xffffff);
		}
	}

	auto& R = dsp.regs();
	for(int i = 0; i < 8; ++i) { R.r[i].var = rnd(); R.n[i].var = rnd(); }
	dsp.setPC(0x40);
	const uint64_t before = dsp.getInstructionCounter();
	unsigned steps = 0;
	while(dsp.getPC().toWord() != stop && steps++ < 2000000)
		dsp.execInterpreter();
	if(dsp.getPC().toWord() != stop) { std::printf("did not reach %05x (pc %06x)\n", stop, dsp.getPC().toWord()); return 1; }
	std::printf("BOOT_INSTR %llu\n", (unsigned long long)(dsp.getInstructionCounter() - before));

	std::ofstream out(argv[3], std::ios::binary);
	auto put = [&](uint32_t w) { w &= 0xffffff; out.write(reinterpret_cast<const char*>(&w), 4); };
	for(uint32_t a = 0; a < 0x2000; ++a) put(mem.get(MemArea_P, a));
	for(uint32_t a = 0; a < 0x10000; ++a) put(mem.get(MemArea_X, a));
	for(uint32_t a = 0; a < 0x10000; ++a) put(mem.get(MemArea_Y, a));
	for(uint32_t a = 0x30000; a < 0x40000; ++a) put(mem.get(MemArea_Y, a));
	return 0;
}

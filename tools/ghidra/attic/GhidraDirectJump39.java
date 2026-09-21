//@category Octatrack
// Session 79 continued a tenth time: dynamic PC-trace diff (frame 346 natural write vs
// frame 518 DIRECT JUMP's extra write) shows near-identical code paths through
// [0x400a2b00,0x400a2e30] (confirming the 0x400a2c66 ACT-vs-snapshot branch genuinely
// forks differently, but NOT what gates whether this whole block executes at all on a
// given tick -- 0x80006626 is never written in either run, per this session's own
// dynamic write-watch). The real per-tick entry gate must be BEFORE 0x400a2b00. Dump
// wider backward context to find it.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump39 extends GhidraScript {
  void dump(Listing listing, long lo, long hi) throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    Address end = sp.getAddress(hi);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }

  public void run() throws Exception {
    Listing listing = currentProgram.getListing();
    println("=== raw disassembly, 0x400a29c0..0x400a2b00 (entry gate for the table-arm block) ===");
    dump(listing, 0x400a29c0L, 0x400a2b00L);
  }
}

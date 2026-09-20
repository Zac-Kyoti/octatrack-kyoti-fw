//@category Octatrack
// Session 79 continued an eighth time: found the table-arm write and its consumer.
// Before designing a fix, need the OUTER trigger for the whole table-arm code block
// (0x400a2c30 onward is mid-loop, "subq.l #0x8,D3; bge" -- a descending per-slot loop
// counter) -- what decides this code runs at all, and on which tick. Dump wider
// context backward from the known region start (TRACE_LO=0x400a2b00) to find the loop
// entry / gating condition.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump35 extends GhidraScript {
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
    println("=== raw disassembly, 0x400a2b00..0x400a2c30 (loop setup / entry gate) ===");
    dump(listing, 0x400a2b00L, 0x400a2c30L);
  }
}

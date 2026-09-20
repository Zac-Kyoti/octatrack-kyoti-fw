//@category Octatrack
// Session 79 continued a seventh time, NEXT item 1: decode the FULL computation at
// TABLE_ARM_PC (0x400a2e0c) that writes DAT_80001904[track] -- confirmed this session
// (exact arithmetic) that the DOMINANT term is a per-step accumulator, corrupted by
// DIRECT JUMP's off-cycle commit. GhidraDirectJump15.java (much earlier) read this as
// "D0 = accumulator - 0x285ff0 + table_46c7a830[track] + D7" but that was before the
// per-step-accumulator structure was understood -- get a full, wide raw dump to see
// where "accumulator" itself comes from (a read from where?) and confirm/refute whether
// the ACT-vs-snapshot branch's chosen value (D3, from the 0x400a2c66 branch) feeds
// ANY part of this, directly or indirectly.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump29 extends GhidraScript {
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
    println("=== raw disassembly, 0x400a2c30..0x400a2e30 (full region: branch through table-arm write) ===");
    dump(listing, 0x400a2c30L, 0x400a2e30L);
  }
}

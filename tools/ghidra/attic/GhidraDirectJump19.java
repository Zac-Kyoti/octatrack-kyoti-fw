//@category Octatrack
// Session 79 continued a fifth time: PC-trace diff (not a single-hypothesis watch) found
// the EXACT diverging branch empirically: at 0x400a2c66, DJ-commit falls through to
// 0x400a2c68 while ground-truth branches away to 0x400a2c8a, starting at frame 475 (14
// frames -- one sub-step countdown tick -- after the commit at 461), not at the commit
// itself. Decode this branch and its condition precisely.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump19 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    println("=== raw disassembly, 0x400a2c40..0x400a2ce0 ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a2c40L), true);
    Address end = sp.getAddress(0x400a2ce0L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

//@category Octatrack
// Session 79 continued a fifth time: (0xa8,SP)'s only real write is `move.l A5,(0xa8,SP)`
// at 0x400a2962 -- a per-track byte-array POINTER (incremented +1 per track later at
// 0x400a3584). Find what A5 is set to right before this store, to identify the actual
// array whose per-track content flips the diverging branch.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump21 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    println("=== raw disassembly, 0x400a2900..0x400a2970 ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a2900L), true);
    Address end = sp.getAddress(0x400a2970L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

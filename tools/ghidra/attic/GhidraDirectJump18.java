//@category Octatrack
// Session 79 continued again: 0x8000668d (the per-track reset-flag word tested at
// 0x400a2d8c) is SET at two sites besides the clear at 0x400a2dd8: 0x400a13dc and
// 0x400a2264. Context around both, to see what condition sets this "do the reset" bit.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump18 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    for (long a : new long[]{0x400a13dcL, 0x400a2264L}) {
      Address w = sp.getAddress(a);
      println("\n=== context around " + w + " ===");
      Address ctxStart = w.subtract(40);
      Address ctxEnd = w.add(20);
      InstructionIterator it = listing.getInstructions(ctxStart, true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.getAddress().compareTo(ctxEnd) > 0) break;
        String marker = ins.getAddress().equals(w) ? "  <=== SITE" : "";
        println(ins.getAddress() + "  " + ins.toString() + marker);
      }
    }
  }
}

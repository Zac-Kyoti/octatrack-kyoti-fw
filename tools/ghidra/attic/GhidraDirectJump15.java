//@category Octatrack
// Session 79 continued again: GhidraDirectJump14 found 10 separate occurrences of the
// DAT_80001904 base-pointer idiom (adda/lea #-0x7fffe6fc) inside FUN_400a1eea alone --
// only one (0x400a2802) has been decoded so far (the clear-on-expiry loop for groups
// 0/1/2). Dump raw context around the other 9 to find the SET side (a write of a FRESH
// value, not a compare-and-clear) and the groups-4/7 loop.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump15 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    long[] sites = {0x400a2bdaL, 0x400a2e12L, 0x400a3290L, 0x400a32f2L,
                     0x400a3306L, 0x400a33ecL, 0x400a34f8L, 0x400a42eaL, 0x400a43b8L};
    for (long s : sites) {
      Address w = sp.getAddress(s);
      println("\n=== context around " + w + " ===");
      Address ctxStart = w.subtract(30);
      Address ctxEnd = w.add(80);
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

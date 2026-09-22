//@category Octatrack
// Session 79 continued a fifth time: the diverging branch (0x400a2c66) tests a stack
// local at (0xa8,SP) -- signed byte, blt taken (use ACT_PAT/ACT_BANK) when negative,
// fallthrough (use 0x800065c1/0x800065c2, PEND_PAT/PEND_BANK-adjacent) when >= 0. Find
// every WRITE to this exact stack offset within FUN_400a1eea (0x400a1eea-0x400a4d90) to
// see what sets it and under what condition -- this is a local, not a call argument
// (the function has zero call-xrefs), so the write must be somewhere earlier in the same
// giant function's own body.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump20 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    println("=== every instruction in FUN_400a1eea mentioning 'a8,SP' (reads AND writes) ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a1eeaL), true);
    Address end = sp.getAddress(0x400a4d90L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      String s = ins.toString();
      if (s.contains("a8,SP") || s.contains("0xa8,SP")) {
        println(ins.getAddress() + "  " + s);
      }
    }
  }
}

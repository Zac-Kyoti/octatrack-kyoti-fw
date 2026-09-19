//@category Octatrack
// Session 70, 14th pass (continued): precise disassembly listing of FUN_400a1eea's
// 0x400a4200..0x400a4500 span -- Hook D (0x400a4220, a single moveb per its own comment
// in patch_directjump.s) through just before the commit (~0x400a44d0), to align exact
// PCs with the SCALE-wrap-check C already decompiled (GhidraDirectJump7.java), since the
// two turned out NOT to be the same code (self-correction: the header comment's "0x400a4220..:
// bar ctr, ping-pong, CHAIN-AFTER gate" describes a whole stretch STARTING near there, not
// that single instruction itself).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump8 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    Address start = sp.getAddress(0x400a1eeaL);
    Address end = sp.getAddress(0x400a4d90L);
    InstructionIterator it = listing.getInstructions(start, true);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

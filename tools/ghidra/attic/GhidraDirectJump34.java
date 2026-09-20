//@category Octatrack
// Session 79 continued a seventh time: FUN_4000ae12's decompile failed (bad instruction
// data, halt_baddata()) and it has ZERO static callers -- get the RAW disassembly
// directly instead (this project's own established practice: raw disasm over
// decompiler when the decompiler struggles) to see what it actually does with
// DAT_80001904 at 0x4000aef6.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump34 extends GhidraScript {
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
    println("=== raw disassembly, 0x4000ae12..0x4000af40 ===");
    dump(listing, 0x4000ae12L, 0x4000af40L);
  }
}

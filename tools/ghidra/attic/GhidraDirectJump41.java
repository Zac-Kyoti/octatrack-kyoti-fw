//@category Octatrack
// Session 79 continued a twelfth time: the first fix attempt only suppressed track 0's
// table-arm write (the one-shot flag got consumed on the FIRST of 8 per-track loop
// iterations) AND missed a second write site entirely -- the dynamic post-fix log shows
// group-4 slots (32-39) still writing via PC 0x400a33f2, a site never found by any of
// this session's earlier scans. Get its full raw context to find the exact instruction
// sequence (mirroring 0x400a2e12/2e18's lea+move.l shape) for a second detour.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump41 extends GhidraScript {
  void dump(Listing listing, long lo, long hi) throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    Address end = sp.getAddress(hi);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      byte[] bytes = ins.getBytes();
      StringBuilder hex = new StringBuilder();
      for (byte b : bytes) hex.append(String.format("%02x", b));
      println(ins.getAddress() + "  len=" + bytes.length + "  bytes=" + hex + "  " + ins.toString());
    }
  }

  public void run() throws Exception {
    Listing listing = currentProgram.getListing();
    println("=== raw disassembly + bytes, 0x400a3380..0x400a3420 ===");
    dump(listing, 0x400a3380L, 0x400a3420L);
  }
}

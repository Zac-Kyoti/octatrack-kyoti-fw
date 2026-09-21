//@category Octatrack
// Session 79 continued a thirteenth time: pursuing candidate (d) -- derive BAR_CTR
// (0x800065b2) fresh from G_ABSTICK at a DIRECT JUMP commit instead of letting it
// reset to a raw 0. Need the exact instruction bytes/context around its reset site
// (0x400a483a, found dynamically -- "continued an eleventh time") to design a detour:
// what condition guards the reset, what registers are live, and confirm this is
// reachable from dj_c's own commit path (Hook C is at 0x400a4840, immediately after).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump42 extends GhidraScript {
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
    println("=== raw disassembly + bytes, 0x400a4790..0x400a4850 (BAR_CTR reset through Hook C site) ===");
    dump(listing, 0x400a4790L, 0x400a4850L);
  }
}

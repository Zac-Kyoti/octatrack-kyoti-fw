//@category Octatrack
// Session 79 continued a twelfth time: preparing the actual patch. Need the exact byte
// length of the table-arm store instruction (0x400a2e18, "move.l D0,(0x0,A0,A1*0x4)")
// and its immediate neighbors, to design a detour (jsr <cave>, needs >= 6 bytes,
// possibly spanning into the next instruction with nop padding like dj_scaleix_fix's
// own detour at 0x400a4220 already does in patch_directjump.s).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump40 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    println("=== instruction lengths + bytes, 0x400a2e00..0x400a2e30 ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a2e00L), true);
    Address end = sp.getAddress(0x400a2e30L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      byte[] bytes = ins.getBytes();
      StringBuilder hex = new StringBuilder();
      for (byte b : bytes) hex.append(String.format("%02x", b));
      println(ins.getAddress() + "  len=" + bytes.length + "  bytes=" + hex + "  " + ins.toString());
    }
  }
}

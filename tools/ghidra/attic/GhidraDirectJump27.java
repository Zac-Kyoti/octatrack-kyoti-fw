//@category Octatrack
// Session 79 continued a sixth time, NEXT item 1: DJ26 found CNTDN_TBL's ONLY writer
// outside FUN_400a1eea is at 0x4009bcc0 (in/near FUN_4009bd44). Get context to see
// what triggers this external write -- if it's DIRECT JUMP's own trigger code (or an
// ordinary trig/note-on handler), that identifies the other real consumer/producer of
// CNTDN_TBL's armed state this fix must not break.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump27 extends GhidraScript {
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
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();

    Address a = sp.getAddress(0x4009bcc0L);
    Function f = getFunctionContaining(a);
    println("=== function containing 0x4009bcc0 ===");
    if (f == null) {
      println("  none");
    } else {
      println("  " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses());
      ReferenceManager rm = currentProgram.getReferenceManager();
      ReferenceIterator rs = rm.getReferencesTo(f.getEntryPoint());
      int n = 0;
      println("  call xrefs:");
      while (rs.hasNext()) {
        Reference r = rs.next();
        println("    from " + r.getFromAddress() + "  type=" + r.getReferenceType());
        n++;
        if (n > 20) { println("    ...(truncated)"); break; }
      }
    }

    println("=== raw context, 0x4009bc60..0x4009bd00 ===");
    dump(listing, 0x4009bc60L, 0x4009bd00L);
  }
}

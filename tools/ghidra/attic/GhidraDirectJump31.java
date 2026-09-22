//@category Octatrack
// Session 79 continued a seventh time: ACCUM (0x4610757c) is never written inside
// FUN_400a1eea itself -- its two main writers are 0x4009bad4/0x4009bb96 (in
// candidate_4009b9cc). Get context there to see what increments it, by how much, and
// how often -- this is the actual source of the per-step growth this session's
// arithmetic found (DAT_80001904's dominant term tracks ACCUM almost directly).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump31 extends GhidraScript {
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
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    Address a = sp.getAddress(0x4009bad4L);
    Function f = getFunctionContaining(a);
    println("=== function containing 0x4009bad4 ===");
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
        Function cf = getFunctionContaining(r.getFromAddress());
        println("    from " + r.getFromAddress() + "  type=" + r.getReferenceType()
                + "  in " + (cf == null ? "?" : cf.getName()));
        n++;
        if (n > 20) { println("    ...(truncated)"); break; }
      }
    }

    println("=== raw context, 0x4009ba90..0x4009bb00 (around first ACCUM write) ===");
    dump(listing, 0x4009ba90L, 0x4009bb00L);
    println("=== raw context, 0x4009bb50..0x4009bbb0 (around second ACCUM write) ===");
    dump(listing, 0x4009bb50L, 0x4009bbb0L);
  }
}

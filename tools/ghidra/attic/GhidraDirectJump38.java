//@category Octatrack
// Session 79 continued an eighth time: 0x80006626 (table-arm-due bitmask) gets CLEARED
// TO 0 at every switch commit (0x400a4054, inside the reset block right before the
// outgoing-pattern snapshot copy). 0x400a1384 (in candidate_400a129e, a DIFFERENT
// function from the per-tick handler) is the only OTHER writer -- find its context and
// its own callers, to trace what re-arms the bitmask after a commit clears it (this is
// almost certainly the real "once per loop" trigger for the table-arm write).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump38 extends GhidraScript {
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
    Function f = getFunctionContaining(sp.getAddress(0x400a1384L));
    println("=== function containing 0x400a1384 ===");
    if (f == null) {
      println("  none");
    } else {
      println("  " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses());
      ReferenceManager rm = currentProgram.getReferenceManager();
      ReferenceIterator rs = rm.getReferencesTo(f.getEntryPoint());
      println("  call xrefs:");
      int n = 0;
      while (rs.hasNext()) {
        Reference r = rs.next();
        Function cf = getFunctionContaining(r.getFromAddress());
        println("    from " + r.getFromAddress() + " type=" + r.getReferenceType()
                + " in " + (cf == null ? "?" : cf.getName()));
        n++;
        if (n > 20) { println("    ...(truncated)"); break; }
      }
    }
    println("=== raw context, 0x400a1340..0x400a13a0 ===");
    dump(listing, 0x400a1340L, 0x400a13a0L);
  }
}

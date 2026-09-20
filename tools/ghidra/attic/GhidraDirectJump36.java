//@category Octatrack
// Session 79 continued an eighth time: DJ35 found the table-arm write's own gate is a
// per-track bitmask (0x80006626), cleared then re-tested around a call to
// 0x400a539c(track) -- that call is the last unknown before the trigger chain is fully
// closed. Get its full raw disassembly + call xrefs to see what it actually decides.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump36 extends GhidraScript {
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
    Function f = getFunctionContaining(sp.getAddress(0x400a539cL));
    println("=== function at 0x400a539c ===");
    if (f == null) {
      println("  none (not in a defined function) -- dumping raw anyway");
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
    println("=== raw disassembly, 0x400a539c..0x400a5480 ===");
    dump(listing, 0x400a539cL, 0x400a5480L);
  }
}

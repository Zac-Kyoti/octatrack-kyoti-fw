//@category Octatrack
// Session 79 continued an eighth time: FUN_400a539c was a red herring (the trig-
// condition-lock reset family, 0x46107950-68, already closed as irrelevant to DIRECT
// JUMP by an earlier session). Find the REAL writer(s) of 0x80006626 (the table-arm-due
// bitmask) other than the clear-then-test in the same block (0x400a2b1a/0x400a2b90) --
// something must SET bit D5 for the test at 0x400a2b90 to ever see it set.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump37 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();

    Address a = sp.getAddress(0x80006626L);
    println("=== resolved xrefs to 0x80006626 ===");
    ReferenceIterator rs = rm.getReferencesTo(a);
    int n = 0;
    while (rs.hasNext()) {
      Reference r = rs.next();
      Function f = getFunctionContaining(r.getFromAddress());
      println("  from " + r.getFromAddress() + " type=" + r.getReferenceType()
              + " in " + (f == null ? "?" : f.getName()));
      n++;
    }
    println("  (" + n + " resolved xrefs)");

    println("=== text scan for '6626' (raw literal, in case unresolved) ===");
    InstructionIterator it = listing.getInstructions(true);
    int hits = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String s = ins.toString();
      if (s.contains("6626")) {
        Function f = getFunctionContaining(ins.getAddress());
        println("  " + ins.getAddress() + "  " + s + "   in " + (f == null ? "?" : f.getName()));
        hits++;
        if (hits > 40) { println("  ...(truncated)"); break; }
      }
    }
    println("  (" + hits + " matches, possibly truncated)");
  }
}

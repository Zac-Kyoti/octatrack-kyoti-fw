//@category Octatrack
// Session 79 continued a sixth time: NEXT item 1 -- confirm the identity of
// 0x800065c1/0x800065c2 (the two bytes immediately BEFORE CNTDN_TBL at 0x800065c3,
// used on the "wrong"/fallthrough side of the 0x400a2c66 blt branch). Resolved xrefs
// to the two Data addresses, PLUS a full-program raw-text scan for their signed lea
// forms (-0x7fff9a3f / -0x7fff9a3e) in case Ghidra hasn't resolved every access as a
// reference (matches this thread's own established lesson: text-scan the signed form,
// don't trust resolved xrefs alone).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump22 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();

    long[] targets = { 0x800065c1L, 0x800065c2L };
    for (long t : targets) {
      Address a = sp.getAddress(t);
      println("=== resolved xrefs to 0x" + Long.toHexString(t) + " ===");
      ReferenceIterator rs = rm.getReferencesTo(a);
      int n = 0;
      while (rs.hasNext()) {
        Reference r = rs.next();
        println("  from " + r.getFromAddress() + "  type=" + r.getReferenceType());
        n++;
      }
      println("  (" + n + " resolved xrefs)");
    }

    println("=== full-program text scan for '7fff9a3f' / '7fff9a3e' (signed lea forms) ===");
    InstructionIterator it = listing.getInstructions(true);
    int hits = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String s = ins.toString();
      if (s.contains("7fff9a3f") || s.contains("7fff9a3e")) {
        println("  " + ins.getAddress() + "  " + s);
        hits++;
      }
    }
    println("  (" + hits + " matches)");

    println("=== full-program text scan for '65c1' / '65c2' (in case of d16(An) form) ===");
    it = listing.getInstructions(true);
    int hits2 = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String s = ins.toString();
      if (s.contains("65c1") || s.contains("65c2")) {
        println("  " + ins.getAddress() + "  " + s);
        hits2++;
        if (hits2 > 80) { println("  ...(truncated)"); break; }
      }
    }
    println("  (" + hits2 + " matches, possibly truncated)");
  }
}

//@category Octatrack
// Session 79 continued a sixth time: DJ23 showed 0x800065c1/c2 are a SNAPSHOT copy of
// 0x800065be/0x800065bd, refreshed only at two specific points inside FUN_400a1eea
// (0x400a4074/0x400a44a6). FUN_400a0570 (the ordinary switch-commit writer, 4 call
// sites) writes 65bd/65be/65bf/65c0/65c1/65c2 ALL together -- so if DIRECT JUMP's own
// commit went through FUN_400a0570, 65c1/c2 could never go stale, contradicting the
// measured ~57-frame lag. Find EVERY write site to 0x800065bd and 0x800065be (not just
// FUN_400a0570's) to find DIRECT JUMP's own, narrower write path.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump24 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();

    long[] targets = { 0x800065bdL, 0x800065beL };
    for (long t : targets) {
      Address a = sp.getAddress(t);
      println("=== resolved xrefs to 0x" + Long.toHexString(t) + " ===");
      ReferenceIterator rs = rm.getReferencesTo(a);
      int n = 0;
      while (rs.hasNext()) {
        Reference r = rs.next();
        Address from = r.getFromAddress();
        Function f = getFunctionContaining(from);
        String fn = f == null ? "?" : f.getName();
        println("  from " + from + "  type=" + r.getReferenceType() + "  in " + fn);
        n++;
      }
      println("  (" + n + " resolved xrefs)");
    }

    println("=== text scan for '65bd' / '65be' (raw literal form, in case unresolved) ===");
    InstructionIterator it = listing.getInstructions(true);
    int hits = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String s = ins.toString();
      if (s.contains("65bd") || s.contains("65be")) {
        Function f = getFunctionContaining(ins.getAddress());
        String fn = f == null ? "?" : f.getName();
        println("  " + ins.getAddress() + "  " + s + "   in " + fn);
        hits++;
        if (hits > 60) { println("  ...(truncated)"); break; }
      }
    }
    println("  (" + hits + " matches, possibly truncated)");
  }
}

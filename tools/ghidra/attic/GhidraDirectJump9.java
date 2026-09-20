//@category Octatrack
// Session 79: find every real (resolved) xref TO DAT_80001904 (the live-nibble-in table
// whose contents diverge, at matched STEP, between a DIRECT JUMP commit and an honestly-
// arrived-at same step -- NOTES.md Session 79). Uses Ghidra's own getReferencesTo(), not a
// literal-byte grep, per the project's own established lesson (Session 70 12th/15th passes)
// that hand-grepping/decompiled-C misreads operands. For each writer found inside
// FUN_400a1eea, dump raw disassembly context around it.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump9 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    FunctionManager fm = currentProgram.getFunctionManager();

    Address tbl = sp.getAddress(0x80001904L);
    Address fnStart = sp.getAddress(0x400a1eeaL);
    Address fnEnd = sp.getAddress(0x400a4d90L);
    Function f = fm.getFunctionContaining(fnStart);
    println("Function: " + f.getName() + " @ " + f.getEntryPoint());

    ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(tbl);
    println("=== resolved xrefs TO 0x80001904 (whole image) ===");
    int n = 0;
    java.util.List<Address> writers = new java.util.ArrayList<>();
    while (refs.hasNext()) {
      Reference r = refs.next();
      Address from = r.getFromAddress();
      boolean inFn = from.compareTo(fnStart) >= 0 && from.compareTo(fnEnd) <= 0;
      println((n++) + ": " + from + "  type=" + r.getReferenceType()
          + "  inFUN_400a1eea=" + inFn);
      if (inFn) writers.add(from);
    }
    println("total refs: " + n + ", inside FUN_400a1eea: " + writers.size());

    for (Address w : writers) {
      println("\n=== context around " + w + " ===");
      Address ctxStart = w.subtract(40);
      Address ctxEnd = w.add(60);
      InstructionIterator it = listing.getInstructions(ctxStart, true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.getAddress().compareTo(ctxEnd) > 0) break;
        String marker = ins.getAddress().equals(w) ? "  <=== XREF" : "";
        println(ins.getAddress() + "  " + ins.toString() + marker);
      }
    }
  }
}

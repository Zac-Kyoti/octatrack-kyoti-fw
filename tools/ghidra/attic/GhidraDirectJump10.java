//@category Octatrack
// Session 79 continued: GhidraDirectJump9 found only 3 resolved xrefs to DAT_80001904 in
// the WHOLE image, NONE inside FUN_400a1eea -- contradicting Session 70 12th pass's own
// characterization ("written by FUN_400a1eea"). Since this table is indexed
// [track + step*8], real writes almost certainly use register-indexed addressing that
// Ghidra's static constant-reference analyzer can't resolve to a fixed xref (only a
// literal base-address LOAD, e.g. lea #0x80001904,Ax, would show up at all). Dump raw
// disassembly context around all 3 actual refs, and also list every function that
// CONTAINS the literal 0x80001904 anywhere in its instruction text (belt-and-braces catch
// for a lea/pea this xref scan might still miss due to how Ghidra represents it).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump10 extends GhidraScript {
  void dumpContext(Listing listing, Address w, int before, int after) {
    Address ctxStart = w.subtract(before);
    Address ctxEnd = w.add(after);
    InstructionIterator it = listing.getInstructions(ctxStart, true);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(ctxEnd) > 0) break;
      String marker = ins.getAddress().equals(w) ? "  <=== XREF" : "";
      println(ins.getAddress() + "  " + ins.toString() + marker);
    }
  }

  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    FunctionManager fm = currentProgram.getFunctionManager();

    Address[] refs = {sp.getAddress(0x4000aef6L), sp.getAddress(0x4009c220L), sp.getAddress(0x4009c2ecL)};
    for (Address w : refs) {
      Function f = fm.getFunctionContaining(w);
      println("\n=== " + w + " -- in function " + (f != null ? f.getName() + " @ " + f.getEntryPoint() : "???") + " ===");
      dumpContext(listing, w, 40, 60);
    }

    println("\n=== belt-and-braces: functions whose instruction text mentions 80001904 ===");
    FunctionIterator fit = fm.getFunctions(true);
    while (fit.hasNext()) {
      Function fn = fit.next();
      InstructionIterator it = listing.getInstructions(fn.getBody(), true);
      boolean hit = false;
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.toString().contains("80001904")) {
          if (!hit) { println("-- " + fn.getName() + " @ " + fn.getEntryPoint()); hit = true; }
          println("   " + ins.getAddress() + "  " + ins.toString());
        }
      }
    }
  }
}

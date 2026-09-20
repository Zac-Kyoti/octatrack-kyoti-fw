//@category Octatrack
// Session 79 continued again: identify what 0x4009d1e8 (the jsr at 0x400a2d7e, whose
// return bit gates the scheduling-reset block) actually does, and what 0x46107568 /
// the (0x94,SP) stack-local test at 0x400a2d1a-2d2a represent. Raw disassembly of
// 0x4009d1e8 itself, plus xrefs to 0x46107568 to see what else touches that flag.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump17 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    FunctionManager fm = currentProgram.getFunctionManager();
    ReferenceManager rm = currentProgram.getReferenceManager();

    Address probe = sp.getAddress(0x4009d1e8L);
    Function f = fm.getFunctionContaining(probe);
    println("Function at 0x4009d1e8: " + (f != null ? f.getName() + " @ " + f.getEntryPoint() + " size " + f.getBody().getNumAddresses() : "??? unbounded"));

    println("\n=== raw disassembly of FUN@0x4009d1e8, up to 200 instrs ===");
    InstructionIterator it = listing.getInstructions(probe, true);
    int n = 0;
    while (it.hasNext() && n < 200) {
      Instruction ins = it.next();
      println(ins.getAddress() + "  " + ins.toString());
      n++;
      if (ins.toString().startsWith("rts") || ins.toString().startsWith("rte")) break;
    }

    println("\n=== resolved xrefs to 0x46107568 (the first bail-test) ===");
    ReferenceIterator refs = rm.getReferencesTo(sp.getAddress(0x46107568L));
    int m = 0;
    while (refs.hasNext()) {
      Reference r = refs.next();
      println((m++) + ": " + r.getFromAddress() + "  type=" + r.getReferenceType());
    }
    println("total: " + m);

    println("\n=== resolved xrefs to 0x8000668d (the reset flag byte) ===");
    ReferenceIterator refs2 = rm.getReferencesTo(sp.getAddress(0x8000668dL));
    m = 0;
    while (refs2.hasNext()) {
      Reference r = refs2.next();
      println((m++) + ": " + r.getFromAddress() + "  type=" + r.getReferenceType());
    }
    println("total: " + m);
  }
}

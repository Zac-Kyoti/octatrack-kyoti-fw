//@category Octatrack
// Session 79 continued a fourteenth time: BAR_CTR fix is dynamically REFUTED (zero effect
// on table-arm write cadence or final mismatch count). New lead from raw objdump of
// 0x400a2a70-0x400a2e40: the real "due" gate at 0x400a2bb0-0x400a2c34 compares
// ACCUM(0x4610757c)-2646001 against values stored INSIDE DAT_80001904 itself (self-
// referential expiry check), then falls through toward the known write sites
// (0x400a2e12/0x400a33ec). Need: (1) this containing function's start address, (2) every
// static caller of it, especially anything on the DIRECT JUMP commit path
// (0x400a4000-0x400a4900), to test whether DJ's commit triggers ONE EXTRA call into this
// periodic due-check function (as opposed to it being purely ACCUM/time driven).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump43 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    FunctionManager fm = currentProgram.getFunctionManager();

    Address probe = sp.getAddress(0x400a2ae0L);
    Function f = fm.getFunctionContaining(probe);
    if (f == null) {
      println("No function contains 0x400a2ae0 in Ghidra's function map.");
    } else {
      println("Containing function: " + f.getName() + " @ " + f.getEntryPoint()
          + "  body=" + f.getBody());
      Address entry = f.getEntryPoint();
      println("=== callers of " + f.getName() + " ===");
      ReferenceManager rm = currentProgram.getReferenceManager();
      ReferenceIterator refs = rm.getReferencesTo(entry);
      while (refs.hasNext()) {
        Reference r = refs.next();
        println("  from " + r.getFromAddress() + "  type=" + r.getReferenceType());
      }
    }

    // Also directly check for any static jsr/bsr operand landing anywhere in the
    // 0x400a2900-0x400a2f00 window, from the whole DJ commit region 0x400a3fff-0x400a4900,
    // in case Ghidra's function boundaries don't match what we care about.
    println("=== jsr/bsr instructions in 0x400a3fff-0x400a4900 whose target lands in 0x400a2900-0x400a2f00 ===");
    Listing listing = currentProgram.getListing();
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a3fffL), true);
    Address stop = sp.getAddress(0x400a4900L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(stop) > 0) break;
      String mn = ins.getMnemonicString();
      if (mn.startsWith("jsr") || mn.startsWith("bsr")) {
        Address[] flows = ins.getFlows();
        for (Address t : flows) {
          if (t.getOffset() >= 0x400a2900L && t.getOffset() <= 0x400a2f00L) {
            println("  " + ins.getAddress() + "  " + ins.toString() + "  -> " + t);
          }
        }
      }
    }
  }
}

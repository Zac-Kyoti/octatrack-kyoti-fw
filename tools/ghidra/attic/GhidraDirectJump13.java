//@category Octatrack
// Session 79 continued: 0x400a27e0-0x400a27f4 writes TRANSPORT(0x800065b8)<-1 immediately
// before reading the 0x4610757c accumulator and computing toward DAT_80001904 (A2 =
// 0x80001904 via adda #-0x7fffe6fc) -- looks like transport-start/track-re-init code.
// Find this function's real boundaries and every caller, and check specifically whether
// DIRECT JUMP's commit path (dj_c's cave 0x400d7600-0x400d7800, or the stock
// switch-commit code 0x400a4800-0x400a4e00) is among them -- if DIRECT JUMP's commit
// accidentally re-enters transport-start-style reinit, that would directly explain why
// ONLY this accumulator-derived table diverges while STEP/REFILL_TBL/SCALE_IX (each
// separately, deliberately hooked) do not.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump13 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    FunctionManager fm = currentProgram.getFunctionManager();
    ReferenceManager rm = currentProgram.getReferenceManager();

    Address probe = sp.getAddress(0x400a27e0L);
    Function f = fm.getFunctionContaining(probe);
    println("Function containing 0x400a27e0: " + (f != null ? f.getName() + " @ " + f.getEntryPoint() + " size " + f.getBody().getNumAddresses() : "??? (unbounded)"));

    Address entry = (f != null) ? f.getEntryPoint() : probe;
    if (f == null) {
      // scan backward for a plausible prologue (link a6 / movem.l) within 0x400 bytes
      println("scanning backward from 0x400a27e0 for a prologue...");
      Address cur = probe;
      for (int i = 0; i < 0x400; i += 2) {
        cur = probe.subtract(i);
        Instruction ins = listing.getInstructionAt(cur);
        if (ins != null && (ins.toString().startsWith("link") || ins.toString().startsWith("movem"))) {
          println("  candidate prologue at " + cur + ": " + ins);
        }
      }
    }

    println("\n=== callers of entry " + entry + " ===");
    ReferenceIterator refs = rm.getReferencesTo(entry);
    int n = 0;
    while (refs.hasNext()) {
      Reference r = refs.next();
      if (r.getReferenceType().isCall()) {
        Address from = r.getFromAddress();
        boolean djCave = from.compareTo(sp.getAddress(0x400d7600L)) >= 0 && from.compareTo(sp.getAddress(0x400d7800L)) <= 0;
        boolean stockCommit = from.compareTo(sp.getAddress(0x400a4800L)) >= 0 && from.compareTo(sp.getAddress(0x400a4e00L)) <= 0;
        println((n++) + ": " + from + "  DJ_CAVE=" + djCave + "  STOCK_COMMIT_RANGE=" + stockCommit);
      }
    }
    println("total callers: " + n);

    println("\n=== raw disassembly, 0x400a27c0..0x400a2850 (wider context) ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a27c0L), true);
    Address end = sp.getAddress(0x400a2850L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

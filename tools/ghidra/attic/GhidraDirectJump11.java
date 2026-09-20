//@category Octatrack
// Session 79 continued: GhidraDirectJump10 found the real DAT_80001904 writers at
// 0x4009c220/0x4009c2ec, inside an UNBOUNDED region (Ghidra's function manager returns
// "???" for both -- a known class of gap in this project, dense ColdFire code Ghidra
// didn't cleanly bound). Gated on 0x800065bc (adjacent to ACT_BANK/ACT_PAT) != -1 and
// 0x80001860 != 0; reads an accumulator at 0x4610757c; involves the 0x8ed8 per-pattern
// blob stride. The critical question: does DIRECT JUMP's own commit path (dj_c's cave
// around 0x400d76xx-0x400d77xx, or the stock switch-commit code 0x400a48xx-0x400a4dxx)
// ever CALL into this region at all -- or does DIRECT JUMP's forced STEP/REFILL_TBL/
// SCALE_IX write leave this region's own output stale? List every CALL-type xref landing
// in [0x4009c000, 0x4009c400], and separately check the specific DIRECT JUMP addresses.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump11 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();

    println("=== CALL-type xrefs landing in [0x4009c000, 0x4009c400] ===");
    int n = 0;
    for (long a = 0x4009c000L; a <= 0x4009c400L; a += 2) {
      Address to = sp.getAddress(a);
      ReferenceIterator rs = rm.getReferencesTo(to);
      while (rs.hasNext()) {
        Reference r = rs.next();
        if (r.getReferenceType().isCall()) {
          println((n++) + ": " + r.getFromAddress() + " -> " + to
              + "  type=" + r.getReferenceType());
        }
      }
    }
    println("total CALL xrefs into window: " + n);

    println("\n=== does anything in dj_c's cave (0x400d7600-0x400d7800) or the stock");
    println("switch-commit code (0x400a4800-0x400a4e00) call into [0x4009c000,0x4009c400]? ===");
    Address[][] ranges = {
      {sp.getAddress(0x400d7600L), sp.getAddress(0x400d7800L)},
      {sp.getAddress(0x400a4800L), sp.getAddress(0x400a4e00L)},
    };
    for (Address[] range : ranges) {
      println("-- scanning " + range[0] + ".." + range[1] + " for calls out --");
      InstructionIterator it = listing.getInstructions(range[0], true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.getAddress().compareTo(range[1]) > 0) break;
        if (ins.getFlowType().isCall()) {
          Address[] flows = ins.getFlows();
          for (Address flow : flows) {
            println("   " + ins.getAddress() + "  " + ins.toString() + "  -> " + flow);
          }
        }
      }
    }

    println("\n=== context: 0x800065bc and 0x80001860 -- any other resolved xrefs? ===");
    for (long a : new long[]{0x800065bcL, 0x80001860L}) {
      Address addr = sp.getAddress(a);
      ReferenceIterator rs = rm.getReferencesTo(addr);
      while (rs.hasNext()) {
        Reference r = rs.next();
        println("   " + r.getFromAddress() + "  type=" + r.getReferenceType());
      }
    }
  }
}

//@category Octatrack
// Session 79 continued a seventh time: DJ29 fully decoded the TABLE_ARM_PC formula:
// DAT_80001904[slot] = ACCUM(0x4610757c) - 0x285ff0 + TBL_46c7a830[idx] + 0x285ff0*D2
// where 0x285ff0 == 2,646,000 decimal, exactly the per-step increment measured via
// arithmetic on the dynamic log. D2 is a pattern-length-derived value (LEN_TBL[scale],
// possibly adjusted by LEN_AC[track]), which is roughly CONSTANT for a given pattern --
// so the actual monotonic per-step growth measured dynamically must come from ACCUM
// (0x4610757c) itself growing over time. Find ACCUM's own writer(s) to see exactly what
// increments it and by how much, per tick or per loop -- this is the real source of the
// "elapsed step count" behavior found this session.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump30 extends GhidraScript {
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
    ReferenceManager rm = currentProgram.getReferenceManager();

    Address a = sp.getAddress(0x4610757cL);
    println("=== resolved xrefs to 0x4610757c (ACCUM) ===");
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

    println("=== raw context, 0x400a2790..0x400a2850 (around the previously-found TRANSPORT<-1 block) ===");
    dump(listing, 0x400a2790L, 0x400a2850L);
  }
}

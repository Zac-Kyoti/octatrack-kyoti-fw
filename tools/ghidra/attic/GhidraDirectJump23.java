//@category Octatrack
// Session 79 continued a sixth time: DJ22 found 0x800065c1/c2's only WRITE sites are
// 0x400a0602/0x400a0614 (OUTSIDE FUN_400a1eea -- a different, earlier function) and
// 0x400a4074/0x400a4080 + 0x400a44a6/0x400a44b2 (both INSIDE FUN_400a1eea, look like
// commit/copy sites: "move.b (A0),(0x800065c1).l"). Identify: (1) what function owns
// 0x400a0602 and what triggers it, (2) what A0/A1 point to at the two in-function copy
// sites, since those look like the real "promote pending to committed" logic this
// branch's fallthrough side actually wants.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump23 extends GhidraScript {
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

    Address a = sp.getAddress(0x400a0602L);
    Function f = getFunctionContaining(a);
    println("=== function containing 0x400a0602 ===");
    if (f == null) {
      println("  none (not in a defined function)");
    } else {
      println("  " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses());
      println("  call xrefs:");
      ReferenceManager rm = currentProgram.getReferenceManager();
      ReferenceIterator rs = rm.getReferencesTo(f.getEntryPoint());
      int n = 0;
      while (rs.hasNext()) {
        Reference r = rs.next();
        println("    from " + r.getFromAddress() + "  type=" + r.getReferenceType());
        n++;
        if (n > 20) { println("    ...(truncated)"); break; }
      }
    }

    println("=== raw context, 0x400a05a0..0x400a0640 (write site) ===");
    dump(listing, 0x400a05a0L, 0x400a0640L);

    println("=== raw context, 0x400a4030..0x400a4090 (in-function copy site 1) ===");
    dump(listing, 0x400a4030L, 0x400a4090L);

    println("=== raw context, 0x400a4460..0x400a44c0 (in-function copy site 2) ===");
    dump(listing, 0x400a4460L, 0x400a44c0L);
  }
}

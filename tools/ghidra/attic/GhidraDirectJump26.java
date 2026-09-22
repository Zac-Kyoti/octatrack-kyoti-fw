//@category Octatrack
// Session 79 continued a sixth time, NEXT item 1: before touching the 0x400a2c66
// branch, characterize every other consumer of CNTDN_TBL (0x800065c3, per-track,
// 8 bytes) end to end -- so a DJ-specific override there can't silently desync some
// other unrelated mechanism that also reads this same countdown.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump26 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();

    // CNTDN_TBL is an 8-byte per-track array; check xrefs to each of the 8 bytes
    // (a computed a0+track access won't show as a resolved xref to any one byte,
    // but any code that reads a FIXED track's slot, or the base address itself
    // via lea, will show up).
    for (long off = 0; off < 8; off++) {
      long addr = 0x800065c3L + off;
      Address a = sp.getAddress(addr);
      ReferenceIterator rs = rm.getReferencesTo(a);
      int n = 0;
      println("=== resolved xrefs to 0x" + Long.toHexString(addr) + " (CNTDN_TBL+" + off + ") ===");
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

    // Signed lea form of 0x800065c3 base (for computed track*1 offset access):
    // 0x800065c3 -> -0x7fff9a3d (already known, this IS CNTDN_TBL's own base --
    // confirmed Session 79 continued a fifth time). Scan the WHOLE image's
    // instructions for this literal to find every base-pointer setup, not just
    // fixed-offset accesses.
    println("=== full-program text scan for '7fff9a3d' (CNTDN_TBL base lea) ===");
    InstructionIterator it = listing.getInstructions(true);
    int hits = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String s = ins.toString();
      if (s.contains("7fff9a3d")) {
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

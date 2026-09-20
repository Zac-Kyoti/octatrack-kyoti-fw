//@category Octatrack
// Session 79 continued a seventh time: ACCUM (0x4610757c) = *(0x46104cf0) + (TEMPO<<4),
// read inside a critical section (SR=0x2700, interrupts masked) -- the classic idiom for
// reading a value an ISR also touches. Find 0x46104cf0's own writer(s) to confirm/refute
// whether it's an interrupt-driven elapsed-time/sample counter (which would mean
// DAT_80001904 is a real-time latch, not sequencer-step-derived data at all).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump32 extends GhidraScript {
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

    Address a = sp.getAddress(0x46104cf0L);
    println("=== resolved xrefs to 0x46104cf0 ===");
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

    println("=== also: resolved xrefs to DAT_80001904's full 256-byte range (0x80001904-0x800019ff), READ type only, outside FUN_400a1eea ===");
    for (long off = 0; off < 256; off += 4) {
      Address b = sp.getAddress(0x80001904L + off);
      ReferenceIterator rs2 = rm.getReferencesTo(b);
      while (rs2.hasNext()) {
        Reference r = rs2.next();
        Function f = getFunctionContaining(r.getFromAddress());
        String fn = f == null ? "?" : f.getName();
        if (!fn.equals("consumer_a6c0_a33f8")) {
          println("  OUTSIDE consumer: from " + r.getFromAddress() + " to +0x"
                  + Long.toHexString(off) + " type=" + r.getReferenceType() + " in " + fn);
        }
      }
    }
    println("  (scan complete)");
  }
}

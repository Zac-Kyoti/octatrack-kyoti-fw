//@category Octatrack
// Session 79 continued: DAT_80001904's group-0/4 divergence between DJ-commit and
// ground-truth, at matched absolute frame AND matched STEP, traces back to an
// accumulator read at 0x4610757c (both writer sites at 0x4009c220/0x4009c2ec read it).
// Ground-truth's value at frame 1101 EXACTLY matches the original stock (never-switched)
// run's own value at the same frame -- consistent with 0x4610757c being a global,
// transport-wide counter that should read identically regardless of which pattern is
// active. Check: does DIRECT JUMP's own hook code (Hook A/B/C/D/E/F, patch_directjump.s'
// cave sites, or the stock switch-commit code 0x400a4800-0x400a4e00) touch 0x4610757c or
// 0x800065b6 (STEP)'s own increment site in a way that could perturb it?
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump12 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    ReferenceManager rm = currentProgram.getReferenceManager();
    Listing listing = currentProgram.getListing();

    Address acc = sp.getAddress(0x4610757cL);
    println("=== resolved xrefs to 0x4610757c (the accumulator DAT_80001904 reads) ===");
    ReferenceIterator refs = rm.getReferencesTo(acc);
    int n = 0;
    while (refs.hasNext()) {
      Reference r = refs.next();
      println((n++) + ": " + r.getFromAddress() + "  type=" + r.getReferenceType());
    }
    println("total: " + n);

    println("\n=== context around each xref ===");
    ReferenceIterator refs2 = rm.getReferencesTo(acc);
    while (refs2.hasNext()) {
      Reference r = refs2.next();
      Address w = r.getFromAddress();
      println("\n-- " + w + " --");
      Address ctxStart = w.subtract(20);
      Address ctxEnd = w.add(20);
      InstructionIterator it = listing.getInstructions(ctxStart, true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.getAddress().compareTo(ctxEnd) > 0) break;
        String marker = ins.getAddress().equals(w) ? "  <=== XREF" : "";
        println(ins.getAddress() + "  " + ins.toString() + marker);
      }
    }

    // patch_directjump.s hook sites, per NOTES.md Session 70 passes 6/8/9:
    // Hook D (SCALE_IX self-heal) @ 0x400a4220, Hook E (G_ABSTICK bump) @ 0x400a3fe4,
    // Hook F (per-track REFILL_TBL resync) @ 0x400a4d36. Check whether any of THESE
    // exact addresses, or the master STEP increment site itself, are anywhere near
    // 0x4610757c's own xref addresses (already printed above) -- eyeballing overlap.
    println("\n=== for reference: DIRECT JUMP hook sites ===");
    println("Hook D (SCALE_IX)  @ 0x400a4220");
    println("Hook E (G_ABSTICK) @ 0x400a3fe4");
    println("Hook F (REFILL_TBL)@ 0x400a4d36");
  }
}

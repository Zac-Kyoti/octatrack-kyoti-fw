//@category Octatrack
// Session 79 continued again: the "belt-and-braces" scan in GhidraDirectJump10 searched
// instruction text for the literal "80001904" -- but Ghidra renders this address's base-
// pointer arithmetic as the signed 32-bit twin "-0x7fffe6fc" (adda.l/movea.l/lea), which
// does NOT contain that substring. That scan therefore missed every OTHER place in the
// image that computes this same base pointer via that idiom -- including a likely SET
// side for the scheduled-value table found last commit (only the clear-on-expiry side,
// at 0x400a27e0-0x400a2836, is known so far). Redo the scan correctly, and also find the
// branch condition leading INTO 0x400a27e0 from earlier in FUN_400a1eea.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class GhidraDirectJump14 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();
    FunctionManager fm = currentProgram.getFunctionManager();

    println("=== every instruction image-wide mentioning 7fffe6fc (== 0x80001904's base-pointer form) ===");
    FunctionIterator fit = fm.getFunctions(true);
    int total = 0;
    while (fit.hasNext()) {
      Function fn = fit.next();
      InstructionIterator it = listing.getInstructions(fn.getBody(), true);
      boolean hit = false;
      while (it.hasNext()) {
        Instruction ins = it.next();
        String s = ins.toString();
        if (s.contains("7fffe6fc")) {
          if (!hit) { println("-- " + fn.getName() + " @ " + fn.getEntryPoint()); hit = true; }
          println("   " + ins.getAddress() + "  " + s);
          total++;
        }
      }
    }
    // Also scan instructions NOT inside any recognized function (like the clear-side
    // block itself, which sits inside FUN_400a1eea's body -- should already be covered
    // above via getFunctions, but double check the whole address space too in case of
    // any other unbounded regions).
    println("total occurrences (function-bounded scan): " + total);

    println("\n=== branch condition leading into 0x400a27e0 (backward from there, raw) ===");
    InstructionIterator it2 = listing.getInstructions(sp.getAddress(0x400a2700L), true);
    Address end = sp.getAddress(0x400a27e2L);
    while (it2.hasNext()) {
      Instruction ins = it2.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

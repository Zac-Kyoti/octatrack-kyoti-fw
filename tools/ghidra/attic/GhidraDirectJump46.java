//@category Octatrack
// Session 79 continued a seventeenth time, part 2: confirming the indexing of the live
// per-track scale-index cache at 0x8000663e before writing a fix that refreshes it.
// GhidraDirectJump45 showed the wrap check at 0x400a3cee compares STEP_IN_PAT[t] against
// LEN_TBL[ *(A3) ] with A3 loaded ONCE at 0x400a3cb4 (lea 0x8000663e,A3) before the
// per-track loop, and refreshed from the pattern blob only right after a wrap
// (0x400a3d08 / 0x400a3d0e). If the loop advances A3 by 1 per track, the cache is a plain
// per-track byte array 0x8000663e[t] and dj_pertrack_fix can refresh it with the scale
// index it already computes. Dump the rest of the loop body to find A3's increment (and
// the loop-back branch) so the stride is measured, not assumed.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump46 extends GhidraScript {
  public void run() throws Exception {
    Listing listing = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    long lo = 0x400a3d20L, hi = 0x400a3e40L;
    println("=== per-track loop body tail: looking for A3/A5/A6/A2 increments + loop branch ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    Address end = sp.getAddress(hi);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      String s = ins.toString();
      // print everything, but flag the address-register updates and the loop branch
      String tag = "";
      if (s.contains("A3") || s.contains("A5") || s.contains("A6") || s.contains("A2")) tag = "   <== ptr";
      if (s.startsWith("b") && s.contains("0x400a3c")) tag = "   <== LOOP BACK";
      println(ins.getAddress() + "  " + String.format("%-34s", s) + tag);
    }
  }
}

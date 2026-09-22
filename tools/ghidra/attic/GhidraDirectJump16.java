//@category Octatrack
// Session 79 continued again: the D7 register-clobbering hypothesis is REFUTED (D7 is
// identical, constant, in both DJ-commit and ground-truth conditions at the table-arm
// site). But the arm site's own FIRING CADENCE differs: ground-truth fires a clean, even
// ~345 frames apart (one full 6-step pattern loop) throughout; DJ-commit fires normally
// EXCEPT for one anomalous ~172-frame (half-cadence) interval exactly straddling the
// commit frame (461), after which the cadence resumes normally but permanently phase-
// shifted relative to ground truth. This means DIRECT JUMP's commit triggers an EXTRA,
// out-of-cycle arm event. Find the branch condition gating entry into the arm/SET block
// (0x400a2e12) to identify exactly what condition the commit satisfies that organic
// per-tick execution normally only satisfies once per pattern loop.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump16 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing listing = currentProgram.getListing();

    println("=== wide backward context, 0x400a2d00..0x400a2e30 ===");
    InstructionIterator it = listing.getInstructions(sp.getAddress(0x400a2d00L), true);
    Address end = sp.getAddress(0x400a2e30L);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      println(ins.getAddress() + "  " + ins.toString());
    }
  }
}

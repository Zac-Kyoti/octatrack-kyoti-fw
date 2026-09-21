//@category Octatrack
// Session 79 continued a seventeenth time: the STEP_IN_PAT fix is validated, but a
// differently-scaled track still runs ONE cycle too long right after a DIRECT JUMP commit
// (measured on DJTESTxxx: track at trackLen 3 wrapped 6 ticks after the commit, then
// self-corrected). Cause is believed to be stock holding the OUTGOING pattern's per-track
// wrap length for that first cycle -- the per-track analogue of the stale-SCALE_IX bug
// Hook D already fixes for the MASTER length.
// Need: what does the wrap check at 0x400a3cf6 actually compare STEP_IN_PAT (0x800064f0[t])
// against -- a register, or a per-track table in memory? If it is a table, dj_pertrack_fix
// can refresh it the same way it already refreshes REFILL_TBL and STEP_IN_PAT (it already
// holds the CORRECT trackLen live in d1), and the fix is ~2 instructions at an existing
// hook site with no new detour.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump45 extends GhidraScript {
  void dump(String label, long lo, long hi) throws Exception {
    println("=== " + label + "  (0x" + Long.toHexString(lo) + " .. 0x" + Long.toHexString(hi) + ") ===");
    Listing listing = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    Address end = sp.getAddress(hi);
    int n = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      byte[] b = ins.getBytes();
      StringBuilder hex = new StringBuilder();
      for (byte x : b) hex.append(String.format("%02x", x));
      println(ins.getAddress() + "  len=" + b.length + "  " + String.format("%-14s", hex) + ins.toString());
      n++;
    }
    if (n == 0) println("  (no defined instructions in this range)");
    println("");
  }

  public void run() throws Exception {
    // the increment (0x400a3ce2) and the wrap-to-zero (0x400a3cf6), plus enough context
    // before the increment to see where the comparison operand is loaded from.
    dump("STEP_IN_PAT increment + wrap check", 0x400a3c90L, 0x400a3d20L);
  }
}

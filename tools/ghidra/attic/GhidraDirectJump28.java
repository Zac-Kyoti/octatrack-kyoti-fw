//@category Octatrack
// Session 79 continued a sixth time: designing a fix for the CNTDN_TBL-armed-window
// exposure (root cause found this session) requires knowing EXACTLY where/how
// CNTDN_TBL[track] transitions from "armed, counting down" to "idle" (0xFF) inside
// LAB_400a4ba0's per-track "==0" branch (Session 70's own decompile excerpt, NOTES.md
// ~L15717-15733, was elided after "REFILL_TBL[t] = QUOTIENT[t]"). The existing patch
// (tools/patch_directjump.s Hook F, @0x400a4d36) already documents the audio per-track
// loop as 0x400a4bb6-0x400a4c62 -- dump that raw, in full, to find the idle-set site.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump28 extends GhidraScript {
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
    Listing listing = currentProgram.getListing();
    println("=== raw disassembly, 0x400a4ba0..0x400a4c70 (LAB_400a4ba0 audio per-track loop) ===");
    dump(listing, 0x400a4ba0L, 0x400a4c70L);
  }
}

//@category Octatrack
// Session 79 continued a sixth time: DJ24 showed FUN_400a1eea's own in-loop block does
// copy-old-to-snapshot (0x400a4074/0x400a4080: c1<-65be, c2<-65bd) THEN writes NEW
// values into 65bd/65be at 0x400a409e/0x400a40aa (just past the previous dump's end) --
// i.e. this looks like the real "commit a pattern switch" sequence: preserve outgoing
// pattern in the c1/c2 snapshot, THEN promote the incoming pattern into the live 65bd/be
// pair. Get the fuller context (source registers/values for the 409e/40aa writes) and
// the matching second block (~400a44c0-400a4520) to confirm the pattern and find what
// feeds the NEW value -- this identifies exactly what a DIRECT JUMP fix needs to mirror.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump25 extends GhidraScript {
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
    println("=== raw context, 0x400a4090..0x400a4160 (block 1: writes to 65bd/65be after the copy) ===");
    dump(listing, 0x400a4090L, 0x400a4160L);
    println("=== raw context, 0x400a44c0..0x400a4560 (block 2: same, second occurrence) ===");
    dump(listing, 0x400a44c0L, 0x400a4560L);
  }
}

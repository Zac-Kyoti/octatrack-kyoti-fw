//@category Octatrack
// Session 79 continued a seventh time: FOUND A REAL CONSUMER -- FUN_4000ae12 both
// writes 0x46104cf0 (the counter ACCUM is built from) AND reads DAT_80001904 itself
// (0x4000aef6). This is a different function from the writer (FUN_400a1eea) and is at
// a low address (0x4000ae12), suggesting a low-level/driver routine, possibly the ISR
// or tick source that actually drives this whole mechanism -- not DSP-side. Get its
// full decompile + call xrefs to understand what it does with DAT_80001904.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.decompiler.*;

public class GhidraDirectJump33 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Function f = getFunctionContaining(sp.getAddress(0x4000ae12L));
    if (f == null) {
      println("no function at 0x4000ae12");
      return;
    }
    println("=== " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses() + " ===");

    ReferenceManager rm = currentProgram.getReferenceManager();
    ReferenceIterator rs = rm.getReferencesTo(f.getEntryPoint());
    println("call xrefs:");
    int n = 0;
    while (rs.hasNext()) {
      Reference r = rs.next();
      Function cf = getFunctionContaining(r.getFromAddress());
      println("  from " + r.getFromAddress() + " type=" + r.getReferenceType()
              + " in " + (cf == null ? "?" : cf.getName()));
      n++;
      if (n > 20) { println("  ...(truncated)"); break; }
    }

    DecompInterface decomp = new DecompInterface();
    decomp.openProgram(currentProgram);
    DecompileResults res = decomp.decompileFunction(f, 60, monitor);
    if (res != null && res.decompileCompleted()) {
      println("=== decompile ===");
      println(res.getDecompiledFunction().getC());
    } else {
      println("decompile failed: " + (res == null ? "null result" : res.getErrorMessage()));
    }
  }
}

//@category Octatrack
// Session 70, 11th pass: full, untruncated decompile of FUN_400a1eea (the 10628-byte
// dispatcher that both writes DAT_800065b6 directly AND calls the trig-condition
// evaluator FUN_400a536c/FUN_400a5164 family) -- looking for the real voice/sample
// trigger call this session has never located, and for anything resembling a
// sub-step/fractional phase field per the new LED-observation finding.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraDirectJump7 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    FunctionManager fm = currentProgram.getFunctionManager();
    DecompInterface dec = new DecompInterface();
    DecompileOptions opts = new DecompileOptions();
    opts.grabFromProgram(currentProgram);
    dec.setOptions(opts);
    dec.openProgram(currentProgram);
    ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

    Address a = sp.getAddress(0x400a1eeaL);
    Function f = fm.getFunctionContaining(a);
    println("Function: " + f.getName() + " @ " + f.getEntryPoint() + " size " + f.getBody().getNumAddresses());
    DecompileResults r = dec.decompileFunction(f, 600, mon);
    if (r == null || !r.decompileCompleted()) {
      println("DECOMPILE FAILED: " + (r != null ? r.getErrorMessage() : "null"));
      return;
    }
    String c = r.getDecompiledFunction().getC();
    println("=== FULL DECOMPILE, " + c.length() + " chars ===");
    println(c);
    println("=== END FULL DECOMPILE ===");
  }
}

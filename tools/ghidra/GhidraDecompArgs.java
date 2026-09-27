//@category Octatrack
// Session 10 (AR). Decompile + list every function whose entry address is given on the
// command line (hex, with or without 0x). Creates the function first if Ghidra has none
// there. Prints, per function: callers, decompiled C (or the failure), then the raw
// listing -- the listing matters because Ghidra's ColdFire decompiler drops or garbles
// mvs/mvz/divsl in places, and the big sequencer ISR needs to be read instruction by
// instruction anyway.
//
// Usage: analyzeHeadless ... -postScript GhidraDecompArgs.java 0x4009905c 0x4009a5b0 ...
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDecompArgs extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    FunctionManager fm = currentProgram.getFunctionManager();
    ReferenceManager rm = currentProgram.getReferenceManager();
    Listing lst = currentProgram.getListing();
    DecompInterface dec = new DecompInterface();
    dec.openProgram(currentProgram);
    ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

    for (String arg : getScriptArgs()) {
      long va = Long.parseLong(arg.replace("0x", ""), 16);
      Address a = sp.getAddress(va);
      Function f = fm.getFunctionAt(a);
      if (f == null) {
        try {
          disassemble(a);
          f = createFunction(a, "FUN_" + Long.toHexString(va));
        } catch (Exception e) {
          println("#### 0x" + Long.toHexString(va) + ": could not create function: " + e);
          continue;
        }
        if (f == null) { println("#### 0x" + Long.toHexString(va) + ": createFunction returned null"); continue; }
      }
      println("");
      println("################ " + f.getName() + " @ 0x" + Long.toHexString(va)
              + "  body=" + f.getBody().getNumAddresses() + " B  ################");
      TreeSet<String> callers = new TreeSet<>();
      ReferenceIterator ri = rm.getReferencesTo(f.getEntryPoint());
      while (ri.hasNext()) {
        Reference r = ri.next();
        Function c = fm.getFunctionContaining(r.getFromAddress());
        callers.add(String.format("%s@%08x[%s]", c != null ? c.getName() : "?", r.getFromAddress().getOffset(), r.getReferenceType()));
      }
      println("callers: " + callers);
      println("---- decompiled C ----");
      var res = dec.decompileFunction(f, 120, mon);
      if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
      else println("(decompile failed: " + (res != null ? res.getErrorMessage() : "no result") + ")");
      println("---- listing ----");
      InstructionIterator it = lst.getInstructions(f.getBody(), true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        StringBuilder b = new StringBuilder();
        for (byte x : ins.getBytes()) b.append(String.format("%02x", x & 0xff));
        println(String.format("%08x  %-14s %s", ins.getAddress().getOffset(), b, ins.toString()));
      }
    }
    println("[GhidraDecompArgs] done.");
  }
}

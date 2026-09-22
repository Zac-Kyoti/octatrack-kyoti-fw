//@category Octatrack
// Session 70, 11th pass: real cross-reference search for FUN_400a536c's output
// (0x46107959[track], 8-byte per-track array), now that full auto-analysis has
// populated the Reference/Constant-Propagation tables for the first time in this
// project's history. Also widens the search to the surrounding memory (a wider
// field could hold a sub-step phase, per the new LED-observation finding) and
// dumps FUN_400a536c itself plus every function referencing it directly.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDirectJump6 extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  ReferenceManager rm;
  Set<Long> dumped = new HashSet<>();

  void dumpFn(long s, String tag) throws Exception {
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionContaining(a);
    if (f == null) { try { disassemble(a); } catch (Exception e) {} f = createFunction(a, null); }
    if (f == null) { println("[!] no fn @ " + Long.toHexString(s) + " (" + tag + ")"); return; }
    if (!dumped.add(f.getEntryPoint().getOffset())) return;
    DecompileResults r = dec.decompileFunction(f, 200, mon);
    println("\n############ " + tag + " :: " + f.getName() + " @ " + f.getEntryPoint()
      + " (size " + f.getBody().getNumAddresses() + ") ############");
    String c = (r != null && r.decompileCompleted()) ? r.getDecompiledFunction().getC()
      : "  (decompile failed: " + (r != null ? r.getErrorMessage() : "null") + ")";
    if (c.length() > 9000) c = c.substring(0, 9000) + "\n  ...(truncated)";
    println(c);
  }

  void xrefRange(long lo, long hi, String label) throws Exception {
    println("\n=== XRefs to " + label + " [" + Long.toHexString(lo) + ".." + Long.toHexString(hi) + "] ===");
    for (long addr = lo; addr <= hi; addr++) {
      Address a = sp.getAddress(addr);
      ReferenceIterator it = rm.getReferencesTo(a);
      while (it.hasNext()) {
        Reference ref = it.next();
        Address from = ref.getFromAddress();
        Function f = fm.getFunctionContaining(from);
        println("  " + Long.toHexString(addr) + " <- " + from
          + "  (" + ref.getReferenceType() + ")  in "
          + (f != null ? f.getName() + "@" + f.getEntryPoint() : "???"));
        if (f != null) dumpFn(f.getEntryPoint().getOffset(), "xref to " + Long.toHexString(addr));
      }
    }
  }

  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    rm = currentProgram.getReferenceManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();

    // 1. FUN_400a536c itself, and everyone who calls it.
    dumpFn(0x400a536cL, "FUN_400a536c (the 2-insn stub)");
    Address fnAddr = sp.getAddress(0x400a536cL);
    Function fn = fm.getFunctionContaining(fnAddr);
    if (fn != null) {
      println("\n=== Callers of FUN_400a536c ===");
      ReferenceIterator it = rm.getReferencesTo(fn.getEntryPoint());
      while (it.hasNext()) {
        Reference ref = it.next();
        Address from = ref.getFromAddress();
        Function caller = fm.getFunctionContaining(from);
        println("  called from " + from + " in "
          + (caller != null ? caller.getName() + "@" + caller.getEntryPoint() : "???"));
        if (caller != null) dumpFn(caller.getEntryPoint().getOffset(), "caller of FUN_400a536c");
      }
    }

    // 2. The output byte array itself, 8 tracks + a little slack either side,
    //    in case the real consumer reads adjacent/wider fields.
    xrefRange(0x46107950L, 0x46107968L, "0x46107959 track-output vicinity");

    println("\n[GhidraDirectJump6] done.");
  }
}

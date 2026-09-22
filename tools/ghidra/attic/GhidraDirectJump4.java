//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDirectJump4 extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  Listing lst; ReferenceManager rm;
  Set<Long> dumped = new HashSet<>();
  void dumpFn(long s, String tag) throws Exception {
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionContaining(a);
    if (f == null) { disassemble(a); f = createFunction(a, null); }
    if (f == null) { println("[!] no fn @ "+Long.toHexString(s)+" ("+tag+")"); return; }
    if (!dumped.add(f.getEntryPoint().getOffset())) return;
    DecompileResults r = dec.decompileFunction(f, 200, mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()
      +" (size "+f.getBody().getNumAddresses()+") ############");
    String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC()
      : "  (decompile failed: "+(r!=null?r.getErrorMessage():"null")+")";
    if (c.length() > 11000) c = c.substring(0,11000)+"\n  ...(truncated)";
    println(c);
  }
  void callers(long s, String tag) {
    println("\n==== callers of "+Long.toHexString(s)+" ("+tag+") ====");
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionAt(a);
    if (f==null) { println("  no fn"); return; }
    for (Function c : f.getCallingFunctions(mon))
      println("  "+c.getName()+" @ "+c.getEntryPoint());
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    lst = currentProgram.getListing();
    rm = currentProgram.getReferenceManager();
    callers(0x400a0570L, "cue-pattern primitive?");
    dumpFn(0x400a0570L, "FUN_400a0570 cue-pattern primitive");
    dumpFn(0x4004a654L, "caller of 400a0570 (pattern-key UI?)");
    callers(0x400a0ef8L, "chain-after arm");
    callers(0x4009f6f0L, "46c8028a clear (reload finish)");
    // who SETS _DAT_46c8028a (the immediate reload flag)  -- byte 0x46c8028a
    println("\n==== refs to 46c8028a ====");
    var ri = rm.getReferencesTo(sp.getAddress(0x46c8028aL));
    while (ri.hasNext()) { Reference rf=ri.next(); Instruction in=lst.getInstructionAt(rf.getFromAddress());
      Function f=fm.getFunctionContaining(rf.getFromAddress());
      println("  "+rf.getFromAddress()+"  "+(in!=null?in:"?")+"  "+(f!=null?f.getName():"(no fn)")+"  "+rf.getReferenceType()); }
    dumpFn(0x400a2500L, "step-engine region reading 46c8028a (400a2532)");
    println("\n[GhidraDirectJump4] done.");
  }
}

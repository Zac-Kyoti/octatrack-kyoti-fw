//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraDirectJump5 extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
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
    if (c.length() > 9000) c = c.substring(0,9000)+"\n  ...(truncated)";
    println(c);
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    dumpFn(0x4009c66eL, "pending->active consumer?");
    dumpFn(0x4009c430L, "8000668b host");
    dumpFn(0x400a1206L, "step-engine pending read region");
    println("\n[GhidraDirectJump5] done.");
  }
}

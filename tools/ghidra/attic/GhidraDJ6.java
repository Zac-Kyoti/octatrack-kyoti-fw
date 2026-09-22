//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraDJ6 extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp; Listing lst; ReferenceManager rm;
  Set<Long> dumped = new HashSet<>();
  void dumpFn(long s, String tag) throws Exception {
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionContaining(a);
    if (f == null) { disassemble(a); f = createFunction(a, null); }
    if (f == null) { println("[!] no fn @ "+Long.toHexString(s)+" ("+tag+")"); return; }
    if (!dumped.add(f.getEntryPoint().getOffset())) { println("(dup "+f.getName()+" for "+tag+")"); return; }
    DecompileResults r = dec.decompileFunction(f, 240, mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()+" (size "+f.getBody().getNumAddresses()+") ############");
    String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC() : "  (fail: "+(r!=null?r.getErrorMessage():"null")+")";
    if (c.length() > 16000) c = c.substring(0,16000)+"\n  ...(truncated)";
    println(c);
  }
  void callers(long s, String tag) {
    println("\n==== callers of "+Long.toHexString(s)+" ("+tag+") ====");
    Function f = fm.getFunctionContaining(sp.getAddress(s));
    if (f==null){ println("  no fn"); return; }
    println("  (containing fn "+f.getName()+" @ "+f.getEntryPoint()+")");
    for (Function c : f.getCallingFunctions(mon)) {
      println("  <- "+c.getName()+" @ "+c.getEntryPoint());
    }
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    dec=new DecompInterface(); dec.openProgram(currentProgram); mon=new ConsoleTaskMonitor();
    lst=currentProgram.getListing(); rm=currentProgram.getReferenceManager();
    // real function boundaries
    for(long a : new long[]{0x400a1030L,0x400a10d2L,0x400a10c8L,0x4009c634L,0x4009b8f0L,0x4009baa0L,0x400a0ef8L,0x400a0570L}){
      Function f=fm.getFunctionContaining(sp.getAddress(a));
      println("fn containing "+Long.toHexString(a)+" = "+(f!=null?f.getName()+" @ "+f.getEntryPoint()+" size "+f.getBody().getNumAddresses():"NONE"));
    }
    callers(0x400a0570L,"cue primitive");
    callers(0x400a1030L,"commit-to-active");
    callers(0x400a0ef8L,"arm countdown 80006688");
    callers(0x4009c634L,"cue-queue builder");
    dumpFn(0x400a1030L,"FUN_400a1030 commit-to-active (does it zero 800065b4?)");
    dumpFn(0x400a10c8L,"step-engine boundary handler (real fn @ ~400a10c8)");
    println("\n[GhidraDJ6] done.");
  }
}

//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDirectJump3 extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  Set<Long> dumped = new HashSet<>();
  void dumpFn(long s, String tag) throws Exception {
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionContaining(a);
    if (f == null) { disassemble(a); f = createFunction(a, null); }
    if (f == null) { println("[!] no fn @ "+Long.toHexString(s)+" ("+tag+")"); return; }
    if (!dumped.add(f.getEntryPoint().getOffset())) { println("(dup "+f.getName()+" for "+tag+")"); return; }
    DecompileResults r = dec.decompileFunction(f, 200, mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()
      +" (size "+f.getBody().getNumAddresses()+") ############");
    String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC()
      : "  (decompile failed: "+(r!=null?r.getErrorMessage():"null")+")";
    if (c.length() > 12000) c = c.substring(0,12000)+"\n  ...(truncated)";
    println(c);
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    dumpFn(0x400a0e70L, "reads/writes 80006688 (CHAIN AFTER count -> countdown)");
    dumpFn(0x400a100cL, "reads/writes 80006688");
    dumpFn(0x4009ba46L, "writes 80006688");
    dumpFn(0x4009f774L, "46c8028a immediate-reload flag");
    dumpFn(0x4000aea8L, "reads 46c8028a near frame");
    dumpFn(0x400a13d8L, "reads 46c8028a");
    dumpFn(0x4009baa0L, "FUN around 4009ba46/bae2 - transport/pattern control");
    // config value consumer: search STATES-section handler for CHAIN behavior
    dumpFn(0x400a0d80L, "near 400a0e70 host");
    println("\n[GhidraDirectJump3] done.");
  }
}

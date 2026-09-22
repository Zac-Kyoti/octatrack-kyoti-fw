//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDirectJump2 extends GhidraScript {
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
    if (c.length() > 14000) c = c.substring(0,14000)+"\n  ...(truncated)";
    println(c);
  }
  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    dumpFn(0x4004b042L, "pattern-select UI (writes 800065bc queued-pat?)");
    dumpFn(0x40061950L, "event loop pattern-commit region");
    dumpFn(0x4009bb2cL, "arms 80006687 countdown");
    dumpFn(0x4009bc00L, "arms 80006514 countdown");
    dumpFn(0x400a1f74L, "reads 80006687 (in step engine caller?)");
    dumpFn(0x4009b5c8L, "FUN_4009b5c8 plays-free start");
    dumpFn(0x4000ae12L, "reads 800065bc near frame");
    dumpFn(0x400258eaL, "reads 800065bc");
    dumpFn(0x40007f16L, "reads 800065bc");
    dumpFn(0x400866c4L, "config parser (PATTERN_CHANGE_CHAIN_BEHAVIOR)");
    println("\n[GhidraDirectJump2] done.");
  }
}

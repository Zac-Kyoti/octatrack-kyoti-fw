//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraDJ7 extends GhidraScript {
  AddressSpace sp; FunctionManager fm; Listing lst; ReferenceManager rm; DecompInterface dec; ConsoleTaskMonitor mon;
  void asmDump(long lo, long hi) {
    Address a = sp.getAddress(lo);
    InstructionIterator it = lst.getInstructions(a, true);
    while (it.hasNext()) {
      Instruction in = it.next();
      if (in.getAddress().getOffset() > hi) break;
      byte[] b; try { b = in.getBytes(); } catch(Exception e){ b=new byte[0]; }
      StringBuilder hx = new StringBuilder();
      for (byte x : b) hx.append(String.format("%02x", x));
      println(String.format("  %s: %-14s %s", in.getAddress(), hx.toString(), in.toString()));
    }
  }
  void refs(long target, String tag) {
    println("\n==== refs to "+Long.toHexString(target)+" ("+tag+") ====");
    var ri = rm.getReferencesTo(sp.getAddress(target));
    boolean any=false;
    while (ri.hasNext()) {
      Reference rf = ri.next(); any=true;
      Instruction in = lst.getInstructionAt(rf.getFromAddress());
      Function f = fm.getFunctionContaining(rf.getFromAddress());
      println("  "+rf.getFromAddress()+"  "+(in!=null?in:"?")+"  ["+rf.getReferenceType()+"]  "+(f!=null?f.getName()+" @"+f.getEntryPoint():"(no fn)"));
    }
    if(!any) println("  (no ref DB entries)");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    lst=currentProgram.getListing(); rm=currentProgram.getReferenceManager();
    dec=new DecompInterface(); dec.openProgram(currentProgram); mon=new ConsoleTaskMonitor();

    println("######## FUN_400a0570 full ASM (0x400a0570..0x400a0732) ########");
    asmDump(0x400a0570L, 0x400a0732L);

    refs(0x46c8028aL, "immediate-reload flag");
    refs(0x80006687L, "CHAIN countdown");
    refs(0x80006688L, "CHAIN countdown reload value");
    refs(0x80006514L, "2nd countdown");
    refs(0x800065b4L, "MASTER STEP POS");

    // whole-image immediate/absolute scan for these (ref DB may be empty)
    println("\n######## instruction scan: any op touching 0x46c8028a / 0x800065b4 ########");
    InstructionIterator it = lst.getInstructions(true);
    while (it.hasNext()) {
      Instruction in = it.next();
      String s = in.toString();
      if (s.contains("46c8028a") || s.contains("800065b4") || s.contains("8006687") || s.contains("80006688")) {
        Function f = fm.getFunctionContaining(in.getAddress());
        byte[] b; try{b=in.getBytes();}catch(Exception e){b=new byte[0];}
        StringBuilder hx=new StringBuilder(); for(byte x:b) hx.append(String.format("%02x",x));
        println(String.format("  %s %-12s %-40s %s", in.getAddress(), hx, s, f!=null?f.getName():"(no fn)"));
      }
    }
    println("\n[GhidraDJ7] done.");
  }
}

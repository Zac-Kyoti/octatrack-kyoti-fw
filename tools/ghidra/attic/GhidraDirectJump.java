//@category Octatrack
// Feasibility RE for a "DIRECT JUMP" pattern-change mode:
//  - who reads PATTERN_CHANGE_CHAIN_BEHAVIOR (the CHAIN AFTER setting)
//  - who writes the live/active pattern global 0x80000003
//  - the step engine / frame ISR that would (or would not) reset step position
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraDirectJump extends GhidraScript {
  DecompInterface dec; ConsoleTaskMonitor mon; FunctionManager fm; AddressSpace sp;
  Listing lst; ReferenceManager rm;
  Set<Long> dumped = new HashSet<>();

  void dumpFn(long s, String tag) throws Exception {
    Address a = sp.getAddress(s);
    Function f = fm.getFunctionContaining(a);
    if (f == null) { disassemble(a); f = createFunction(a, null); }
    if (f == null) { println("[!] no fn @ "+Long.toHexString(s)+" ("+tag+")"); return; }
    if (!dumped.add(f.getEntryPoint().getOffset())) { println("(already dumped "+f.getName()+" for "+tag+")"); return; }
    DecompileResults r = dec.decompileFunction(f, 180, mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()
      +" (size "+f.getBody().getNumAddresses()+") ############");
    String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC()
      : "  (decompile failed: "+(r!=null?r.getErrorMessage():"null")+")";
    if (c.length() > 9000) c = c.substring(0,9000)+"\n  ...(truncated)";
    println(c);
  }

  void writeXrefs(long lo, long hi, String tag) {
    println("\n==== WRITE xrefs into ["+Long.toHexString(lo)+".."+Long.toHexString(hi)+"] ("+tag+") ====");
    for (long a=lo; a<=hi; a++) {
      var ri = rm.getReferencesTo(sp.getAddress(a));
      while (ri.hasNext()) {
        Reference rf = ri.next();
        Instruction ins = lst.getInstructionAt(rf.getFromAddress());
        Function f = fm.getFunctionContaining(rf.getFromAddress());
        String s = ins!=null?ins.toString():"?";
        boolean w = rf.getReferenceType().isWrite();
        boolean interesting = w || s.startsWith("lea") || s.startsWith("movea") || s.startsWith("pea") || s.startsWith("adda");
        if (!interesting) continue;
        println(String.format("  +%d %s %-34s %-8s %s", a-lo, rf.getFromAddress(), s,
          w?"WRITE":"addr", f!=null?f.getName():"(no fn)"));
      }
    }
  }

  long findString(String needle) throws Exception {
    Memory m = currentProgram.getMemory();
    for (MemoryBlock b : m.getBlocks()) {
      if (!b.isInitialized()) continue;
      byte[] buf = new byte[(int)b.getSize()];
      b.getBytes(b.getStart(), buf);
      byte[] pat = needle.getBytes("ASCII");
      outer:
      for (int i=0; i<=buf.length-pat.length; i++) {
        for (int j=0; j<pat.length; j++) if (buf[i+j]!=pat[j]) continue outer;
        return b.getStart().getOffset() + i;
      }
    }
    return 0;
  }

  void refsToAddr(long target, String tag) throws Exception {
    println("\n==== refs to "+Long.toHexString(target)+" ("+tag+") ====");
    var ri = rm.getReferencesTo(sp.getAddress(target));
    int n=0;
    while (ri.hasNext()) {
      Reference rf = ri.next();
      Instruction ins = lst.getInstructionAt(rf.getFromAddress());
      Function f = fm.getFunctionContaining(rf.getFromAddress());
      println(String.format("  %s %-34s %s", rf.getFromAddress(),
        ins!=null?ins.toString():"?", f!=null?f.getName():"(no fn)"));
      n++;
    }
    if (n==0) println("  (none - may need scalar scan)");
  }

  void scanImm(long value, String tag) {
    println("\n==== immediate-operand scan for 0x"+Long.toHexString(value)+" ("+tag+") ====");
    InstructionIterator it = lst.getInstructions(true);
    int n=0;
    while (it.hasNext() && n<40) {
      Instruction ins = it.next();
      for (int oi=0; oi<ins.getNumOperands(); oi++) {
        Object[] ops = ins.getOpObjects(oi);
        for (Object o : ops) {
          if (o instanceof ghidra.program.model.scalar.Scalar) {
            long v = ((ghidra.program.model.scalar.Scalar)o).getUnsignedValue();
            if (v == value) {
              Function f = fm.getFunctionContaining(ins.getAddress());
              println(String.format("  %s %-34s %s", ins.getAddress(), ins.toString(),
                f!=null?f.getName():"(no fn)"));
              n++;
            }
          }
        }
      }
    }
  }

  public void run() throws Exception {
    sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    fm = currentProgram.getFunctionManager();
    dec = new DecompInterface(); dec.openProgram(currentProgram);
    mon = new ConsoleTaskMonitor();
    lst = currentProgram.getListing();
    rm = currentProgram.getReferenceManager();

    for (String s : new String[]{"PATTERN_CHANGE_CHAIN_BEHAVIOR", "CHAIN AFTER", "CHAIN BEHAVIOR", "PATTERN CHANGE"}) {
      long off = findString(s);
      println("string \""+s+"\" @ "+Long.toHexString(off));
      if (off!=0) refsToAddr(off, "str:"+s);
    }

    // live/active pattern + part globals
    writeXrefs(0x80000002L, 0x80000003L, "active part/pattern");
    // per-track pattern / part shadow arrays
    writeXrefs(0x8000182aL, 0x80001839L, "per_track_part/pattern");
    // step-engine bitmasks and step counter candidates
    writeXrefs(0x800065b0L, 0x800065c0L, "seq-stepping state (incl DAT_800065b8/be)");
    writeXrefs(0x80001810L, 0x80001824L, "tempo/phase accumulator");

    // key functions from NOTES
    dumpFn(0x4000aad0L, "frame ISR (phase accum / step advance)");
    dumpFn(0x4000c8a4L, "frame builder");
    dumpFn(0x400a1eeaL, "per-step sequencer engine");
    dumpFn(0x4009c550L, "FUN_4009c550 tempo-period-from-pattern");
    dumpFn(0x40009094L, "apply_part");
    dumpFn(0x4005a044L, "PTN key handler");

    println("\n[GhidraDirectJump] done.");
  }
}

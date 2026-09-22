//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraDJ8 extends GhidraScript {
  AddressSpace sp; FunctionManager fm; DecompInterface dec; ConsoleTaskMonitor mon; ReferenceManager rm; Listing lst;
  Set<Long> dumped=new HashSet<>();
  void dumpFn(long s,String tag) throws Exception {
    Address a=sp.getAddress(s); Function f=fm.getFunctionContaining(a);
    if(f==null){disassemble(a);f=createFunction(a,null);}
    if(f==null){println("[!] no fn @"+Long.toHexString(s));return;}
    if(!dumped.add(f.getEntryPoint().getOffset())){println("(dup "+f.getName()+")");return;}
    DecompileResults r=dec.decompileFunction(f,300,mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()+" (size "+f.getBody().getNumAddresses()+") ############");
    String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():"  (fail)";
    if(c.length()>20000)c=c.substring(0,20000)+"\n ...(trunc)";
    println(c);
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    dec=new DecompInterface(); dec.openProgram(currentProgram); mon=new ConsoleTaskMonitor();
    rm=currentProgram.getReferenceManager(); lst=currentProgram.getListing();
    // Disassemble the whole hot cluster so refs resolve
    disassemble(sp.getAddress(0x4009b400L));
    disassemble(sp.getAddress(0x4009c700L));
    // find fn boundaries
    for(long a: new long[]{0x4009b400L,0x4009b8f0L,0x4009b9ccL,0x4009bae2L,0x4009bbccL,0x4009c3f4L,0x4009c430L,0x4009c500L,0x4009c634L}){
      Function f=fm.getFunctionContaining(sp.getAddress(a));
      println("fn@"+Long.toHexString(a)+" = "+(f!=null?f.getName()+" @"+f.getEntryPoint()+" sz "+f.getBody().getNumAddresses():"NONE"));
    }
    // the sequencer msg dispatcher: decompile the big fn(s)
    dumpFn(0x4009b400L,"seq cluster head");
    dumpFn(0x4009c634L,"cue-queue builder FUN_4009c634");
    // who calls FUN_4009c634 / the 0x12 handler -- search refs
    println("\n==== refs to 4009c634 ====");
    var ri=rm.getReferencesTo(sp.getAddress(0x4009c634L));
    while(ri.hasNext()){var r=ri.next();var f=fm.getFunctionContaining(r.getFromAddress());
      println("  "+r.getFromAddress()+" ["+r.getReferenceType()+"] "+(f!=null?f.getName():"?"));}
    println("\n[GhidraDJ8] done.");
  }
}

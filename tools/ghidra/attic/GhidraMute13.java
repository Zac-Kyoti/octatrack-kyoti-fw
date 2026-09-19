// GhidraMute13.java -- who posts into FUN_40061a94's own input queue (0x460d17ae)? That
// queue's consumer loop is where the 'J' case (XOR 0x100<<track into _DAT_80000008, the
// MUTE_STATE bits hooks 9/10 actually gate on) lives. FUN_40000c3c (the generic RTOS
// queue-post primitive) takes the queue control block as param_1, so search refs to the
// queue address itself, not to FUN_40000c3c generically (too many unrelated callers).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute13 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,260,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }
    void ensure(long a){ Address ad=sp.getAddress(a); if(fm.getFunctionContaining(ad)==null){
        try{ disassemble(ad); createFunction(ad,null); }catch(Exception e){} } }
    void dumpAt(long a,String tag){
        ensure(a);
        Function f=fm.getFunctionContaining(sp.getAddress(a));
        if(f==null){println("\n// no fn @0x"+Long.toHexString(a)+" ("+tag+")");return;}
        if(!dumped.add(f.getEntryPoint().getOffset())){println("// (dup "+f.getName()+" via "+Long.toHexString(a)+")");return;}
        println("\n########## "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" (via 0x"+Long.toHexString(a)+" "+tag+") ##########");
        println(decomp(f));
    }
    void refsTo(long a,String tag){
        println("\n===== references to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> fns = new TreeSet<>();
        while(it.hasNext()){
            Reference r=it.next();
            Function cf=fm.getFunctionContaining(r.getFromAddress());
            println("  from "+r.getFromAddress()+" in "+(cf!=null?cf.getName()+"@"+cf.getEntryPoint():"NOFUNC")+" "+r.getReferenceType());
            if(cf!=null) fns.add(cf.getEntryPoint().getOffset());
        }
        for(long e: fns) dumpAt(e,"ref to "+tag);
    }
    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec=new DecompInterface(); dec.openProgram(currentProgram);
        refsTo(0x460d17aeL, "queue 0x460d17ae (FUN_40061a94's own input queue)");
        dec.dispose();
        println("\n[GhidraMute13] done.");
    }
}

// GhidraMute11.java -- part 12 handoff, option 1: find the real periodic task that syncs
// _DAT_460fab40 (the mask FUN_40083ab4 writes synchronously) into _DAT_80000008 (MUTE_STATE,
// what hooks 9/10's SHADOW state is ultimately derived from -- documented since Session 9's
// "V4" finding but never located). Query real Ghidra-resolved WRITE xrefs to 0x80000008 and
// decompile every writer, looking for one that reads _DAT_460fab40 and shifts/masks it into
// the 8+t bit position.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute11 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,220,mon);
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
    void refsTo(long a,String tag,boolean writesOnly){
        println("\n===== references to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> fns = new TreeSet<>();
        while(it.hasNext()){
            Reference r=it.next();
            boolean isWrite = r.getReferenceType().isWrite();
            if (writesOnly && !isWrite) continue;
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

        // WRITE-only refs to MUTE_STATE itself -- the sync task, if Ghidra can resolve it.
        refsTo(0x80000008L, "_DAT_80000008 (MUTE_STATE) WRITES", true);

        // Also: every ref (read+write) to _DAT_460fab40, the mask FUN_40083ab4 sets -- whatever
        // reads it (besides FUN_40083ab4 itself and FUN_400836d8) is the sync task's likely source read.
        refsTo(0x460fab40L, "_DAT_460fab40 (all refs)", false);

        dec.dispose();
        println("\n[GhidraMute11] done.");
    }
}

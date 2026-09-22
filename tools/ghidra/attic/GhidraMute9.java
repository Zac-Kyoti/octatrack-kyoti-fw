// GhidraMute9.java -- statically RE what writes 0x460d10d0/0x460d10d4 (the two tst.l-gated
// early-bailout checks inside FUN_40083ab4 found by the "part 11 addendum" real-key-path
// attempt) and decompile FUN_40083ab4 itself cleanly, since r2 chokes on part of its body.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute9 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,200,mon);
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
    void writersTo(long a,String tag){
        println("\n===== references to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> callerFns = new TreeSet<>();
        while(it.hasNext()){
            Reference r=it.next();
            Function cf=fm.getFunctionContaining(r.getFromAddress());
            println("  from "+r.getFromAddress()+" in "+(cf!=null?cf.getName()+"@"+cf.getEntryPoint():"NOFUNC")+" "+r.getReferenceType());
            if(cf!=null) callerFns.add(cf.getEntryPoint().getOffset());
        }
        for(long e: callerFns) dumpAt(e,"writer/reader of "+tag);
    }
    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        // The function itself, whose r2 disassembly hit an "invalid" opcode mid-body.
        dumpAt(0x40083ab4L, "FUN_40083ab4 itself");

        // The three key handlers emu_mute.py already attributes as writers (confirm + get full bodies).
        dumpAt(0x40030a6cL, "mh_a6c (sets _DAT_460d10d8 per emu_mute.py)");
        dumpAt(0x40030c60L, "mh_c60 (sets _DAT_460d10d4 per emu_mute.py)");
        dumpAt(0x40030e6cL, "mh_e6c (sets _DAT_460d10d0 per emu_mute.py)");

        // Real Ghidra-resolved xrefs (not a literal grep) to all three flag words + FUN_40083ab4 itself.
        writersTo(0x460d10d0L, "_DAT_460d10d0");
        writersTo(0x460d10d4L, "_DAT_460d10d4");
        writersTo(0x460d10d8L, "_DAT_460d10d8");
        writersTo(0x40083ab4L, "FUN_40083ab4 (who calls it)");

        dec.dispose();
        println("\n[GhidraMute9] done.");
    }
}

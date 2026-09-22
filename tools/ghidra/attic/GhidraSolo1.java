// GhidraSolo1.java -- the SOLO path through the per-frame mute gate FUN_40004dbc.
// Goal: does SOLO set the same _DAT_80000008 mute bits for non-soloed tracks (so the
// existing patch_softmute `pre` logic would just work), or a separate mask (_DAT_8000000c)?
// And does FUN_40004dbc's solo branch use the same DSP-frame level-word layout as the
// normal branch, so keeping those words has the same "FX inserts still reach the mix" effect?
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSolo1 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp; Listing lst;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();

    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,300,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }
    void ensure(long a){ Address ad=sp.getAddress(a); if(fm.getFunctionContaining(ad)==null){
        try{ disassemble(ad); createFunction(ad,null); }catch(Exception e){} } }
    void dumpAt(long a,String tag){
        ensure(a);
        Function f=fm.getFunctionContaining(sp.getAddress(a));
        if(f==null){println("\n// no fn @0x"+Long.toHexString(a)+" ("+tag+")");return;}
        if(!dumped.add(f.getEntryPoint().getOffset())){println("// (dup "+f.getName()+" via "+tag+")");return;}
        println("\n########## "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" (via 0x"+Long.toHexString(a)+" "+tag+") ##########");
        println(decomp(f));
    }
    void disRange(long lo,long hi,String tag){
        println("\n----- disasm "+tag+"  0x"+Long.toHexString(lo)+" .. 0x"+Long.toHexString(hi)+" -----");
        try{ disassemble(sp.getAddress(lo)); }catch(Exception e){}
        InstructionIterator it=lst.getInstructions(sp.getAddress(lo),true);
        while(it.hasNext()){ Instruction in=it.next(); if(in.getAddress().getOffset()>hi)break;
            StringBuilder bs=new StringBuilder();
            try{ for(byte b: in.getBytes()) bs.append(String.format("%02x",b&0xff)); }catch(Exception e){}
            println(String.format("  %08x  %-22s %s", in.getAddress().getOffset(), bs.toString(), in.toString())); }
    }
    void refs(long a,String tag){
        println("\n===== refs to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> writers=new TreeSet<>();
        while(it.hasNext()){ Reference r=it.next(); Function cf=fm.getFunctionContaining(r.getFromAddress());
            Instruction in=lst.getInstructionAt(r.getFromAddress());
            println(String.format("  %s  %-26s %-9s in %s", r.getFromAddress(),
                in!=null?in.toString():"(data)", r.getReferenceType(),
                cf!=null?cf.getName():"?"));
            if(cf!=null && r.getReferenceType().isWrite()) writers.add(cf.getEntryPoint().getOffset());
        }
        for(long w:writers) dumpAt(w,"writer of "+tag);
    }

    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        // 1. the per-frame mute gate -- full, both branches
        dumpAt(0x40004dbcL,"the mute gate FUN_40004dbc");
        disRange(0x40004dbcL,0x40004f40L,"FUN_40004dbc full");

        // 2. SOLO flag + candidate solo mask
        refs(0x80000037L,"SOLO_FLAG byte");
        refs(0x8000000cL,"solo mask? _DAT_8000000c");
        refs(0x80000008L,"mute mask _DAT_80000008 (writers only shown below)");

        // 3. LED painter solo branch (mirrors what counts as 'muted by solo')
        dumpAt(0x40083eb0L,"LED painter FUN_40083eb0");

        // 4. the voice-cmd queue hook target -- how does IT see mute?
        dumpAt(0x40005178L,"voice-cmd queue FUN_40005178");
        disRange(0x40005178L,0x40005230L,"FUN_40005178 head");

        dec.dispose(); println("\n[GhidraSolo1] done.");
    }
}

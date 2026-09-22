// GhidraSolo2.java -- confirm the SOLO mask layout: is _DAT_80000008 bits 0..7 the
// "this track is soloed" set?  Dump the solo key handler(s), FUN_40033970 ("solo active?"),
// and every writer that touches _DAT_80000008 with a `1<<t` (low-8) pattern.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSolo2 extends GhidraScript {
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

    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        // NOTES: _DAT_80000037 setters @0x40065172/8e, 0x400654e0/fc
        for(long a: new long[]{0x40065172L,0x4006518eL,0x400654e0L,0x400654fcL})
            dumpAt(a,"solo key handler @"+Long.toHexString(a));
        disRange(0x40065140L,0x40065260L,"solo handler A region");
        disRange(0x400654a0L,0x40065560L,"solo handler B region");

        // "is solo active" predicate used by the LED painter
        dumpAt(0x40033970L,"FUN_40033970 (solo active?)");

        // _DAT_8000000c writers (the LED-painter solo mask)  + _DAT_8000009c reader
        dumpAt(0x4004d870L,"FUN_4004d870 (called after mute-mask edits)");
        dumpAt(0x4007c428L,"FUN_4007c428 (mask transform)");
        dumpAt(0x4004d948L,"FUN_4004d948");
        dumpAt(0x4004d780L,"FUN_4004d780");

        // FUN_40005178 caller -- how the 'flag' arg (param_3) relates to mute/solo
        println("\n===== callers of FUN_40005178 =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(0x40005178L));
        TreeSet<Long> s=new TreeSet<>();
        while(it.hasNext()){ Reference r=it.next(); Function cf=fm.getFunctionContaining(r.getFromAddress());
            println("  from "+r.getFromAddress()+" in "+(cf!=null?cf.getName():"?"));
            if(cf!=null) s.add(cf.getEntryPoint().getOffset()); }
        for(long e:s) dumpAt(e,"caller of FUN_40005178");

        dec.dispose(); println("\n[GhidraSolo2] done.");
    }
}

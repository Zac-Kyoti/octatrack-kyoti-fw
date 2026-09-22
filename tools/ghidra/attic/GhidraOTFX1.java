// GhidraOTFX1.java -- Session 14: the "new OT+FX" mute mode.
// Goal: find a way to instantly silence a track's DRY contribution while (a) the FX
// insert tail still reaches MAIN and (b) the voice keeps advancing its sample cursor
// (so unmute resumes at the playhead, like stock OT).
//
// Questions:
//  1. FUN_40004db8 -- exact per-track DSP-frame word layout (dest +0/+2/+4/+6), which
//     word is MAIN, which CUE, which (if any) is a pre-insert voice level, and exactly
//     which _DAT_80000008 bit gates each.
//  2. Who FILLS the source arrays 0x80000c60 / 0x80000c80 / 0x8000485a each frame
//     (the upstream mix/voice updater) -- decompile the writers.
//  3. Who READS the frame double-buffer 0x80003c10 downstream (the DSP push) -- the
//     8-byte-per-track stride consumer.
//  4. _DAT_46c7ff64 (post-FX MAIN-out mute) -- how the frame path applies it.
//  5. FUN_400068e4 (control-rate voice updater) + FUN_40008f84 -- is there a per-voice
//     output-gain slot distinct from the AMP envelope segments?
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraOTFX1 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp; Listing lst;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();

    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,400,mon);
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
            println(String.format("  %08x  %-24s %s", in.getAddress().getOffset(), bs.toString(), in.toString())); }
    }
    void refs(long a,String tag,boolean dumpWriters){
        println("\n===== refs to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> writers=new TreeSet<>();
        int n=0;
        while(it.hasNext()){ Reference r=it.next(); Function cf=fm.getFunctionContaining(r.getFromAddress());
            Instruction in=lst.getInstructionAt(r.getFromAddress());
            println(String.format("  %s  %-30s %-9s in %s", r.getFromAddress(),
                in!=null?in.toString():"(data)", r.getReferenceType(),
                cf!=null?cf.getName():"?"));
            if(cf!=null && r.getReferenceType().isWrite()) writers.add(cf.getEntryPoint().getOffset());
            n++;
        }
        println("  ("+n+" refs, "+writers.size()+" distinct writer fns)");
        if(dumpWriters) for(long w:writers) dumpAt(w,"writer of "+tag);
    }

    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        // 1. the per-frame mute gate -- decompile + FULL byte-level disasm
        dumpAt(0x40004db8L,"the mute gate FUN_40004db8");
        disRange(0x40004db8L,0x40004f42L,"FUN_40004db8 full (both branches + tail)");

        // 2. who fills the three source arrays each frame
        refs(0x80000c60L,"src array A (dest+2 gate=bit t / dest+6-ish)",true);
        refs(0x80000c80L,"src array B (dest+4, UNGATED)",true);
        refs(0x8000485aL,"src array C (dest+6, UNGATED, stride 8)",true);

        // 3. downstream: who consumes the frame double-buffer
        refs(0x80003c10L,"frame double-buffer base _DAT_80003c10",false);
        refs(0x80004800L,"frame flip index _DAT_80004800",false);
        refs(0x800000e0L,"_DAT_800000e0 (frame region selector)",false);

        // 4. post-FX MAIN-out mute mask + its frame-path consumers
        refs(0x46c7ff64L,"_DAT_46c7ff64 post-FX MAIN-out silence",true);
        dumpAt(0x4000c8a4L,"frame_builder FUN_4000c8a4 (reads 46c7ff64 @0x4000c93e)");
        disRange(0x4000c920L,0x4000c960L,"frame_builder around the 46c7ff64 gate");

        // 5. voice updater + note-off primitive -- per-voice gain vs env segments
        dumpAt(0x400068e4L,"control-rate voice updater FUN_400068e4");
        dumpAt(0x40008f84L,"per-track note-off FUN_40008f84");

        dec.dispose(); println("\n[GhidraOTFX1] done.");
    }
}

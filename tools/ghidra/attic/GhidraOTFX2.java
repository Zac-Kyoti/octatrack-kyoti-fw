// GhidraOTFX2.java -- Session 14: identify the three FUN_40004db8 source arrays.
// Byte-search found non-FUN_40004db8 code touching each:
//   0x80000c60 (array A): 0x4000d6d6
//   0x80000c80 (array B): 0x40000e8c (init), 0x4000cc78, 0x4000cd66
//   0x8000485a (array C): 0x40004c10, 0x40000e8c?
//   frame ptr 0x80003c10 readers: 0x4000ac28, 0x4000d16c, 0x4000d1a8, 0x4000d2e8, 0x4000d984
// Decompile the containing functions so we can label A/B/C = MAIN level / CUE / voice level / pan.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraOTFX2 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp; Listing lst;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();

    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,400,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }
    void dumpAt(long a,String tag){
        Address ad=sp.getAddress(a);
        if(fm.getFunctionContaining(ad)==null){ try{ disassemble(ad); createFunction(ad,null);}catch(Exception e){} }
        Function f=fm.getFunctionContaining(ad);
        if(f==null){println("\n// no fn @0x"+Long.toHexString(a)+" ("+tag+")");return;}
        if(!dumped.add(f.getEntryPoint().getOffset())){println("// (dup "+f.getName()+" via "+tag+")");return;}
        println("\n########## "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" (via 0x"+Long.toHexString(a)+" "+tag+") ##########");
        println(decomp(f));
    }
    // manual PC-walk disassembler (disRange via InstructionIterator was empty under -noanalysis)
    void disWalk(long lo,long hi,String tag){
        println("\n----- disWalk "+tag+"  0x"+Long.toHexString(lo)+" .. 0x"+Long.toHexString(hi)+" -----");
        long a=lo;
        while(a<hi){
            Address ad=sp.getAddress(a);
            try{ disassemble(ad); }catch(Exception e){}
            Instruction in=lst.getInstructionAt(ad);
            if(in==null){ println(String.format("  %08x  <no insn>", a)); a+=2; continue; }
            StringBuilder bs=new StringBuilder();
            try{ for(byte b: in.getBytes()) bs.append(String.format("%02x",b&0xff)); }catch(Exception e){}
            println(String.format("  %08x  %-24s %s", a, bs.toString(), in.toString()));
            a += in.getLength();
        }
    }

    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        disWalk(0x40004db8L,0x40004f42L,"FUN_40004db8 (the mute gate) full");

        dumpAt(0x4000d6d6L,"toucher of array A 0x80000c60");
        dumpAt(0x4000cc78L,"toucher of array B 0x80000c80 (a)");
        dumpAt(0x4000cd66L,"toucher of array B 0x80000c80 (b)");
        dumpAt(0x40000e8cL,"init toucher of array B/C");
        dumpAt(0x40004c10L,"toucher of array C 0x8000485a (just above the gate)");

        dumpAt(0x4000ac28L,"frame-ptr reader 0x4000ac28");
        dumpAt(0x4000d16cL,"frame-ptr reader 0x4000d16c");
        dumpAt(0x4000d1a8L,"frame-ptr reader 0x4000d1a8");
        dumpAt(0x4000d2e8L,"frame-ptr reader 0x4000d2e8");
        dumpAt(0x4000d984L,"frame-ptr reader 0x4000d984");

        dec.dispose(); println("\n[GhidraOTFX2] done.");
    }
}

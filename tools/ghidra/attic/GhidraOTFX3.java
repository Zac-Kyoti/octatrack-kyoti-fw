// GhidraOTFX3.java -- Session 14: the per-voice pre-FX amp array 0x46c7ff42.
// FUN_400068e4 returns the per-voice amp level (struct+0x18); a caller stores it per voice
// into an array at 0x46c7ff42 (stride 4, 8 voices), right below _DAT_46c7ff64 (post-FX MAIN
// mute).  Byte-search: 0x46c7ff42 referenced at 0x400015de, 0x4000d31c, 0x4000f894.
// Decompile the real containing functions + trace what 0x46c7ff42 feeds (the DSP frame push).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraOTFX3 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp; Listing lst;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();

    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,600,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }

    // find the real enclosing function without creating a bogus one
    Function enclosing(long a){
        Address ad=sp.getAddress(a);
        Function f=fm.getFunctionContaining(ad);
        if(f!=null) return f;
        // walk backwards up to 0x800 bytes for a defined function start
        for(long b=a; b>a-0x1000; b-=2){
            Function g=fm.getFunctionAt(sp.getAddress(b));
            if(g!=null) return g;
        }
        return null;
    }
    void dumpAt(long a,String tag){
        Function f=enclosing(a);
        if(f==null){println("\n// no enclosing fn for 0x"+Long.toHexString(a)+" ("+tag+")");return;}
        if(!dumped.add(f.getEntryPoint().getOffset())){println("// (dup "+f.getName()+" via "+tag+")");return;}
        println("\n########## "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()
                +"  [target 0x"+Long.toHexString(a)+" = "+tag+"] ##########");
        println(decomp(f));
    }
    void refs(long a,String tag){
        println("\n===== refs to 0x"+Long.toHexString(a)+" ("+tag+") =====");
        ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        while(it.hasNext()){ Reference r=it.next();
            Function cf=fm.getFunctionContaining(r.getFromAddress());
            Instruction in=lst.getInstructionAt(r.getFromAddress());
            println(String.format("  %s  %-30s %-9s in %s", r.getFromAddress(),
                in!=null?in.toString():"(data)", r.getReferenceType(), cf!=null?cf.getName():"?"));
        }
    }

    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        dumpAt(0x4000d16cL,"per-frame DSP frame fill / voice loop");
        dumpAt(0x4000d31cL,"stores FUN_400068e4 return -> 0x46c7ff42");
        dumpAt(0x4000f894L,"other 0x46c7ff42 toucher");
        dumpAt(0x400015deL,"init/other 0x46c7ff42 toucher");
        refs(0x46c7ff42L,"per-voice pre-FX amp array");

        // where does the frame region 0x46c7ff42 sits in get pushed to the DSP?
        refs(0x46c7ff00L,"frame region base-ish 0x46c7ff00");
        dumpAt(0x4000b936L,"voice-cmd gate reading 46c7ff64 @0x4000b936");

        dec.dispose(); println("\n[GhidraOTFX3] done.");
    }
}

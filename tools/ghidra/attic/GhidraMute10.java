// GhidraMute10.java -- follow-up to GhidraMute9: FUN_40083ab4 turned out to NOT gate its
// mute-apply logic on _DAT_460d10d0/d4 at all (both branches converge and always apply the
// mute) -- so the D0=0x8 "argument-independent gate" the real-key-path test hit must come
// from somewhere else. FUN_40083208 runs FIRST, unconditionally, before either tst.l -- check
// it (and FUN_40033970, called in the special block) as the more likely source.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute10 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,200,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }
    void ensure(long a){ Address ad=sp.getAddress(a); if(fm.getFunctionContaining(ad)==null){
        try{ disassemble(ad); createFunction(ad,null); }catch(Exception e){} } }
    void dumpAt(long a,String tag){
        ensure(a);
        Function f=fm.getFunctionContaining(sp.getAddress(a));
        if(f==null){println("\n// no fn @0x"+Long.toHexString(a)+" ("+tag+")");return;}
        println("\n########## "+f.getName()+" @"+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()+" (via 0x"+Long.toHexString(a)+" "+tag+") ##########");
        println(decomp(f));
    }
    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec=new DecompInterface(); dec.openProgram(currentProgram);
        dumpAt(0x40083208L,"FUN_40083208 -- called unconditionally, first thing, in FUN_40083ab4");
        dumpAt(0x40033970L,"FUN_40033970 -- called in FUN_40083ab4's special uVar1==DAT_100b14cc block");
        dumpAt(0x40033998L,"FUN_40033998 -- gate at top of FUN_400836d8 (0x40033998 from emu_mute.py's g_33998)");
        dumpAt(0x40033990L,"FUN_40033990 -- gate at top of FUN_400836d8 (g_33990)");
        dec.dispose();
        println("\n[GhidraMute10] done.");
    }
}

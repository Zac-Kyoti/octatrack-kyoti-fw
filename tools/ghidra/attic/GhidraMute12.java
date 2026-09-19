// GhidraMute12.java -- follow-up to GhidraMute11's big find: _DAT_80000008's mute bits are
// NOT synced from _DAT_460fab40 by a periodic task at all -- they're toggled by a KERNEL
// EVENT ('J', subcase 0, XOR 0x100<<track) inside FUN_40061a94's giant message-dispatch
// switch, completely independent of _DAT_460fab40/FUN_40083ab4/FUN_400836d8. So the real
// per-key dispatcher must POST that event separately from calling FUN_40083ab4. Decompile
// FUN_40040250 (the real "single press -> mute" top-level handler, per original Session-9
// docs) in full to see whether/how it does both.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute12 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,300,mon);
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
        dumpAt(0x40040250L,"FUN_40040250 -- real top-level track-key dispatcher (Session-9 docs)");
        dumpAt(0x40000c3cL,"FUN_40000c3c -- kernel event post (emu_mute.py's f_00c3c, 'STUB' per that file's own comment)");
        dumpAt(0x40061a94L,"FUN_40061a94 -- the big message-dispatch switch itself (context around the 'J' case)");
        dec.dispose();
        println("\n[GhidraMute12] done.");
    }
}

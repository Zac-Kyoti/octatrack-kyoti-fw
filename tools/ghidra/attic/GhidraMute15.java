// GhidraMute15.java -- part 15/16 follow-up: decompile FUN_4000f450 in full (the shared
// FLEX/STATIC per-trig handler, downstream of hook 9's own gate at 0x4000d498) to find its
// own reuse-vs-fresh-bind decision, and check FUN_40008f84 (the note-off/soft-release
// primitive) + the watchdog force-free call chain, against real hardware data:
//   - mute right after a REUSE trig (same/default sample): "echo" cycles for ~2 pattern
//     cycles, correctly reflects pitch/VOL p-locks, ignores sample-lock p-locks.
//   - mute right after a FRESH-BIND trig (different sample), with a LATER fresh-bind trig
//     still to come: that later trig echoes exactly ONCE, no cycling.
//   - mute right after a FRESH-BIND trig with NOTHING after it before mute: no echo at all.
// Need the real decompile to explain the asymmetry between the last two cases, not more
// speculation.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute15 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,300,mon);
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
    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec=new DecompInterface(); dec.openProgram(currentProgram);

        dumpAt(0x4000f450L, "FUN_4000f450 -- shared FLEX/STATIC per-trig handler, reuse-vs-fresh-bind decision");
        dumpAt(0x40008f84L, "FUN_40008f84 -- soft-release/note-off primitive, arms the 45-frame watchdog");
        dumpAt(0x40000ee0L, "FUN_40000ee0 -- voice active-state query (0/1/2), watchdog checks ==2");
        dumpAt(0x40006844L, "FUN_40006844 -- FUN_40006820's real per-track work (SR raise, arena-slot clear, FUN_4000672c)");
        dumpAt(0x4000672cL, "FUN_4000672c -- the actual 'start the voice' call fresh_bind's real work ends in");

        dec.dispose();
        println("\n[GhidraMute15] done.");
    }
}

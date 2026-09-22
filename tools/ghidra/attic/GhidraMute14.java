// GhidraMute14.java -- part 13 continued: the diag_echo_realkey.py return-address
// instrumentation found BOTH of the 2 leaked fresh_bind dispatches came from the exact same
// call site, 0x40008110 (jsr 0x40006820), return address 0x40008114 -- a real caller not in
// patch_softmute.s's own "SEVEN callers" list for FUN_40006820 (not a coverage gap for hook
// 10, which gates the function's own entry regardless of caller count, but worth knowing
// what this caller IS). Decompile its containing function to understand why it might call
// fresh_bind(track=1) twice within a single frame.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraMute14 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    String decomp(Function f){ try{ DecompileResults dr=dec.decompileFunction(f,260,mon);
        if(dr!=null&&dr.getDecompiledFunction()!=null) return dr.getDecompiledFunction().getC(); }catch(Exception e){} return "  <fail>"; }
    public void run() throws Exception {
        fm=currentProgram.getFunctionManager();
        sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec=new DecompInterface(); dec.openProgram(currentProgram);
        Address a = sp.getAddress(0x40008114L);
        Function f = fm.getFunctionContaining(a);
        if (f == null) { println("no function contains 0x40008114"); return; }
        println("########## " + f.getName() + " @" + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses() + " ##########");
        println(decomp(f));

        // who calls THIS function? (i.e. what's upstream of the double-dispatch)
        println("\n===== callers of " + f.getName() + " @" + f.getEntryPoint() + " =====");
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        TreeSet<Long> callers = new TreeSet<>();
        while (it.hasNext()) {
            Reference r = it.next();
            Function cf = fm.getFunctionContaining(r.getFromAddress());
            println("  from " + r.getFromAddress() + " in " + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "NOFUNC") + " " + r.getReferenceType());
            if (cf != null) callers.add(cf.getEntryPoint().getOffset());
        }
        for (long ca : callers) {
            Function cf = fm.getFunctionAt(sp.getAddress(ca));
            if (cf == null) continue;
            println("\n########## caller " + cf.getName() + " @" + cf.getEntryPoint() + " size=" + cf.getBody().getNumAddresses() + " ##########");
            println(decomp(cf));
        }
        dec.dispose();
        println("\n[GhidraMute14] done.");
    }
}

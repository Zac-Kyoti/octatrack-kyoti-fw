// GhidraSoloMix7.java -- hardware says the solo cut is INSTANT and kills FX tails, and
// addendum 9 proved it is not stock's solo branch in FUN_40004dbc. But that function does
// not INVENT the per-track level words -- it COPIES them from source tables:
//     0x40004dd6  lea 0x80000c60,%a3   ; mvzw (%a3)+ -> word A, word B per track
//     0x40004ddc  lea 0x80000c80,%a2
//     0x40004de2  lea 0x8000485a,%a1
// If the solo gesture zeroes a SOURCE entry for the non-soloed tracks, the builder copies
// zeros faithfully, the cut is instant and post-FX, and no amount of D5 manipulation in
// hook 1 can prevent it. Find every writer of those tables.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSoloMix7 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    void scan(long base, int len, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        println("\n===== writers into " + tag + " (0x" + Long.toHexString(base)
                + " .. +0x" + Integer.toHexString(len) + ") =====");
        TreeSet<Long> fns = new TreeSet<>();
        for (int off = 0; off < len; off += 2) {
            ReferenceIterator it = currentProgram.getReferenceManager()
                    .getReferencesTo(sp.getAddress(base + off));
            while (it.hasNext()) {
                Reference r = it.next();
                Function cf = fm.getFunctionContaining(r.getFromAddress());
                println("  +0x" + Integer.toHexString(off) + "  " + r.getFromAddress() + " "
                        + r.getReferenceType() + " in "
                        + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "NOFUNC"));
                if (cf != null && r.getReferenceType().isWrite()) fns.add(cf.getEntryPoint().getOffset());
            }
        }
        for (long e : fns) {
            if (!dumped.add(e)) continue;
            Function f = fm.getFunctionContaining(sp.getAddress(e));
            println("\n########## " + f.getName() + " @" + f.getEntryPoint()
                    + " size=" + f.getBody().getNumAddresses() + " ##########");
            try { println(dec.decompileFunction(f, 300, mon).getDecompiledFunction().getC()); }
            catch (Exception ex) { println("  <decompile failed>"); }
        }
    }
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        scan(0x80000c60L, 0x20, "level source table A");
        scan(0x80000c80L, 0x20, "level source table B");
        scan(0x8000485aL, 0x40, "the third source (a1, stride 8)");
        dec.dispose();
    }
}

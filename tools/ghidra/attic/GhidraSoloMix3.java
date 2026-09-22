// GhidraSoloMix3.java -- who sets the two cue/solo mode flags?
//   0x80000034 -- gates an extra DSP-frame write (0x40004d8c, ORs 0x600 into the frame word)
//                 and gates FUN_4007c428's solo-aggregate transform.
//   0x80000037 -- SOLO_FLAG, the frame builder's own solo/not-solo branch.
// The user's gesture is MIXER then CUE+TRIG, so one of these setters should sit in the
// MIXER screen's key handling.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSoloMix3 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();
    void refs(long a, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        println("\n===== references to 0x" + Long.toHexString(a) + " (" + tag + ") =====");
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        TreeSet<Long> fns = new TreeSet<>();
        int n = 0;
        while (it.hasNext()) {
            Reference r = it.next(); n++;
            Function cf = fm.getFunctionContaining(r.getFromAddress());
            println("  " + r.getFromAddress() + "  " + r.getReferenceType() + "  in "
                    + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "NOFUNC"));
            if (cf != null && r.getReferenceType().isWrite()) fns.add(cf.getEntryPoint().getOffset());
        }
        println("  total refs " + n + ", " + fns.size() + " distinct WRITER function(s)");
        for (long e : fns) {
            if (!dumped.add(e)) continue;
            Function f = fm.getFunctionContaining(sp.getAddress(e));
            println("\n##### " + f.getName() + " @" + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses() + " #####");
            try { println(dec.decompileFunction(f, 240, mon).getDecompiledFunction().getC()); }
            catch (Exception ex) { println("  <fail>"); }
        }
    }
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        refs(0x80000034L, "cue/solo MODE flag");
        refs(0x80000037L, "SOLO_FLAG");
        dec.dispose();
    }
}

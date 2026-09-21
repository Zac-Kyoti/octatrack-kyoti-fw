// GhidraSoloMix5.java -- the user's second route to SOLO: FUNC+UP/DOWN -> "QUICK MUTE" trig
// mode, then CUE+TRIG on the grid. Part 15 already established QUICK MUTE and FUNC+TRACK
// behave identically, and part 12 mapped the mute-UI cluster (the 9 functions referencing
// _DAT_460fab40). So the SOLO branch should be a sibling of FUN_40083ab4 inside that same
// cluster, taken when CUE is held. Dump the whole cluster and read it.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSoloMix5 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    void dump(long a, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Function f = currentProgram.getFunctionManager().getFunctionContaining(sp.getAddress(a));
        if (f == null) { println("\n// no function @0x" + Long.toHexString(a) + " (" + tag + ")"); return; }
        println("\n########## " + f.getName() + " @" + f.getEntryPoint()
                + " size=" + f.getBody().getNumAddresses() + "  (" + tag + ") ##########");
        try { println(dec.decompileFunction(f, 240, mon).getDecompiledFunction().getC()); }
        catch (Exception e) { println("  <fail>"); }
    }
    void refs(long a, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        println("\n===== refs to 0x" + Long.toHexString(a) + " (" + tag + ") =====");
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(a));
        while (it.hasNext()) {
            Reference r = it.next();
            Function cf = fm.getFunctionContaining(r.getFromAddress());
            println("  " + r.getFromAddress() + " " + r.getReferenceType() + " in "
                    + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "NOFUNC"));
        }
    }
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        // the mute-UI cluster (part 12): every function that touches _DAT_460fab40
        long[] cluster = {0x40083480L, 0x400834d8L, 0x400836d8L, 0x400839dcL, 0x40083a30L,
                          0x40083a7cL, 0x40083ab4L, 0x40083ce0L, 0x40083e40L};
        for (long a : cluster) dump(a, "mute-UI cluster");
        // the internal masks the cluster maintains -- is there a solo twin of 0x460fab40?
        refs(0x460fab40L, "internal MUTE mask");
        refs(0x460fab44L, "its neighbour (solo twin?)");
        dec.dispose();
    }
}

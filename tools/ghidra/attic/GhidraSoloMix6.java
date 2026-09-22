// GhidraSoloMix6.java -- the solo hard cut SURVIVED a fix that defuses both of stock's
// solo-branch paths inside FUN_40004dbc (hardware, 20 Sep). So the cut is NOT in the frame
// builder at all. Session 57's finding names the other candidate: the per-track levels the
// DSP actually receives are produced by the LEVEL CHAIN (0x4000cb4e/cc20/ced0/ced4), a
// different function entirely, which this project has never gated (hook 12 tried its site
// and was abandoned over the EMAC/MACSR hazard, not because the site was wrong).
// Question this answers: does the level chain read MUTE_STATE / SOLO_FLAG / the cue-mode
// flag at all? If yes, that is where solo silencing happens and why nothing we hook helps.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSoloMix6 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();

        // which function owns the level chain, and what does it read?
        LinkedHashSet<Long> seen = new LinkedHashSet<>();
        for (long a : new long[]{0x4000cb4eL, 0x4000cc20L, 0x4000ced0L, 0x4000ced4L, 0x4000cae8L}) {
            Function f = fm.getFunctionContaining(sp.getAddress(a));
            println("  0x" + Long.toHexString(a) + " -> " + (f != null ? f.getName() + "@" + f.getEntryPoint() : "NO FUNCTION"));
            if (f != null && seen.add(f.getEntryPoint().getOffset())) {
                println("\n########## " + f.getName() + " @" + f.getEntryPoint()
                        + " size=" + f.getBody().getNumAddresses() + " ##########");
                try { println(dec.decompileFunction(f, 300, mon).getDecompiledFunction().getC()); }
                catch (Exception e) { println("  <decompile failed>"); }
            }
        }
        dec.dispose();
    }
}

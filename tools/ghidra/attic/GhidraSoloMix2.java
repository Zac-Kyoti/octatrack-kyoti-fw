// GhidraSoloMix2.java -- part 18 addendum 6 follow-up. GhidraSoloMix1 showed that NONE of
// the 13 MUTE_STATE writers ever SETS a solo bit (1<<track); they only read them. The one
// thing they share is that several funnel the word through FUN_4007c428 before storing it.
// If solo is derived rather than stored, that transform is where it happens -- and it would
// explain why four different poked "solo" states all behaved correctly in the DSP port.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraSoloMix2 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    void dump(long a, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Function f = currentProgram.getFunctionManager().getFunctionContaining(sp.getAddress(a));
        if (f == null) { println("\n// no function @0x" + Long.toHexString(a) + " (" + tag + ")"); return; }
        println("\n########## " + f.getName() + " @" + f.getEntryPoint()
                + " size=" + f.getBody().getNumAddresses() + "  (" + tag + ") ##########");
        try { DecompileResults dr = dec.decompileFunction(f, 240, mon);
              println(dr.getDecompiledFunction().getC()); } catch (Exception e) { println("  <fail>"); }
    }
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        dump(0x4007c428L, "the MUTE_STATE transform every writer funnels through");
        dump(0x4004d948L, "called by solo-engage 0x400654dc with -1");
        dump(0x4004d780L, "called by FUN_40065514 alongside it");
        dec.dispose();
    }
}

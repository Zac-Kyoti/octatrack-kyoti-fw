// GhidraSoloMix4.java -- the track-key dispatcher's THIRD branch. Part 12 decompiled
// FUN_40040250 (top-level track-key handler) and recorded that besides the mute calls it
// ends with FUN_40083e40 + FUN_4007c264. FUN_4007c264 sits right next to FUN_4007c428, the
// solo-aggregate transform -- so this branch is the prime candidate for what CUE+TRIG does
// while the MIXER's cue/solo mode flag (0x80000034) is set.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraSoloMix4 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    void dump(long a, String tag) {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Function f = currentProgram.getFunctionManager().getFunctionContaining(sp.getAddress(a));
        if (f == null) { println("\n// no function @0x" + Long.toHexString(a) + " (" + tag + ")"); return; }
        println("\n########## " + f.getName() + " @" + f.getEntryPoint() + " (" + tag + ") ##########");
        try { println(dec.decompileFunction(f, 240, mon).getDecompiledFunction().getC()); }
        catch (Exception e) { println("  <fail>"); }
    }
    public void run() throws Exception {
        dec = new DecompInterface(); dec.openProgram(currentProgram);
        dump(0x4007c264L, "track-key dispatcher's 3rd branch, neighbour of the solo transform");
        dump(0x40083e40L, "its companion in that branch");
        dump(0x400654dcL, "solo-engage handler (sets SOLO_FLAG + 0x100b1497)");
        dec.dispose();
    }
}

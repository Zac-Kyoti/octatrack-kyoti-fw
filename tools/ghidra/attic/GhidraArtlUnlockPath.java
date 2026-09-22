//@category Octatrack
// Session 78. The emulator drive of the REAL ARTLTEST1 settled that FUN_40041bc4 never
// writes the stored `#1` array (0 writes anywhere in TRAC across 64 arg combinations),
// so it is NOT what clears a p-lock -- yet ARTLTEST2 proves a real erase does reach `#1`
// (.strd has one lock left, .work has none).
//
// New lead: 0x46c7dfda is an [8 track][32 param] working copy of a step's `#1` record,
// initialised to all-0xFF at 0x40040bec and lazily filled from `#1` by 0x40043c7e.
// 0x40044724 writes 0xFF (= "param not locked") INTO that array for the current track
// (0x100b14cc), then tests the LIVE gate 0x460d172a and calls 0x4004271c (if 0x46c7dd26)
// or 0x40042d1c, both with the same 0x46c7e956 longword the knob-op dispatcher caches.
// That is the shape of the actual erase. Decompile the whole cluster.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlUnlockPath extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40044710L, 0x4004271cL, 0x40042d1cL, 0x40043c7eL };
        String[] labels = { "unlock_writer_44710", "live_prop_4271c", "prop_42d1c", "lazy_load_43c7e" };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        for (int i = 0; i < targets.length; i++) {
            Address a = sp.getAddress(targets[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) { try { disassemble(a); f = createFunction(a, labels[i]); } catch (Exception e) {} }
            if (f == null) { println("no function @ " + a); continue; }
            DecompileResults res = dec.decompileFunction(f, 240, mon);
            println("\n==================== " + labels[i] + " (target " + a + ") @ "
                    + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlUnlockPath] done.");
    }
}

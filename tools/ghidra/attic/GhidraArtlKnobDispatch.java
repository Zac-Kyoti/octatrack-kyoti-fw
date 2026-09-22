//@category Octatrack
// Session 78, post-flash: the dead flash is now explained (wrong predicate), but the
// emulator dump of the REAL ARTLTEST1 trigless lock showed all three of the patch's
// guards would have PASSED on that project -- so if FUN_40041bc4 had been called, the
// detour would have fired. It didn't. That points at Session 30's never-tested
// assumption that FUN_40041bc4 IS the LIVE [NO]+knob erase handler.
//
// Decompile the p-lock knob-op dispatcher (~0x40062a00, Session 28 characterized it only
// from raw disassembly) to see exactly which function each opcode routes to and under
// what conditions -- i.e. what a [NO]+knob turn in LIVE REC actually calls. Note both
// FUN_40041784 and FUN_40041bc4 bail unless 0x460d1a90 == 0, so if that flag means
// "[NO] is held" neither of them can be the erase path at all.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlKnobDispatch extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40062a00L, 0x40033bceL };
        String[] labels = { "knob_op_dispatcher_62a00", "flag_1a90_cluster_33bce" };
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
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + labels[i] + " (target " + a + ") @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlKnobDispatch] done.");
    }
}

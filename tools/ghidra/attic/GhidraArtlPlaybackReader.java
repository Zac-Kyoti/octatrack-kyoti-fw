//@category Octatrack
// Session 78 continued again: rather than crack the EDITOR's own complex (page, encoder) ->
// byte-offset table resolver (0x4009b2d4 -- looks like several more sessions on its own),
// check the PLAYBACK side instead. Session 30 said "0x4009d740+ (per-param loop 0x4009d7dc,
// 32x) consults a 64-bit param bitmap at blob+pat*0x8ed8+track*0x91a+0x0a (TRAC+0x0a) AND the
// #1 value records at TRAC+0x59" -- this is what actually APPLIES p-locks every step, so it
// almost certainly does a plain linear scan (bit i -> byte i), no table needed. Confirming
// that relationship directly answers the one open question for the auto-remove detour:
// does clearing bit i of the param-lock bitmap for (track,step) correspond 1:1 to byte i of
// #1[track][step], so the detour can diff the bitmap against #1 instead of decoding which of
// 0x40041bc4's own local_5/table-driven fields maps to which byte.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlPlaybackReader extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4009d740L, 0x4009d1e8L };
        String[] labels = { "plock_apply_9d740", "step_handler_9d1e8" };
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
            println("\n==================== " + labels[i] + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlPlaybackReader] done.");
    }
}

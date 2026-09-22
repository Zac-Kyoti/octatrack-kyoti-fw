//@category Octatrack
// Session 78 continued a fifth time: Session 39's own last open candidate for the
// "+0x4900 -> #1" commit, never checked by anyone -- FW_TRANSPORT (0x4009b964)'s STOP case
// (the START case is already known: 0x4009c458). Today's live hardware test (pattern switch
// while still PLAYING doesn't clear the stuck LED) is consistent with the commit living on
// STOP specifically, since every real export this session required the user to actually stop
// the sequencer to pull the card. Decompile the transport dispatcher to find and inspect the
// STOP branch.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlTransportStop extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4009b964L };
        String[] labels = { "FW_TRANSPORT_9b964" };
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
        println("\n[GhidraArtlTransportStop] done.");
    }
}

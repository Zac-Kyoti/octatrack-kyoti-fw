//@category Octatrack
// Session 78 continued: Session 30 found the LIVE erase path (0x40041bc4) does NOT
// call the full LED-bitmap rebuild 0x400339d8 directly -- "it calls 0x40045614 then
// redraws." Decompile that function to see whether IT is what actually updates
// LOCK_LIVE/LOCK_STORED (0x46c7d2e4/0x46c7d48c) incrementally after an erase, and
// whether it reads the TRAC+0x10 trig-type-layer mask (real hardware now shows this
// bit survives a p-lock erase) rather than re-deriving purely from #1.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlEraseRedraw extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40045614L, 0x40041bc4L };
        String[] labels = { "erase_redraw_40045614", "FUN_40041bc4_LIVE_erase" };
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
        println("\n[GhidraArtlEraseRedraw] done.");
    }
}

//@category Octatrack
// Session 78 continued a sixth time: every LIVE p-lock edit function found this session
// (0x40041784, 0x40041bc4, 0x4004f124) sets a global dirty flag, _DAT_100f8598 = 1, plus a
// per-bank flag at blob+0x9b332. The only found caller of the "SAVE PROJECT" poster
// (0x40023630) is the CREATE-NEW-PROJECT flow, not an ongoing save -- consistent with real
// Octatrack behavior (no manual save; it autosaves implicitly). Whatever reads this dirty
// flag to decide "there's unsaved work, flush it" is the best remaining candidate for the
// actual +0x4900 -> #1 commit (or whatever performs it), likely a periodic/idle background
// task Session 39 already guessed at but never found. Full xref search.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.LinkedHashSet;
import java.util.Set;

public class GhidraArtlDirtyFlag extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x100f8598L };
        String[] labels = { "DAT_100f8598_dirty_flag" };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        Set<Function> toDecompile = new LinkedHashSet<>();

        for (int i = 0; i < targets.length; i++) {
            Address a = sp.getAddress(targets[i]);
            println("\n==================== xrefs to " + labels[i] + " @ " + a + " ====================");
            ReferenceIterator refs = rm.getReferencesTo(a);
            int n = 0;
            while (refs.hasNext()) {
                Reference r = refs.next();
                Address from = r.getFromAddress();
                Function f = fm.getFunctionContaining(from);
                println("  " + from + "  " + r.getReferenceType() + "  in " + (f != null ? f.getName() + "@" + f.getEntryPoint() : "?"));
                if (f != null) toDecompile.add(f);
                n++;
            }
            if (n == 0) println("  (no references found)");
        }

        for (Function f : toDecompile) {
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraArtlDirtyFlag] done.");
    }
}

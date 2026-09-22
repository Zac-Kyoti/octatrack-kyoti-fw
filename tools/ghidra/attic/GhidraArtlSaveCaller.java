//@category Octatrack
// Session 78 continued a sixth time: raw byte search found exactly ONE `jsr` call site to
// the SAVE PROJECT poster 0x40023630 (Session 37's own harness target), at 0x400645e6 --
// distinct from Session 34's wrong guess 0x400645ce (which turned out to be the CREATE-NEW-
// PROJECT dialog, FUN_400644f0). Decompile whatever function actually contains 0x400645e6 to
// find the REAL save-project orchestrator, and check whether it does any p-lock commit work
// before calling the low-level poster (Session 37's own test called the poster directly,
// which would skip any such pre-save step).
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

public class GhidraArtlSaveCaller extends GhidraScript {
    @Override
    public void run() throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

        Address callSite = sp.getAddress(0x400645e6L);
        Function f = fm.getFunctionContaining(callSite);
        println("Function containing 0x400645e6: " + (f != null ? f.getName() + " @ " + f.getEntryPoint() + " end=" + f.getBody().getMaxAddress() : "NONE -- undefined, will disassemble"));
        if (f == null) {
            try { disassemble(callSite); f = createFunction(callSite, "save_caller_guess"); } catch (Exception e) { println("createFunction failed: " + e); }
        }

        Set<Function> toDecompile = new LinkedHashSet<>();
        if (f != null) toDecompile.add(f);

        // also: who calls THIS function (the real "SAVE PROJECT" menu entry point)?
        if (f != null) {
            println("\n==================== callers of " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            ReferenceIterator refs = rm.getReferencesTo(f.getEntryPoint());
            int n = 0;
            while (refs.hasNext()) {
                Reference r = refs.next();
                Address from = r.getFromAddress();
                Function cf = fm.getFunctionContaining(from);
                println("  " + from + "  in " + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "?"));
                if (cf != null) toDecompile.add(cf);
                n++;
            }
            if (n == 0) println("  (no callers found)");
        }

        for (Function fn : toDecompile) {
            DecompileResults res = dec.decompileFunction(fn, 180, mon);
            println("\n==================== " + fn.getName() + " @ " + fn.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraArtlSaveCaller] done.");
    }
}

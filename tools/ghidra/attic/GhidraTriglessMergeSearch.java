//@category Octatrack
// Session 78 continued: re-check, against the FULL-ANALYSIS project (Session 70's
// Constant Reference Analyzer run persists in ghidra_project -- so these xrefs are
// Ghidra-resolved, not literal-byte grep like Session 33 originally had to use),
// whether anything besides the known LIVE write/erase cluster
// (0x40041f02/0x40041f72/0x40042546/0x40042642) touches the +0x4900 live-edit
// buffer (DAT_400e6ae0 = blob + 0x4900), and whether any function references BOTH
// that buffer's base constant and TRAC's #1 store offset region -- i.e. hunt for
// the "+0x4900 -> #1" merge Session 33/34 could not locate.
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

public class GhidraTriglessMergeSearch extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x400e6ae0L };
        String[] labels = { "DAT_400e6ae0_plus0x4900_base" };
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

        // Also known SAVE-path candidates flagged in Session 34's NEXT list.
        long[] known = { 0x400645ceL };
        String[] knownLabels = { "SAVE_PROJECT_400645ce" };
        for (int i = 0; i < known.length; i++) {
            Address a = sp.getAddress(known[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) { try { disassemble(a); f = createFunction(a, knownLabels[i]); } catch (Exception e) {} }
            if (f != null) toDecompile.add(f);
            else println("no function @ " + a);
        }

        for (Function f : toDecompile) {
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraTriglessMergeSearch] done.");
    }
}

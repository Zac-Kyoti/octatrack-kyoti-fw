//@category Octatrack
// Session 78 continued a fourth time: FUN_40041784 (the LIVE writer) and FUN_40041bc4 (the
// LIVE eraser) both write a small per-encoder-slot side cache, DAT_46c7d4cc/DAT_46c7d4cd
// (2 bytes per param_2/encoder-slot entry: bank+pattern, then track+step) -- and, this
// session's own decompile of the writer just showed it NEVER resolves a page+encoder into a
// specific #1 byte offset; it only writes ONE generic value slot (+0x4900+2) per step. Since
// something clearly DOES get the value into #1 by save time (real hardware proof, this
// session), whatever reads DAT_46c7d4cc/cd to know "what pending edit needs committing,
// where" is the best remaining lead on the missing merge. Full xref search on both symbols.
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

public class GhidraArtlPendingCache extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x46c7d4ccL, 0x46c7d4cdL, 0x46c7d4cfL };
        String[] labels = { "DAT_46c7d4cc_pending_bankpat", "DAT_46c7d4cd_pending_trkstep", "DAT_46c7d4cf_flag" };
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
            if (f.getEntryPoint().getOffset() == 0x40041784L || f.getEntryPoint().getOffset() == 0x40041bc4L) continue; // already have these
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraArtlPendingCache] done.");
    }
}

//@category Octatrack
// Session 78 continued a fifth time: Session 40 (2026-09-08) found, via octabam's own
// hardware-verified RE (not this project's), that 0x4000c42c-0x4000c5a0 is named "the p-lock
// applier" with an armed-bitmask check at 0x4000bd14 -- never followed up here (the thread
// was shelved for HW Phase 0 right after). Decompile both to see if this is the missing
// "+0x4900 (or the armed-param bitmap) -> #1 / live voice" commit that Sessions 33/34/37/38/39
// and this session's own re-run all failed to find anywhere in the edit/save/load path.
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

public class GhidraArtlPlockApplier extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4000c42cL, 0x4000bd14L };
        String[] labels = { "octabam_plock_applier_c42c", "armed_bitmask_check_bd14" };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        Set<Function> toDecompile = new LinkedHashSet<>();

        for (int i = 0; i < targets.length; i++) {
            Address a = sp.getAddress(targets[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) { try { disassemble(a); f = createFunction(a, labels[i]); } catch (Exception e) {} }
            if (f == null) { println("no function @ " + a); continue; }
            try { f.setName(labels[i], ghidra.program.model.symbol.SourceType.USER_DEFINED); } catch (Exception e) {}
            toDecompile.add(f);
            println("\n==================== callers of " + labels[i] + " @ " + f.getEntryPoint() + " ====================");
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

        for (Function f : toDecompile) {
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraArtlPlockApplier] done.");
    }
}

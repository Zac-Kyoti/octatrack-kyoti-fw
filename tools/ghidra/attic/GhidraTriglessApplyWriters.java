//@category Octatrack
// Session 78 (auto-remove trigless lock, resuming Section 13): who WRITES
// DAT_400d7c44 / DAT_400d7c48 (the "pending per-track apply" index that gates
// fb_caller_93ec0 / fb_caller_96ad4, found in Session 58 part 17)? If a writer
// is the per-step sequencer engine reading a step's stored p-lock record with
// no accompanying trig dispatch, that's the trigless-lock live-apply mechanism
// -- and its read side is the natural anchor for the auto-remove detour.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.LinkedHashSet;
import java.util.Set;

public class GhidraTriglessApplyWriters extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] datTargets = { 0x400d7c44L, 0x400d7c48L, 0x400d7c4cL };
        String[] datLabels = { "DAT_400d7c44", "DAT_400d7c48", "DAT_400d7c4c_pickup_owner" };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

        Set<Function> toDecompile = new LinkedHashSet<>();

        for (int i = 0; i < datTargets.length; i++) {
            Address a = sp.getAddress(datTargets[i]);
            println("\n==================== xrefs to " + datLabels[i] + " @ " + a + " ====================");
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
            if (n == 0) println("  (no references found -- may need full analysis / a wider search)");
        }

        // Also: the two known consumers, for cross-reference while reading.
        long[] known = { 0x40093ec0L, 0x40096ad4L };
        String[] knownLabels = { "fb_caller_93ec0", "fb_caller_96ad4" };
        for (int i = 0; i < known.length; i++) {
            Address a = sp.getAddress(known[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) { try { disassemble(a); f = createFunction(a, knownLabels[i]); } catch (Exception e) {} }
            if (f != null) { try { f.setName(knownLabels[i], SourceType.USER_DEFINED); } catch (Exception e) {} toDecompile.add(f); }
        }

        for (Function f : toDecompile) {
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + f.getName() + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }

        println("\n[GhidraTriglessApplyWriters] done.");
    }
}

//@category Octatrack
// Session 78, post-flash: patch_triglock.s failed on hardware because it keyed its
// predicate on the +0x48d8 64-bit field using Session 30's label for it ("which params
// are locked"). FUN_40041bc4's own use says otherwise: the bit index it passes to both
// helpers below is iVar8 == local_6, and the SAME iVar8 indexes 0x46c7d2e4, an array
// whose semantics are independently established as byte[STEP] = track bitmap. So the
// field should be per-STEP. Decompile the two helpers to confirm they are in fact
// bit-index operations over the 64-bit pair (test / build-mask), closing the argument.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlBitHelpers extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x400a6904L, 0x400a694cL };
        String[] labels = { "bit_test_a6904", "bit_mask_a694c" };
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
        println("\n[GhidraArtlBitHelpers] done.");
    }
}

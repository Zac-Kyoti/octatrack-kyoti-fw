// Ghidra post-script (Java) -- figure out what 0x800018fe actually gates.
// MUTEMODE_NEW's amp-gate hook lives inside a block guarded by
// `tst.l 0x800018fe ; bne <skip whole per-track loop>`. Hardware test shows
// muting has NO audible effect at all with that build -- need to know when
// this flag is set/cleared to know if the guarded block ever runs in normal
// playback.
//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraMuteModeGuard extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4000520cL, 0x400068a2L, 0x4000d0a0L };
        String[] labels = { "writer_a_800018fe", "writer_b_800018fe", "amp_frame_filler" };

        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

        for (int i = 0; i < targets.length; i++) {
            Address a = sp.getAddress(targets[i]);
            Function f = fm.getFunctionContaining(a);
            if (f == null) {
                try { disassemble(a); f = createFunction(a, labels[i]); }
                catch (Exception e) { println("[!] could not create function @ " + a + ": " + e); }
            }
            if (f == null) { println("==== " + labels[i] + ": no function @ " + a + " ===="); continue; }
            try { f.setName(labels[i], SourceType.USER_DEFINED); } catch (Exception e) {}

            DecompileResults res = dec.decompileFunction(f, 120, mon);
            println("\n==================== " + labels[i] + " @ " + f.getEntryPoint() + " (ref @ " + a + ") ====================");
            if (res != null && res.decompileCompleted()) {
                println(res.getDecompiledFunction().getC());
            } else {
                println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
            }
        }
        println("\n[GhidraMuteModeGuard] done.");
    }
}

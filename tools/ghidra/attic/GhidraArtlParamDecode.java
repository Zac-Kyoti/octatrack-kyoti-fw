//@category Octatrack
// Session 78 continued again: decompile the param-address resolver 0x4009b2d4 (Session 32
// called it "maps (param-page, param-index) -> a byte offset... via tables 0x46c7756c/
// 759c/75bc/75ce/757c, 0x400aba50, 0x400eb034, 0x400e2230, 0x400e6ad8", never fully
// decompiled clean) and the armed-mode eraser sibling 0x4004f124, to find the concrete
// formula from FUN_40041bc4's local_5 (the 6-bit param field) to a byte offset inside #1's
// 32-byte per-step p-lock record -- the one piece still missing for the auto-remove detour.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlParamDecode extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4009b2d4L, 0x4004f124L, 0x4009b290L };
        String[] labels = { "param_addr_resolver_9b2d4", "armed_eraser_4f124", "track_gate_9b290" };
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
        println("\n[GhidraArtlParamDecode] done.");
    }
}

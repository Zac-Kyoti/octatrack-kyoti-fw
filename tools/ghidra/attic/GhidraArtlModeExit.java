//@category Octatrack
// Session 78 continued a seventh time: real hardware evidence just found (whole-file diff,
// ARTLTEST1 .strd vs .work) shows EXACTLY 3 bytes differ in the entire 636KB bank -- the one
// #1 byte for the erased param, plus a 2-byte trailing checksum. Nothing else changed: no
// separate +0x4900 disk-chunk content differs at all. That means whatever commits the edit
// into #1 also fully resets ALL live-edit working state in the SAME operation (a real
// "commit and clear", not a lazy/partial one) -- strongly consistent with Session 38's own
// mode-exit hypothesis (leaving the LIVE-REC/trig screen: 0x40062196 clears the armed-param
// bitmap 0x46c7d344/348) which Session 39's own checklist never actually got around to
// decompiling (it lists 0x4004ef54/0x400369c8/0x4005fb44/0x4009da20 as checked, but not
// 0x40062120-ish itself or the "0x4004d870/0x4004d640/0x4004d948 p-lock draw family").
// Decompile all of them now, looking specifically for a write into #1 (0x91a stride + 0x59)
// sourced from +0x4900 (0x8b0 stride).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlModeExit extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40062196L, 0x4004d870L, 0x4004d640L, 0x4004d948L };
        String[] labels = { "mode_exit_62196", "plock_draw_4d870", "plock_draw_4d640", "plock_draw_4d948" };
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
            println("\n==================== " + labels[i] + " (target " + a + ") @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlModeExit] done.");
    }
}

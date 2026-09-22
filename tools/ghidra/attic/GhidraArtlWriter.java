//@category Octatrack
// Session 78 continued a fourth time: decompile the LIVE writer 0x40041784 (sibling of the
// eraser 0x40041bc4 already decompiled) to see how it indexes the +0x48d8/+0x48e0 "which
// params are locked" working bitmap (Session 30) -- specifically whether that bit index
// lines up with #1's own flat 0-31 byte index (confirmed this session via the playback loop:
// PTCH locked at #1 byte 0x00, LEN at byte 0x02, from a real hardware export). If the bitmap
// uses the same indexing, the auto-remove detour can work by diffing the live bitmap against
// #1 instead of needing the full (page,encoder)->byte-index static table.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlWriter extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40041784L, 0x4004ef54L };
        String[] labels = { "live_writer_41784", "armed_writer_4ef54" };
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
        println("\n[GhidraArtlWriter] done.");
    }
}

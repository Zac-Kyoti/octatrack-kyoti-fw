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

public class GhidraEchoCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40007960L, 0x40043c50L, 0x4007eb3eL, 0x4008044eL, 0x4008055cL, 0x40093ec0L, 0x40096ad4L };
        String[] labels = { "frame_playback_engine", "fb_caller_40043c50", "fb_caller_4007eb3e",
                             "fb_caller_8044e", "fb_caller_8055c", "fb_caller_93ec0", "fb_caller_96ad4" };
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
            try { f.setName(labels[i], SourceType.USER_DEFINED); } catch (Exception e) {}
            DecompileResults res = dec.decompileFunction(f, 180, mon);
            println("\n==================== " + labels[i] + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res!=null?res.getErrorMessage():"null") + ")");
        }
        println("\n[GhidraEchoCallers] done.");
    }
}

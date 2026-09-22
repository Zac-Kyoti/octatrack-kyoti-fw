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

public class GhidraLiveNibble extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x4000b910L, 0x4000b9bcL, 0x400a2e22L, 0x400a3a68L };
        String[] labels = { "live_nibble_writer_a", "live_nibble_writer_b", "reader_400a2e22", "reader_400a3a68" };
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
            println("\n==================== " + labels[i] + " @ " + f.getEntryPoint() + " (requested " + a + ") ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res!=null?res.getErrorMessage():"null") + ")");
        }
        println("\n[GhidraLiveNibble] done.");
    }
}

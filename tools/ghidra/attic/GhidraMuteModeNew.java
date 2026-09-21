// Ghidra post-script (Java) -- decompile the stock functions needed for a
// from-scratch MUTE MODE redesign: the per-frame amp filler, the voice mailbox
// writer, the trig-to-voice bridge, and the stock per-frame mute gate.
// Fresh probe, not derived from any prior mute-session script.
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

public class GhidraMuteModeNew extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = {
            0x4000d0a0L, 0x400977ccL, 0x40005178L, 0x40004db8L
        };
        String[] labels = {
            "amp_frame_filler", "trig_to_voice", "voice_mailbox_write", "perframe_mute_gate"
        };

        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

        for (int i = 0; i < targets.length; i++) {
            Address a = sp.getAddress(targets[i]);
            Function f = fm.getFunctionAt(a);
            if (f == null) {
                try { disassemble(a); f = createFunction(a, labels[i]); }
                catch (Exception e) { println("[!] could not create function @ " + a + ": " + e); }
            }
            if (f == null) { println("==== " + labels[i] + ": no function @ " + a + " ===="); continue; }
            try { f.setName(labels[i], SourceType.USER_DEFINED); } catch (Exception e) {}

            DecompileResults res = dec.decompileFunction(f, 120, mon);
            println("\n==================== " + labels[i] + " @ " + a + " ====================");
            if (res != null && res.decompileCompleted()) {
                println(res.getDecompiledFunction().getC());
            } else {
                println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
            }
        }
        println("\n[GhidraMuteModeNew] done.");
    }
}

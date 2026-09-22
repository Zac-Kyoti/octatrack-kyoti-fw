//@category Octatrack
// Session 78. FUN_40042158 -- entry found at the `linkw %fp,#-84` immediately after
// FUN_40041bc4's end (0x40042156), which is why earlier sessions never saw it as its own
// function -- is the ONLY writer of the stored p-lock array `#1` (TRAC+0x59). Proven two
// ways: it holds both of the binary's only code literals pointing at TRAC+0x58 (the `#1`
// base, 0x400422e0 / 0x400423d8), and the emulator drive of the real ARTLTEST1 showed
// FUN_40041bc4 writing 0 bytes anywhere in TRAC across 64 argument combinations.
//
// The write is `move.b d5, a0@(1,a1:l)` at 0x400422ee with bank=d7, pattern=d6, step=d3,
// track=fp@(8), param=fp@(12), value=fp@(19) -- every field the trigless-lock feature
// needs, in registers, at one instruction. Decompile it to pin the erase (value 0xFF)
// path and what it does with the stored-p-lock per-step bitmap 0x46c7d48c, which the LED
// rebuild 0x400339d8 reads.
//
// FUN_40054cd8 is the value resolver case 64 calls first (`if (result < 0) bail`), so it
// decides what value -- including 0xFF, "param not locked" -- ever reaches `#1`.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlStoreWriter extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40042158L, 0x40054cd8L };
        String[] labels = { "plock_store_writer_42158", "value_resolver_54cd8" };
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
            DecompileResults res = dec.decompileFunction(f, 300, mon);
            println("\n==================== " + labels[i] + " @ " + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlStoreWriter] done.");
    }
}

//@category Octatrack
// Session 78. The hardware trace (ARTLTEST8, diag v3) finally named the gesture's path by
// measurement rather than inference:
//
//   opcode 1 (case 0x40061dac) -> sets TRAC+0x10 bit 6 AND writes #1[6][0]/#1[6][2]
//   opcode 8 (case 0x40061ed4) -> clears #1[6][0]/#1[6][2] and NEVER touches TRAC+0x10
//
// None of opcodes 64/65/66/70/74 occur at all, so the whole 0x40062xxx p-lock cluster
// (FUN_40041bc4 / FUN_40041784 / FUN_40042158 / FUN_4004f124 / FUN_4004ef54) that this
// thread chased since Session 26 is uninvolved -- which is why three builds did nothing.
//
// Case 8's LIVE branch (0x460d172a != 0) calls FUN_40041af4, which sits immediately
// BEFORE FUN_40041bc4 and has no `linkw`, so every function-boundary scan missed it. It
// reads the current track from 0x80000000, gates on 0x460d1a90 / 0x460d1a94, and tail
// calls the actual workers:
//
//   0x40038668  MIDI tracks   (0x80000012 != 0)
//   0x40038874  AUDIO tracks  <- the one this feature needs
//
// with (trackmask, flag, selector) where selector is 0x460d1a98 or 0x460d1a9c.
//
// Decompile those, plus opcode 1's case, to find where #1 is written with 0xFF and where
// the trigless-lock flag TRAC+0x10 is set -- the create/erase pair whose asymmetry is the
// bug.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class GhidraArtlRealErase extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = { 0x40038874L, 0x40038668L, 0x40041af4L };
        String[] labels = { "audio_plock_erase_38874", "midi_plock_erase_38668",
                            "live_erase_dispatch_41af4" };
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
            println("\n==================== " + labels[i] + " (target " + a + ") @ "
                    + f.getEntryPoint() + " ====================");
            if (res != null && res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("  (decompile failed: " + (res != null ? res.getErrorMessage() : "null") + ")");
        }
        println("\n[GhidraArtlRealErase] done.");
    }
}

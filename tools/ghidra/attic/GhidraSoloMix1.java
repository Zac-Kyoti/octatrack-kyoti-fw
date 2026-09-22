// GhidraSoloMix1.java -- part 18 addendum 6's handoff item 2.
//
// The open bug: on hardware, silencing a track by SOLO (engaged as MIXER, then CUE+TRIG)
// always gives an OT-style hard cut with no FX tails, in every MUTE MODE. Four emulated
// solo/cue states all behave CORRECTLY in the DSP-rendering port, so the state the hardware
// is actually in is something none of them reproduces.
//
// Two things to find here:
//   1. WHO SETS THE PER-TRACK SOLO BITS (MUTE_STATE 0x80000008, bits 0..7). The solo-engage
//      handler found this session (0x400654dc) sets only the flag 0x80000037 plus a
//      persisted copy at 0x100b1497, and calls FUN_4004d948(-1) -- it sets NO per-track bit.
//      Part 13 ran this same xref query and recorded only the COUNT ("13 functions"), never
//      the addresses, so this re-runs it and PRINTS THEM.
//   2. Whether the LEVEL CHAIN (0x4000cb4e / 0x4000cc20 / 0x4000ced0 / 0x4000ced4 -- per
//      Session 57 the real producer of the per-track levels the DSP receives, as opposed to
//      the frame builder every hook this project ships gates) reads the solo/cue state at
//      all. If it does, that is where the hard cut lives and why nothing we hook can see it.
//
// Run:
//   JAVA_HOME=/opt/homebrew/opt/openjdk@21 \
//   /opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless \
//     ~/Documents/octatrack-kyoti-fw/ghidra_project octamax \
//     -process "section_3_MAIN_OS.bin" -noanalysis \
//     -scriptPath ~/Documents/octatrack-kyoti-fw/tools/ghidra/attic \
//     -postScript GhidraSoloMix1.java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;

public class GhidraSoloMix1 extends GhidraScript {
    DecompInterface dec; ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
    FunctionManager fm; AddressSpace sp;
    LinkedHashSet<Long> dumped = new LinkedHashSet<>();

    String decomp(Function f){
        try { DecompileResults dr = dec.decompileFunction(f, 240, mon);
              if (dr != null && dr.getDecompiledFunction() != null)
                  return dr.getDecompiledFunction().getC(); } catch (Exception e) {}
        return "  <decompile failed>";
    }

    void dumpFn(long entry, String tag){
        Function f = fm.getFunctionContaining(sp.getAddress(entry));
        if (f == null) { println("\n// no function @0x" + Long.toHexString(entry) + " (" + tag + ")"); return; }
        if (!dumped.add(f.getEntryPoint().getOffset())) return;
        println("\n########## " + f.getName() + " @" + f.getEntryPoint()
                + " size=" + f.getBody().getNumAddresses() + "  (" + tag + ") ##########");
        println(decomp(f));
    }

    // Every reference to an address, listed with its containing function. Part 13's mistake
    // was summarising this as a count; the addresses are the whole point.
    TreeSet<Long> listRefs(long addr, String tag, boolean writesOnly){
        println("\n===== " + (writesOnly ? "WRITE" : "ALL") + " references to 0x"
                + Long.toHexString(addr) + "  (" + tag + ") =====");
        TreeSet<Long> fns = new TreeSet<>();
        ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(sp.getAddress(addr));
        while (it.hasNext()) {
            Reference r = it.next();
            if (writesOnly && !r.getReferenceType().isWrite()) continue;
            Function cf = fm.getFunctionContaining(r.getFromAddress());
            println("  from " + r.getFromAddress() + "  in "
                    + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "NOFUNC")
                    + "  " + r.getReferenceType());
            if (cf != null) fns.add(cf.getEntryPoint().getOffset());
        }
        println("  -> " + fns.size() + " distinct function(s)");
        return fns;
    }

    public void run() throws Exception {
        fm = currentProgram.getFunctionManager();
        sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        dec = new DecompInterface();
        dec.openProgram(currentProgram);

        // 1. MUTE_STATE writers -- the solo-bit setter must be among them.
        TreeSet<Long> writers = listRefs(0x80000008L, "MUTE_STATE (solo 0-7 / mute 8-15 / cue 16-23)", true);

        // 2. The solo-mode flag and its persisted twin, for the MIXER-side handler.
        listRefs(0x80000037L, "SOLO_FLAG", false);
        listRefs(0x100b1497L, "SOLO_FLAG's persisted copy (set by 0x400654dc)", false);

        // 3. Does the LEVEL CHAIN read any of this at all?
        println("\n===== level-chain sites (Session 57: the REAL producer of the DSP's per-track levels) =====");
        for (long a : new long[]{0x4000cb4eL, 0x4000cc20L, 0x4000ced0L, 0x4000ced4L}) {
            Function f = fm.getFunctionContaining(sp.getAddress(a));
            println("  0x" + Long.toHexString(a) + " -> "
                    + (f != null ? f.getName() + "@" + f.getEntryPoint() : "NO FUNCTION"));
        }

        // Decompile every MUTE_STATE writer; the solo setter is whichever one builds a mask
        // in bits 0..7 (1 << track) rather than 0x100 << track (mute) or 0x10000 << track (cue).
        for (long e : writers) dumpFn(e, "MUTE_STATE writer");

        // And the level-chain function itself, once.
        dumpFn(0x4000ced0L, "level chain");
        dec.dispose();
    }
}

//@category Octatrack
// Session 79 continued a twenty-first time. GhidraDirectJump47 enumerated OT's complete
// per-track state vector: EIGHT 16-entry arrays (audio 0-7 then MIDI 8-15), matching AR's
// eight. Five have known semantics. Three do not, and AR's commit writes all eight of its
// own, so the OT port must either write these three or justify skipping each:
//
//   0x80006500[t]  ARMED      -- gate, loop top requires ==1; cleared at 0x400a3dac.
//                                Nothing in the per-track loop ever SETS it. Who does?
//   0x800065c3[t]  CNTDN_TBL  -- read-only inside the loop (tst.b (0xf3,ptr) 0x400a3cfc,
//                                bge skips the scale refresh). Armed somewhere else.
//   0x80006604[t]  PAIR       -- 2 bytes/track; its hi byte is copied to 0x800065d3[t]
//                                at 0x400a3d36. Written somewhere else.
//
// These arrays are reached through cursor registers (lea base,An then An++ / indexed), so
// Ghidra's reference manager alone under-reports them: a `lea 0x80006500,A5` followed by
// eight `addq.l #1,A5` produces ONE reference, not eight. So scan every instruction in the
// program for BOTH (a) any read/write reference landing inside a target range, and (b) any
// scalar operand equal to an address inside a target range -- the latter catches lea / pea
// / move.l #imm cursor setup, which is how these arrays are actually addressed.
//
// Usage: -postScript GhidraDirectJump48.java  (ranges are compiled in below)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.util.*;

public class GhidraDirectJump48 extends GhidraScript {

  static class Range {
    final String name; final long lo, hi;
    Range(String n, long l, long h) { name = n; lo = l; hi = h; }
    boolean has(long a) { return a >= lo && a < hi; }
  }

  public void run() throws Exception {
    List<Range> ranges = Arrays.asList(
        new Range("NEXT_STEP  0x800065e4[16x2]", 0x800065e4L, 0x80006604L),
        new Range("PAIR       0x80006604[16x2]", 0x80006604L, 0x80006624L),
        new Range("ARMSRC_MSK 0x80006684", 0x80006684L, 0x80006686L));

    // hits[rangeName] -> list of "pc  instruction   [how]   (function)"
    LinkedHashMap<String, List<String>> hits = new LinkedHashMap<>();
    for (Range r : ranges) hits.put(r.name, new ArrayList<>());

    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();
    FunctionManager fm = currentProgram.getFunctionManager();

    long scanned = 0;
    InstructionIterator it = listing.getInstructions(true);
    while (it.hasNext()) {
      if (monitor.isCancelled()) break;
      Instruction ins = it.next();
      scanned++;
      long pc = ins.getAddress().getOffset();
      Function f = fm.getFunctionContaining(ins.getAddress());
      String fname = f != null ? f.getName() : "-";

      // (a) resolved references
      for (Reference ref : rm.getReferencesFrom(ins.getAddress())) {
        if (!ref.getReferenceType().isData()) continue;
        long t = ref.getToAddress().getOffset();
        String how = ref.getReferenceType().isWrite() ? "WRITE ref"
                   : ref.getReferenceType().isRead() ? "read  ref" : "data  ref";
        for (Range r : ranges) {
          if (r.has(t)) {
            hits.get(r.name).add(String.format("%08x  %-42s %-10s ->%08x  (%s)",
                    pc, ins.toString(), how, t, fname));
          }
        }
      }

      // (b) scalar operands that are themselves an address in a target range
      //     (lea / pea / move.l #imm cursor setup -- invisible to (a) after the first use)
      int nops = ins.getNumOperands();
      for (int i = 0; i < nops; i++) {
        for (Object o : ins.getOpObjects(i)) {
          long v;
          if (o instanceof Scalar) v = ((Scalar) o).getUnsignedValue();
          else if (o instanceof Address) v = ((Address) o).getOffset();
          else continue;
          for (Range r : ranges) {
            if (r.has(v)) {
              String line = String.format("%08x  %-42s %-10s ->%08x  (%s)",
                      pc, ins.toString(), "CURSOR", v, fname);
              List<String> L = hits.get(r.name);
              if (L.isEmpty() || !L.get(L.size() - 1).equals(line)) L.add(line);
            }
          }
        }
      }
    }

    println("=== scanned " + scanned + " instructions ===");
    for (Range r : ranges) {
      List<String> L = hits.get(r.name);
      // de-duplicate while preserving order
      LinkedHashSet<String> uniq = new LinkedHashSet<>(L);
      println("");
      println("================================================================");
      println("  " + r.name + "   -- " + uniq.size() + " site(s)");
      println("================================================================");
      for (String s : uniq) println("  " + s);
    }
  }
}

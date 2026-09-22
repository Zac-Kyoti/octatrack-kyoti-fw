//@category Octatrack
// Session 79 continued a twentieth time. AR-side Session 8 (ar-kyoti-fw, commit 4afd3c3)
// retracted the "AR's commit writes one variable" claim: AR's DIRECT JUMP commit actually
// rebuilds EIGHT parallel 13-entry per-track arrays from scratch, in two unconditional
// loops over all 13 tracks, from one master new_step plus each track's own length/scale.
// No per-track value survives a commit, so "stale per-track variable" is not a failure
// mode that exists on AR. OT has instead been repairing per-track globals one at a time
// (STEP_IN_PAT, TRK_SCALE_IX, CNTDN_TBL, REFILL_TBL, BAR_CTR, table-arm cadence) -- six
// fixes, each exposing the next.
//
// To port AR's discipline we first need the OT-side equivalent of "the eight arrays":
// the COMPLETE per-track state vector. Five are known (STEP_IN_PAT 0x800064f0,
// TRK_SCALE_IX 0x8000663e, REFILL_TBL 0x800064d0, CNTDN_TBL 0x800065c3, plus MIDI
// counterparts 0x80006646 / 0x80006508). AR had eight. The honest answer is "we do not
// know how many OT has", and guessing is exactly what produced the last regression.
//
// So: enumerate every location WRITTEN inside stock's own per-track loop. Uses Ghidra's
// getResultObjects() rather than mnemonic pattern-matching, so reads are not mistaken for
// writes, and prints branch targets so the loop's back-edge (hence its true extent and
// trip count) is measured rather than assumed.
//
// Usage: -postScript GhidraDirectJump47.java [loAddrHex hiAddrHex]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.util.*;

public class GhidraDirectJump47 extends GhidraScript {

  public void run() throws Exception {
    long lo = 0x400a3c40L, hi = 0x400a3e60L;
    String[] args = getScriptArgs();
    if (args.length >= 2) {
      lo = Long.parseLong(args[0].replace("0x", ""), 16);
      hi = Long.parseLong(args[1].replace("0x", ""), 16);
    }
    Listing listing = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    ReferenceManager rm = currentProgram.getReferenceManager();

    println("=== OT per-track loop: full decode + measured write set ===");
    println(String.format("range %08x .. %08x", lo, hi));
    println("");

    // Collected write targets: absolute address -> list of PCs that write it.
    TreeMap<Long, List<String>> absWrites = new TreeMap<>();
    // Branch edges, to find the loop back-edge.
    List<String> backEdges = new ArrayList<>();
    List<String> fwdBranches = new ArrayList<>();

    Address end = sp.getAddress(hi);
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      long pc = ins.getAddress().getOffset();
      String text = ins.toString();
      String mnem = ins.getMnemonicString();

      // --- what does this instruction WRITE? (registers and memory, per Ghidra) ---
      StringBuilder w = new StringBuilder();
      Object[] res = ins.getResultObjects();
      for (Object o : res) {
        if (o instanceof Register) {
          w.append(" ").append(((Register) o).getName());
        } else if (o instanceof Address) {
          Address a = (Address) o;
          w.append(" [").append(a).append("]");
          if (a.isMemoryAddress()) {
            long t = a.getOffset();
            absWrites.computeIfAbsent(t, k -> new ArrayList<>())
                     .add(String.format("%08x %s", pc, text));
          }
        }
      }

      // --- memory references Ghidra resolved for this instruction ---
      StringBuilder refs = new StringBuilder();
      for (Reference r : rm.getReferencesFrom(ins.getAddress())) {
        if (r.getReferenceType().isWrite()) {
          refs.append("  W->").append(r.getToAddress());
          long t = r.getToAddress().getOffset();
          absWrites.computeIfAbsent(t, k -> new ArrayList<>())
                   .add(String.format("%08x %s", pc, text));
        } else if (r.getReferenceType().isRead()) {
          refs.append("  r->").append(r.getToAddress());
        } else if (r.getReferenceType().isFlow() && !r.getReferenceType().isCall()) {
          long t = r.getToAddress().getOffset();
          String edge = String.format("%08x -> %08x   %s", pc, t, text);
          if (t <= pc) backEdges.add(edge); else fwdBranches.add(edge);
        }
      }

      String tag = "";
      if (w.length() > 0) tag = "   writes:" + w;
      println(String.format("%08x  %-40s%s%s", pc, text, tag, refs));
    }

    println("");
    println("=== BACK EDGES (candidate loop bottoms) ===");
    if (backEdges.isEmpty()) println("  (none in range -- loop bottom is outside it)");
    for (String e : backEdges) println("  " + e);

    println("");
    println("=== FORWARD BRANCHES (exits / skips) ===");
    for (String e : fwdBranches) println("  " + e);

    println("");
    println("=== DISTINCT ABSOLUTE ADDRESSES WRITTEN IN RANGE ===");
    println("  (this is the candidate OT per-track state vector; AR's equivalent is 8 arrays)");
    for (Map.Entry<Long, List<String>> e : absWrites.entrySet()) {
      Address a = sp.getAddress(e.getKey());
      Symbol s = getSymbolAt(a);
      println(String.format("  %08x  %-28s  %d write site(s)",
              e.getKey(), s != null ? s.getName() : "", e.getValue().size()));
      for (String site : e.getValue()) println("        " + site);
    }
    println("");
    println("total distinct absolute write targets: " + absWrites.size());
  }
}

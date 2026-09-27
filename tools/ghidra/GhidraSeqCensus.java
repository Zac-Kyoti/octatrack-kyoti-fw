//@category Octatrack
// Session 10 (AR). The OT thread restarted from scratch after its "gold" DIRECT JUMP
// build turned out to be step-fractional even at 1x / NORMAL mode / 16-vs-7-step
// patterns. The decision: understand AR's WHOLE sequencer timing engine, not just the
// commit loops, before designing the OT port again.
//
// This script is the census pass: for every known sequencer global (master scalars,
// request/commit globals, the eight per-track arrays) it lists EVERY instruction that
// touches it -- data references AND bare scalar operands (cursor setups for
// register-indirect loops, which reference-only scans under-report) -- with the
// enclosing function. Then it prints, for each function that touched anything, its
// callers and callees, so the engine's call graph can be read off in one pass.
//
// Usage: analyzeHeadless ... -postScript GhidraSeqCensus.java > out/ghidra/seq_census.txt
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.util.*;

public class GhidraSeqCensus extends GhidraScript {
  // name -> address. Everything measured in AR_DIRECT_JUMP.md sections 1, 2 and 9.
  static final Object[][] GLOBALS = {
    {"transport_running",      0x405666e0L},
    {"master_step",            0x405666e4L},
    {"master_tick_phase",      0x405666e6L},
    {"master_step_minus1",     0x405666e8L},
    {"arr_one_L",              0x405666ecL},
    {"arr_track_step",         0x40566720L},
    {"arr_track_zero",         0x4056672dL},
    {"arr_track_step_minus1",  0x4056673aL},
    {"pat_cur_a",              0x40566754L},
    {"pat_cur_b",              0x40566755L},
    {"pat_prev",               0x40566756L},
    {"master_res_ix",          0x40566774L},
    {"arr_track_res_ix",       0x40566775L},
    {"arr_track_minus1",       0x405667baL},
    {"arr_track_cntdn",        0x405667c7L},
    {"cntdn_end_sentinel",     0x405667d4L},
    {"commit2_gate",           0x405667d6L},
    {"req_target_pat",         0x405667dcL},
    {"req_direct_start",       0x405667e0L},
    {"req_countdown",          0x405667e4L},
    {"req_countdown_base",     0x405667e8L},
    {"req_target_step",        0x405667f4L},
    {"req_substep_rem",        0x405667f6L},
    {"arr_track_step2",        0x40566830L},
    {"commit2_flag",           0x40566748L},
    {"tick_ctr_40566570",      0x40566570L},
    {"flag_40566578",          0x40566578L},
    {"ctr_40566814",           0x40566814L},
    {"tps_table",              0x401a8ff0L},
  };

  public void run() throws Exception {
    Listing listing = currentProgram.getListing();
    ReferenceManager rm = currentProgram.getReferenceManager();
    FunctionManager fm = currentProgram.getFunctionManager();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();

    LinkedHashMap<Long, String> names = new LinkedHashMap<>();
    LinkedHashMap<Long, List<String>> hits = new LinkedHashMap<>();
    // Script args "name=0xaddr ..." override the built-in table (any other global set).
    String[] args = getScriptArgs();
    if (args.length > 0) {
      for (String s : args) {
        String[] kv = s.split("=");
        long v = Long.parseLong(kv[1].replace("0x", ""), 16);
        names.put(v, kv[0]); hits.put(v, new ArrayList<>());
      }
    } else {
      for (Object[] g : GLOBALS) { names.put((Long) g[1], (String) g[0]); hits.put((Long) g[1], new ArrayList<>()); }
    }
    TreeMap<Long, String> touching = new TreeMap<>();   // function entry -> name
    TreeMap<Long, Integer> orphans = new TreeMap<>();   // pc with no function

    long n = 0;
    InstructionIterator it = listing.getInstructions(true);
    while (it.hasNext()) {
      if (monitor.isCancelled()) break;
      Instruction ins = it.next();
      n++;
      long pc = ins.getAddress().getOffset();
      Function f = fm.getFunctionContaining(ins.getAddress());
      String fn = f != null ? f.getName() : "-";
      LinkedHashSet<String> lines = new LinkedHashSet<>();
      LinkedHashSet<Long> touched = new LinkedHashSet<>();
      for (Reference r : rm.getReferencesFrom(ins.getAddress())) {
        if (!r.getReferenceType().isData()) continue;
        long to = r.getToAddress().getOffset();
        if (hits.containsKey(to)) {
          String how = r.getReferenceType().isWrite() ? "WRITE" :
                       r.getReferenceType().isRead() ? "read " : "data ";
          lines.add(String.format("%08x  %-44s %s  (%s)", pc, ins.toString(), how, fn));
          touched.add(to);
        }
      }
      for (int i = 0; i < ins.getNumOperands(); i++)
        for (Object o : ins.getOpObjects(i)) {
          long v = (o instanceof Scalar) ? ((Scalar) o).getUnsignedValue()
                 : (o instanceof Address) ? ((Address) o).getOffset() : -1;
          if (hits.containsKey(v)) {
            lines.add(String.format("%08x  %-44s %s  (%s)", pc, ins.toString(), "CURSOR", fn));
            touched.add(v);
          }
        }
      for (long t : touched) for (String l : lines) if (!hits.get(t).contains(l)) hits.get(t).add(l);
      if (!touched.isEmpty()) {
        if (f != null) touching.put(f.getEntryPoint().getOffset(), f.getName());
        else orphans.put(pc, 1);
      }
    }
    println("=== scanned " + n + " instructions ===");
    for (long t : hits.keySet()) {
      println("");
      println(String.format("=== %s  %08x  (%d sites) ===", names.get(t), t, hits.get(t).size()));
      for (String s : hits.get(t)) println("  " + s);
    }

    println("");
    println("=== functions touching sequencer globals: callers / callees ===");
    for (Map.Entry<Long, String> e : touching.entrySet()) {
      Function f = fm.getFunctionAt(sp.getAddress(e.getKey()));
      println("");
      println(String.format("--- %s @ %08x  body=%d B", e.getValue(), e.getKey(), f.getBody().getNumAddresses()));
      TreeSet<String> callers = new TreeSet<>();
      ReferenceIterator ri = rm.getReferencesTo(f.getEntryPoint());
      while (ri.hasNext()) {
        Reference r = ri.next();
        if (!r.getReferenceType().isCall()) continue;
        Function c = fm.getFunctionContaining(r.getFromAddress());
        callers.add(String.format("%s@%08x", c != null ? c.getName() : "?", r.getFromAddress().getOffset()));
      }
      println("    callers: " + callers);
      TreeSet<String> callees = new TreeSet<>();
      InstructionIterator bi = listing.getInstructions(f.getBody(), true);
      while (bi.hasNext()) {
        Instruction ins = bi.next();
        for (Reference r : ins.getReferencesFrom())
          if (r.getReferenceType().isCall()) {
            Function c = fm.getFunctionAt(r.getToAddress());
            callees.add(String.format("%s@%08x", c != null ? c.getName() : ("sub_" + Long.toHexString(r.getToAddress().getOffset())), ins.getAddress().getOffset()));
          }
      }
      println("    callees: " + callees);
    }
    if (!orphans.isEmpty()) {
      println("");
      println("=== sites with NO enclosing function (Ghidra never made one; create + decompile) ===");
      for (long pc : orphans.keySet()) println(String.format("  %08x", pc));
    }
    println("[GhidraSeqCensus] done.");
  }
}

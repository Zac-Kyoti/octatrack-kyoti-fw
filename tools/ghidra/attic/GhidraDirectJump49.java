//@category Octatrack
// Session 79 continued a twenty-first time, part 2. GhidraDirectJump48 found NO writer
// anywhere in decoded code for the per-track array PAIR (0x80006604, 2 bytes/track, 16
// tracks) -- only the two cursor setups that READ it (0x400a3ca4, 0x400a3dcc). Before
// concluding "PAIR is never written", rule out the obvious alternative: NOTES.md records
// an undecoded gap inside consumer_a6c0_a33f8 around 0x400a4568-0x400a4b99 where Ghidra
// defined no instructions. A writer hiding in undecoded bytes would be invisible to a scan
// that iterates defined instructions, and asserting "never written" on that basis would be
// exactly the kind of unverified claim that produced the last hardware regression.
//
// Measure instruction coverage across the function's whole body so the gap's real extent
// (if any) is a number, not a memory. Then, for any gap found, scan its RAW BYTES for the
// 32-bit constants that would have to appear in a cursor setup targeting PAIR.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.util.*;

public class GhidraDirectJump49 extends GhidraScript {
  public void run() throws Exception {
    long lo = 0x400a1eeaL, hi = 0x400a4f20L;
    String[] a = getScriptArgs();
    if (a.length >= 2) {
      lo = Long.parseLong(a[0].replace("0x", ""), 16);
      hi = Long.parseLong(a[1].replace("0x", ""), 16);
    }
    Listing listing = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Memory mem = currentProgram.getMemory();

    println(String.format("=== instruction coverage %08x .. %08x ===", lo, hi));
    List<long[]> gaps = new ArrayList<>();
    long cursor = lo, covered = 0;
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    while (it.hasNext()) {
      Instruction ins = it.next();
      long pc = ins.getAddress().getOffset();
      if (pc >= hi) break;
      if (pc > cursor) gaps.add(new long[]{cursor, pc});
      long len = ins.getLength();
      covered += len;
      cursor = Math.max(cursor, pc + len);
    }
    if (cursor < hi) gaps.add(new long[]{cursor, hi});

    println(String.format("  total bytes %d, decoded %d (%.1f%%), gaps %d",
            hi - lo, covered, 100.0 * covered / (hi - lo), gaps.size()));
    for (long[] g : gaps)
      println(String.format("  GAP %08x .. %08x   (%d bytes)", g[0], g[1], g[1] - g[0]));

    // Constants that a cursor setup into PAIR would have to contain, as raw big-endian
    // 32-bit values: the array base and the MIDI half base.
    long[] wanted = {0x80006604L, 0x80006614L, 0x800065e4L, 0x800065f4L};
    println("");
    println("=== raw-byte search of gaps for per-track array base constants ===");
    if (gaps.isEmpty()) println("  (no gaps -- nothing hidden; the scan of decoded code is complete)");
    for (long[] g : gaps) {
      int n = (int) (g[1] - g[0]);
      if (n <= 0 || n > 1 << 20) continue;
      byte[] buf = new byte[n];
      mem.getBytes(sp.getAddress(g[0]), buf);
      for (long wv : wanted) {
        for (int i = 0; i + 4 <= n; i++) {
          long v = ((buf[i] & 0xffL) << 24) | ((buf[i + 1] & 0xffL) << 16)
                 | ((buf[i + 2] & 0xffL) << 8) | (buf[i + 3] & 0xffL);
          if (v == wv)
            println(String.format("  HIT %08x  constant %08x inside gap %08x..%08x",
                    g[0] + i, wv, g[0], g[1]));
        }
      }
    }
    println("  (no HIT lines above means those constants do not occur in any gap)");
  }
}

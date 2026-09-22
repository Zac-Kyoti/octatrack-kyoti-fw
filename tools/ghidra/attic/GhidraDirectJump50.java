//@category Octatrack
// Session 79 continued a twenty-first time, part 3. GhidraDirectJump49 proved the 1586-byte
// undecoded gap 0x400a4568..0x400a4b9a is NOT empty: it contains the cursor-setup constants
// for PAIR (0x80006604 @ 0x400a485c) and NEXT_STEP (0x800065e4 @ 0x400a4862). So the
// earlier "PAIR has no writer anywhere in the firmware" reading was an artefact of scanning
// only DEFINED instructions -- the writer was sitting in undecoded bytes.
//
// Raw objdump of that region shows the shape (lea PAIR/NEXT_STEP/CNTDN_TBL/LEN_TBL cursors,
// a divsl.l at 0x400a4912, then muls/sub -- i.e. a modulo -- then move.w D2,(A1) into PAIR
// and move.w D2,(A0) into NEXT_STEP) but objdump garbles ColdFire mvs/mvz/muls.l/divsl into
// `.short`, which is exactly the trap NOTES.md already records. So force Ghidra to decode
// the gap properly and print it.
//
// This MODIFIES the Ghidra project (adds instructions where there were none). That is the
// desired outcome -- the gap should have been decoded long ago -- and
// ghidra_project.bak_pre_fullanalysis_s70/ exists as a fallback. Run without -noanalysis
// side effects: DisassembleCommand only, no auto-analysis re-run.
//
// Usage: -postScript GhidraDirectJump50.java [loHex hiHex]
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump50 extends GhidraScript {
  public void run() throws Exception {
    long lo = 0x400a485aL, hi = 0x400a4a20L;
    String[] a = getScriptArgs();
    if (a.length >= 2) {
      lo = Long.parseLong(a[0].replace("0x", ""), 16);
      hi = Long.parseLong(a[1].replace("0x", ""), 16);
    }
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Address start = sp.getAddress(lo), end = sp.getAddress(hi);
    AddressSet set = new AddressSet(start, end);

    println(String.format("=== forcing disassembly %08x .. %08x ===", lo, hi));
    DisassembleCommand cmd = new DisassembleCommand(start, set, true);
    boolean ok = cmd.applyTo(currentProgram, monitor);
    println("  DisassembleCommand applied=" + ok + "  status=" + cmd.getStatusMsg());

    Listing listing = currentProgram.getListing();
    println("");
    println("=== decoded listing ===");
    InstructionIterator it = listing.getInstructions(start, true);
    int n = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      StringBuilder w = new StringBuilder();
      for (Object o : ins.getResultObjects())
        if (o instanceof Address) w.append("  W->").append(o);
      println(String.format("%08x  %-8s %-40s%s",
              ins.getAddress().getOffset(),
              bytesOf(ins), ins.toString(), w));
      n++;
    }
    println("  (" + n + " instructions)");
  }

  private String bytesOf(Instruction ins) throws Exception {
    byte[] b = ins.getBytes();
    StringBuilder s = new StringBuilder();
    for (int i = 0; i < b.length && i < 4; i++) s.append(String.format("%02x", b[i]));
    return s.toString();
  }
}

//@category Octatrack
// Session 79 continued a fifteenth time: BAR_CTR is refuted; chasing the REAL gate for the
// extra table-arm write. Raw objdump of 0x400a2a70-0x400a2e40 (ColdFire opcodes partly
// garbled, hence this proper-decode probe) suggests:
//   - a per-track byte flag at *(0xb0,SP) is SET TO 1 at ~0x400a2aac and CLEARED at
//     ~0x400a2afa;
//   - the path to the known write site (0x400a2e12) is gated at ~0x400a2c48-0x400a2c52 on
//     that same flag reading 1 (mvz.b (A2),D0 ; moveq #1,D1 ; cmp.l D0,D1 ; bne skip);
//   - the flag gets set when a LENGTH DIFFERENCE (LEN_TBL[SCALE_IX] - LEN_TBL[other],
//     computed ~0x400a2a96/0x400a2a9a) comes out <= 0, in the same breath as clamping
//     CNTDN_TBL[track] (via the (0xa8,SP) pointer) to 0.
// That would tie the extra write directly to CNTDN_TBL/SCALE_IX at a DIRECT JUMP commit.
// Need a trustworthy decode of 0x400a2a40-0x400a2ad0 (and the gate at 0x400a2c40-0x400a2c70)
// before instrumenting it dynamically.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class GhidraDirectJump44 extends GhidraScript {
  void dump(String label, long lo, long hi) throws Exception {
    println("=== " + label + "  (0x" + Long.toHexString(lo) + " .. 0x" + Long.toHexString(hi) + ") ===");
    Listing listing = currentProgram.getListing();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    InstructionIterator it = listing.getInstructions(sp.getAddress(lo), true);
    Address end = sp.getAddress(hi);
    int n = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      if (ins.getAddress().compareTo(end) > 0) break;
      byte[] bytes = ins.getBytes();
      StringBuilder hex = new StringBuilder();
      for (byte b : bytes) hex.append(String.format("%02x", b));
      println(ins.getAddress() + "  len=" + bytes.length + "  " + String.format("%-14s", hex) + ins.toString());
      n++;
    }
    if (n == 0) println("  (no defined instructions in this range)");
    println("");
  }

  public void run() throws Exception {
    dump("flag-set path + CNTDN_TBL clamp", 0x400a2a40L, 0x400a2ad0L);
    dump("bitmask gate + clear block head", 0x400a2ad0L, 0x400a2b10L);
    dump("write-path gate on the flag", 0x400a2c40L, 0x400a2c70L);
  }
}

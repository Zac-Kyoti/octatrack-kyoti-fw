// Ghidra post-script (Java) -- raw instruction listing (address + mnemonic) for
// a given range, since r2's m68k plugin mis-decodes several ColdFire opcodes in
// this region. Used to pinpoint exact hook bytes for the fresh MUTE MODE design.
//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;

public class GhidraMuteModeAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[][] ranges = {
            {0x4000d0a0L, 0x4000d3e0L},   // amp_frame_filler through the amp-write loop
            {0x400977ccL, 0x40097920L},   // trig_to_voice full body
            {0x40005178L, 0x400051d0L},   // voice mailbox writer prologue
        };
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing listing = currentProgram.getListing();
        for (long[] r : ranges) {
            println("\n---- range 0x" + Long.toHexString(r[0]) + "-0x" + Long.toHexString(r[1]) + " ----");
            Address start = sp.getAddress(r[0]);
            Address end = sp.getAddress(r[1]);
            try { disassemble(start); } catch (Exception e) {}
            Instruction ins = listing.getInstructionAt(start);
            if (ins == null) ins = listing.getInstructionAfter(start);
            while (ins != null && ins.getAddress().compareTo(end) < 0) {
                StringBuilder bytesb = new StringBuilder();
                try {
                    byte[] b = ins.getBytes();
                    for (byte bb : b) bytesb.append(String.format("%02x", bb));
                } catch (Exception e) {}
                println(ins.getAddress() + "  " + bytesb + "  " + ins.toString());
                ins = ins.getNext();
            }
        }
        println("\n[GhidraMuteModeAsm] done.");
    }
}

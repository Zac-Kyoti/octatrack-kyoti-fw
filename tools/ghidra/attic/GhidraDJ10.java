//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraDJ10 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing lst=currentProgram.getListing();
    FunctionManager fm=currentProgram.getFunctionManager();
    // Make sure FUN_400a1eea is disassembled as a function
    Address ent=sp.getAddress(0x400a1eeaL);
    if(fm.getFunctionAt(ent)==null){ disassemble(ent); createFunction(ent,null); }
    long[][] ranges = {
      {0x400a3f60L, 0x400a4230L},   // pattern-boundary / pending-pattern switch
      {0x400a2500L, 0x400a2760L},   // _DAT_46c8028a immediate-reload block
    };
    for(long[] rg : ranges){
      println("\n========== LISTING "+Long.toHexString(rg[0])+" .. "+Long.toHexString(rg[1])+" ==========");
      Address a=sp.getAddress(rg[0]);
      while(a.getOffset() < rg[1]){
        Instruction in=lst.getInstructionAt(a);
        if(in==null){ disassemble(a); in=lst.getInstructionAt(a); }
        if(in==null){ println(String.format("  %s  (no insn)",a)); a=a.add(2); continue; }
        byte[] b; try{b=in.getBytes();}catch(Exception e){b=new byte[0];}
        StringBuilder hx=new StringBuilder(); for(byte x:b) hx.append(String.format("%02x",x));
        // reference comment
        StringBuilder rc=new StringBuilder();
        for(Reference r: in.getReferencesFrom()){
          if(r.getToAddress()!=null && (r.getReferenceType().isData()||r.getReferenceType().isCall()||r.getReferenceType().isJump()))
            rc.append(" -> ").append(r.getToAddress());
        }
        println(String.format("  %s: %-12s %-40s%s", in.getAddress(), hx, in.toString(), rc));
        a=in.getAddress().add(in.getLength());
      }
    }
    println("\n[GhidraDJ10] done.");
  }
}

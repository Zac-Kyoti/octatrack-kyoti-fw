//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class GhidraDJ12 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    Listing lst=currentProgram.getListing();
    FunctionManager fm=currentProgram.getFunctionManager();
    Address ent=sp.getAddress(0x400a1eeaL);
    Function f=fm.getFunctionContaining(ent);
    if(f==null){ disassemble(ent); f=createFunction(ent,null); }
    // force full disassembly by decompiling
    DecompInterface dec=new DecompInterface(); dec.openProgram(currentProgram);
    dec.decompileFunction(f,300,new ghidra.util.task.ConsoleTaskMonitor());
    println("function "+f.getName()+" body: "+f.getBody().getMinAddress()+" .. "+f.getBody().getMaxAddress());
    long lo=0x400a46fcL, hi=0x400a4a44L;
    InstructionIterator it=lst.getInstructions(sp.getAddress(lo), true);
    int n=0;
    while(it.hasNext() && n<600){
      Instruction in=it.next();
      long va=in.getAddress().getOffset();
      if(va>hi) break;
      n++;
      byte[] b; try{b=in.getBytes();}catch(Exception e){b=new byte[0];}
      StringBuilder hx=new StringBuilder(); for(byte x:b) hx.append(String.format("%02x",x));
      String rc="";
      try{
        for(Reference r: in.getReferencesFrom()){
          Address t=r.getToAddress();
          if(t!=null && !r.getReferenceType().isFlow()) rc+=" ->"+t;
        }
      }catch(Exception e){}
      println(String.format("%08x: %-14s %-42s%s", va, hx, in.toString(), rc));
    }
    println("(printed "+n+" insns)");
    println("[GhidraDJ12] done.");
  }
}

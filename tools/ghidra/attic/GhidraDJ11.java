//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraDJ11 extends GhidraScript {
  public void run() throws Exception {
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    FunctionManager fm=currentProgram.getFunctionManager();
    DecompInterface dec=new DecompInterface();
    DecompileOptions opts=new DecompileOptions();
    opts.setMaxPayloadMBytes(64);
    dec.setOptions(opts);
    dec.toggleCCode(true);
    dec.openProgram(currentProgram);
    for(long fa : new long[]{0x400a1eeaL}){
      Address a=sp.getAddress(fa);
      Function f=fm.getFunctionContaining(a);
      if(f==null){disassemble(a); f=createFunction(a,null);}
      DecompileResults r=dec.decompileFunction(f,600,new ghidra.util.task.ConsoleTaskMonitor());
      println("=== "+f.getName()+" (size "+f.getBody().getNumAddresses()+") ===");
      if(r!=null&&r.decompileCompleted()) println(r.getDecompiledFunction().getC());
      else println("FAIL: "+(r!=null?r.getErrorMessage():"null"));
    }
    println("[GhidraDJ11] done.");
  }
}

//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
public class GhidraDJ14 extends GhidraScript {
  public void run() throws Exception {
    var sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    var fm=currentProgram.getFunctionManager();
    var dec=new DecompInterface(); dec.openProgram(currentProgram);
    var mon=new ghidra.util.task.ConsoleTaskMonitor();
    for(long a: new long[]{0x40033968L, 0x400a536cL}){
      var f=fm.getFunctionContaining(sp.getAddress(a));
      if(f==null){disassemble(sp.getAddress(a)); f=createFunction(sp.getAddress(a),null);}
      var r=dec.decompileFunction(f,120,mon);
      println("\n#### "+f.getName()+" @"+f.getEntryPoint()+" ####");
      println(r!=null&&r.decompileCompleted()?r.getDecompiledFunction().getC():"(fail)");
    }
  }
}

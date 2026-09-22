//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.util.*;
public class GhidraDJ9 extends GhidraScript {
  AddressSpace sp; FunctionManager fm; DecompInterface dec; ConsoleTaskMonitor mon; ReferenceManager rm; Listing lst;
  Set<Long> dumped=new HashSet<>();
  void dumpFn(long s,String tag) throws Exception {
    Address a=sp.getAddress(s); Function f=fm.getFunctionContaining(a);
    if(f==null){disassemble(a);f=createFunction(a,null);}
    if(f==null){println("[!] no fn @"+Long.toHexString(s)+" ("+tag+")");return;}
    if(!dumped.add(f.getEntryPoint().getOffset())){println("(dup "+f.getName()+" for "+tag+")");return;}
    DecompileResults r=dec.decompileFunction(f,300,mon);
    println("\n############ "+tag+" :: "+f.getName()+" @ "+f.getEntryPoint()+" (size "+f.getBody().getNumAddresses()+") ############");
    String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():"  (fail: "+(r!=null?r.getErrorMessage():"?")+")";
    if(c.length()>22000)c=c.substring(0,22000)+"\n ...(trunc)";
    println(c);
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    dec=new DecompInterface(); dec.openProgram(currentProgram); mon=new ConsoleTaskMonitor();
    rm=currentProgram.getReferenceManager(); lst=currentProgram.getListing();
    // Disassemble broad ranges so createFunction finds real entries
    for(long a=0x4009b000L; a<0x4009d000L; a+=2) { try{ if(lst.getInstructionAt(sp.getAddress(a))==null) disassemble(sp.getAddress(a)); }catch(Exception e){} }
    // now enumerate functions in the range
    println("== functions 0x4009b000-0x4009d000 ==");
    FunctionIterator fi=fm.getFunctions(sp.getAddress(0x4009b000L), true);
    while(fi.hasNext()){ Function f=fi.next(); if(f.getEntryPoint().getOffset()>0x4009d000L) break;
      println("  "+f.getName()+" @"+f.getEntryPoint()+" sz "+f.getBody().getNumAddresses()); }
    // decompile the ones that look like the pattern-transport controller
    dumpFn(0x4009b8f4L,"?");
    dumpFn(0x4009bd44L,"?");
    dumpFn(0x4009c1e0L,"?");
    dumpFn(0x4009c4e0L,"?");
    // and the msg-0x12 area: FUN_400a0708 host (running-branch caller of FUN_40000c3c) already = FUN_400a0570.
    // find the seq task dispatcher: search image for byte pattern of cmpi.b #0x12 near 0x4009xxxx
    println("\n== scan for opcode compares (0x0c00/0x0c40 cmpi with 0x11/0x12/0x30) 0x40090000-0x400b0000 ==");
    Address a=sp.getAddress(0x40090000L);
    ghidra.program.model.mem.Memory m=currentProgram.getMemory();
    byte[] buf=new byte[0x20000];
    m.getBytes(a,buf);
    for(int i=0;i+4<buf.length;i+=2){
      int w=((buf[i]&0xff)<<8)|(buf[i+1]&0xff);
      int nx=((buf[i+2]&0xff)<<8)|(buf[i+3]&0xff);
      // cmpi.b #imm,Dn  = 0x0C00 | reg ; ext word = imm (byte in low)
      if((w&0xFFF8)==0x0C00 && (nx==0x0011||nx==0x0012||nx==0x0030||nx==0x0018||nx==0x0008)){
        long va=0x40090000L+i; Function f=fm.getFunctionContaining(sp.getAddress(va));
        println(String.format("  %08x cmpi.b #%02x,d%d   %s", va, nx, w&7, f!=null?f.getName()+" @"+f.getEntryPoint():"(no fn)"));
      }
    }
    println("\n[GhidraDJ9] done.");
  }
}

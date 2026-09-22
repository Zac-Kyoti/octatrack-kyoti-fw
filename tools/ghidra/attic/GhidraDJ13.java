//@category Octatrack
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
public class GhidraDJ13 extends GhidraScript {
  AddressSpace sp; FunctionManager fm; DecompInterface dec; ghidra.util.task.ConsoleTaskMonitor mon;
  java.util.Set<Long> seen=new java.util.HashSet<>();
  void dump(long s,String tag) throws Exception {
    Address a=sp.getAddress(s); Function f=fm.getFunctionContaining(a);
    if(f==null){disassemble(a);f=createFunction(a,null);}
    if(f==null){println("no fn @"+Long.toHexString(s));return;}
    if(!seen.add(f.getEntryPoint().getOffset())){println("(dup "+f.getName()+")");return;}
    DecompileResults r=dec.decompileFunction(f,240,mon);
    println("\n#### "+tag+" :: "+f.getName()+" @"+f.getEntryPoint()+" ("+f.getBody().getNumAddresses()+"B) ####");
    String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():"(fail)";
    if(c.length()>13000)c=c.substring(0,13000)+"...(trunc)";
    println(c);
  }
  long findStr(String s) throws Exception {
    Memory m=currentProgram.getMemory();
    for(MemoryBlock b:m.getBlocks()){ if(!b.isInitialized())continue;
      byte[] buf=new byte[(int)b.getSize()]; b.getBytes(b.getStart(),buf);
      byte[] p=s.getBytes("ASCII");
      outer: for(int i=0;i<=buf.length-p.length;i++){ for(int j=0;j<p.length;j++) if(buf[i+j]!=p[j]) continue outer; return b.getStart().getOffset()+i; }
    } return 0;
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace(); fm=currentProgram.getFunctionManager();
    dec=new DecompInterface(); dec.openProgram(currentProgram); mon=new ghidra.util.task.ConsoleTaskMonitor();
    dump(0x4009e884L,"FUN_4009e884 (2-steps-early preload, called from step engine)");
    // program change send: find string, refs
    long s=findStr("MIDI_PROGRAM_CHANGE_SEND"); println("str @"+Long.toHexString(s));
    var rm=currentProgram.getReferenceManager();
    // scan for 0xC0 program-change status construction: `ori.b #0xC0` / `#0xc0` immediates near midi send
    Memory m=currentProgram.getMemory(); Address a=sp.getAddress(0x40000400L);
    byte[] buf=new byte[0x110000]; m.getBytes(a,buf);
    println("\n== candidates: '#0xC0' immediate (0x00c0 ext word after cmpi/ori/move) ==");
    int n=0;
    for(int i=0;i+2<buf.length && n<30;i+=2){
      int w=((buf[i]&0xff)<<8)|(buf[i+1]&0xff);
      int nx=((buf[i+2]&0xff)<<8)|(buf[i+3]&0xff);
      // move.b #imm,Dn = 0x70xx (moveq) ; or ori.b #imm = 0x00xx ext ; look for 0x00c0 as ext word
      if(nx==0x00c0 && ((w&0xff00)==0x0000 || (w&0xfff8)==0x7000 || (w&0xf1ff)==0x103c)){
        long va=0x40000400L+i; Function f=fm.getFunctionContaining(sp.getAddress(va));
        println(String.format("  %08x w=%04x ext=00c0  %s", va, w, f!=null?f.getName():"?"));
        n++;
      }
    }
    // also: moveq #-64 (0x70c0) which = 0xC0
    println("\n== moveq #-64 (0x70c0) ==");
    n=0;
    for(int i=0;i+1<buf.length && n<40;i+=2){
      int w=((buf[i]&0xff)<<8)|(buf[i+1]&0xff);
      if(w==0x70c0){ long va=0x40000400L+i; Function f=fm.getFunctionContaining(sp.getAddress(va));
        println(String.format("  %08x moveq #-64,d0   %s", va, f!=null?f.getName()+" @"+f.getEntryPoint():"?")); n++; }
    }
    println("\n[GhidraDJ13] done.");
  }
}

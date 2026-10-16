#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Writes the generated half of octabam-modules/blackpyramids-303/ from the sources the standalone
build uses (tools/build_blackpyramids_303.py), and proves each piece is the standalone's bytes:

  bp_runtime.s     the ColdFire runtime as ONE GNU-as unit: cf/machine.s, the C (control, record,
                   params and the Y table) as `m68k-elf-gcc -S` output, and libgcc's __muldi3 (the
                   one routine the link pulls; octabam's DRAM link has no libgcc) as words. Laid out
                   as runtime.ld lays the objects out (.text, .rodata, .rodata.*, .data, in link
                   order), each file's local labels made unique. Linked alone at the standalone's
                   address it must be the standalone runtime byte for byte -- the module's
                   Linked.reference -- and this script refuses to write it otherwise.
  bp_dsp_A.asm /   each payload's DSP source as the standalone assembles it (macros expanded,
  bp_dsp_B.asm     layout substituted), for reading; tools/dsp_xasm.py assembles it
  bp_dsp_data.py   each payload's assembled words, the X words over SPRING's records, the seam
                   and continuation, with sha256s: what bp_image.py writes

Usage:  python3 tools/ot303/octabam_module.py        (after tools/build_blackpyramids_303.py)
"""
import hashlib, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "ot303"))
import dram            # noqa: E402
import hwprobe_image   # noqa: E402
import asm_macros      # noqa: E402

CF = ROOT / "tools/ot303/cf"
WORK = ROOT / "out/ot303/cf"
OUT = ROOT / "octabam-modules/blackpyramids-303"
# the standalone builder's flags (tools/build_blackpyramids_303.py CFLAGS)
CFLAGS = ["-mcpu=5407", "-msoft-float", "-O2", "-ffreestanding", "-fno-builtin", "-fno-common", "-fno-jump-tables",
          "-fno-asynchronous-unwind-tables", "-fno-ident", "-fomit-frame-pointer", "-fno-zero-initialized-in-bss",
          "-Wall", "-Wextra", "-Werror"]
C_UNITS = ("control", "record", "params", "ytab")       # the standalone's link order, after machine.o
SUB = {"text": 0, "rodata": 1, "rodata.str": 2, "data": 3}


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def sections_of(obj):
    """{section: alignment in bytes} of an object's non-empty alloc sections"""
    out = {}
    for line in run("m68k-elf-objdump", "-h", obj).splitlines():
        f = line.split()
        if len(f) == 7 and f[1].startswith(".") and int(f[2], 16):
            out[f[1]] = 1 << int(f[6].split("**")[1])
    return out


def split(asm, tag):
    """gcc -S text -> {kind: [lines]}, its local labels and file-static symbols renamed apart"""
    globs = set(re.findall(r"^\s*\.globl\s+(\S+)", asm, re.M))
    defined = set(re.findall(r"^([A-Za-z_.$][A-Za-z0-9_.$]*):", asm, re.M))
    local = sorted((d for d in defined if d not in globs), key=len, reverse=True)
    for name in local:
        new = (f".L{tag}_{name[2:]}" if name.startswith(".L") else f"{tag}__{name}")
        # a use may carry a size suffix (`core_frames.l`), never another identifier character
        asm = re.sub(rf"(?<![A-Za-z0-9_.$]){re.escape(name)}(?![A-Za-z0-9_$])(?!\.(?![bwls](?![A-Za-z0-9_.$])))", new, asm)
    parts = {k: [] for k in SUB}
    cur = "text"
    for line in asm.splitlines():
        s = line.strip()
        if s == ".text":
            cur = "text"; continue
        if s == ".data":
            cur = "data"; continue
        if s.startswith(".section"):
            name = s.split()[1].rstrip(",")
            cur = "rodata.str" if name.startswith(".rodata.") else "rodata" if name == ".rodata" else None
            if cur is None:
                sys.exit(f"{tag}: section {name} not handled")
            continue
        if s.startswith(".file") or s == "#NO_APP" or s == "#APP":
            continue
        parts[cur].append(line)
    parts["rodata.str"] = tail_merge(parts["rodata.str"])
    return parts


def tail_merge(lines):
    """ld's SEC_MERGE tail merging (bfd merge.c) of one `.rodata.str1.1` chunk: sorted by reversed
    content, a string that is a suffix of the next one is not stored -- its label points into that
    one's tail (here: "" lands on "ACC"'s NUL). The unit keeps it as a `.set`."""
    strs, label = [], None
    for line in lines:
        m = re.match(r"^(\S+):$", line.strip())
        if m:
            label = m.group(1); continue
        m = re.match(r'^\.string\s+"(.*)"$', line.strip())
        if m and label:
            strs.append((label, m.group(1).encode().decode("unicode_escape"))); label = None; continue
        if line.strip():
            sys.exit(f"rodata.str: unexpected {line!r}")
    order = sorted(strs, key=lambda t: t[1][::-1])
    into = {}
    for (la, a), (lb, b) in zip(order, order[1:]):
        if b.endswith(a):
            into[la] = (lb, len(b) - len(a))
    def root(l):
        off = 0
        while l in into:
            l, o = into[l]; off += o
        return l, off
    out = []
    for la, a in strs:
        if la in into:
            continue
        out += [f"{la}:", "\t.string\t\"" + a.encode("unicode_escape").decode().replace('"', '\\"') + "\""]
    for la, a in strs:
        if la in into:
            r, off = root(la)
            out.append(f"\t.set\t{la}, {r} + {off}")
    return out


LABEL = re.compile(r"^([A-Za-z_.$][A-Za-z0-9_.$]*):")
# gas's m68k pseudo-branches: to a symbol outside the file they assembled as Bcc.L (opcode
# 0x6cff | cc << 8, then the 32-bit displacement from the extension word). Written out as words:
# octabam assembles DRAM units for -mcpu=54455, whose gas table refuses Bcc.L although the chip
# runs it (the standalone does, on the unit) -- the words are the same bytes for either CPU.
_CC = dict(ra=0, sr=1, hi=2, ls=3, cc=4, hs=4, cs=5, lo=5, ne=6, eq=7, vc=8, vs=9, pl=10, mi=11,
           ge=12, lt=13, gt=14, le=15)
JBRANCH = {"jbsr": 1, "jra": 0, "jbra": 0, **{f"j{c}": v for c, v in _CC.items() if c not in ("ra", "sr")}}
PAREN = re.compile(r"^\(([A-Za-z_.$][A-Za-z0-9_.$]*)([+-](?:0x[0-9a-fA-F]+|\d+))?\)$")   # `(sym)` absolute
PREFIX = re.compile(r"^(?:[A-Za-z_.$][A-Za-z0-9_.$]*|\d+):")      # a label before an instruction
OPND = re.compile(r"^([A-Za-z_.$][A-Za-z0-9_.$]*)([+-](?:0x[0-9a-fA-F]+|\d+))?$")


def absolute(lines, here, every):
    """In one chunk (one file's one section), give every bare-symbol operand naming a symbol of
    ANOTHER chunk an explicit `.l`. Assembled apart, such a reference was another file's or another
    section's, so gas left it absolute long; in the one unit it would relax it (a `jsr` or `lea` to
    PC-relative) and every byte after it would move. References inside the chunk stay as written:
    the standalone's gas relaxed them, and this one relaxes them the same way."""
    out = []
    for line in lines:
        code, sep, comment = line.partition("|") if "|" in line else (line, "", "")
        body = code
        m = PREFIX.match(body.strip())
        lead = ""
        if m:
            i = code.index(m.group(0)) + len(m.group(0))
            lead, body = code[:i], code[i:]
        st = body.strip()
        if not st or st.startswith(".") or st.startswith("#"):
            out.append(line)
            continue
        mn, _, ops = st.partition(" ")
        ops = ops.strip()
        if not ops:
            out.append(line)
            continue
        parts, depth, cur = [], 0, ""
        for ch in ops:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur); cur = ""
            else:
                cur += ch
        parts.append(cur)
        new = []
        indent = body[:len(body) - len(body.lstrip())]
        mo = OPND.match(ops)
        if mn in JBRANCH and mo and mo.group(1) in every and mo.group(1) not in here:
            out.append(f"{lead}{indent}.short\t0x{0x60ff | JBRANCH[mn] << 8:04x}\t| {mn} {ops} (Bcc.L)")
            out.append(f"{indent}.long\t{ops} - .")
            continue
        for op in parts:
            mo = OPND.match(op.strip()) or PAREN.match(op.strip())
            if mo and mo.group(1) in every and mo.group(1) not in here:
                op = op.strip() + ".l"
            new.append(op)
        out.append(f"{lead}{indent}{mn}\t{','.join(new)}" + (f" {sep}{comment}" if sep else ""))
    return out


def runtime_source():
    hwprobe_image.write_ytab(WORK / "ytab.c")
    pieces, aligns = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for u in C_UNITS:
            src = WORK / "ytab.c" if u == "ytab" else CF / f"{u}.c"
            s, o = tmp / f"{u}.s", tmp / f"{u}.o"
            run("m68k-elf-gcc", *CFLAGS, f"-I{CF}", "-S", src, "-o", s)
            run("m68k-elf-as", "-mcpu=5407", "-o", o, s)
            pieces[u] = split(s.read_text(), u)
            aligns[u] = sections_of(o)
        # __muldi3, from the ColdFire multilib's libgcc (its .text carries no relocations)
        lib = run("m68k-elf-gcc", "-mcpu=5407", "-print-libgcc-file-name").strip()
        assert "m5407" in lib, lib
        run("m68k-elf-ar", "x", lib, "_muldi3.o", cwd=tmp)
        mo = tmp / "_muldi3.o"
        if ".text" in run("m68k-elf-objdump", "-r", "-j", ".text", mo):
            assert "RELOCATION RECORDS FOR [.text]" not in run("m68k-elf-objdump", "-r", "-j", ".text", mo)
        run("m68k-elf-objcopy", "-O", "binary", "-j", ".text", mo, tmp / "m.bin")
        mul = (tmp / "m.bin").read_bytes()
        mul_align = sections_of(mo)[".text"]
    mach = (CF / "machine.s").read_text()
    assert not re.search(r"^\s*\.(data|section|bss)\b", mach, re.M), "machine.s: .text only"

    chunks = {("machine", "text"): mach.splitlines()}
    for u in C_UNITS:
        for k in SUB:
            if pieces[u][k]:
                chunks[(u, k)] = pieces[u][k]
    defs = {c: {LABEL.match(l.strip()).group(1) for l in ls if LABEL.match(l.strip())} for c, ls in chunks.items()}
    every = set().union(*defs.values()) | {"__muldi3"}
    for c in chunks:
        chunks[c] = absolute(chunks[c], defs[c], every)
    mach = "\n".join(chunks[("machine", "text")])
    for (u, k), ls in chunks.items():
        if u != "machine":
            pieces[u][k] = ls

    out = ["| BLACKPYRAMIDS_303's ColdFire runtime as one unit. GENERATED by tools/ot303/octabam_module.py",
           "| from tools/ot303/cf/{machine.s,control.c,record.c,params.c} and the Y table -- do not edit;",
           "| edit those and regenerate. Subsections keep the standalone link's layout: 0 .text, 1 .rodata,",
           "| 2 .rodata.*, 3 .data (tools/build_blackpyramids_303.py runtime.ld).",
           "        .text 0", "| ---- machine.s", mach]
    for k, sub in SUB.items():
        for u in C_UNITS:
            if not pieces[u][k]:
                continue
            sec = {"text": ".text", "rodata": ".rodata", "rodata.str": ".rodata.str1.1", "data": ".data"}[k]
            a = aligns[u].get(sec, 1)
            if k == "data" and not any(pieces[x][k] for x in C_UNITS[:C_UNITS.index(u)]):
                a = max(a, 4)                        # runtime.ld: .data : ALIGN(4)
            out += [f"        .text {sub}", f"| ---- {u}.c {sec}", f"        .balign {a},0"] + pieces[u][k]
        if k == "text":
            out += ["        .text 0", "| ---- libgcc __muldi3 (m5407 multilib), its bytes",
                    f"        .balign {mul_align},0", "        .globl __muldi3", "__muldi3:"]
            out += ["        .short " + ",".join(f"0x{int.from_bytes(mul[i:i + 2], 'big'):04x}" for i in range(j, min(j + 16, len(mul)), 2))
                    for j in range(0, len(mul), 16)]
    # ld aligns its location for every later input .data, empty ones included (4 in each file
    # after control.c, and libgcc's): the output .data ends on 4
    out += ["        .text 3", "        .balign 4,0"]
    return "\n".join(out) + "\n"


def link_alone(src_text, at, cpu):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "u.s").write_text(src_text)
        run("m68k-elf-as", f"-mcpu={cpu}", "-o", tmp / "u.o", tmp / "u.s")
        run("m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", tmp / "u.elf", tmp / "u.o")
        run("m68k-elf-objcopy", "-O", "binary", tmp / "u.elf", tmp / "u.bin")
        und = run("m68k-elf-nm", "-u", tmp / "u.elf").replace("U _start", "").strip()   # ld's default entry
        assert not und, f"undefined: {und}"
        return (tmp / "u.bin").read_bytes()


def main():
    ref = (WORK / "ot303_runtime.bin").read_bytes()
    src = runtime_source()
    for cpu in ("5407", "54455"):             # the standalone's ISA, and octabam's DRAM units'
        got = link_alone(src, dram.RESERVE, cpu)
        if got != ref:
            n = next((i for i in range(min(len(got), len(ref))) if got[i] != ref[i]), min(len(got), len(ref)))
            sys.exit(f"bp_runtime.s (-mcpu={cpu}) is not the standalone runtime: {len(got)} vs {len(ref)} B, "
                     f"first difference at +0x{n:x}")
    sha = hashlib.sha256(ref).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bp_runtime.s").write_text(src)
    print(f"  bp_runtime.s: {len(ref)} B linked alone at 0x{dram.RESERVE:08x} (5407 and 54455) = the standalone "
          f"runtime, sha256 {sha}")

    data = ["# BLACKPYRAMIDS_303's DSP, both payloads. GENERATED by tools/ot303/octabam_module.py from",
            "# tools/ot303/{ot303_engine.asm,host.asm} through tools/ot303/hwprobe_image.py (host=True) -- the",
            "# standalone build's words; bp_dsp_<payload>.asm is the source as assembled. Do not edit.",
            f"RUNTIME_ADDR = 0x{dram.RESERVE:08x}", f"RUNTIME_SHA256 = {sha!r}", "PAYLOAD = {"]
    for tag in ("A", "B"):
        b = hwprobe_image.build(tag, host=True)
        s, _ = hwprobe_image.source(tag, host=True)
        (OUT / f"bp_dsp_{tag}.asm").write_text(
            f"; BLACKPYRAMIDS_303, DSP payload {tag}, org P:${b['org']:x}. GENERATED by tools/ot303/octabam_module.py\n"
            f"; (tools/ot303/ot303_engine.asm + host.asm, macros expanded, layout substituted); tools/dsp_xasm.py\n"
            f"; assembles it into bp_dsp_data.py's words. Do not edit.\n" + asm_macros.expand(s))
        w = b["words"]
        x = sorted(b["x"].items())
        wsha = hashlib.sha256(b"".join(v.to_bytes(3, "big") for v in w)).hexdigest()
        data += [f"    {tag!r}: dict(",
                 f"        org=0x{b['org']:05x}, seam=0x{b['seam']:05x}, seam_entry=0x{b['seam_entry']:05x}, cont=0x{b['cont']:05x},",
                 f"        words_sha256={wsha!r},",
                 "        words=(" + ",".join(f"0x{v:06x}" for v in w) + "),",
                 "        x=(" + ",".join(f"(0x{a:05x},0x{v:06x})" for a, v in x) + "),",
                 "    ),"]
        print(f"  payload {tag}: {len(w)} words at P:0x{b['org']:05x}, {len(x)} X words, seam P:0x{b['seam']:05x} -> "
              f"P:0x{b['seam_entry']:05x}")
    data.append("}")
    (OUT / "bp_dsp_data.py").write_text("\n".join(data) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
A thin, verifying layer over dsp_asm (vendor/dsp56300 dsp_host) for DSP56300
source that needs what dsp_asm gets wrong or lacks. Added for repitch-kyoti
rev 11 (NOTES Session 110).

dsp_asm traps this layer exists for (each measured, 2026-09-28):
  * an ALU op with an XY DUAL move (`mac y0,x0,a x:(r0)+,x0 y:(r4)+,y0`)
    assembles SILENTLY as `macsu y0,x0,a` -- a different instruction, moves
    dropped. A single parallel move and a plain XY `move` both encode right,
    and on this chip an XY+ALU word is exactly the XY move's encoding with the
    ALU opcode in its low byte (stock's own `mac y0,x0,a x:(r0)+,x1
    y:(r5)+n5,y1` = d5b8d2). So those lines are built from the two halves.
  * operand order matters: `mpy x0,y0,a x:(r6)+,x1` drops the move where
    `mpy y0,x0,a ...` keeps it. Caught by the check below.
  * no `movem`, no data directive, no constants, no backward short branches
    (`bge label` to an earlier label -> InvalidInstruction; use `jcc`).

Extensions accepted here:
    NAME    equ     expr            textual constant (python int expression)
            dc      v[,v...]        raw data words (expr each)
            movem   p:(rN)+,D       program-memory read, D in x0 x1 y0 y1 a b
            <alu>   x:...,R y:...,R XY dual move with an ALU op

THE CHECK: the finished blob is disassembled and every instruction is
compared, operand for operand, with the source (labels resolved). Any
mismatch is fatal. Data words are skipped.

    python3 tools/dsp_xasm.py SRC ORG [--list]      (prints words as hex)
    import dsp_xasm; words, syms = dsp_xasm.assemble(src_text, org)
"""
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DSP_ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DSP_DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"

MOVEM_DST = {"x0": 0b000100, "x1": 0b000101, "y0": 0b000110, "y1": 0b000111,
             "a": 0b001110, "b": 0b001111}


BRANCHES = {"bra", "bsr", "bcc", "bcs", "beq", "bge", "bgt", "bhs", "ble", "blo", "blt",
            "bmi", "bne", "bpl", "bvc", "bvs", "bec", "bes", "blc", "bls", "bnn", "bnr"}


class AsmError(Exception):
    pass


def _run_asm(text, org):
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "s.asm"
        out = pathlib.Path(d) / "s.bin"
        sym = pathlib.Path(d) / "s.sym"
        src.write_text(text)
        r = subprocess.run([str(DSP_ASM), "-in", str(src), "-org", f"{org:x}", "-out", str(out),
                            "-list", "-sym", str(sym)], capture_output=True, text=True)
        if r.returncode:
            raise AsmError(r.stdout + r.stderr)
        raw = out.read_bytes()
        syms = {}
        for line in sym.read_text().splitlines():
            if line.strip():
                n, a = line.split()
                syms[n] = int(a, 16)
        listing = [l for l in r.stdout.splitlines() if re.match(r"^[0-9a-f]{6}: ", l)]
    words = [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]
    return words, syms, listing


def _one(ins):
    """Assemble one position-independent instruction; its words."""
    words, _, _ = _run_asm(f"z_:\n        {ins}\n", 0x1000)
    return words


def disassemble(words, org):
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "d.bin"
        p.write_bytes(b"".join(w.to_bytes(3, "little") for w in words))
        r = subprocess.run([str(DSP_DIS), "-in", str(p), "-pc", f"{org:x}", "-le"],
                           capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^([0-9a-f]{6}): (.*?)\s*;\s*([0-9a-f ]+)$", line)
        if m:
            out[int(m.group(1), 16)] = (m.group(2).strip(), len(m.group(3).split()))
    return out


def _norm(text, syms):
    """Canonical operand tokens for comparing source with disassembly."""
    t = text.lower().replace("<", "").replace(">", "")
    t = re.sub(r"^movem\b", "move", t.strip())
    for name in sorted(syms, key=len, reverse=True):
        t = re.sub(rf"\b{re.escape(name.lower())}\b", f"${syms[name]:x}", t)
    toks = re.findall(r"[a-z_][a-z0-9_.]*|\$[0-9a-f]+|#|[-+()]|,|:|\d+", t)
    out = []
    for tk in toks:
        if tk.startswith("$"):
            out.append(str(int(tk[1:], 16)))
        elif tk.isdigit():
            out.append(str(int(tk)))
        else:
            out.append(tk)
    return out


def _split_moves(rest):
    """'y0,x0,a x:(r0)+,x0 y:(r4)+,y0' -> ('y0,x0,a', 'x:(r0)+,x0', 'y:(r4)+,y0')."""
    parts = rest.split()
    return parts


def assemble(src, org):
    # ---- equ + comments
    consts = {}
    lines = []
    for raw in src.splitlines():
        line = raw.split(";", 1)[0].rstrip()
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(.+)$", line)
        if m:
            consts[m.group(1)] = int(eval(m.group(2).replace("$", "0x"), {}, dict(consts)))
            continue
        lines.append(line)

    def subst(s):
        for n in sorted(consts, key=len, reverse=True):
            s = re.sub(rf"\b{n}\b", f"${consts[n] & 0xffffff:x}", s)
        return s

    # ---- specials -> placeholders
    labels = set()
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):", line)
        if m:
            labels.add(m.group(1))
    out_lines, specials = [], []           # specials: (index in out_lines, kind, payload)
    for line in lines:
        s = subst(line)
        body = s.strip()
        if not body:
            continue
        if body.endswith(":") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*:$", body):
            out_lines.append(body)
            continue
        lab = ""
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", body)
        if m:
            lab, body = m.group(1) + ":", m.group(2)
            out_lines.append(lab)
        op, _, rest = body.partition(" ")
        rest = rest.strip()
        if op == "dc":
            vals = [int(eval(v.replace("$", "0x"), {}, dict(consts))) & 0xffffff for v in rest.split(",")]
            for v in vals:
                specials.append((len(out_lines), "dc", v))
                out_lines.append("        nop")
            continue
        if op == "movem":
            m = re.match(r"^p:\(r([0-7])\)\+,(\w+)$", rest.replace(" ", ""))
            if not m:
                raise AsmError(f"movem form not supported: {body}")
            rn, dst = int(m.group(1)), m.group(2)
            w = 0x07 << 16 | 1 << 15 | 1 << 14 | 0b011 << 11 | rn << 8 | 0b10 << 6 | MOVEM_DST[dst]
            specials.append((len(out_lines), "movem", (w, body)))
            out_lines.append("        nop")
            continue
        if op in BRANCHES and rest in labels:
            # always the long form, displacement patched once labels are known
            specials.append((len(out_lines), "br", (op, rest, body)))
            out_lines.append(f"        {op}     >$100")
            continue
        parts = rest.split()
        if len(parts) == 3 and parts[1].startswith("x:") and parts[2].startswith("y:") and op != "move":
            specials.append((len(out_lines), "xy", (op, parts, body)))
            out_lines.append("        nop")
            continue
        out_lines.append("        " + body)

    text = "\n".join(out_lines) + "\n"
    words, syms, listing = _run_asm(text, org)

    # map each emitted instruction back to its out_lines index
    addr_of_line = {}
    inst_idx = [i for i, l in enumerate(out_lines) if not l.endswith(":")]
    if len(listing) != len(inst_idx):
        raise AsmError(f"listing has {len(listing)} entries for {len(inst_idx)} instructions")
    for i, l in zip(inst_idx, listing):
        addr_of_line[i] = int(l[:6], 16)

    expect = {}                            # addr -> source text to compare (None = data)
    for i, l in zip(inst_idx, listing):
        expect[addr_of_line[i]] = l.split(":", 1)[1].split(";")[0].strip()
    for idx, kind, pay in specials:
        a = addr_of_line[idx]
        if kind == "dc":
            words[a - org] = pay
            expect[a] = None
        elif kind == "br":
            op, target, body = pay
            if words[a - org + 1] != 0x100:
                raise AsmError(f"P:{a:05x}: {op} placeholder did not assemble long")
            words[a - org + 1] = (syms[target] - a) & 0xffffff
            expect[a] = ("br", op, syms[target])
        elif kind == "movem":
            words[a - org] = pay[0]
            expect[a] = pay[1]
        else:
            op, parts, body = pay
            mv = _one(f"move {parts[1]} {parts[2]}")
            alu = _one(f"{op} {parts[0]}")
            if len(mv) != 1 or len(alu) != 1 or (mv[0] & 0xff) != 0 or (mv[0] >> 23) != 1:
                raise AsmError(f"cannot build XY+ALU for: {body}")
            words[a - org] = (mv[0] & 0xffff00) | (alu[0] & 0xff)
            expect[a] = body

    # ---- THE CHECK
    dis = disassemble(words, org)
    for a, src_text in sorted(expect.items()):
        if src_text is None:
            continue
        got = dis.get(a)
        if got is None and src_text == "nop" and words[a - org] == 0:
            continue                       # the disassembler prints no line for a nop
        if got is None:
            raise AsmError(f"P:{a:05x}: no disassembly for '{src_text}'")
        if isinstance(src_text, tuple):
            _, op, target = src_text
            g = got[0].split()
            dest = None
            if len(g) == 2:
                m = re.match(r"^(?:[a-z]+_)([0-9a-f]+)$", g[1])          # func_001200: absolute
                if m:
                    dest = int(m.group(1), 16)
                else:
                    m = re.match(r"^(-?)\$([0-9a-f]+)$", g[1])            # $8 / -$d: relative
                    if m:
                        dest = (a + (-1 if m.group(1) else 1) * int(m.group(2), 16)) & 0xffffff
            if g[0] != op or dest != target:
                raise AsmError(f"P:{a:05x}: branch encodes as '{got[0]}', wanted {op} -> {target:05x}")
            continue
        if _norm(got[0], syms) != _norm(src_text, syms):
            raise AsmError(f"P:{a:05x}: encodes as '{got[0]}', source says '{src_text}'")
    return words, syms


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]).read_text()
    org = int(sys.argv[2], 16)
    try:
        words, syms = assemble(src, org)
    except AsmError as e:
        sys.exit(f"dsp_xasm: {e}")
    if "--list" in sys.argv:
        dis = disassemble(words, org)
        for a in range(org, org + len(words)):
            if a in dis:
                print(f"{a:05x}: {words[a - org]:06x}  {dis[a][0]}")
    print(f"{len(words)} words, {len(syms)} symbols")

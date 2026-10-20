#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Shared dsp_asm/dsp56kDisassemble helper -- used by both build_sidechain_compressor.py's
sc_assemble() and emu_sc_dsp3.py's assemble() so the two never drift (same
rationale as sc_tables.py for the coefficient tables).

Session 76 continued yet again: both call sites used to find `rts` boundaries
by scanning raw 24-bit CODE WORDS for the literal value 0x00000c (rts's own
opcode encoding) -- but 0x00000c is also a perfectly ordinary DISPLACEMENT
for a 2-word `bra`/`bcc` (or an operand word for a 2-word long-immediate
move), so a branch that happens to jump exactly 12 words forward is
indistinguishable, to a raw word scan, from a real standalone `rts`. This
went undetected for many sessions because no prior branch's displacement
ever happened to collide -- until this session's KEY FLT HP re-entry
declick added `bra zz08` with a displacement of exactly 12, which silently
shifted every later rts index by one and pointed `moncommit`'s computed
address into the MIDDLE of zz18's body instead of moncommit's real entry.
Caught only because emu_sc_dsp3_moncommit.py failed after a full rebuild --
NOT by the existing round-trip disassembly check (which only rejects
invalid opcodes, not wrong addresses) -- so this would have gone to
hardware wired wrong had the moncommit test not been re-run post-edit.

Fix: find `rts` from the DISASSEMBLER's own parsed instruction boundaries
(it already knows a 2-word instruction's second word is an operand, not a
new opcode), not by scanning raw words.
"""
import re

_RTS_LINE = re.compile(r"^([0-9a-f]{6}):\s+rts\b", re.MULTILINE)


def find_rts(dis_text, cave_org):
    """Return word-offsets (relative to cave_org) of every real standalone
    `rts` instruction in dsp56kDisassemble's -le text output."""
    return sorted(int(m.group(1), 16) - cave_org for m in _RTS_LINE.finditer(dis_text))


def mnemonic_mismatches(asm_text, disasm_text):
    """Instructions dsp_asm encoded as something else (2026-10-19: `tfr a,b` came back as
    `rnd b`, `cmp b,a` as `maxm a,b`; the opcode round trip did not notice). Compares the
    first word of every source instruction with the disassembly, in order. Returns
    [(index, source, disassembly)]; an empty list is clean."""
    import re
    src = []
    for line in asm_text.splitlines():
        s = line.split(";")[0].strip()
        if not s or s.endswith(":"):
            continue
        src.append(s)
    dis = [re.sub(r"\s+", " ", l[8:].split(";")[0]).strip()
           for l in disasm_text.splitlines() if re.match(r"^[0-9a-f]{6}: ", l)]
    out = [(i, a, b) for i, (a, b) in enumerate(zip(src, dis)) if a.split()[0] != b.split()[0]]
    if len(dis) < len(src):
        out.append((len(dis), "(source continues)", "(disassembly ended)"))
    return out

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303: expand `NAME macro` .. `endm` blocks (no parameters) before tools/dsp_xasm.py, which has
# no macros. A line holding only NAME is replaced by the block's lines. Labels inside a macro
# would repeat, so they are refused.
import re


def expand(src):
    macros, out, cur = {}, [], None
    for line in src.splitlines():
        code = line.split(';', 1)[0].strip()
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s+macro$', code)
        if m:
            cur = m.group(1); macros[cur] = []; continue
        if code == 'endm':
            cur = None; continue
        if cur is not None:
            if re.match(r'^[A-Za-z_][A-Za-z0-9_]*:', code):
                raise ValueError(f'label inside macro {cur}: {line}')
            macros[cur].append(line); continue
        if code in macros:
            out.extend(macros[code]); continue
        out.append(line)
    if cur is not None:
        raise ValueError(f'macro {cur} has no endm')
    return '\n'.join(out) + '\n'


def yspace(src):
    """the names a `;@Y` line lists: they live in Y memory (everything else named is X)"""
    names = set()
    for line in src.splitlines():
        if line.startswith(';@Y'):
            names.update(line[3:].split())
    return names


def layout(src, **vals):
    """rewrite `NAME equ VALUE ;@LAYOUT ...` lines: the builders place the engine per payload"""
    seen = set()

    def sub(m):
        name = m.group(1)
        if name not in vals:
            return m.group(0)
        seen.add(name)
        return f'{name:<8}equ     ${vals[name]:x}{m.group(3)}'
    out = re.sub(r'^([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(\S+)(\s*;@LAYOUT.*)$', sub, src, flags=re.M)
    missing = set(vals) - seen
    if missing:
        raise ValueError(f'no ;@LAYOUT line for {sorted(missing)}')
    return out

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
VARISPEED_EMUS's DSP kernel: no address register used for addressing right after it
is loaded.

The DSP56300 stalls an instruction that generates an address with an R or N register
the previous instruction wrote (a move, a parallel register move, a LUA); dsp56kEmu
neither stalls nor prices it, so the profile cannot see one. This reads the assembled
kernel (tools/repitch_dsp_src.py, both payloads) and lists every pair of instructions,
adjacent in address order, where the first writes rN / nN and the second addresses with
it ((rN), (rN)+, (rN)+nN, (rN+nN), (rN+disp), and nN as the update or index).
Post-updates by the AGU itself ((rN)+, (rN)+nN) are not loads and do not count. A
branch target's other predecessor is a branch, which writes no AGU register.

    python3 tools/repitch_dsp_stall_check.py
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dsp_xasm                          # noqa: E402
import repitch_dsp_src as dsrc           # noqa: E402

ORG = 0x1400


def writes(text):
    op, *ops = text.split()
    w = set()
    for tok in ops:
        m = re.search(r",([rn][0-7])$", tok)            # move ...,rN / parallel S,rN
        if m:
            w.add(m.group(1))
    if op == "lua":
        w.add(ops[-1].split(",")[-1])
    return w


def addressing(text):
    u = set()
    for m in re.finditer(r"\((r[0-7])\)(?:[+-](n[0-7]))?", text):
        u.update(x for x in m.groups() if x)
    for m in re.finditer(r"\((r[0-7])[+-](n[0-7]|\$?[0-9a-f]+)\)", text):
        u.add(m.group(1))
        if m.group(2).startswith("n"):
            u.add(m.group(2))
    return u


def main():
    bad = 0
    for tag in ("A", "B"):
        words, syms, _ = dsrc.assemble(ORG, tag)
        dis = dsp_xasm.disassemble(words, ORG)
        name = {v: k for k, v in syms.items()}
        addrs, a = [], ORG                      # every instruction in order (the disassembler
        while a < ORG + len(words):             # prints no line for a nop: it is one too)
            addrs.append(a)
            if a not in dis:
                dis[a] = ("nop", 1)
            a += dis[a][1]
        for a, b in zip(addrs, addrs[1:]):
            hit = writes(dis[a][0]) & addressing(dis[b][0])
            if hit:
                bad += 1
                print(f"  {tag} P:{a:05x} {name.get(a, ''):6} {dis[a][0]:40s} -> {dis[b][0]}   [{', '.join(sorted(hit))}]")
        print(f"payload {tag}: {len(words)} words, {len(addrs)} instructions checked")
    print("PASS: no address register is used right after it is loaded" if not bad else f"FAIL: {bad} stalls")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

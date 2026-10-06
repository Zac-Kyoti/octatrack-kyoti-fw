#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""Summarise ot_emu's OT_ISR_OUT / OT_TICK_OUT episode files (ot_emu_load_audit.patch):
one line per file, instructions per episode -- mean, p50, p99, p99.9, max. The frame ISR is
the IPL-5 episodes above ~5,000 instructions; the small ones are other level-5+ interrupts."""
import sys, statistics as st
def stats(path, skip=200):
    ep=[tuple(map(int,l.split())) for l in open(path)]
    ep=ep[skip:]
    L=sorted(x[1] for x in ep)
    if not L: return None
    return dict(n=len(L), mean=st.mean(L), p50=L[len(L)//2], p99=L[int(len(L)*0.99)], p999=L[int(len(L)*0.999)], max=L[-1], maxat=max(ep,key=lambda x:x[1])[0])
if __name__=='__main__':
    for p in sys.argv[1:]:
        s=stats(p)
        print('%-40s n %6d  mean %7.0f  p50 %6d  p99 %6d  p99.9 %6d  max %6d (at instr %d)'%(p.split('/')[-1],s['n'],s['mean'],s['p50'],s['p99'],s['p999'],s['max'],s['maxat']))

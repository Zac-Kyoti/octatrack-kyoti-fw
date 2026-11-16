#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS RE probe (2026-10-30, scope §1.9): which code draws the main screen's track sidebars?
A write watch on the main window's edge columns (the rotated plane 0x46c7e0ea: rows 0-7 = screen
x 0-7, rows 120-127 = x 120-127) during a project load, a track change and 120 UI ticks, on the
stock image. Prints each writer PC with the ROM return addresses on its stack. Result: RECT /
glyph writes from FUN_4003fed8 (called by FUN_40052200), only during the load: route A never runs
0x40052200, so a track change is not repainted there.

  python3 tools/clyps_probe_sidebar.py
"""
import os, pathlib, sys, collections
ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
os.chdir(OCTABAM); sys.path.insert(0, str(OCTABAM / "tools")); import toolpath  # noqa
sys.path.insert(0, str(OCTABAM / "tools" / "emu")); import emu_rtos as er
import unicorn as U
image = str(ROOT / "out/raw/section_3_MAIN_OS.bin")
proj = os.path.expanduser("~/Desktop/OT Backup/KYOTI/OT DEMO")
card, staged = er.stage_project(proj, "OCTABAM", "OT DEMO", tree="out/_emu_clyps_sbprobe")
r, rt = er.attach(image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
if not rt.gate_m6a()[0]:
    rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
rd = lambda ad, n=4: int.from_bytes(bytes(rt.uc.mem_read(ad, n)), "big")
def wins():
    w = rd(0x460BABF0); out = []
    while w and w < 0x50000000:
        out.append((w, rd(w + 0x30), rd(w + 0x34), [rd(w + o) for o in range(0, 0x38, 4)])); w = rd(w)
    return out
for w in wins(): print("win", hex(w[0]), hex(w[1]), " ".join(f"{x:x}" for x in w[3]))
log = collections.Counter(); phase = ["boot"]
def stackrom(uc):
    sp = uc.reg_read(U.m68k_const.UC_M68K_REG_A7)
    vals = []
    for i in range(0, 0x100, 4):
        v = int.from_bytes(bytes(uc.mem_read(sp + i, 4)), "big")
        if 0x40000400 <= v < 0x40110000: vals.append(v)
        if len(vals) >= 6: break
    return tuple(vals)
hooked = set()
def hook(bm):
    if bm in hooked: return
    hooked.add(bm)
    def on_w(uc, acc, addr, size, val, ud):
        off = addr - bm; x = off // 8
        pc = uc.reg_read(U.m68k_const.UC_M68K_REG_PC)
        log[(phase[0], "R" if x >= 120 else "L", hex(pc), tuple(hex(v) for v in stackrom(uc)))] += 1
    rt.uc.hook_add(U.UC_HOOK_MEM_WRITE, on_w, begin=bm, end=bm + 63)
    rt.uc.hook_add(U.UC_HOOK_MEM_WRITE, on_w, begin=bm + 960, end=bm + 1023)
for w in wins(): hook(w[1])
phase[0] = "load"
rt.load_project_live("OCTABAM", staged, run_ms=6000)
rt.run(ms=300)
for w in wins(): print("win", hex(w[0]), hex(w[1]), " ".join(f"{x:x}" for x in w[3])); hook(w[1])
def call(addr, *args):
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    return rt.call_as_main(addr, args=args, budget=600000)
phase[0] = "trk"
for k in (0x32, 0x11):
    if k == 0x11: rt.uc.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))
    call(0x40031734, k, 1); call(0x40031734, k, 0)
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.uc.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0])); rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
    rt.run(ms=200)
phase[0] = "uitick"
for i in range(120):
    call(0x40056c28)
rt.run(ms=500)
print("active", rd(0x80000000, 1))
for k, n in sorted(log.items()): print(n, *k)

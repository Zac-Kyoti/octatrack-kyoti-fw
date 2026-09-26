#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 101: the FIRE oracle. Every prior phase oracle judged commits by STEP-ADVANCE
instants (0x400a3d78). Hardware says V5.7 still sounds fractional while every counter
we preserve stays protected -- so judge by what is audible instead: entries into
FUN_400a536c (the trig-fire call, reached from the CNTDN tail at 0x400a4bde/0x400a4bd2
region and from the advance path at 0x400a3d98), argument = track index on the stack.

Per commit segment this reports, for a chosen track: the fire-tick congruence classes
mod tps, advance classes alongside (the old observable), and whether either re-phased.
If fires re-phase where advances do not, the audible bug is finally reproduced in the
emulator and iteration gets cheap again.

Usage: python3 tools/diag_fire_phase.py --project DIR --pattern N --to-pattern M
       [--track T] [--image IMG]
"""
import argparse
import bisect
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
FIRE_FN = 0x400A536C
TAIL_PC, ADV_PC = 0x400A4BE6, 0x400A3D78
STEP_ARR = 0x800064D0
TRK_SCALE_IX, LEN_TBL = 0x8000663E, 0x400ABA50
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--jumps", type=int, default=6)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--image", default=str(V5),
                    type=lambda p: str(pathlib.Path(p).resolve()))
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"fire_{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1).to_bytes(4, "big"))
    rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, njump=0, commits=[], fires=[], adv=[])
    targets = [a.to_pattern, a.pattern]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1

    def on_fire(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        trk = int.from_bytes(bytes(u.mem_read(sp + 4, 4)), "big")
        st["fires"].append((st["tick"], trk))

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc == TAIL_PC and (not st["commits"] or st["commits"][-1] != st["tick"]):
            st["commits"].append(st["tick"])
        elif pc == ADV_PC:
            st["adv"].append(st["tick"])

    watch = STEP_ARR + a.track
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=FIRE_FN, end=FIRE_FN)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=watch, end=watch)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    tsc = bytes(rt.uc.mem_read(TRK_SCALE_IX + a.track, 1))[0]
    tps = int.from_bytes(bytes(rt.uc.mem_read(LEN_TBL + 4 * tsc, 4)), "big")
    tfires = [t for t, trk in st["fires"] if trk == a.track]
    print(f"track {a.track} tps={tps}; commits={st['commits']}; "
          f"fires total={len(st['fires'])}, this track={len(tfires)}")
    if not tfires:
        print("NO FIRES OBSERVED for this track -- check the fixture has trigs on it")
        return 1

    def classes(events):
        out = {}
        for tk in events:
            out.setdefault(bisect.bisect_right(st["commits"], tk), set()).add(tk % tps)
        return {k: sorted(v) for k, v in out.items()}

    fc, ac = classes(tfires), classes(st["adv"])
    print(f"\n{'segment':>8} {'after commit':>13} {'FIRE classes':>16} "
          f"{'ADV classes':>14} {'fire re-phased?':>16}")
    prev = None
    for seg in sorted(set(fc) | set(ac)):
        cm = st["commits"][seg - 1] if 0 < seg <= len(st["commits"]) else "-"
        f, ad = fc.get(seg), ac.get(seg)
        rp = "" if f is None or prev is None else ("YES" if f != prev else "no")
        print(f"{seg:>8} {str(cm):>13} {str(f):>16} {str(ad):>14} {rp:>16}")
        if f is not None:
            prev = f
    print("\nfire ticks (this track):", tfires[:40],
          "..." if len(tfires) > 40 else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

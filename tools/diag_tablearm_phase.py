#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 101: the TABLE-ARM oracle -- timing of writes into DAT_80001904, the 8x8 int
array feeding the audible live-nibble computation (Session 70 12th/13th pass; write gate
0x400a2d28 requires that track's ticks-within-step == 0). FUN_400a536c turned out to be
the reposition callback, not the trig dispatch, so this watches the table the audio
engine actually consumes.

Per audio track: write-tick congruence classes mod that track's tps, segmented by commit,
plus writer PCs seen. If these instants re-phase at armed commits while STEP advances do
not, the audible symptom is reproduced in the emulator.

Usage: python3 tools/diag_tablearm_phase.py --project DIR --pattern N --to-pattern M
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
TAIL_PC = 0x400A4BE6
TBL = 0x80001904
TBL_END = TBL + 8 * 8 * 4
STEP_ARR = 0x800064D0
TRK_SCALE_IX, LEN_TBL = 0x8000663E, 0x400ABA50
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--jumps", type=int, default=6)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--dump-track", type=int, default=-1)
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

    tag = f"tbl_{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}"
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

    st = dict(tick=0, njump=0, commits=[], writes=[], pcs={})
    targets = [a.to_pattern, a.pattern]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1

    def on_tbl(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        trk = ((addr - TBL) // 4) % 8
        st["writes"].append((st["tick"], trk, pc))
        st["pcs"][pc] = st["pcs"].get(pc, 0) + 1

    def on_commit(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc == TAIL_PC and (not st["commits"] or st["commits"][-1] != st["tick"]):
            st["commits"].append(st["tick"])

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_tbl, begin=TBL, end=TBL_END - 1)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_commit, begin=STEP_ARR, end=STEP_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"commits={st['commits']}; table-arm writes total={len(st['writes'])}")
    print("writer PCs:", {hex(k): v for k, v in sorted(st["pcs"].items())})
    if not st["writes"]:
        print("NO TABLE-ARM WRITES OBSERVED")
        return 1
    # Session 101 cont.: class SETS hid the shape ("one stray write at the commit" vs
    # "fractional until the wrap" both print [0,3]); report per-writer-PC counts per
    # class per segment instead, and dump raw (tick,pc) for --dump-track.
    for trk in range(8):
        evs = [(t, pc) for t, k, pc in st["writes"] if k == trk]
        if not evs:
            continue
        tsc = bytes(rt.uc.mem_read(TRK_SCALE_IX + trk, 1))[0]
        tps = int.from_bytes(bytes(rt.uc.mem_read(LEN_TBL + 4 * tsc, 4)), "big")
        segs = {}
        for tk, pc in evs:
            seg = bisect.bisect_right(st["commits"], tk)
            segs.setdefault(seg, {}).setdefault(pc, {})
            segs[seg][pc][tk % tps] = segs[seg][pc].get(tk % tps, 0) + 1
        print(f"track {trk} tps={tps} writes={len(evs)}")
        for seg in sorted(segs):
            parts = []
            for pc in sorted(segs[seg]):
                cc = ",".join(f"{c}x{n}" for c, n in sorted(segs[seg][pc].items()))
                parts.append(f"{hex(pc)}[{cc}]")
            print(f"   s{seg}: " + "  ".join(parts))
        if trk == a.dump_track:
            print(f"   raw: {[(t, hex(pc)) for t, pc in evs]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

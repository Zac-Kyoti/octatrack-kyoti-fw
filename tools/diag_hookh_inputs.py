#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: what does Hook H (0x400a47f6) actually SEE at an armed commit?

The proposed fix converts the outgoing position through TIME rather than carrying a step
count across a master-scale change:

    ticksIntoCycle = MASTER_STEP * tps_old + TICK_CTR
    newMasterStep  = (ticksIntoCycle / tps_new) mod newMasterLen

That needs tps_old = the OUTGOING master's ticks-per-step. The question is whether
SCALE_IX (0x8000663d) still holds the outgoing scale at Hook H's site, or whether Hook D
(0x400a4220, earlier in the same tick) has already replaced it with the incoming one --
Hook D recomputes SCALE_IX from ACT_PAT, and ACT_PAT is updated around 0x400a44d0, which
is BEFORE 0x400a47f6. If SCALE_IX is already the incoming value the formula silently
degenerates.

A code hook at 0x400a47f6 fires BEFORE that instruction runs (NOTES.md S87 rule 1), which
is exactly what we want here: the register/global state Hook H is handed.

Usage: python3 tools/diag_hookh_inputs.py --project DIR --pattern N --to-pattern M
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
HOOKH_PC = 0x400A47F6
HOOKD_PC = 0x400A4220
ACTPAT_PC = 0x400A44D0
MASTER_STEP, TICK_CTR, SCALE_IX = 0x800065B2, 0x800065B6, 0x8000663D
ACT_PAT, ACT_BANK = 0x800065BE, 0x800065BD
PAT_MSCALE, PAT_SCALE, PAT_SMODE = 0x400EB032, 0x400EB034, 0x400EB035
LEN_TBL = 0x400ABA50
G_ARMED = 0x80006A40
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--jumps", type=int, default=4)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=260)
    ap.add_argument("--image", default=str(V5))
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_hh_{tag}")
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

    st = dict(tick=0, njump=0, rows=[], order=[])
    targets = [a.to_pattern, a.pattern]
    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1

    def mark(u, addr, size, user):
        st["order"].append((st["tick"], addr))

    def on_hookh(u, addr, size, user):
        armed = bytes(u.mem_read(G_ARMED, 1))[0]
        if armed in (0, 0xAA):
            return
        tbl = [int.from_bytes(bytes(u.mem_read(LEN_TBL + 4 * i, 4)), "big") for i in range(8)]
        six = bytes(u.mem_read(SCALE_IX, 1))[0]
        ap_ = bytes(u.mem_read(ACT_PAT, 1))[0]
        ab = bytes(u.mem_read(ACT_BANK, 1))[0]
        off = ap_ * 0x8ED8 + ab * 0x9B340
        smode = bytes(u.mem_read(PAT_SMODE + off, 1))[0]
        inc_ix = bytes(u.mem_read((PAT_MSCALE if smode else PAT_SCALE) + off, 1))[0]
        st["rows"].append(dict(
            t=st["tick"],
            ms=int.from_bytes(bytes(u.mem_read(MASTER_STEP, 2)), "big"),
            tc=bytes(u.mem_read(TICK_CTR, 1))[0],
            six=six, tps_from_scaleix=tbl[six] if six < 8 else None,
            act=ap_, inc_ix=inc_ix, tps_incoming=tbl[inc_ix] if inc_ix < 8 else None))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hookh, begin=HOOKH_PC, end=HOOKH_PC)
    for pc in (HOOKD_PC, ACTPAT_PC, HOOKH_PC):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mark, begin=pc, end=pc)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    names = {HOOKD_PC: "HookD(0x400a4220)", ACTPAT_PC: "ACT_PAT=PEND(0x400a44d0)",
             HOOKH_PC: "HookH(0x400a47f6)"}
    print(f"{a.pattern} -> {a.to_pattern}, armed commits seen: {len(st['rows'])}\n")
    for r_ in st["rows"]:
        print(f"  t{r_['t']:4d}  MASTER_STEP={r_['ms']:3d} TICK_CTR={r_['tc']} "
              f"| SCALE_IX={r_['six']} (tps {r_['tps_from_scaleix']}) "
              f"| ACT_PAT={r_['act']} incoming scale idx={r_['inc_ix']} "
              f"(tps {r_['tps_incoming']})")
        same = r_['tps_from_scaleix'] == r_['tps_incoming']
        print(f"        -> SCALE_IX is the {'INCOMING' if same else 'OUTGOING'} master's tps")
    print("\nsite ordering within a commit tick (first 12 events):")
    seen = [e for e in st["order"] if st["rows"] and e[0] == st["rows"][0]["t"]]
    for tk, pc in seen[:12]:
        print(f"   t{tk}  {names.get(pc, hex(pc))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

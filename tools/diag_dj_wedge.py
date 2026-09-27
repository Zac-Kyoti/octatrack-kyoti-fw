#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 107: the DJ-ON-not-persistent wedge (hardware: "after a couple of switches they
start to cue again").

Hypothesis from reading dl_arm: a cue that reaches dj_land on a MASTER BOUNDARY tick
(TICK_CTR == tps-1) computes LAND_CNTDN = 1 and goes to ARMED -- but the ARMED->commit
branch only runs on a LATER dj_land entry, and stock's decrement (same tick, right below
the hook) takes the byte 1 -> 0 and runs its zero-landing NOW with the stale
transport-start snapshot; Hook N sees ARMED (not LANDING) and never consumes, so dj_state
wedges at ARMED and every later cue falls back to stock wrap cueing.

This tool cues by PHASE: each cue fires on the first tick >= its schedule whose TICK_CTR
(read at phase-G entry, i.e. the value dj_land will see NEXT tick is read+1) equals the
requested phase.  Phase tps-2 (default 4 at 1x) => dj_land sees tps-1 = the boundary tick.

Watch: dj_state (found per-image by scanning for `moveq #2; move.b d0,(abs).l` into the DJ
cave), LAND_CNTDN writes with writer PC, per-tick state samples, and STEP_ARR commits at
the landing/wrap PCs.

Usage:
  python3 tools/diag_dj_wedge.py --project ~/Desktop/DJTEST2 --pattern 3 --to-pattern 4 \
      --image out/_wedge_repro_v63.bin --phases 1,4,1,1
"""
import argparse
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
TICK_CTR = 0x800065B6
LAND_CNTDN = 0x80006687
ACT_BANK, ACT_PAT = 0x800065BD, 0x800065BE
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
STEP_ARR = 0x800064D0
LAND_PC, TAIL_PC = 0x400A20DE, 0x400A4BE6
IMG_BASE = 0x40000400


def find_dj_state(image_path):
    img = pathlib.Path(image_path).read_bytes()
    for m in re.finditer(bytes.fromhex("700213c0"), img):
        tgt = int.from_bytes(img[m.start() + 4:m.start() + 8], "big")
        if 0x400D7400 <= tgt < 0x400D7900:
            return tgt
    sys.exit("could not locate dj_state (moveq #2 + move.b into the DJ cave)")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--image", required=True,
                    type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--phases", default="1,4,1,1",
                    help="TICK_CTR value (at phase-G entry) each cue waits for; dj_land sees value+1")
    ap.add_argument("--gap", type=int, default=45)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=280)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    phases = [int(x) for x in a.phases.split(",")]

    dj_state_addr = find_dj_state(a.image)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"wedge_{pathlib.Path(a.image).stem}"
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

    st = dict(tick=0, njump=0, ev=[], commits=[], cues=[])
    targets = [a.to_pattern, a.pattern]

    def snap(u):
        g = lambda ad: bytes(u.mem_read(ad, 1))[0]
        return (g(dj_state_addr), g(LAND_CNTDN), g(PEND_PAT), g(ACT_PAT), g(TICK_CTR))

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        st["ev"].append(("TICK", st["tick"], None, snap(u)))
        n = st["njump"]
        if n < len(phases) and st["tick"] >= a.cue_at + n * a.gap:
            if bytes(u.mem_read(TICK_CTR, 1))[0] == phases[n]:
                u.mem_write(PEND_BANK, bytes([bank]))
                u.mem_write(PEND_PAT, bytes([targets[n % 2]]))
                st["cues"].append((st["tick"], targets[n % 2], phases[n]))
                st["njump"] += 1

    def on_w(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["ev"].append(("W", st["tick"], (addr, value & 0xFF, pc), None))

    def on_commit(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc in (LAND_PC, TAIL_PC) and (not st["commits"] or st["commits"][-1][0] != st["tick"]):
            st["commits"].append((st["tick"], pc))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=dj_state_addr, end=dj_state_addr)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=LAND_CNTDN, end=LAND_CNTDN)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_commit, begin=STEP_ARR, end=STEP_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 110:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    nm = {dj_state_addr: "dj_state", LAND_CNTDN: "LAND_CNTDN"}
    out = [f"image={a.image} dj_state@{dj_state_addr:#x} phases={phases}",
           f"cues={st['cues']}",
           f"commits={[(t, 'LAND' if p == LAND_PC else 'WRAP') for t, p in st['commits']]}",
           ""]
    last = None
    for kind, tk, d, s in st["ev"]:
        if kind == "TICK":
            if s[:4] != (last[:4] if last else None):
                out.append(f"t{tk:<4} state={s[0]} cntdn={s[1]:>3} pend={s[2]} act={s[3]} tickctr={s[4]}")
                last = s
        else:
            addr, val, pc = d
            out.append(f"t{tk:<4}   W {nm[addr]:>10} <- {val:#04x}  pc={pc:#x}")
    verdict = []
    # wedge signature: dj_state byte stuck at 1 for the rest of the run after some tick
    states = [(tk, s[0]) for k, tk, d, s in st["ev"] if k == "TICK"]
    if states:
        final = states[-1][1]
        verdict.append(f"final dj_state={final} "
                       f"({'WEDGED (ARMED, never consumed)' if final == 1 else 'not wedged'})")
    land_ticks = [t for t, p in st["commits"] if p == LAND_PC]
    verdict.append(f"landings={len(land_ticks)} of {len(st['cues'])} cues; wraps="
                   f"{len(st['commits']) - len(land_ticks)}")
    out += [""] + ["VERDICT: " + v for v in verdict]
    txt = "\n".join(out)
    print(txt)
    if a.out:
        p = pathlib.Path(a.out)
        if not p.is_absolute():
            p = ROOT / p
        p.write_text(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

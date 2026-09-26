#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: does stock's own mid-cycle PHASE-ALIGNMENT machinery run at a DIRECT JUMP
commit, or does something in the DJ path bypass it?

Established by measurement (tools/diag_step_align.py, DJMAST2 pattern 0 -> 1, master 1x ->
2x, track 1x): across the commit the track stays locked at a 6-tick period but its phase
relative to the master shifts and NEVER recovers. The commit restarts the track's step at
the commit instant, which is not quantised to the track's own step grid.

Stock computes the quantity that would fix this. Its rebuild at 0x400a4918-0x400a492a
forms PAIR[t] = D7 - ceil(D7/tps_t)*tps_t (+tps_t when negative) -- the SUB-STEP tick
remainder -- stores it at 0x80006604[t] (2 bytes/track, MIDI twin 0x80006614), sets bit t
of the hold mask 0x80006626 when it is > 0 (0x400a4b12-0x400a4b22 in the MIDI twin, audio
twin near 0x400a497c), and the per-tick loop consumes that bit at 0x400a3d12, copying
PAIR's low byte into 0x800065d3[t] at 0x400a3d36 and SKIPPING that track's advance.

So: is PAIR[t] non-zero at our commits, is the hold bit set, and does 0x400a3d36 run?

Usage:
  python3 tools/diag_pair_phase.py --project DIR --pattern N --to-pattern M [--image IMG]
"""
import argparse
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
TAIL_PC = 0x400A4BE6
HOLD_CONSUME_PC = 0x400A3D36    # PAIR low byte -> 0x800065d3[t], track skips its advance
HOLD_CLEAR_PC = 0x400A3D28      # clears bit t of the hold mask
ADVANCE_PC = 0x400A3D78
PAIR = 0x80006604               # 2 bytes/track, audio; MIDI twin 0x80006614
PHASE = 0x800065D3              # 1 byte/track
HOLD_MASK = 0x80006626          # word, bit t = "track t holds this step"
STEP_ARR, TICKS_ARR = 0x800064D0, 0x800064F0
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--jumps", type=int, default=6,
                    help="alternate between the two patterns this many times, so commits "
                         "land on BOTH master-step parities in one boot")
    ap.add_argument("--gap", type=int, default=53,
                    help="ticks between jumps; deliberately coprime with the master cycle "
                         "so successive commits land at different sub-positions")
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

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}_{a.pattern}_{a.to_pattern}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_pp_{tag}")
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

    st = dict(tick=0, cued=None, commit=None, ev=[], pcs=collections.Counter(),
              pcfirst={})

    st["njump"] = 0
    st["targets"] = [a.to_pattern, a.pattern]
    st["commits"] = []

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            tgt = st["targets"][st["njump"] % 2]
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([tgt]))
            st["njump"] += 1
            if st["cued"] is None:
                st["cued"] = st["tick"]

    def on_code(u, addr, size, user):
        st["pcs"][addr] += 1
        st["pcfirst"].setdefault(addr, st["tick"])

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if addr == STEP_ARR and pc == TAIL_PC:
            if st["commit"] is None:
                st["commit"] = st["tick"]
            if not st["commits"] or st["commits"][-1] != st["tick"]:
                st["commits"].append(st["tick"])
        if PAIR <= addr < PAIR + 32:
            st["ev"].append((st["tick"], "PAIR", (addr - PAIR) // 2, pc, value))
        elif PHASE <= addr < PHASE + 16:
            st["ev"].append((st["tick"], "PHASE", addr - PHASE, pc, value & 0xFF))
        elif addr == HOLD_MASK or addr == HOLD_MASK + 1:
            st["ev"].append((st["tick"], "HOLDMASK", -1, pc, value))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    for pc in (HOLD_CONSUME_PC, HOLD_CLEAR_PC):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_code, begin=pc, end=pc)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP_ARR, end=HOLD_MASK + 2)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    print(f"image={pathlib.Path(a.image).name}  {a.pattern} -> {a.to_pattern}  "
          f"cued=t{st['cued']}  commit=t{st['commit']}  ticks={st['tick']}")
    print(f"\nstock's hold-path execution counts:")
    for pc, nm in ((HOLD_CONSUME_PC, "0x400a3d36 hold CONSUME (PAIR -> 0x800065d3, skip advance)"),
                   (HOLD_CLEAR_PC, "0x400a3d28 hold mask CLEAR")):
        n = st["pcs"].get(pc, 0)
        first = st["pcfirst"].get(pc)
        print(f"   {nm}: x{n}" + (f", first at t{first}" if n else "  <-- NEVER RUNS"))
    ms_at = {}
    print(f"\ncommits observed: {st['commits']}")
    print(f"\nper-commit: PAIR[0] (0 = track was on a step boundary = CLEAN, "
          f"non-zero = sub-step remainder = FRACTIONAL):")
    for c in st["commits"]:
        pairs = [(t, v) for tk, kind, t, pc, v in st["ev"]
                 if kind == "PAIR" and tk == c and t < 8]
        holds = [(pc, v) for tk, kind, t, pc, v in st["ev"]
                 if kind == "HOLDMASK" and tk == c]
        p0 = dict(pairs).get(0)
        verdict = "CLEAN" if p0 == 0 else ("FRACTIONAL" if p0 else "?")
        print(f"   commit t{c:4d}: PAIR[0]={p0}  all-audio PAIR={[v for _t, v in pairs]}  "
              f"holdmask writes={len(holds)}  -> {verdict}")
    ct = st["commit"]
    print(f"\nPAIR / PHASE / HOLDMASK writes near the FIRST commit (t{ct}):")
    for tk, kind, t, pc, v in st["ev"]:
        if ct is None or abs(tk - ct) <= 3:
            who = "CAVE" if 0x400D7400 <= pc < 0x400D7C3C else "stock"
            trk = f"[trk {t}]" if t >= 0 else "       "
            print(f"   t{tk:4d} {kind:9s}{trk} pc=0x{pc:08x}[{who}] = {v}")
    nz = [(tk, t, v) for tk, kind, t, pc, v in st["ev"]
          if kind == "PAIR" and ct is not None and tk == ct and v != 0]
    print(f"\nnon-zero PAIR[t] at the commit tick: "
          f"{nz if nz else 'none -- every track was exactly on a step boundary'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

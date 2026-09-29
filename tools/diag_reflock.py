#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 107/108 -- the V7 REFERENCE-LOCK oracle, recorder half.

The V7 spec (the author's, 2026-09-27): after a DIRECT JUMP to pattern B, B must play
exactly as if it were the only pattern ever programmed and had been running since PLAY,
locked to the master metronome.  So the gate is not a proxy (congruence classes, step
advances) but EQUALITY with a reference run:

    REF : PLAY on B, never switch.
    RUN : PLAY on A, switch to B (and back) at chosen ticks.
    PASS: from the landing on, RUN's full per-tick engine state == REF's at the same tick,
          and the audible fire table carries B's events only (A's pending ones purged).

Because the engine is deterministic given its state and the pattern data, state
equality at one tick after the landing implies equality for ever after -- the proxies
V1-V5 were graded by (fire-time classes mod tps) are blind to whole-step shifts; this
is not.  The metronome counters (0x80006511 beat-in-bar, 0x80006512 tick-in-beat,
phase I @0x400a4d36, independent of the pattern's master step) are recorded too: they
must match between REF and RUN at every tick, or the two runs are not on the same clock.

Records per tick (sampled at phase-G entry 0x400a3fdc): ACT/PEND, master step 0x800065b2,
master tick 0x800065b6, SCALE_IX, first-fire/hold masks, and 16-entry per-track arrays
(STEP, STEP-1, TICKS, ARMED, CNTDN, RELOAD, TRK_SCALE), metronome counters, sample clock.
Plus every write to the fire table 0x80001904 (8x8 longs) with the tick and writer PC.

Usage:
  python3 tools/diag_reflock.py --image IMG --project DIR --start P [--switch T:P ...]
      [--normal-len P=LEN ...] [--dj 0|1] [--ticks N] --out out/reflock_X.json
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
FIRE_TBL, FIRE_END = 0x80001904, 0x80001904 + 8 * 8 * 4
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
STEP_ARR = 0x800064D0
LAND_PC, TAIL_PC = 0x400A20DE, 0x400A4BE6
# Pending-event model (stock's own purge at 0x400a43b6-0x400a4464 defines "cancelled":
# it clears the record long and the slot bit in the track's mask; the time is untouched).
# Three slots per track, index = track + slot*8, times are sample-clock values.
EV_TABLES = {  # kind: (times base, mask base)
    "a": (0x80001904, 0x46C7FE44),   # audio, primary (writer 0x400a2e18)
    "b": (0x80001984, 0x46C7FE8C),   # audio, secondary table (same purge loop)
    "m": (0x46C76A26, 0x46C77BE2),   # MIDI tracks 8-15 (as 0-7 here)
}
BUILDER_A, BUILDER_A_RET = 0x4009D1E8, 0x400A2D82   # step_handler_confirmed, audio E call
BUILDER_M, BUILDER_M_RET = 0x4009CF4C, 0x400A39CA   # MIDI twin
PC_SEND = 0x4009E884        # stock's MIDI Program Change sender (bank, pattern)

SCALARS = {  # name: (addr, size)
    "act_bank": (0x800065BD, 1), "act_pat": (0x800065BE, 1),
    "pend_pat": (0x800065C0, 1),
    "m_step": (0x800065B2, 2), "m_tick": (0x800065B6, 1), "scale_ix": (0x8000663D, 1),
    "ff_mask": (0x80006624, 2), "hold_mask": (0x80006626, 2),
    "met_run": (0x80006510, 1), "met_beat": (0x80006511, 1), "met_tick": (0x80006512, 1),
    "sclk": (0x4610757C, 4),
}
ARRAYS = {  # name: base (16 bytes each, audio 0-7, MIDI 8-15)
    "step": 0x800064D0, "step_m1": 0x800064E0, "ticks": 0x800064F0, "armed": 0x80006500,
    "cntdn": 0x800065C3, "reload": 0x800065D3, "trk_scale": 0x8000663E,
}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--switch", action="append", default=[], help="T:PATTERN, cue written at tick T")
    ap.add_argument("--normal-len", action="append", default=[], help="PATTERN=LEN (forces NORMAL mode)")
    ap.add_argument("--setb", action="append", default=[],
                    help="PATTERN:OFFSET=VAL -- poke one pattern-blob byte after load (hex ok), e.g. 6:0x8e52=3")
    ap.add_argument("--setw", action="append", default=[],
                    help="PATTERN:OFFSET=VAL -- poke one pattern-blob word, e.g. 6:0x8e50=-1 (INF)")
    ap.add_argument("--extra", action="append", default=[],
                    help="NAME=ADDR:SIZE -- also record this address every tick (e.g. a cave counter)")
    ap.add_argument("--dj", type=int, default=1)
    ap.add_argument("--dj-mode-addr", type=lambda v: int(v, 0), default=DJ_MODE,
                    help="where DJ_MODE lives: 0x800000d8 standalone; the combined KYOTI image "
                         "keeps it in DIRECT JUMP's cave (out/KYOTI/kyoti_v1.0_map.json)")
    ap.add_argument("--ticks", type=int, default=300)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    switches = sorted((int(t), int(p)) for t, p in (s.split(":") for s in a.switch))
    lens = {int(p): int(l) for p, l in (s.split("=") for s in a.normal_len)}

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = a.tag or f"reflock_{pathlib.Path(a.image).stem}_{a.start}_{len(switches)}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    for pat, ln in lens.items():
        blob = 0x400E21E0 + bank * 0x9B340 + pat * 0x8ED8
        rt.uc.mem_write(blob + 0x8E55, b"\x00")
        rt.uc.mem_write(blob + 0x8E53, bytes([ln]))
    pokes = []
    for spec, width in [(s, 1) for s in a.setb] + [(s, 2) for s in a.setw]:
        pat, rest = spec.split(":", 1)
        off, val = rest.split("=")
        blob = 0x400E21E0 + bank * 0x9B340 + int(pat) * 0x8ED8
        v = int(val, 0) & ((1 << (8 * width)) - 1)
        rt.uc.mem_write(blob + int(off, 0), v.to_bytes(width, "big"))
        pokes.append([int(pat), int(off, 0), width, v])
    for spec in a.extra:
        nm, rest = spec.split("=")
        ad, sz = rest.split(":")
        SCALARS[nm] = (int(ad, 0), int(sz))
    rt.seq_select_live(bank, a.start)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(a.dj_mode_addr, (1 if a.dj else 0).to_bytes(4, "big"))

    st = dict(tick=0, states=[], fires=[], commits=[], cues=[], calls=[], pcs=[])
    pend = list(switches)

    def rd(u, addr, n):
        return int.from_bytes(bytes(u.mem_read(addr, n)), "big")

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        s = {k: rd(u, ad, n) for k, (ad, n) in SCALARS.items()}
        for k, base in ARRAYS.items():
            s[k] = list(bytes(u.mem_read(base, 16)))
        for kind, (tb, mb) in EV_TABLES.items():
            raw = bytes(u.mem_read(tb, 3 * 8 * 4))
            s["ev_" + kind] = [int.from_bytes(raw[i * 4:i * 4 + 4], "big") for i in range(24)]
            s["mask_" + kind] = list(bytes(u.mem_read(mb, 8)))
        s["t"] = st["tick"]
        st["states"].append(s)
        while pend and pend[0][0] == st["tick"]:
            _, p = pend.pop(0)
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([p]))
            st["cues"].append([st["tick"], p])

    def on_builder(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        w = [int.from_bytes(bytes(u.mem_read(sp + 4 * i, 4)), "big") for i in range(6)]
        ret = w[0]
        if ret not in (BUILDER_A_RET, BUILDER_M_RET):
            return
        sx = lambda v: v - (1 << 32) if v & 0x80000000 else v
        st["calls"].append([st["tick"], "a" if addr == BUILDER_A else "m",
                            sx(w[1]), sx(w[2]), sx(w[3]), sx(w[4]), sx(w[5])])

    def on_pc(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        w = [int.from_bytes(bytes(u.mem_read(sp + 4 * i, 4)), "big") for i in range(3)]
        st["pcs"].append([st["tick"], w[1], w[2], w[0]])   # tick, bank, pattern, return address

    def on_fire(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["fires"].append([st["tick"], (addr - FIRE_TBL) // 4, value & 0xFFFFFFFF, pc])

    def on_commit(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc in (LAND_PC, TAIL_PC) and (not st["commits"] or st["commits"][-1][0] != st["tick"]):
            st["commits"].append([st["tick"], "LAND" if pc == LAND_PC else "WRAP"])

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_fire, begin=FIRE_TBL, end=FIRE_END - 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_builder, begin=BUILDER_A, end=BUILDER_A)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_builder, begin=BUILDER_M, end=BUILDER_M)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_pc, begin=PC_SEND, end=PC_SEND)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_commit, begin=STEP_ARR, end=STEP_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 140:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    meta = dict(image=a.image, project=a.project, start=a.start, switches=switches,
                normal_len=lens, pokes=pokes, dj=a.dj, bank=bank, ticks=st["tick"])
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(json.dumps(dict(meta=meta, cues=st["cues"], commits=st["commits"],
                                   states=st["states"], fires=st["fires"],
                                   calls=st["calls"], pcs=st["pcs"])))
    print(f"wrote {out}: ticks={st['tick']} cues={st['cues']} commits={st['commits']} "
          f"fires={len(st['fires'])}")
    print("program changes (tick, bank, pattern, from):",
          [(pt, b, pp, hex(r)) for pt, b, pp, r in st["pcs"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

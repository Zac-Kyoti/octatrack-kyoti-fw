#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI -- where a jump's incoming Part reaches the engine (V7.2 work, 2026-11-13).

Two modes, both on a real hardware-exported project (out/fixtures/...):

  --dump OUT.npz --start P --at T
      play pattern P (DJ off) to tick T, park in main's idle loop and save every mapped memory
      region, plus the pattern -> Part table and the LFO AUTO CHANGE byte (0x80000050).  The offline
      checker (tools/check_dj_part.py) replays the Part applies on that snapshot in a bare Unicorn
      (no interrupts, no timing noise) and diffs what each writes.

  --trace OUT.json --start P --switch T:P2 [--switch ...] --ticks N [--dj 0|1] [--dj-mode-addr A]
      record, at every tick (phase-G entry 0x400a3fdc), the engine's per-track records
      (0x80000100..0x80001900, the MIDI engine 0x46c76dc0..0x46c77600, 0x80006640..0x80006680) as
      byte diffs, and every call of the light Part apply 0x40009e00, TRK_APPLY 0x40001f18 and the
      symbols given with --sym NAME=ADDR (DIRECT JUMP's publish routines), with the tick and the
      sample clock.  A track's fired events (record bit 2 = a sounding trig) are logged from the
      audio fire-table writer 0x400a2e18 and the MIDI one, so a grader can find each track's first
      sounding trig after a landing.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
TICK_PC = 0x400A3FDC
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
DJ_MODE = 0x800000D8
LIGHT_APPLY, TRK_APPLY = 0x40009E00, 0x40001F18
TRACE = [(0x80000100, 0x1800), (0x46C76DC0, 0x840), (0x80006640, 0x40), (0x80001828, 2)]
EV = {"a": (0x80001904, 0x46C7E998, 0x46C7FE44, 0x4610757C), "b": (0x80001984, 0x46C7FAA4, 0x46C7FE8C, 0x4610757C),
      "m": (0x46C76A26, 0x46C769C0, 0x46C77BE2, 0x46107564)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--dump")
    ap.add_argument("--at", type=int, default=60)
    ap.add_argument("--trace")
    ap.add_argument("--switch", action="append", default=[])
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--dj", type=int, default=0)
    ap.add_argument("--dj-mode-addr", type=lambda v: int(v, 0), default=DJ_MODE)
    ap.add_argument("--sym", action="append", default=[], help="NAME=ADDR: log calls of this routine")
    ap.add_argument("--poke", action="append", default=[], help="ADDR=VAL[:SIZE] after the load")
    ap.add_argument("--snap", action="append", type=int, default=[], help="TICK: save the traced regions whole")
    ap.add_argument("--tag", default="djpart")
    a = ap.parse_args(argv)
    switches = sorted((int(t), int(p)) for t, p in (s.split(":") for s in a.switch))

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{a.tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    for spec in a.poke:
        ad, rest = spec.split("=")
        val, _, sz = rest.partition(":")
        u.mem_write(int(ad, 0), int(val, 0).to_bytes(int(sz or 4), "big"))
    parts = [rd(0x400E21E0 + bank * 0x9B340 + p * 0x8ED8 + 0x8E57, 1) for p in range(16)]
    print(f"bank {bank}: pattern -> Part {parts}; LFO AUTO CHANGE (0x80000050) = {rd(0x80000050, 1)}; "
          f"START SILENT default (0x8000004f) = {rd(0x8000004F, 1)}", flush=True)
    rt.seq_select_live(bank, a.start)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    u.mem_write(a.dj_mode_addr, (1 if a.dj else 0).to_bytes(4, "big"))
    st = dict(tick=0, frames=[], calls=[], fires=[], cues=[], snaps={})
    pend = list(switches)
    prev = {}

    def on_tick(uc, addr, size, user):
        st["tick"] += 1
        if a.trace:
            fr = {"t": st["tick"], "sclk": rd(0x4610757C, 4), "mclk": rd(0x46107564, 4),
                  "act": rd(0x800065BE, 1), "d": [], "ev": {}}
            for kind, (tb, rb, mb, _clk) in EV.items():
                if kind == "b":
                    continue
                fr["ev"][kind] = [[rd(tb + 4 * i, 4), rd(rb + 4 * i, 4)] for i in range(24)] + \
                    [list(bytes(uc.mem_read(mb, 8)))]
            for base, n in TRACE:
                cur = bytes(uc.mem_read(base, n))
                old = prev.get(base)
                if old is not None:
                    i = 0
                    while i < n:
                        if cur[i] != old[i]:
                            j = i
                            while j < n and cur[j] != old[j]:
                                j += 1
                            fr["d"].append([base + i, cur[i:j].hex()])
                            i = j
                        else:
                            i += 1
                prev[base] = cur
            st["frames"].append(fr)
            if st["tick"] in a.snap:
                st["snaps"][st["tick"]] = {f"{b:08x}": bytes(uc.mem_read(b, n)).hex() for b, n in TRACE}
        while pend and pend[0][0] == st["tick"]:
            _, p = pend.pop(0)
            uc.mem_write(PEND_BANK, bytes([bank]))
            uc.mem_write(PEND_PAT, bytes([p]))
            st["cues"].append([st["tick"], p])

    names = {LIGHT_APPLY: "LIGHT_APPLY", TRK_APPLY: "TRK_APPLY"}
    for spec in a.sym:
        nm, ad = spec.split("=")
        names[int(ad, 0)] = nm

    def on_call(uc, addr, size, user):
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        w = [rd(sp + 4 * i, 4) for i in range(4)]
        st["calls"].append([st["tick"], names[addr], w[1:], rd(0x4610757C, 4), w[0],
                            uc.reg_read(er.eb.UC_M68K_REG_D6)])

    def on_fire(uc, addr, size, user):
        # the audio fire-time store (0x400a2e18): d0 = time, a1 = idx (track + slot*8); the record follows
        d0 = uc.reg_read(er.eb.UC_M68K_REG_D0)
        a1 = uc.reg_read(er.eb.UC_M68K_REG_A1)
        st["fires"].append([st["tick"], "a", a1 % 8, a1 // 8, d0, rd(0x4610757C, 4)])

    if a.trace:
        u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
        for ad in names:
            u.hook_add(er.eb.UC_HOOK_CODE, on_call, begin=ad, end=ad)
        u.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=0x400A2E18, end=0x400A2E18)
    else:
        u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.start_transport_live()
    goal = a.at if a.dump else a.ticks
    spins = 0
    while st["tick"] < goal and spins < max(400, goal):
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before and not a.dump:
            break
    if a.dump:
        import numpy as np
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        regs = {}
        for beg, end, perm in u.mem_regions():
            regs[f"r_{beg:08x}"] = np.frombuffer(bytes(u.mem_read(beg, end - beg + 1)), dtype=np.uint8)
        out = pathlib.Path(a.dump)
        if not out.is_absolute():
            out = ROOT / out
        np.savez_compressed(out, bank=bank, parts=np.array(parts), tick=st["tick"], **regs)
        print(f"wrote {out}: tick {st['tick']}, {len(regs)} regions", flush=True)
    if a.trace:
        out = pathlib.Path(a.trace)
        if not out.is_absolute():
            out = ROOT / out
        out.write_text(json.dumps(dict(meta=dict(image=a.image, project=a.project, start=a.start, bank=bank,
                                                 parts=parts, dj=a.dj, switches=switches),
                                       cues=st["cues"], frames=st["frames"], calls=st["calls"], fires=st["fires"],
                                       snaps=st["snaps"])))
        print(f"wrote {out}: ticks {st['tick']} calls {len(st['calls'])} fires {len(st['fires'])}", flush=True)
        for c in st["calls"]:
            print("  call", c[0], c[1], [hex(x) for x in c[2]], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

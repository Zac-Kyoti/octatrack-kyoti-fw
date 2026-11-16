#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI V7.2 in KYOTI-with-Clyps -- the two publish overlaps (the user, 2026-11-14), recorder half.
tools/check_dj_clyps_overlap.py grades it.

  (a) a Clyps FULL load whose Part slice is still waiting for its first sounding trig (cl_spd / cl_spn) when a
      DIRECT JUMP jump lands -- into a pattern on the same Part and on another Part;
  (b) a DIRECT JUMP per-track publish still waiting (dj_spd / dj_spn) when Clyps loads that track (SEQ, FULL).

Drives the real OT DEMO export the way trkseq's tools/diag_clyps_lock.py does (Clyps opened with [PTN]+[BANK]
on the active track; a load = a trig key, FUNC + trig = FULL), with DIRECT JUMP on, LFO AUTO CHANGE poked on
(0x80000050 -- DIRECT JUMP defers a track's Part only then), and records per tick (phase-G entry 0x400a3fdc):
the playing pattern and its Part, every audio track's trig mask in the playing pattern (Clyps edits it in
place), the audio pending-event table (times, records, slot masks) and both clocks, cl_spd / cl_spn and
dj_spd / dj_spn; and every TRK_APPLY / MIDI apply / publish / landing call with the tick and call order.

  python3 tools/diag_dj_clyps_overlap.py --image KC.bin --syms SYMS.txt --project DIR --out OUT.json \
      --track 4 --start 4 --ops f0,J5@k0

  ops (comma-separated, each optionally @kN = wait N ms first, else 150 ms):
    sK / fK  a Clyps SEQ / FULL load of slot K on the active track; returns once Clyps lands it
    JP       a DIRECT JUMP cue to pattern P; returns as soon as it lands (no settle)
    w        wait 1 s
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
ACT, RUNNING = 0x800065BE, 0x800065B8
TICK_PC = 0x400A3FDC
SCLK, MCLK = 0x4610757C, 0x46107564
FUNC = 0x2D


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--syms", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="djov")
    ap.add_argument("--track", type=int, default=4)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--ops", required=True)
    ap.add_argument("--lfo", type=int, default=1, help="LFO AUTO CHANGE (0x80000050)")
    ap.add_argument("--tail", type=int, default=6000, help="ms after the last op")
    a = ap.parse_args(argv)
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(a.syms).read_text().splitlines())}
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_djov_{a.name}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    bb = BLOB + bank * BANKSTRIDE

    def main_call(addr, *args):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=600000)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)          # call_as_main leaks its arguments
        return r_

    def tail():
        u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
        main_call(er.KERNEL_POST, er.SYS_QUEUE, er.SYS_MSG_SCRATCH)

    def key(code, ev, ms=0):
        if ev and 0x10 <= code <= 0x17:
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))
        main_call(SET_KEY, code, ev)
        tail()
        if ms:
            rt.run(ms=ms)

    def settle(ms, every=34):
        for _ in range(max(1, ms // every)):
            rt.run(ms=every)
            main_call(0x40056C28)
            tail()

    if rd(0x80000012, 4):
        key(0x35, 1, 40); key(0x35, 0, 40)
    key(0x10 + a.track, 1, 40); key(0x10 + a.track, 0, 40)
    u.mem_write(0x80000050, bytes([a.lfo]))
    st = dict(tick=0, q=0)
    states, calls, lands = [], [], []

    def on_tick(uc, ad, sz, ud):
        st["tick"] += 1
        act = rd(ACT, 1)
        slab = bb + act * PATSTRIDE
        states.append(dict(
            t=st["tick"], act=act, part=rd(slab + 0x8E57, 1), sclk=rd(SCLK, 4), mclk=rd(MCLK, 4),
            masks=[bytes(uc.mem_read(slab + k * TRAC_A, 8)).hex() for k in range(8)],
            lens=[rd(slab + k * TRAC_A + 0x50, 1) for k in range(8)],
            ev=[rd(0x80001904 + 4 * i, 4) for i in range(24)], rec=[rd(0x46C7E998 + 4 * i, 4) for i in range(24)],
            emask=list(bytes(uc.mem_read(0x46C7FE44, 8))),
            cl_spd=[rd(syms["cl_spd"] + 2 * k, 2) for k in range(16)], cl_spn=rd(syms["cl_spn"], 1),
            dj_spd=[rd(syms["dj_spd"] + 2 * k, 2) for k in range(16)], dj_spn=rd(syms["dj_spn"], 1)))

    def mk(nm):
        def f(uc, ad, sz, ud):
            s_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
            st["q"] += 1
            calls.append([st["tick"], nm, [rd(s_ + 4 * k, 4) for k in (1, 2, 3)],
                          uc.reg_read(er.eb.UC_M68K_REG_D6), rd(SCLK, 4), st["q"]])
        return f
    for nm, ad in (("TRK_APPLY", 0x40001F18), ("LIGHT_APPLY", 0x40009E00), ("PART_APPLY", 0x40009094),
                   ("cl_mapply", syms["cl_mapply"]), ("dj_mapply", syms["dj_mapply"]),
                   ("cl_sppub", syms["cl_sppub"]), ("cl_spflush", syms["cl_spflush"]), ("cl_landone", syms["cl_landone"]),
                   ("cl_slice", syms.get("cl_slice")), ("dj_pub1", syms["dj_pub1"]), ("dj_sparm", syms["dj_sparm"]),
                   ("dj_spflush", syms["dj_spflush"])):
        if ad:
            u.hook_add(er.eb.UC_HOOK_CODE, mk(nm), begin=ad, end=ad)
    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    u.mem_write(syms["DJ_MODE"], (1).to_bytes(4, "big"))

    rt.seq_select_live(bank, a.start)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=600)
    key(0x2E, 1, 40); key(0x2F, 1, 40); key(0x2F, 0, 40); key(0x2E, 0, 40)     # Clyps: [PTN]+[BANK]
    print(f"running {rd(RUNNING, 4)}, Clyps open {rd(syms['cl_open'], 1)}, LFO AUTO CHANGE {rd(0x80000050, 1)}",
          flush=True)
    settle(200)
    for i, opx in enumerate(a.ops.split(",")):
        op, _, when = opx.partition("@")
        rt.run(ms=int(when[1:]) if when.startswith("k") else 150)
        if op[0] == "J":
            p = int(op[1:])
            u.mem_write(0x800065BF, bytes([bank]))
            u.mem_write(0x800065C0, bytes([p]))
            g = 0
            while rd(ACT, 1) != p and g < 3000:
                rt.run(ms=2)
                g += 1
            print(f"#{i} {opx}: landed, act {rd(ACT, 1)} at tick {st['tick']}", flush=True)
            continue
        if op == "w":
            settle(1000)
            continue
        nl = sum(1 for c in calls if c[1] == "cl_landone")
        if op[0] == "s":
            key(int(op[1:]), 1); key(int(op[1:]), 0)
        elif op[0] == "f":
            key(FUNC, 1); key(int(op[1:]), 1); key(int(op[1:]), 0); key(FUNC, 0)
        g = 0
        while sum(1 for c in calls if c[1] == "cl_landone") == nl and g < 300:
            settle(34)
            g += 1
        print(f"#{i} {opx}: Clyps landed at tick {st['tick']}", flush=True)
    settle(a.tail)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(meta=dict(name=a.name, ops=a.ops, track=a.track, start=a.start, bank=bank,
                                             lfo=a.lfo, image=a.image), states=states, calls=calls)))
    print(f"wrote {out}: ticks {st['tick']}, calls {len(calls)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

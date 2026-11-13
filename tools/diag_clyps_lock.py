#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- the REF-LOCK oracle (DIRECT JUMP V7's, tools/diag_reflock.py + tools/model_reflock.py) applied to
Clyps' landings, recorder half (the user's CL24 report, 2026-11-11: "sometimes the incoming sequence gets
offset by a step"; and: use DIRECT JUMP's logic, look deeply -- lengths, scales, master lengths / scales).

Runs the real OT DEMO export, varies it IN RAM after the load (--poke, stock-style: the pattern blob's own
bytes), plays, opens Clyps on T1 and runs --ops: each op is a Clyps gesture at a chosen time. Records, per
tick (phase-G entry 0x400a3fdc, t = 1 on the first running tick -- model_reflock's sample point): master
step / tick / scale, every track's STEP / TICKS / TRK_SCALE; every audio builder call (tick, track, step);
every Clyps landing (cl_landone: tick, track, the tick path) and request (cl_cueload: tick, track, code);
the slab's per-track length / scale and the master's after every landing. tools/check_clyps_lock.py
grades it against DIRECT JUMP's position model.

  CLYPS_SYMS=out/clyps/kyoti_cl24_syms.txt python3 tools/diag_clyps_lock.py --image IMG --project DIR \
      --name N --out out/clyps/lock/N.json [--dj] [--chain STEPS] [--poke P:OFF=VAL[:SIZE] ...] \
      [--ops s1,s15,o@m0,...] [--track 0]
  ops: sK = slot K (pattern K of the playing bank, 0-based), fK = FULL slot K, o = ORIG SEQ, of = ORIG
       SEQ/MCH/FX (the trig of the pattern you are on, [FUNC] for the FULL form); a suffix @mK waits for master step K first (0 = the cycle's last audible step), @kN
       waits N ms; without one, an irregular delay walks the press through every tick of a step.
"""
import argparse, json, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
ACT, RUNNING, MSTEP, TICK_CTR, SCALE_IX = 0x800065BE, 0x800065B8, 0x800065B2, 0x800065B6, 0x8000663D
STEP_ARR, TICKS_ARR, TSCALE_ARR = 0x800064D0, 0x800064F0, 0x8000663E
TICK_PC = 0x400A3FDC
BUILDER_A, BUILDER_A_RET = 0x4009D1E8, 0x400A2D82
FIRE_STORE = 0x400A2E18          # audio fire time store: d0 = time, a1 = track + slot*8, d7 = ahead * 0x285ff0
SCLK = 0x4610757C
PAGE, FUNC = 0x1B, 0x2D


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dj", action="store_true")
    ap.add_argument("--chain", type=int, default=None)
    ap.add_argument("--poke", action="append", default=[])
    ap.add_argument("--ops", default="s1,s15")
    ap.add_argument("--track", type=int, default=0, help="the active track (0-based audio)")
    ap.add_argument("--start", type=int, default=None, help="the pattern to play (0-based), default: as loaded")
    ap.add_argument("--stride", type=int, default=29)
    ap.add_argument("--tail", type=int, default=800, help="ms after the last landing")
    ap.add_argument("--cond", action="store_true", help="also record the trig-condition counters per tick")
    ap.add_argument("--leds", action="store_true", help="also record the LED base / invert bitmaps per tick")
    ap.add_argument("--parts", type=lambda v: int(v, 0), default=0,
                    help="BANKSZ: at the end compare the playing Part with the load snapshot's")
    a = ap.parse_args(argv)
    sp = os.environ.get("CLYPS_SYMS", str(ROOT / "out/clyps_syms.txt"))
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(sp).read_text().splitlines())}
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_clyps_lock_{a.name}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def main_call(addr, *args):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=600000)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)
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
    bb = BLOB + bank * BANKSTRIDE
    act = rd(ACT, 1) if a.start is None else a.start
    slab_ad = bb + act * PATSTRIDE
    for spec in a.poke:                       # P:OFF=VAL[:SIZE], pattern P of the playing bank
        lhs, rhs = spec.split("=")
        p, off = lhs.split(":")
        val, _, sz = rhs.partition(":")
        n = int(sz or 1)
        ad = bb + int(p, 0) * PATSTRIDE + int(off, 0)
        u.mem_write(ad, (int(val, 0) & ((1 << (8 * n)) - 1)).to_bytes(n, "big"))
        print(f"poke pattern {int(p, 0) + 1} +{int(off, 0):#x} = {int(val, 0):#x} ({n} B)", flush=True)
    if a.chain is not None:
        qt = [rd(0x400D80DC + 4 * i, 4) for i in range(17)]
        u.mem_write(slab_ad + 0x8E56, bytes([qt.index(a.chain)]))

    def params(p):
        base = bb + p * PATSTRIDE
        tr = bytes(u.mem_read(base + 0x8E50, 8))
        trk = [(rd(base + t * TRAC_A + 0x50, 1), rd(base + t * TRAC_A + 0x51, 1), rd(base + t * TRAC_A + 0x54, 1))
               for t in range(8)]
        return dict(mlen=int.from_bytes(tr[0:2], "big"), mscale=tr[2], len=tr[3], scale=tr[4], mode=tr[5],
                    chain=tr[6], trk=trk)

    st = dict(tick=0, q=0)
    states, builds, lands, reqs, snaps, fires = [], [], [], [], [], []
    ctx = {"where": None}

    def on_tick(uc, ad, sz, ud):
        st["tick"] += 1
        row = [st["tick"], rd(MSTEP, 2), rd(TICK_CTR, 1), rd(SCALE_IX, 1),
               list(u.mem_read(STEP_ARR, 16)), list(u.mem_read(TICKS_ARR, 16)),
               list(u.mem_read(TSCALE_ARR, 16))]
        if a.cond:      # A:B pass counters (long[16]) + the three latch bytes [16] (0x400a536c / 0x400a539c)
            raw = bytes(u.mem_read(0x46107918, 64))
            row += [[int.from_bytes(raw[i * 4:i * 4 + 4], "big") for i in range(16)],
                    list(u.mem_read(0x46107959, 16)), list(u.mem_read(0x46107969, 16)),
                    list(u.mem_read(0x46107979, 16)), rd(ACT, 1)]
        if a.leds:      # 0x460ba98c: the LEDs' base bits (die / 8, die % 8); 0x460ba9ae: LED_FLASH's inverted dies
            row.append([bytes(u.mem_read(0x460BA98C, 17)).hex(), bytes(u.mem_read(0x460BA9AE, 17)).hex()])
        states.append(row)

    def on_build(uc, ad, sz, ud):
        s = uc.reg_read(er.eb.UC_M68K_REG_A7)
        if rd(s, 4) != BUILDER_A_RET:
            return
        st["q"] += 1
        builds.append([st["tick"], rd(s + 4, 4), rd(s + 16, 4), st["q"]])

    def on_fire(uc, ad, sz, ud):
        idx = uc.reg_read(er.eb.UC_M68K_REG_A1)
        d7 = uc.reg_read(er.eb.UC_M68K_REG_D7)
        fires.append([st["tick"], idx & 7, idx >> 3, d7 // 0x285FF0, st["q"]])

    def on_landin(uc, ad, sz, ud):
        ctx["where"] = "tick"

    def on_wrapin(uc, ad, sz, ud):
        ctx["where"] = "wrap"

    def on_landone(uc, ad, sz, ud):
        st["q"] += 1
        lands.append([st["tick"], uc.reg_read(er.eb.UC_M68K_REG_D6), ctx["where"], rd(MSTEP, 2), rd(TICK_CTR, 1),
                      st["q"]])

    def on_req(uc, ad, sz, ud):
        s = uc.reg_read(er.eb.UC_M68K_REG_A7)
        st["q"] += 1
        reqs.append([st["tick"], rd(s + 4, 4), rd(s + 8, 4), rd(s + 12, 4), rd(MSTEP, 2), rd(TICK_CTR, 1), st["q"]])

    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    u.hook_add(er.eb.UC_HOOK_CODE, on_build, begin=BUILDER_A, end=BUILDER_A)
    u.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=FIRE_STORE, end=FIRE_STORE)
    u.hook_add(er.eb.UC_HOOK_CODE, on_landin, begin=syms["cl_land"], end=syms["cl_land"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_wrapin, begin=syms["cl_wrap"], end=syms["cl_wrap"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_landone, begin=syms["cl_landone"], end=syms["cl_landone"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_req, begin=syms["cl_cueload"], end=syms["cl_cueload"])
    applies = []         # CL25b: every engine-facing apply, its tick (what changes the SOUND, and when)
    for name, ad in (("TRK_APPLY", 0x40001F18), ("PART_APPLY", 0x40009094), ("LIGHT_APPLY", 0x40009E00),
                     ("PICKUP_SET", 0x40097290), ("cl_fullone", syms.get("cl_fullone")), ("cl_slice", syms.get("cl_slice"))):
        if ad:
            def mk(nm):
                def f(uc, a_, sz, ud):
                    s_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
                    applies.append([st["tick"], nm, [rd(s_ + 4 * k, 4) for k in (1, 2, 3)], rd(SCLK, 4), st["q"]])
                return f
            u.hook_add(er.eb.UC_HOOK_CODE, mk(name), begin=ad, end=ad)
    u.hook_add(er.eb.UC_HOOK_MEM_WRITE, lambda uc, acc, ad, sz, val, ud: applies.append(
        [st["tick"], "ENG_RESTART", [val & 0xFF], rd(SCLK, 4), st["q"]]), begin=0x8000184C, end=0x8000184C)
    purges = []          # CL25: (tick, track, the slot mask before / after cl_tpurge)
    if "cl_tpurge" in syms:
        pst = {}

        def on_pin(uc, ad, sz, ud):
            t = uc.reg_read(er.eb.UC_M68K_REG_D6)
            mk = 0x46C7FE44 + t if t < 8 else 0x46C77BE2 + t - 8
            pst["t"], pst["mk"], pst["b"] = t, mk, rd(mk, 1)
            if t < 8:       # the pending events' fire times against the sample clock (the purge's margin)
                now = rd(SCLK, 4)
                pst["dt"] = [((rd(0x80001904 + 4 * (t + 8 * k), 4) - now + (1 << 31)) % (1 << 32)) - (1 << 31)
                             for k in range(3) if pst["b"] >> k & 1]

        def on_pout(uc, ad, sz, ud):
            purges.append([st["tick"], pst["t"], pst["b"], rd(pst["mk"], 1), pst.get("dt")])
        u.hook_add(er.eb.UC_HOOK_CODE, on_pin, begin=syms["cl_tpurge"], end=syms["cl_tpurge"])
        u.hook_add(er.eb.UC_HOOK_CODE, on_pout, begin=syms["pu_out"], end=syms["pu_out"])
    if a.dj:
        u.mem_write(syms["DJ_MODE"], (1).to_bytes(4, "big"))
    p0 = params(act)
    print(f"bank {bank + 1} pattern {act + 1}: {p0}", flush=True)
    snaps.append([0, p0])

    rt.seq_select_live(bank, act)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=600)
    key(0x2E, 1, 40); key(0x2F, 1, 40); key(0x2F, 0, 40); key(0x2E, 0, 40)
    print(f"running {rd(RUNNING, 4)}, Clyps open {rd(syms['cl_open'], 1)}, DJ {a.dj}", flush=True)
    settle(200)

    for i, opx in enumerate(a.ops.split(",")):
        op, _, when = opx.partition("@")
        if when.startswith("m"):
            want = int(when[1:])
            g = 0
            while rd(MSTEP, 2) != want and g < 4000:
                rt.run(ms=6)
                g += 1
        elif when.startswith("k"):
            rt.run(ms=int(when[1:]))
        else:
            rt.run(ms=150 + (i * a.stride) % 400)
        nl = len(lands)
        if op[0] == "j":                      # a stock cue: PEND_BANK / PEND_PAT (diag_reflock's way)
            u.mem_write(0x800065BF, bytes([bank]))
            u.mem_write(0x800065C0, bytes([int(op[1:])]))
            settle(3000)
            snaps.append([st["tick"], params(rd(ACT, 1))])
            print(f"#{i} {opx}: cued, act now {rd(ACT, 1)} at tick {st['tick']}", flush=True)
            continue
        if op == "w":
            settle(1000)
            continue
        if op == "d":                         # one DOWN arrow: where the arrows show
            key(0x20, 1); key(0x20, 0)
            settle(300)
            print(f"#{i} d: cur {rd(syms['cl_cur'], 1) + 1} shown {rd(syms['cl_pmoved'], 1)}", flush=True)
            continue
        if op == "P":                         # ORIG PTN+PRT: [PTN]+[BANK]+[YES]
            key(0x2E, 1); key(0x2F, 1); key(0x31, 1); key(0x31, 0); key(0x2F, 0); key(0x2E, 0)
            settle(3000)
            print(f"#{i} P: cur {rd(syms['cl_cur'], 1) + 1} shown {rd(syms['cl_pmoved'], 1)} "
                  f"sbank {rd(syms['cl_sbank'], 1)}", flush=True)
            continue
        if op[0] == "y":                      # the arrows to slot K, then [YES]
            g2 = 0
            while rd(syms["cl_cur"], 1) != int(op[1:]) and g2 < 20:
                key(0x20, 1); key(0x20, 0)
                g2 += 1
            rt.run(ms=300)
            key(0x31, 1); key(0x31, 0)
        elif op[0] == "s":
            key(int(op[1:]), 1); key(int(op[1:]), 0)
        elif op[0] == "f":
            key(FUNC, 1); key(int(op[1:]), 1); key(int(op[1:]), 0); key(FUNC, 0)
        elif op == "o":
            key(act, 1); key(act, 0)                # CL29: ORIG = the trig of the pattern you are on
        elif op == "of":
            key(FUNC, 1); key(act, 1); key(act, 0); key(FUNC, 0)
        g = 0
        while len(lands) == nl and g < 300:
            settle(68)
            g += 1
        settle(300)
        snaps.append([st["tick"], params(act)])
        l = lands[-1] if len(lands) > nl else None
        print(f"#{i} {opx}: requests {[x[:6] for x in reqs if x[0] >= (l[0] - 400 if l else 0)][-2:]} landing "
              f"{l}; cur {rd(syms['cl_cur'], 1) + 1} shown {rd(syms['cl_pmoved'], 1)}", flush=True)
    settle(a.tail)
    parts = None
    if a.parts:     # CL29: the playing pattern's Part now vs as loaded (the snapshot, cl_bss + bank * BANKSZ)
        pi = rd(slab_ad + 0x8E57, 1) & 3
        live = bytes(u.mem_read(bb + 0x8ED80 + pi * 0x18B2, 0x18B2))
        snap = bytes(u.mem_read(syms["cl_bss"] + bank * a.parts + 0x8ED80 + pi * 0x18B2, 0x18B2))
        diff = [i for i in range(0x18B2) if live[i] != snap[i]]
        parts = dict(part=pi, diff=diff[:64], n=len(diff))
        print(f"Part {pi + 1} now vs as loaded: {len(diff)} bytes differ {[hex(i) for i in diff[:12]]}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(meta=dict(name=a.name, dj=a.dj, chain=a.chain, pokes=a.poke, ops=a.ops,
                                             track=a.track, pattern=act, bank=bank),
                                   states=states, builds=builds, fires=fires, lands=lands, reqs=reqs, snaps=snaps,
                                   purges=purges, applies=applies, parts=parts)))
    print(f"wrote {out}: ticks {st['tick']}, landings {len(lands)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

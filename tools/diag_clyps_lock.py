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
  ops: sK = slot K (pattern K of the playing bank, 0-based), fK = FULL slot K, x = STOP then PLAY, Y = a bare [YES], v = print the view, bK / bY = a load sampled for the cued blink, k+ / k- = [BANK] + DOWN / UP, o = ORIG SEQ, of = ORIG
       SEQ/MCH/FX (the trig of the pattern you are on, [FUNC] for the FULL form); a suffix @mK waits for master step K first (0 = the cycle's last audible step), @kN
       waits N ms; without one, an irregular delay walks the press through every tick of a step.
  CL39 (a stock pattern cue's second highlight; exit 1 on a failed CHECK): qK = [PTN] + trig K, rK = [PTN]+[BANK]+trig K
       (a card reload of another pattern: its toast, then stock's cue) -- both sampled for 48 UI ticks: the blink's phase
       runs, cl_pbq, and the composed screens' on / off difference (one inverted bar on the cued slot's cell, or none
       with another bank shown); ql = wait for the landing (the solid highlight, steady); qv = sample the cue
       already up (after k+ / k-); qc = cancel ([PTN] + the
       playing pattern's trig: no bar, steady); qdK = [PTN] + trig K with DIRECT JUMP on (--dj), sampled to its landing.
  CL39b (the cue's box is the select box's frame; no draws from the UI tick): press-only ops cK / c- ([PTN] + trig K /
       the playing pattern's trig), pK (trig K: a SEQ load), FK ([FUNC] + trig K: a FULL load), L (wait for a Clyps
       landing), WN (the whole composed window into the record's "windows", taken in the arrows' on phase) -- compare
       two images' runs with tools/cmp_clyps_windows.py; the run counts cl_draw calls made inside cl_uitick (on the unit:
       the UI task drawing over the sys task) and FAILs a CL39b image on any.
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
    ap.add_argument("--partreads", action="store_true",
                    help="CL34 study: log every read of the playing pattern's Part (pc, offset, tick, sample clock)")
    ap.add_argument("--shots", default=None, help="CL34: a directory for screen PNGs (op v and the b ops' phases)")
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
    shots = None
    if a.shots:
        import lcd_view
        shots = pathlib.Path(a.shots)
        if not shots.is_absolute():
            shots = ROOT / shots
        shots.mkdir(parents=True, exist_ok=True)
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
        fires.append([st["tick"], idx & 7, idx >> 3, d7 // 0x285FF0, st["q"], uc.reg_read(er.eb.UC_M68K_REG_D0),
                      rd(SCLK, 4)])

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
    preads = {}          # CL34 study: (pc, Part offset) -> [count, first tick, last tick, first sample clock]
    if a.partreads:
        def on_pread(uc, acc, ad, sz, val, ud):
            pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
            k = (pc, ad - pr_base[0])
            e = preads.get(k)
            if e is None:
                preads[k] = [1, st["tick"], st["tick"], rd(SCLK, 4)]
            else:
                e[0] += 1
                e[2] = st["tick"]
        pr_base = [0]
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

    ledtbl = [rd(0x400A74CE + 4 * k_, 4) for k_ in range(16)]

    def shot(nm):
        if shots:
            main_call(0x40056C28)     # one UI tick: the screen is composed as on the unit's next frame
            lcd_view.png(lcd_view.pixels(bytes(u.mem_read(0x46C7E0EA, 1024))), str(shots / f"{nm}.png"))

    def view():     # CL34: the arrows (shown / tucked under the box), and their slot's LED (base bits)
        tk = main_call(syms["cl_tuck"]) & 0xFF if "cl_tuck" in syms else -1
        cur, base = rd(syms["cl_cur"], 1), bytes(u.mem_read(0x460BA98C, 17))
        bit = lambda die: (base[die // 8] >> (die % 8)) & 1
        led = {(1, 1): "yellow", (1, 0): "red", (0, 1): "green", (0, 0): "off"}[(bit(ledtbl[cur]), bit(ledtbl[cur] + 1))]
        return (f"arrows on {rd(syms['cl_sbank'], 1) + 1}:{cur + 1} pmoved {rd(syms['cl_pmoved'], 1)} "
                f"ysup {rd(syms['cl_ysup'], 1)} tucked {tk} -> {'SHOWN' if rd(syms['cl_pmoved'], 1) and not tk else 'not shown'}; "
                f"their slot's LED {led}")

    # CL39 (the user, 2026-11-20): a stock pattern cue's second highlight. Per UI tick (0x40056c28 -> cl_uitick ->
    # cl_cblink), the screen AS COMPOSED (stock's composer 0x40013abc into [0x400b9710], windows included), the
    # arrows' phase cl_cph, the cue cl_pcq (cl_cblink's) and the bar cl_draw drew, cl_pbq.
    fails = []

    def qcheck(ok, what):
        print(f"      CHECK {'PASS' if ok else 'FAIL'}: {what}", flush=True)
        if not ok:
            fails.append(what)

    def composed():
        buf_ = rd(0x400B9710, 4)
        main_call(0x40013ABC)
        return bytes(u.mem_read(buf_, 1024))

    def qsample(n, ms=17):
        seq = []
        for _ in range(n):
            rt.run(ms=ms)
            main_call(0x40056C28)
            tail()
            seq.append(dict(ph=rd(syms["cl_cph"], 1), pcq=rd(syms["cl_pcq"], 2), pbq=rd(syms["cl_pbq"], 4),
                            act=rd(ACT, 1), bank=rd(syms["cl_bank"], 1), scr=composed()))
        return seq

    def qruns(seq):         # (phase, UI ticks) runs while the cue is up
        lens = []
        for x in seq:
            if x["pcq"] == 0xFFFF:
                continue
            if lens and lens[-1][0] == x["ph"]:
                lens[-1][1] += 1
            else:
                lens.append([x["ph"], 1])
        return lens

    def qdiff(s0, s1):      # differing pixels (x, y) of two composed screens, inside Clyps' window (x 8..119; the
        import lcd_view as lv   # track tabs outside it follow the sequencer)
        p0, p1 = lv.pixels(s0), lv.pixels(s1)
        return {(x, y) for y in range(len(p0)) for x in range(8, 120) if p0[y][x] != p1[y][x]}

    def qwin(s0):           # the window's pixels only
        import lcd_view as lv
        return tuple(tuple(row[8:120]) for row in lv.pixels(s0))

    def qcrop(s0, r_):
        import lcd_view as lv
        p0 = lv.pixels(s0)
        return [tuple(p0[y][r_[0]:r_[2] + 1]) for y in range(r_[1], r_[3] + 1)]

    def qrect(d):           # -> (x0, y0, x1, y1) when d is a full rectangle, else None
        if not d:
            return None
        xs, ys = [p[0] for p in d], [p[1] for p in d]
        r_ = (min(xs), min(ys), max(xs), max(ys))
        return r_ if len(d) == (r_[2] - r_[0] + 1) * (r_[3] - r_[1] + 1) else None

    def qcell(slot):        # the bar's columns on screen: the window at x 8 (WIN_DX), cl_colx's bar x0 / x1
        cx = syms["cl_colx"] + (8 if slot >= 8 else 0)
        return 8 + rd(cx + 2, 2), 8 + rd(cx + 4, 2)

    def qbox(slot):         # a cell's bar / box on the composed screen (measured on CL39's bars: row r at y 12 + 6r ..
        x0, x1 = qcell(slot)    # 18 + 6r, x as cl_colx; adjacent rows share a pixel row)
        return (x0, 12 + 6 * (slot & 7), x1, 18 + 6 * (slot & 7))

    qst = {}
    # CL39b: a cl_draw entered while cl_uitick runs = a draw in the UI task on the unit (prio 3, preempting the sys
    # task's draws: the CL39 garbage). The gate calls the tick from main, so here it only shows up as nesting.
    tkst = dict(inside=False, draws=0)
    if "cl_uitick" in syms and "uk_out" in syms:
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: tkst.update(inside=True),
                   begin=syms["cl_uitick"], end=syms["cl_uitick"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: tkst.update(inside=False),
                   begin=syms["uk_out"], end=syms["uk_out"])

        def on_draw(uc, ad, sz, ud):
            if tkst["inside"]:
                tkst["draws"] += 1
        u.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=syms["cl_draw"], end=syms["cl_draw"])
    wins = {}

    def qblink(code, label):    # the cue is up: its slot blinks as a second highlight in the arrows' phase
        seq = qsample(48)
        up = [x for x in seq if x["pcq"] == code]
        on = [x for x in up if x["ph"]]
        off = [x for x in up if not x["ph"]]
        lens = qruns(seq)
        print(f"      {label}: cue 0x{code:04x}; pcq seen {sorted({hex(x['pcq']) for x in seq})}; phase runs {lens}", flush=True)
        qcheck(len(up) == len(seq), f"{label}: cl_pcq holds the cue on every UI tick ({len(up)}/{len(seq)})")
        qcheck(all(l_[1] == (20 if l_[0] else 10) for l_ in lens[1:-1]) and len(lens) >= 3,
               f"{label}: the arrows' blink, 20 on / 10 off UI ticks ({lens})")
        same = code >> 8 == rd(syms["cl_bank"], 1)
        qcheck(all(x["pbq"] == (code if same else 0xFFFFFFFF) for x in on) and all(x["pbq"] == 0xFFFFFFFF for x in off),
               f"{label}: cl_pbq = the cue in the on phase{'' if same else ' -- never: another bank is shown'}, -1 in the off phase")
        if on and off:
            d = qdiff(on[-1]["scr"], off[-1]["scr"])
            r_ = qrect(d)
            R = qbox(code & 15)
            if same:        # CL39b: the select box's 1 px frame (the user), minus pixels already set (arrows on it)
                border = {(x, y) for x in range(R[0], R[2] + 1) for y in range(R[1], R[3] + 1)
                          if x in (R[0], R[2]) or y in (R[1], R[3])}
                cols = [sum(1 for p_ in d if p_[0] == c) for c in (R[0], R[2])]
                qcheck(bool(d) and d <= border and min(cols) >= 2,
                       f"{label}: on vs off differ by one 1 px frame on slot {(code & 15) + 1}'s cell {R}: {len(d)} px, "
                       f"{len(d - border)} outside its border, its sides {cols} px")
            else:
                qcheck(not d, f"{label}: another bank shown -- the on and off phases draw the same screen ({len(d)} px differ)")
            qst.update(code=code, on=on[-1]["scr"], off=off[-1]["scr"], rect=R, act=rd(ACT, 1))
        # the screen is stable within a phase (no flicker): every on-phase screen equal, every off-phase one too
        non, noff = len({qwin(x["scr"]) for x in on}), len({qwin(x["scr"]) for x in off})
        qcheck(non <= 1 and noff <= 1, f"{label}: one window screen per phase ({non} on, {noff} off)")

    def qsettled(label, code, ref, what):   # after a landing / a cancel: no cue, no bar, no blink; the cue's cell as ref
        seq = qsample(40)
        qcheck(all(x["pcq"] == 0xFFFF and x["pbq"] == 0xFFFFFFFF for x in seq),
               f"{label}: no cue left (cl_pcq 0xffff, cl_pbq -1 on all {len(seq)} UI ticks)")
        nw = len({qwin(x["scr"]) for x in seq})
        qcheck(nw == 1, f"{label}: the window is steady over {len(seq)} UI ticks (no blink): {nw} screen(s)")
        if ref is not None and qst.get("rect") and qst.get("code") == code and code >> 8 == rd(syms["cl_bank"], 1):
            c1, c0 = qcrop(seq[-1]["scr"], qst["rect"]), qcrop(qst[ref], qst["rect"])
            if ref == "on":     # CL39b: the cue's box is a frame now -- the highlight = the off phase's cell inverted
                c0 = [tuple(1 - v for v in r) for r in qcrop(qst["off"], qst["rect"])]
            k_, o_ = code & 15, qst.get("act", -1)
            shared = ""
            if ref == "on" and o_ >= 0 and o_ // 8 == k_ // 8 and abs(o_ - k_) == 1:
                # the playing pattern's bar was the next row: two XOR bars share one pixel row (a 1 px gap between
                # them while both show); after the landing that row is the lone highlight's again
                ix = 0 if o_ < k_ else len(c0) - 1
                c0, c1 = [r for j, r in enumerate(c0) if j != ix], [r for j, r in enumerate(c1) if j != ix]
                shared = f"; the row shared with slot {o_ + 1}'s bar left out"
            qcheck(c1 == c0, f"{label}: slot {k_ + 1}'s cell = the cue's {ref} phase ({what}{shared})")
            if c1 != c0:            # the cell then / now (# set), the row's text included
                for r0, r1 in zip(c0, c1):
                    print("        " + "".join("#" if v else "." for v in r0) + "   " +
                          "".join("#" if v else "." for v in r1), flush=True)
        return seq

    def qland(code, label, cap=4000):       # wait for the landing, then it must be the solid highlight
        g = 0
        while rd(ACT, 1) != (code & 15) and g < cap:
            rt.run(ms=17)
            main_call(0x40056C28)
            tail()
            g += 1
        qcheck(rd(ACT, 1) == (code & 15), f"{label}: landed on pattern {(code & 15) + 1} after {g} UI ticks")
        settle(200)
        qsettled(label, code, "on", "the off phase's cell inverted: the full highlight, unblinking")


    if a.partreads:     # the playing pattern's Part, from here on (after the start: the stock start's own reads stay out)
        pr_base[0] = bb + 0x8ED80 + (rd(slab_ad + 0x8E57, 1) & 3) * 0x18B2
        u.hook_add(er.eb.UC_HOOK_MEM_READ, on_pread, begin=pr_base[0], end=pr_base[0] + 0x18B1)
        print(f"Part reads watched: 0x{pr_base[0]:08x} (Part {(rd(slab_ad + 0x8E57, 1) & 3) + 1})", flush=True)

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
        if op[0] == "W":                      # CL39b: the whole Clyps window (x 8..119) after 40 UI ticks, taken in the
            g = 0                             # arrows' on phase if anything blinks; masked by the compare: the cued
            for g in range(40):               # pattern's cell
                rt.run(ms=17)
                main_call(0x40056C28)
                tail()
            for g in range(40):
                if rd(syms["cl_cph"], 1):
                    break
                rt.run(ms=17)
                main_call(0x40056C28)
                tail()
            settle(68)
            pend = (rd(0x800065BF, 1), rd(0x800065C0, 1))
            wins[op[1:]] = dict(scr=composed().hex(), cph=rd(syms["cl_cph"], 1), act=rd(ACT, 1), pend=pend,
                                bank=rd(syms["cl_bank"], 1))
            print(f"#{i} {op}: window taken (cph {rd(syms['cl_cph'], 1)}, act {rd(ACT, 1)}, pend {pend})", flush=True)
            continue
        if op[0] == "c":                      # CL39b: press only -- cK = [PTN] + trig K, c- = [PTN] + the playing trig
            k_ = rd(ACT, 1) if op[1:] == "-" else int(op[1:])
            key(0x2E, 1); key(k_, 1); key(k_, 0); key(0x2E, 0)
            settle(100)
            continue
        if op[0] in "pF" and op[1:].isdigit():   # CL39b: press only -- pK = trig K (a SEQ load), FK = [FUNC] + trig K
            k_ = int(op[1:])
            if op[0] == "F":
                key(FUNC, 1); key(k_, 1); key(k_, 0); key(FUNC, 0)
            else:
                key(k_, 1); key(k_, 0)
            settle(100)
            continue
        if op == "L":                         # CL39b: wait for the next Clyps landing (up to ~20 s)
            nl0, g = len(lands), 0
            while len(lands) == nl0 and g < 600:
                settle(34)
                g += 1
            print(f"#{i} L: landed {lands[-1] if len(lands) > nl0 else None}", flush=True)
            continue
        if op[0] == "q":                      # CL39: stock pattern cues -- qK = [PTN] + trig K (a stock cue made in
            act0 = rd(ACT, 1)                 # Clyps), rK = [PTN]+[BANK]+trig K (a card reload of another pattern:
            if op == "qc":                    # the toast, then stock's cue), ql = wait for the landing, qc = cancel
                key(0x2E, 1); key(act0, 1); key(act0, 0); key(0x2E, 0)      # ([PTN] + the playing pattern's trig)
                qcheck(rd(0x800065C0, 1) == act0, f"#{i} qc: stock's cue is the playing pattern again")
                qsettled(f"#{i} qc", qst.get("code", -1), "off", "back as it was before the cue: no bar")
                continue
            if op == "ql":
                qland(qst.get("code", 0xFFFF), f"#{i} ql")
                continue
            if op == "qv":                    # the cue already up (e.g. after k+ / k-): sample it again
                qblink(rd(syms["cl_pcq"], 2), f"#{i} qv")
                continue
            dj_ = op[1] == "d"                # qdK: DIRECT JUMP on -- the cue lands at the next step
            k_ = int(op[2:] if dj_ else op[1:])
            code = (rd(0x800065BD, 1) << 8) | k_
            key(0x2E, 1); key(k_, 1); key(k_, 0); key(0x2E, 0)
            if dj_:
                seq = []
                for _ in range(400):
                    seq += qsample(1)
                    if seq[-1]["act"] == k_:
                        break
                pre = [x for x in seq if x["pcq"] == code]
                print(f"      #{i} {opx}: {len(pre)} UI ticks cued, phases {[x['ph'] for x in pre]}, "
                      f"bars {[hex(x['pbq']) for x in pre]}", flush=True)
                qcheck(bool(pre) and all(x["ph"] == 1 and x["pbq"] == code for x in pre),
                       f"#{i} {opx}: DIRECT JUMP on -- the second highlight shows (on phase) until the jump lands")
                qland(code, f"#{i} {opx}")
                continue
            qblink(code, f"#{i} {opx}")
            continue
        if op[0] == "r" and op[1:].isdigit():  # CL39: [PTN]+[BANK]+trig K: pattern K back from the card (another
            k_ = int(op[1:])                  # pattern: the toast at once, then stock's cue)
            code = (rd(0x800065BD, 1) << 8) | k_
            g0 = rd(syms["rq_gen"], 1)
            key(0x2E, 1); key(0x2F, 1); key(k_, 1); key(k_, 0); key(0x2F, 0); key(0x2E, 0)
            g = 0
            while rd(syms["cl_pcq"], 2) != code and g < 600:
                rt.run(ms=17)
                main_call(0x40056C28)
                tail()
                g += 1
            print(f"      #{i} {opx}: the card job and stock's cue took {g} UI ticks; its toast line 1 "
                  f"{bytes(u.mem_read(syms['rq_line1'], 12)).split(b'\\0')[0]!r}", flush=True)
            qcheck(rd(syms["rq_gen"], 1) != g0 and rd(syms["rq_jgen"], 1) == rd(syms["rq_gen"], 1)
                   and rd(syms["rq_busy"], 1) == 0, f"#{i} {opx}: it was a card reload (request generation "
                   f"{g0} -> {rd(syms['rq_gen'], 1)}, its job done)")
            qblink(code, f"#{i} {opx}")
            continue
        if op == "x":                         # STOP (stock's COND_RESET(-1), 0x400a12b8), then PLAY again
            key(0x27, 1); key(0x27, 0)
            settle(600)
            stopped = rd(RUNNING, 4)
            rt.start_transport_live()
            settle(300)
            print(f"#{i} x: stopped ({stopped}), running {rd(RUNNING, 4)} at tick {st['tick']}", flush=True)
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
        if op == "Y":                         # a bare [YES]: whatever the screen shows
            nl0 = len(reqs)
            key(0x31, 1); key(0x31, 0)
            settle(1500)
            print(f"#{i} Y: requests {len(reqs) - nl0}; {view()}", flush=True)
            continue
        if op[0] == "b":                      # CL34: a load (bK = trig K, bY = [YES]) sampled until it lands: the
            nl0 = len(lands)                  # cued slot's arrows' blink phase (cl_cph) against cl_T mod 24
            if op[1:] == "Y":
                key(0x31, 1); key(0x31, 0)
            else:
                key(int(op[1:]), 1); key(int(op[1:]), 0)
            seq, g = [], 0
            tk = (a.track or 0) * 2
            while len(lands) == nl0 and g < 400:
                rt.run(ms=40)
                main_call(0x40056C28)         # route A runs no UI tick (task 0x40056c40's 1/60 s message): call its
                g += 1                        # patched site (-> cl_uitick -> cl_cblink), as diag_clyps_ui does
                cue = rd(syms["cl_cue"] + tk, 2)
                seq.append((st["tick"], rd(syms["cl_T"], 4) % 24, rd(syms["cl_cph"], 1),
                            0xFFFFFFFF if cue == 0xFFFF else cue))
                if shots and (len(seq) < 2 or seq[-1][2] != seq[-2][2]) and len(seq) < 12:
                    shot(f"{i:02d}_{op}_{len(seq):03d}_ph{seq[-1][2]}")
            settle(400)
            shot(f"{i:02d}_{op}_landed")
            runs = []
            for t_, m_, ph, cq in seq:
                if not runs or runs[-1][1] != ph:
                    runs.append([t_, ph, m_, cq])
            on_ = [x for x in seq if x[3] != 0xFFFFFFFF]       # CL34: 120 BPM fixed -- per UI tick: 20 on, 10 off
            lens, cur_ = [], None
            for x in on_:
                if cur_ and cur_[0] == x[2]:
                    cur_[1] += 1
                else:
                    cur_ = [x[2], 1]
                    lens.append(cur_)
            bad = [l_ for l_ in lens[1:-1] if l_[1] != (20 if l_[0] else 10)]
            print(f"      blink runs (phase, UI ticks): {lens[:12]}", flush=True)
            print(f"#{i} {opx}: cued {hex(seq[0][3]) if seq else None}, landed {lands[-1] if len(lands) > nl0 else None}; "
                  f"phase runs (tick, on, T mod 24) {[(r[0], r[1], r[2]) for r in runs][:16]}; samples {len(seq)}, "
                  f"runs off 20 / 10 {len(bad)} {bad[:3]}; after: cph {rd(syms['cl_cph'], 1)}; {view()}", flush=True)
            continue
        if op in ("k+", "k-"):                # CL34: [BANK] held + DOWN / UP -- the view to the next / previous bank
            key(0x2F, 1); key(0x20 if op == "k+" else 0x33, 1); key(0x20 if op == "k+" else 0x33, 0); key(0x2F, 0)
            settle(400)
            print(f"#{i} {op}: view bank {rd(syms['cl_bank'], 1) + 1}; {view()}", flush=True)
            continue
        if op == "v":                         # the view now
            settle(300)
            print(f"#{i} v: {view()}", flush=True)
            shot(f"{i:02d}_v")
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
              f"{l}; {view()}", flush=True)
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
                                   purges=purges, applies=applies, parts=parts, windows=wins,
                                   preads=[[pc, off] + v for (pc, off), v in sorted(preads.items())])))
    print(f"wrote {out}: ticks {st['tick']}, landings {len(lands)}", flush=True)
    print(f"CL39b: cl_draw entered inside the UI tick (cl_uitick) {tkst['draws']} time(s) -- the unit's UI task "
          f"(prio 3) drawing over the sys task", flush=True)
    if "cl_dreq" in syms:
        qcheck(tkst["draws"] == 0, "CL39b: no cl_draw from the UI tick (the redraws go to the sys task's tail)")
    if fails:
        print(f"CL39 checks: {len(fails)} FAIL", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

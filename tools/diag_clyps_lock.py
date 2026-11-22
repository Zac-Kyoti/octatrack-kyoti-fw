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
  CL39c: gK = after k+ / k-, [PTN] held shows the shown bank's grid (data green, no red), [PTN] + trig K cues that
       bank's pattern (yellow on the next [PTN]), its box blinks there; ql then checks the landing's bank too. The run
       counts the sys-queue posts of cl_dpost per UI tick.
  CL39b (the cue's box is the select box's frame; no draws from the UI tick): press-only ops cK / c- ([PTN] + trig K /
       the playing pattern's trig), pK (trig K: a SEQ load), FK ([FUNC] + trig K: a FULL load), L (wait for a Clyps
       landing), WN (the whole composed window into the record's "windows", taken in the arrows' on phase) -- compare
       two images' runs with tools/cmp_clyps_windows.py; the run counts cl_draw calls made inside cl_uitick (on the unit:
       the UI task drawing over the sys task) and FAILs a CL39b image on any.
  CL40 (one cue mark, one cursor): --bankb plays bank B (bank A copied there in RAM after the load, as a stock pattern
       copy would, its originals re-snapped; then stock's own [BANK] + B + pattern pick, stopped, Clyps closed); every
       draw counts its arrow sets (cd_arrows) and the run FAILs on two in one window; q / r ops expect the load
       confirmation flash on the picked slot first (cl_flk, cl_fcode), the blink's box after it; O = close and reopen
       Clyps: the view on the playing bank; T = two lone [PTN] taps (the second closes stock's SELECT PATTERN): the grid
       is the shown bank's on every press, release and in the window; P checks ORIG PTN+PRT's flash on its slot;
       tK = trig K (a cued SEQ load): the flash on its slot, then the select box's frame blinking there; uK = a lone
       [PTN] tap, then trig K in stock's SELECT PATTERN: the bank shown is cued.
  CL41 (the bank shown is the bank acted on): rK reloads pattern K of the bank SHOWN (after k- with --bankb: bank A
       while B plays) -- an edit of its slab and Part in RAM first, then the chord: its grid while held = the shown
       bank's pattern view, the view stays, the toast names that bank, the slab / Part = the card's again, the
       playing bank's pattern K untouched; P presses [BANK] first and checks the chord's grid and the view before the
       [YES], the view on the playing bank after it; KN = TRACK N: the view stays, the track's arrows in it; R =
       [PTN] + the active TRACK (a card SEQ reload of the playing pattern's track): it lands, the view stays.
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
WIN_SLOT_ = 0x460D1E5C           # the SHOW_WIN popup handle (stock's [PTN] / [BANK] windows)


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
    ap.add_argument("--bankb", action="store_true", help="CL40: play bank B (bank A copied there in RAM)")
    ap.add_argument("--parts", type=lambda v: int(v, 0), default=0,
                    help="BANKSZ: at the end compare the playing Part with the load snapshot's")
    a = ap.parse_args(argv)
    sp = os.environ.get("CLYPS_SYMS", str(ROOT / "out/clyps_syms.txt"))
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(sp).read_text().splitlines())}
    CL40 = "cl_flcode" in syms
    CL41 = "rq_jbk" in syms
    CL42 = "cl_s_currp" in syms      # the view never follows a landing (the user, 2026-11-21); the header
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
    if a.bankb:     # CL40: bank A -> bank B in RAM (16 slabs + 4 Parts, a whole-bank pattern copy), its originals
        u.mem_write(BLOB + BANKSTRIDE, bytes(u.mem_read(BLOB + bank * BANKSTRIDE, 0x95048)))   # re-snapped
        main_call(syms["cl_snapbank"], 1)
        p_ = 0 if a.start is None else a.start
        key(0x2F, 1); key(0x01, 1); key(0x01, 0); key(p_, 1); key(p_, 0); key(0x2F, 0)  # stock: [BANK] + B + pattern
        bank = rd(0x800065BD, 1)
        print(f"--bankb: stock's pick -> UI bank {rd(0x80000002, 1)}, playing {bank}:{rd(ACT, 1)}", flush=True)
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
    hdr = []             # CL42: the header's texts as drawn (cl_text at HDR_Y 57), the latest draw's
    if "cl_text" in syms:
        def on_text(uc, ad, sz, ud):
            s_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
            if rd(s_ + 8, 4) == 57:
                hdr.append(bytes(uc.mem_read(rd(s_ + 12, 4), 24)).split(b"\0")[0].decode("latin-1"))
        u.hook_add(er.eb.UC_HOOK_CODE, on_text, begin=syms["cl_text"], end=syms["cl_text"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: hdr.clear(), begin=syms["cl_draw"], end=syms["cl_draw"])
    zfail = dict(n=0, hit=0)   # CL42 op Z: the next card job's open fails as a never-saved bank's does (-12): a fault
    if "rj_opened" in syms:    # injected at its result test (tst.l %d0, 10 B before rj_opened), the data untouched
        def on_open(uc, ad, sz, ud):
            if zfail["n"]:
                zfail["n"] -= 1
                zfail["hit"] += 1
                uc.reg_write(er.eb.UC_M68K_REG_D0, 0xFFFFFFF4)
        u.hook_add(er.eb.UC_HOOK_CODE, on_open, begin=syms["rj_opened"] - 10, end=syms["rj_opened"] - 10)
    toasts = []          # CL42: every card-reload toast (cl_toast2), its tick
    if "cl_toast2" in syms:
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: toasts.append(st["tick"]),
                   begin=syms["cl_toast2"], end=syms["cl_toast2"])
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
                            act=rd(ACT, 1), bank=rd(syms["cl_bank"], 1), flk=rd(syms["cl_flk"], 1) if CL40 else 0,
                            fc=rd(syms["cl_fcode"], 2), scr=composed()))
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
    # The current TCB (0x800068fc) tells the tick's own task from another one that ran meanwhile: here the tick runs
    # as main (prio 0), so the sys task (prio 1) its post wakes preempts it and draws in its tail -- on the unit the
    # poster is the UI task (prio 3), which the sys task cannot preempt. Only draws in the tick's own task count.
    tkst = dict(inside=False, draws=0, other=0, tcb=0)
    if "cl_uitick" in syms and "uk_out" in syms:
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: tkst.update(inside=True, tcb=rd(0x800068FC, 4),
                                                                           calls=tkst.get("calls", 0) + 1),
                   begin=syms["cl_uitick"], end=syms["cl_uitick"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: tkst.update(inside=False),
                   begin=syms["uk_out"], end=syms["uk_out"])

        def on_draw(uc, ad, sz, ud):
            if tkst["inside"]:
                if rd(0x800068FC, 4) == tkst["tcb"]:
                    tkst["draws"] += 1
                else:
                    tkst["other"] += 1
        u.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=syms["cl_draw"], end=syms["cl_draw"])
    wins = {}
    posts = dict(n=0, t0=None)          # CL39c: cl_dpost's real posts (dp_post), against the transport's ticks
    if "dp_post" in syms:
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: posts.update(n=posts["n"] + 1),
                   begin=syms["dp_post"], end=syms["dp_post"])

    arw = dict(n=0, max=0, bad=0)       # CL40: arrow sets per window draw (cd_arrows calls between cl_draw and cd_boxed)
    if "cd_arrows" in syms and "cd_boxed" in syms:
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: arw.update(n=0), begin=syms["cl_draw"], end=syms["cl_draw"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: arw.update(n=arw["n"] + 1),
                   begin=syms["cd_arrows"], end=syms["cd_arrows"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: arw.update(max=max(arw["max"], arw["n"]),
                                                                          bad=arw["bad"] + (arw["n"] > 1)),
                   begin=syms["cd_boxed"], end=syms["cd_boxed"])

    def grid():                         # the trig LEDs as painted now: R / G / Y / . per slot
        main_call(0x4007E998, 0)
        b_ = bytes(u.mem_read(0x460BA98C, 17))
        die = lambda d_: (b_[d_ // 8] >> (d_ % 8)) & 1
        return "".join({(1, 1): "Y", (1, 0): "R", (0, 1): "G", (0, 0): "."}[(die(ledtbl[n]), die(ledtbl[n] + 1))]
                       for n in range(16))

    def pgrid(b_):                      # stock's [PTN] grid of bank b_: green = data, red = the playing pattern there
        g_ = ["G" if main_call(0x4009A464, n, b_) & 0xFFFFFFFF else "." for n in range(16)]
        if b_ == rd(0x800065BD, 1):
            g_[rd(ACT, 1)] = "R"
        return "".join(g_)

    def qblink(code, label, fresh=True):    # the cue is up: its slot blinks as a second highlight in the arrows' phase
        seq = qsample(78 if CL40 else 48)
        up = [x for x in seq if x["pcq"] == code]
        fl = []
        if CL40 and fresh:            # CL40: the load confirmation flash on the picked slot first, the blink's box after it
            fl = [x for x in seq if x["flk"]]
            qcheck(bool(fl) and seq[0]["flk"] and all(x["fc"] == code for x in fl) and len(fl) < 32,
                   f"{label}: the confirmation flash on {chr(65 + (code >> 8))}{(code & 15) + 1:02d} first "
                   f"({len(fl)} UI ticks, fcode {sorted({hex(x['fc']) for x in fl})})")
            up = [x for x in up if not x["flk"]]
        on = [x for x in up if x["ph"]]
        off = [x for x in up if not x["ph"]]
        lens = qruns(seq)
        print(f"      {label}: cue 0x{code:04x}; pcq seen {sorted({hex(x['pcq']) for x in seq})}; phase runs {lens}", flush=True)
        qcheck(all(x["pcq"] == code for x in seq), f"{label}: cl_pcq holds the cue on every UI tick ({len(up)}/{len(seq)})")
        qcheck(all(l_[1] == (20 if l_[0] else 10) for l_ in lens[1:-1]) and len(lens) >= 3,
               f"{label}: the arrows' blink, 20 on / 10 off UI ticks ({lens})")
        same = code >> 8 == rd(syms["cl_bank"], 1)
        if CL40 and fl and same:    # the flash: the cell inverted / plain, no frame meanwhile
            qcheck(all(x["pbq"] == 0xFFFFFFFF for x in fl), f"{label}: no cue box while the flash runs")
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
            qst.update(code=code, on=on[-1]["scr"], off=off[-1]["scr"], rect=R, act=rd(ACT, 1),
                       arw=bool(rd(syms["cl_pmoved"], 1)) and not rd(syms["cl_ysup"], 1)       # CL42: the arrows
                       and ((rd(syms["cl_sbank"], 1) << 8) | rd(syms["cl_cur"], 1)) == code)   # shown on the cue
        # the screen is stable within a phase (no flicker): every on-phase screen equal, every off-phase one too
        non, noff = len({qwin(x["scr"]) for x in on}), len({qwin(x["scr"]) for x in off})
        qcheck(non <= 1 and noff <= 1, f"{label}: one window screen per phase ({non} on, {noff} off)")

    def qsettled(label, code, ref, what):   # after a landing / a cancel: no cue, no bar, no blink; the cue's cell as ref
        seq = qsample(40)
        qcheck(all(x["pcq"] == 0xFFFF and x["pbq"] == 0xFFFFFFFF for x in seq),
               f"{label}: no cue left (cl_pcq 0xffff, cl_pbq -1 on all {len(seq)} UI ticks)")
        nw = len({qwin(x["scr"]) for x in seq})
        qcheck(nw == 1, f"{label}: the window is steady over {len(seq)} UI ticks (no blink): {nw} screen(s)")
        if ref is not None and qst.get("arw") and "cl_phide" in syms and qst.get("code") == code:
            print(f"      {label}: the cell vs the cue's {ref} phase not compared -- the arrows sat on the cued slot and "
                  f"hide at its landing (CL42; the op list checks a-)", flush=True)
        elif ref is not None and qst.get("rect") and qst.get("code") == code and code >> 8 == rd(syms["cl_bank"], 1):
            c1, c0 = qcrop(seq[-1]["scr"], qst["rect"]), qcrop(qst[ref], qst["rect"])
            if ref == "off" and (main_call(syms["cl_srccode"]) & 0x0F0F) == (code & 0x0F0F) and "cl_ptnbank" in syms:
                ref = "on"      # CL39c: the cued slot is the select box's: it blinked, and after a cancel it is drawn
                what += "; the select box's slot: its on phase, the box solid again"
                c0 = qcrop(qst["on"], qst["rect"])
            if ref == "on" and "solid again" not in what:   # CL39b: the highlight = the off phase's cell inverted
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
        g, vb0 = 0, rd(syms["cl_bank"], 1)
        while rd(ACT, 1) != (code & 15) and g < cap:
            rt.run(ms=17)
            main_call(0x40056C28)
            tail()
            g += 1
        qcheck(rd(ACT, 1) == (code & 15) and rd(0x800065BD, 1) == code >> 8,
               f"{label}: landed on {chr(65 + (code >> 8))}{(code & 15) + 1:02d} after {g} UI ticks")
        settle(200)
        if CL42:
            qcheck(rd(syms["cl_bank"], 1) == vb0, f"{label}: the view stays on {chr(65 + vb0)} (CL42: never to a landing)")
        elif CL40:
            qcheck(rd(syms["cl_bank"], 1) == code >> 8, f"{label}: the view on the landed pattern's bank")
        if CL40:
            while rd(syms["cl_flk"], 1) and g < cap:      # a quick landing (DIRECT JUMP): the flash ends first
                settle(34)
                g += 1
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
            g = 0                             # CL42: until it lands (was a fixed 3 s)
            while rd(ACT, 1) != int(op[1:]) and g < 400:
                settle(34)
                g += 1
            settle(300)
            snaps.append([st["tick"], params(rd(ACT, 1))])
            print(f"#{i} {opx}: cued, act now {rd(ACT, 1)} at tick {st['tick']}", flush=True)
            continue
        if op == "w":
            settle(1000)
            continue
        if op[0] == "g":                      # CL39c: gK -- after k+ / k-: [PTN] in Clyps acts on the bank shown
            k_, vb, ub = int(op[1:]), rd(syms["cl_bank"], 1), rd(0x80000002, 1)
            base_ = lambda: bytes(u.mem_read(0x460BA98C, 17))
            die = lambda b_, d_: (b_[d_ // 8] >> (d_ % 8)) & 1

            def grid():
                main_call(0x4007E998, 0)          # repaint the grid (route A runs no LED tick)
                b_ = base_()
                return [(die(b_, ledtbl[n]), die(b_, ledtbl[n] + 1)) for n in range(16)]
            qcheck(vb != ub, f"#{i} {op}: the view is on another bank ({chr(65 + vb)}) than the current ({chr(65 + ub)})")
            want = [1 if main_call(0x4009A464, n, vb) & 0xFFFFFFFF else 0 for n in range(16)]
            key(0x2E, 1)
            g0 = grid()
            qcheck([x[1] for x in g0] == want and not any(x[0] for x in g0),
                   f"#{i} {op}: [PTN] held: the grid = bank {chr(65 + vb)}'s patterns with data {''.join(map(str, want))}, "
                   f"no red ({g0})")
            key(k_, 1); key(k_, 0); key(0x2E, 0)
            settle(100)
            pend = (rd(0x800065BF, 1), rd(0x800065C0, 1))
            qcheck(pend == (vb, k_), f"#{i} {op}: [PTN] + trig {k_ + 1} cued {chr(65 + vb)}{k_ + 1:02d} (PEND {pend})")
            key(0x2E, 1)
            g1 = grid()
            key(k_, 1); key(k_, 0)            # the same pick again (no change): consumed, so the release opens no
            key(0x2E, 0)                      # stock pattern window over the view (a lone [PTN] tap would)
            settle(100)
            qcheck((rd(0x800065BF, 1), rd(0x800065C0, 1)) == (vb, k_) and rd(WIN_SLOT_, 4) == 0,
                   f"#{i} {op}: still cued, no stock window over the view")
            qcheck(g1[k_] == (1, 1), f"#{i} {op}: [PTN] held again: {chr(65 + vb)}{k_ + 1:02d} yellow ({g1[k_]})")
            qblink((vb << 8) | k_, f"#{i} {op}")
            continue
        if op[0] == "t" and op[1:].isdigit():  # CL40: tK = trig K (a SEQ load, cued): the flash on its slot first,
            k_ = int(op[1:])                  # then the select box's frame blinks there (no arrows), one phase
            code = (rd(syms["cl_bank"], 1) << 8) | k_
            key(k_, 1); key(k_, 0)
            seq = qsample(78)
            tc = rd(syms["cl_cue"] + 2 * a.track, 2)
            fl = [x for x in seq if x["flk"]]
            qcheck(bool(fl) and seq[0]["flk"] and all(x["fc"] == code for x in fl) and len(fl) < 32 and tc == code,
                   f"#{i} {op}: cued {tc:#06x}; the confirmation flash on its slot first ({len(fl)} UI ticks)")
            on = [x for x in seq if not x["flk"] and x["ph"]]
            off = [x for x in seq if not x["flk"] and not x["ph"]]
            if on and off:
                d, R = qdiff(on[-1]["scr"], off[-1]["scr"]), qbox(k_)
                border = {(x, y) for x in range(R[0], R[2] + 1) for y in range(R[1], R[3] + 1)
                          if x in (R[0], R[2]) or y in (R[1], R[3])}
                cols = [sum(1 for p_ in d if p_[0] == c) for c in (R[0], R[2])]
                qcheck(bool(d) and d <= border and min(cols) >= 2, f"#{i} {op}: after the flash, on vs off differ by "
                       f"one 1 px frame on slot {k_ + 1}'s cell: {len(d)} px, {len(d - border)} outside, sides {cols}")
            else:
                qcheck(False, f"#{i} {op}: blink phases after the flash ({len(on)} on, {len(off)} off)")
            continue
        if op[0] == "u" and op[1:].isdigit():  # CL40: uK = a lone [PTN] tap (stock's SELECT PATTERN opens), then trig
            k_, vb_ = int(op[1:]), rd(syms["cl_bank"], 1)   # K in that window: it cues the bank shown
            key(0x2E, 1); key(0x2E, 0); settle(100)
            w_ = rd(WIN_SLOT_, 4)
            key(k_, 1); key(k_, 0); settle(100)
            pend = (rd(0x800065BF, 1), rd(0x800065C0, 1))
            qcheck(w_ != 0 and pend == (vb_, k_), f"#{i} {op}: [PTN] tap (window {w_:#x}), then trig {k_ + 1}: cued "
                   f"{chr(65 + pend[0])}{pend[1] + 1:02d}, the bank shown {chr(65 + vb_)}")
            continue
        if op == "O":                         # CL40: close ([NO]) and reopen Clyps -- the view on the playing bank
            key(0x32, 1); key(0x32, 0)
            settle(200)
            key(0x2E, 1); key(0x2F, 1); key(0x2F, 0); key(0x2E, 0)
            settle(300)
            pb_, vb_ = rd(0x800065BD, 1), rd(syms["cl_bank"], 1)
            qcheck(rd(syms["cl_open"], 1) == 1 and vb_ == pb_,
                   f"#{i} O: reopened on bank {chr(65 + vb_)}, the playing pattern's {chr(65 + pb_)}; {view()}")
            continue
        if op == "T":                         # CL40: two lone [PTN] taps -- every grid the shown bank's
            vb_ = rd(syms["cl_bank"], 1)
            want = pgrid(vb_) if "cl_ptnbank" in syms else pgrid(rd(0x80000002, 1))
            seen = []
            for n_ in range(2):
                key(0x2E, 1); seen.append(("press", grid()))
                key(0x2E, 0); settle(100); seen.append(("up", grid()))
            print(f"#{i} T: view {chr(65 + vb_)}, want {want}: {seen}", flush=True)
            qcheck(all(g_ == want for w_, g_ in seen[:3]), f"#{i} T: [PTN] grid = bank {chr(65 + vb_)}'s on the press, "
                   f"in the window and on the second press")
            qcheck(rd(WIN_SLOT_, 4) == 0 and rd(syms["cl_open"], 1) == 1 and rd(syms["cl_bank"], 1) == vb_,
                   f"#{i} T: the second tap closed the window, Clyps still on bank {chr(65 + vb_)}")
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
                                bank=rd(syms["cl_bank"], 1), tcue=rd(syms["cl_cue"] + 2 * a.track, 2))
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
                qblink(rd(syms["cl_pcq"], 2), f"#{i} qv", fresh=False)
                continue
            dj_ = op[1] == "d"                # qdK: DIRECT JUMP on -- the cue lands at the next step
            k_ = int(op[2:] if dj_ else op[1:])
            code = (rd(syms["cl_bank"] if "cl_ptnbank" in syms else 0x800065BD, 1) << 8) | k_   # CL39c: the bank shown
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
                qcheck(bool(pre) and all(x["ph"] == 1 and (x["fc"] == code and x["flk"] if CL40 else x["pbq"] == code)
                                         for x in pre),
                       f"#{i} {opx}: DIRECT JUMP on -- the {'confirmation flash' if CL40 else 'second highlight'} "
                       f"shows until the jump lands")
                qland(code, f"#{i} {opx}")
                continue
            qblink(code, f"#{i} {opx}")
            continue
        if op[0] == "r" and op[1:].isdigit():  # CL39: [PTN]+[BANK]+trig K: pattern K back from the card (another
            k_ = int(op[1:])                  # pattern: the toast at once, then stock's cue) -- of the playing bank;
            pb_, vb_ = rd(0x800065BD, 1), rd(syms["cl_bank"], 1)    # CL41: of the bank shown
            code = ((vb_ if CL41 else pb_) << 8) | k_
            g0 = rd(syms["rq_gen"], 1)
            if CL41:                          # an edit in RAM the card must undo: T1's first trig-mask byte, and a
                tb_ = code >> 8               # byte of T1's machine slice in the pattern's Part (diag_clyps_ui L's)
                sad = BLOB + tb_ * BANKSTRIDE + k_ * PATSTRIDE
                pad = BLOB + tb_ * BANKSTRIDE + 0x8ED80 + (rd(sad + 0x8E57, 1) & 3) * 0x18B2
                oad = BLOB + pb_ * BANKSTRIDE + k_ * PATSTRIDE      # the playing bank's pattern K
                opd = BLOB + pb_ * BANKSTRIDE + 0x8ED80 + (rd(oad + 0x8E57, 1) & 3) * 0x18B2
                pre_s, pre_p = bytes(u.mem_read(sad, PATSTRIDE)), bytes(u.mem_read(pad, 0x18B2))
                pre_os, pre_op = bytes(u.mem_read(oad, PATSTRIDE)), bytes(u.mem_read(opd, 0x18B2))
                u.mem_write(sad, bytes([rd(sad, 1) ^ 0x81]))
                u.mem_write(pad + 0x2A, bytes([rd(pad + 0x2A, 1) ^ 0x55]))
                key(0x2E, 1); key(0x2F, 1)
                g_, want_ = grid(), pgrid(vb_)
                qcheck(g_ == want_ and rd(syms["cl_bank"], 1) == vb_,
                       f"#{i} {opx}: the chord held: the view stays on {chr(65 + vb_)} (playing {chr(65 + pb_)}), its grid = "
                       f"bank {chr(65 + vb_)}'s pattern view {want_} ({g_})")
                key(k_, 1); key(k_, 0); key(0x2F, 0); key(0x2E, 0)
            else:
                key(0x2E, 1); key(0x2F, 1); key(k_, 1); key(k_, 0); key(0x2F, 0); key(0x2E, 0)
            g = 0
            while rd(syms["cl_pcq"], 2) != code and g < 600 and (rd(ACT, 1), rd(0x800065BD, 1)) != (k_, code >> 8):
                rt.run(ms=17)
                main_call(0x40056C28)
                tail()
                g += 1
            print(f"      #{i} {opx}: the card job and stock's cue took {g} UI ticks; its toast line 1 "
                  f"{bytes(u.mem_read(syms['rq_line1'], 12)).split(b'\\0')[0]!r}", flush=True)
            if CL41:
                NOS = {0x899 + k * TRAC_A for k in range(8)} | set(range(0x8E5C, PATSTRIDE))
                now_s = bytes(u.mem_read(sad, PATSTRIDE))
                ds = [j for j in range(PATSTRIDE) if j not in NOS and now_s[j] != pre_s[j]]
                pix = rd(sad + 0x8E57, 1) & 3      # the card's saved Part may differ from the loaded .work there:
                wsd = set()                         # those bytes come back as saved (the reload's point), not as loaded
                try:
                    def _pc(fn):
                        d_ = (pathlib.Path(a.project) / fn).read_bytes()
                        st_ = 0x8EEC if ((d_[0x14] << 8) | d_[0x15]) >= 0x17 else 0x8EE8
                        return d_[0x16 + 16 * st_ + 0x18BB * pix + 9:][:0x18B2]
                    w_, c_ = _pc(f"bank{tb_ + 1:02d}.work"), _pc(f"bank{tb_ + 1:02d}.strd")
                    wsd = {j for j in range(0x18B2) if w_[j] != c_[j]}
                except OSError:
                    pass
                dp = [j for j in range(0x18B2) if rd(pad + j, 1) != pre_p[j] and j not in wsd]
                if rd(pad + 0x2A, 1) != pre_p[0x2A]:
                    dp.append(0x2A)
                line1 = bytes(u.mem_read(syms['rq_line1'], 12)).split(b'\0')[0].decode()
                qcheck(rd(syms["cl_bank"], 1) == vb_ and rd(syms["rq_jbk"], 1) == vb_
                       and line1 == f"PATTERN {chr(65 + vb_)}{k_ + 1:02d}",
                       f"#{i} {opx}: the view stays on {chr(65 + vb_)}; the job read bank {chr(65 + rd(syms['rq_jbk'], 1))}; "
                       f"toast {line1!r}")
                qcheck(not ds and not dp, f"#{i} {opx}: {chr(65 + vb_)}{k_ + 1:02d}'s slab and Part = the card's again "
                       f"({len(ds)} / {len(dp)} bytes differ from as loaded, {[hex(j) for j in (ds + dp)[:6]]})")
                if vb_ != pb_:
                    qcheck(bytes(u.mem_read(oad, PATSTRIDE)) == pre_os and bytes(u.mem_read(opd, 0x18B2)) == pre_op,
                           f"#{i} {opx}: the playing bank's {chr(65 + pb_)}{k_ + 1:02d} and its Part untouched")
            elif CL40:
                qcheck(rd(syms["cl_bank"], 1) == code >> 8, f"#{i} {opx}: the chord took the view to the playing bank")
            qcheck(rd(syms["rq_gen"], 1) != g0 and rd(syms["rq_jgen"], 1) == rd(syms["rq_gen"], 1)
                   and rd(syms["rq_busy"], 1) == 0, f"#{i} {opx}: it was a card reload (request generation "
                   f"{g0} -> {rd(syms['rq_gen'], 1)}, its job done)")
            if a.dj:                          # CL41: DIRECT JUMP on -- the jump lands at the next step (no blink to time)
                qst.clear()
                qst.update(code=code)
                qland(code, f"#{i} {opx}")
                continue
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
            psad = BLOB + rd(0x800065BD, 1) * BANKSTRIDE + rd(ACT, 1) * PATSTRIDE    # CL42: an in-RAM edit of the
            pre_p0 = rd(psad, 1)                                                     # playing pattern's T1: the
            if CL42:                                                                 # originals (the snapshot) undo it
                pre_p0 = rd(syms["cl_bss"] + rd(0x800065BD, 1) * syms["BANKSZ"] + rd(ACT, 1) * PATSTRIDE, 1)
                u.mem_write(psad, bytes([pre_p0 ^ 0x81]))
            if CL41:                          # [BANK] first (the other order than r's): the chord's grid and the view
                vb_, pb_ = rd(syms["cl_bank"], 1), rd(0x800065BD, 1)    # before the [YES], the view moves at it
                key(0x2F, 1); key(0x2E, 1)
                g_, want_ = grid(), pgrid(vb_)
                qcheck(g_ == want_ and rd(syms["cl_bank"], 1) == vb_,
                       f"#{i} P: the chord held: the view stays on {chr(65 + vb_)} (playing {chr(65 + pb_)}), its grid = "
                       f"bank {chr(65 + vb_)}'s pattern view {want_} ({g_})")
                key(0x31, 1); key(0x31, 0); key(0x2E, 0); key(0x2F, 0)
            else:
                key(0x2E, 1); key(0x2F, 1); key(0x31, 1); key(0x31, 0); key(0x2F, 0); key(0x2E, 0)
            if CL40:
                mine = (rd(0x800065BD, 1) << 8) | rd(ACT, 1)
                vw_ = (vb_ if CL41 else mine >> 8) if CL42 else mine >> 8
                qcheck(rd(syms["cl_flk"], 1) > 0 and rd(syms["cl_fcode"], 2) == mine and rd(syms["cl_ftgt"], 1) == 0
                       and rd(syms["cl_bank"], 1) == vw_,
                       f"#{i} P: ORIG PTN+PRT's confirmation flash on its slot {mine:#06x} (drawn only with its bank shown), "
                       f"the view on {chr(65 + vw_)} ({'CL42: it stays' if CL42 else 'its bank'})")
            settle(3000)
            if CL42:
                qcheck(rd(psad, 1) == pre_p0, f"#{i} P: the playing pattern's originals restored (T1's edited byte "
                       f"{rd(psad, 1):#04x}, as loaded {pre_p0:#04x})")
            print(f"#{i} P: cur {rd(syms['cl_cur'], 1) + 1} shown {rd(syms['cl_pmoved'], 1)} "
                  f"sbank {rd(syms['cl_sbank'], 1)}", flush=True)
            continue
        if op[0] == "K" and op[1:].isdigit():  # CL41: TRACK N -- the view stays; the track's arrows (if any) in it
            t_, vb_ = int(op[1:]) - 1, rd(syms["cl_bank"], 1)
            key(0x10 + t_, 1); key(0x10 + t_, 0)
            settle(200)
            pm_, sb_ = rd(syms["cl_pmoved"], 1), rd(syms["cl_sbank"], 1)
            qcheck(rd(0x80000000, 1) == t_ and rd(syms["cl_bank"], 1) == vb_ and (not pm_ or sb_ == vb_),
                   f"#{i} {op}: track {t_ + 1}; the view stays on {chr(65 + vb_)} (now {chr(65 + rd(syms['cl_bank'], 1))}); "
                   f"{view()}")
            continue
        if op == "Ru":                        # CL42: [PTN] + the active TRACK on an UNEDITED track: the card's copy is
            t_ = rd(0x80000000, 1)            # what plays -- the job runs, nothing lands, no toast (cl_cueload's same
            g0, nl0, nt0 = rd(syms["rq_gen"], 1), len(lands), len(toasts)   # test; cl_rqarm1 "nothing to land")
            key(0x2E, 1); key(0x10 + t_, 1); key(0x10 + t_, 0); key(0x2E, 0)
            g = 0
            while (rd(syms["rq_busy"], 1) or rd(syms["rq_jgen"], 1) != rd(syms["rq_gen"], 1) or g < 20) and g < 120:
                settle(34)
                g += 1
            settle(600)
            qcheck(rd(syms["rq_gen"], 1) != g0 and rd(syms["rq_busy"], 1) == 0 and len(lands) == nl0
                   and len(toasts) == nt0,
                   f"#{i} Ru: unedited T{t_ + 1}: request {g0} -> {rd(syms['rq_gen'], 1)}, job done; "
                   f"{len(lands) - nl0} landing(s), {len(toasts) - nt0} toast(s) (by design: none)")
            continue
        if op[0] == "R" and (len(op) == 1 or op[1] in "Bh0123456789"):   # CL41 / CL42: a card TRACK reload
            # R[B][h][N]: [PTN] (B: [BANK], the FULL form) + TRACK N (1-8; default the active one); h = hold the
            # modifier 600 ms first (UI ticks run: its hold events, as a hand does). CL42 checks the real effect: an
            # in-RAM edit of the track's record (and, FULL on T1, its machine slice) undone by the card, the toast
            # (cl_toast2 called, line 1 TRK SEQ / TRK FULL), a SRC_CARD landing on that track, the view staying.
            rest = op[1:]
            full_ = rest.startswith("B")
            rest = rest[1:] if full_ else rest
            hold_ = rest.startswith("h")
            rest = rest[1:] if hold_ else rest
            t_ = int(rest) - 1 if rest else rd(0x80000000, 1)
            vb_, g0, nl0, nr0, nt0 = rd(syms["cl_bank"], 1), rd(syms["rq_gen"], 1), len(lands), len(reqs), len(toasts)
            pb_, pp_ = rd(0x800065BD, 1), rd(ACT, 1)
            sad = BLOB + pb_ * BANKSTRIDE + pp_ * PATSTRIDE + t_ * TRAC_A
            pad = BLOB + pb_ * BANKSTRIDE + 0x8ED80 + (rd(BLOB + pb_ * BANKSTRIDE + pp_ * PATSTRIDE + 0x8E57, 1) & 3) * 0x18B2
            pre_r, pre_m = rd(sad, 1), rd(pad + 0x2A, 1)
            u.mem_write(sad, bytes([pre_r ^ 0x81]))
            if full_ and t_ == 0:
                u.mem_write(pad + 0x2A, bytes([pre_m ^ 0x55]))
            mk_ = 0x2F if full_ else 0x2E
            key(mk_, 1)
            if hold_:                         # held 600 ms (SET_KEY takes press / release only; stock's [PTN]
                settle(600)                   # hold event only sets the tap flag 0x460d1ab2, 0x4005a0cc)
            key(0x10 + t_, 1); key(0x10 + t_, 0); key(mk_, 0)
            g = 0
            while (len(lands) == nl0 or rd(syms["rq_busy"], 1)) and g < 240:
                settle(34)
                g += 1
            settle(300)
            print(f"      #{i} {opx}: waited {g} x 34 ms", flush=True)
            line1 = bytes(u.mem_read(syms['rq_line1'], 12)).split(b'\0')[0].decode()
            cards = [x for x in reqs[nr0:] if x[1] == t_ and (x[2] >> 8) & 0xFF == 0xFC]
            qcheck(rd(syms["rq_gen"], 1) != g0 and cards and len(lands) > nl0 and rd(syms["rq_busy"], 1) == 0,
                   f"#{i} {opx}: T{t_ + 1}'s card {'FULL' if full_ else 'SEQ'} reload: a request (generation {g0} -> "
                   f"{rd(syms['rq_gen'], 1)}), {len(cards)} SRC_CARD load(s) on T{t_ + 1}, {len(lands) - nl0} landing(s), "
                   f"the job done")
            qcheck(len(toasts) > nt0 and line1 == ("TRK FULL" if full_ else "TRK SEQ"),
                   f"#{i} {opx}: its toast ({len(toasts) - nt0} shown, line 1 {line1!r})")
            want_r = rd(syms["RQ_SLAB"] + t_ * TRAC_A, 1)    # the card's staged copy (--bankb: B is A's copy in RAM;
            qcheck(rd(sad, 1) == want_r and rd(sad, 1) != pre_r ^ 0x81      # after a slot load: another sequence)
                   and (not (full_ and t_ == 0) or a.bankb or rd(pad + 0x2A, 1) == pre_m),
                   f"#{i} {opx}: the in-RAM edit undone by the card's copy (record byte {rd(sad, 1):#04x} want {want_r:#04x}"
                   + (f", machine byte {rd(pad + 0x2A, 1):#04x} want {pre_m:#04x}" if full_ and t_ == 0 else "") + ")")
            qcheck(rd(syms["cl_open"], 1) == 1 and rd(syms["cl_bank"], 1) == vb_ and rd(syms["cl_boxreq"], 1) == 0,
                   f"#{i} {opx}: the view stays on {chr(65 + vb_)} (now {chr(65 + rd(syms['cl_bank'], 1))}); {view()}")
            continue
        if op in ("a+", "a-") or (op[0] == "a" and op[1:-1].isdigit() and op[-1] in "+-"):
            # CL42 (the user's arrow rule): a+ / a- = the active track's arrows shown / hidden -- the state
            # (cl_pmoved and not hidden) AND the window as drawn now (cd_arrows calls in one cl_draw); aN+ / aN- =
            # track N's record (shown = 0x8000 without 0x4000). The trig LED under shown arrows is yellow (except the
            # pattern you are on, CL34 option b).
            want_ = op[-1] == "+"
            if len(op) == 2:
                main_call(syms["cl_draw"])
                tk_ = main_call(syms["cl_tuck"]) & 0xFF
                sh_ = bool(rd(syms["cl_pmoved"], 1)) and not tk_ and rd(syms["cl_sbank"], 1) == rd(syms["cl_bank"], 1)
                qcheck(sh_ == want_ and (arw["n"] == 1) == want_,
                       f"#{i} {op}: the arrows {'shown' if want_ else 'hidden'} (state {sh_}, drawn {arw['n']}); {view()}")
            else:
                t_ = int(op[1:-1]) - 1
                rec_ = rd(syms["cl_pre"] + 2 * t_, 2)
                qcheck(((rec_ & 0xC000) == 0x8000) == want_,
                       f"#{i} {op}: T{t_ + 1}'s arrows {'shown' if want_ else 'hidden'} in its record ({rec_:#06x})")
            continue
        if op == "H":                         # CL42: [PTN] alone held -- the header "PTN LOAD: CURR PTN+PRT" (drawn by
            h0 = list(hdr)                    # the UI tail, the sys task), back as before on its release
            key(0x2E, 1)
            settle(100)                       # the tail runs in the sys task: let it
            h1 = list(hdr)
            key(0x2E, 0)
            settle(100)
            h2 = list(hdr)
            qcheck(h1[:2] == ["PTN LOAD:", "CURR PTN+PRT"] and h2 == h0 and rd(syms["cl_hdrst"], 1) == 0,
                   f"#{i} H: [PTN] held: header {h1}; released: {h2} (before {h0})")
            continue
        if op == "Z":                         # CL42: the next card job fails at its open (a never-saved bank, -12)
            zfail["n"] = 1
            continue
        if op == "Zc":                        # ... and afterwards: it did fail, and nothing of it is left busy
            qcheck(zfail["hit"] == 1 and rd(syms["rq_busy"], 1) == 0,
                   f"#{i} Zc: the injected failure hit {zfail['hit']} job(s); busy after it {rd(syms['rq_busy'], 1)}")
            continue
        if op == "^":                         # CL42: one UP arrow
            key(0x33, 1); key(0x33, 0)
            settle(300)
            print(f"#{i} ^: cur {rd(syms['cl_cur'], 1) + 1} shown {rd(syms['cl_pmoved'], 1)}", flush=True)
            continue
        if op == "Y0":                        # CL42: a bare [YES] with nothing to aim at on screen: loads nothing
            nr_ = len(reqs)
            key(0x31, 1); key(0x31, 0)
            settle(600)
            qcheck(len(reqs) == nr_, f"#{i} Y0: [YES] with no arrows shown and none under the box: {len(reqs) - nr_} "
                   f"request(s); {view()}")
            continue
        if op == "N":                         # CL42: [NO] -- close Clyps (the stock screen)
            key(0x32, 1); key(0x32, 0)
            settle(200)
            print(f"#{i} N: Clyps open {rd(syms['cl_open'], 1)}", flush=True)
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
    print(f"CL39b: cl_draw entered inside the UI tick (cl_uitick), in its own task, {tkst['draws']} time(s) -- on the "
          f"unit the UI task (prio 3) drawing over the sys task; meanwhile in another task {tkst['other']}", flush=True)
    if "dp_post" in syms:
        nt = tkst.get("calls", 0)           # the unit's UI tick: 60 per second
        print(f"CL39c: cl_dpost posted {posts['n']} sys message(s) in {nt} UI ticks: {posts['n'] / max(nt, 1):.3f} per "
              f"tick = {60 * posts['n'] / max(nt, 1):.1f} per second at the unit's 60 ticks / s", flush=True)
    if "cd_boxed" in syms:
        print(f"CL40: arrow sets per window draw, at most {arw['max']}; draws with two or more: {arw['bad']}", flush=True)
        qcheck(arw["bad"] == 0, "CL40: at most one set of arrows in the window, every draw")
    if "cl_dreq" in syms:
        qcheck(tkst["draws"] == 0, "CL39b: no cl_draw from the UI tick (the redraws go to the sys task's tail)")
    if fails:
        print(f"CL39 checks: {len(fails)} FAIL", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

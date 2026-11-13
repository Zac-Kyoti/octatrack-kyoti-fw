#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT -- the REF-LOCK oracle applied to its landings, recorder half (2026-11-13: Clyps' landing
rules ported, reference/handoffs/RELOAD_CLYPS_PORT.md). Clyps' tools/diag_clyps_lock.py (trkseq), itself DIRECT
JUMP V7's tools/diag_reflock.py + tools/model_reflock.py, with RELOAD's gestures.

Runs the real OT DEMO export. --cpoke edits the pattern IN RAM before SAVE PROJECT (what the CARD holds), --lpoke
after it (what PLAYS until a reload), both stock-style: the pattern blob's own bytes. Then PLAY and --ops: each op a
RELOAD gesture (or a live edit that makes the next reload change something) at a chosen time. Records, per tick
(phase-G entry 0x400a3fdc, t = 1 on the first running tick -- model_reflock's sample point): master step / tick /
scale, every track's STEP / TICKS / TRK_SCALE (+ --cond: the A:B pass counters); every audio builder call (tick,
track, step) and fire (ahead); every landing that fires a track (rl_ffland: tick, track) and every wrap / stopped
landing; every arming of a reload (rl_arm 0 -> non-zero: the tracks pending, the kind); the purges (rl_tpurge,
before / after); every engine apply (TRK_APPLY, the whole-Part apply, PICKUP, the restart byte) and every publish
armed (rl_pubt); the slab's per-track length / scale and the master's after every op. tools/check_reload_lock.py
grades it against DIRECT JUMP's position model; tools/check_reload_full.py the FULL publishes.

  python3 tools/diag_reload_lock.py --image IMG --elf ELF --project DIR --name N --out out/rlcp/lock/N.json \
      [--cond] [--cpoke OFF=VAL[:SIZE] ...] [--lpoke OFF=VAL[:SIZE] ...] [--ops x0,s0,...] [--start P]
  ops (track t 0-based): sT = [PTN] + [TRACK t+1] (SEQ), fT = [BANK] + [TRACK t+1] (FULL), p = [PTN] + [BANK] +
       trig of the playing pattern (the whole pattern in place), xT = flip T's first trig-mask byte (a live edit),
       X = STOP, then PLAY again (the graders re-base the model on the restart),
       WT = a FULL reload of audio T forced to land in the wrap body (diag_reload_quant.py's W; the model is off
       around it: the master length is cut for one cycle),
       yT = flip audio T's machine page 1 byte in the playing Part (a live slice edit), w = wait 1 s;
       a suffix @mK waits for master step K first (0 = the cycle's last audible step), @kN waits N ms; without
       one, an irregular delay walks the press through every tick of a step.
"""
import argparse, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY, SAVE_PROJECT = 0x40031734, 0x40022850
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A, TRAC_M = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A, 0x8B0
PART_OFF, PARTSZ = 0x8ED80, 0x18B2
ACT, RUNNING, MSTEP, TICK_CTR, SCALE_IX = 0x800065BE, 0x800065B8, 0x800065B2, 0x800065B6, 0x8000663D
STEP_ARR, TICKS_ARR, TSCALE_ARR = 0x800064D0, 0x800064F0, 0x8000663E
TICK_PC = 0x400A3FDC
BUILDER_A, BUILDER_A_RET = 0x4009D1E8, 0x400A2D82
FIRE_STORE = 0x400A2E18          # audio fire time store: d0 = time, a1 = track + slot*8, d7 = ahead * 0x285ff0
SCLK = 0x4610757C
PTN, BANK = 0x2E, 0x2F


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--elf", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dj-mode-at", type=lambda x: int(x, 0), default=None,
                    help="DIRECT JUMP KYOTI's DJ_MODE (a KYOTI image): turned ON for the run")
    ap.add_argument("--cpoke", action="append", default=[])
    ap.add_argument("--lpoke", action="append", default=[])
    ap.add_argument("--ops", default="x0,s0")
    ap.add_argument("--start", type=int, default=None, help="the pattern to play (0-based), default: as loaded")
    ap.add_argument("--stride", type=int, default=29)
    ap.add_argument("--tail", type=int, default=800, help="ms after the last landing")
    ap.add_argument("--cond", action="store_true", help="also record the trig-condition counters per tick")
    a = ap.parse_args(argv)
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_reload_lock_{a.name}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def main_call(addr, *args):
        # emu_rtos's call_as_main leaves the arguments on main's stack: restore main's SP (Clyps' gates)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=600000)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)
        return r_

    def key(code, ev, ms=40):
        if ev and 0x10 <= code <= 0x17:
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))     # no double tap (as diag_clyps_ui.py)
        main_call(SET_KEY, code, ev)
        if ms:
            rt.run(ms=ms)

    def settle(ms, every=34):
        # route A runs no UI tick (task 0x40056c40's 1/60 s message, where rl_uitick sits): call the patched
        # site as one tick does
        for _ in range(max(1, ms // every)):
            rt.run(ms=every)
            main_call(0x40056C28)

    if rd(0x80000012, 4):
        key(0x35, 1); key(0x35, 0)
    bb = BLOB + bank * BANKSTRIDE
    act = rd(ACT, 1) if a.start is None else a.start
    slab_ad = bb + act * PATSTRIDE
    link = lambda: rd(slab_ad + 0x8E57, 1) & 3

    def poke(specs, what):
        for spec in specs:                      # OFF=VAL[:SIZE], the playing pattern
            lhs, rhs = spec.split("=")
            val, _, sz = rhs.partition(":")
            n = int(sz or 1)
            u.mem_write(slab_ad + int(lhs, 0), (int(val, 0) & ((1 << (8 * n)) - 1)).to_bytes(n, "big"))
            print(f"{what} poke pattern {act + 1} +{int(lhs, 0):#x} = {int(val, 0):#x} ({n} B)", flush=True)
    poke(a.cpoke, "card")
    main_call(SAVE_PROJECT)
    rt.run(ms=8000)                             # the card = RAM now
    poke(a.lpoke, "live")

    def params(p):
        base = bb + p * PATSTRIDE
        tr = bytes(u.mem_read(base + 0x8E50, 8))
        trk = [(rd(base + t * TRAC_A + 0x50, 1), rd(base + t * TRAC_A + 0x51, 1), rd(base + t * TRAC_A + 0x54, 1))
               for t in range(8)]
        return dict(mlen=int.from_bytes(tr[0:2], "big"), mscale=tr[2], len=tr[3], scale=tr[4], mode=tr[5],
                    chain=tr[6], trk=trk)

    st = dict(tick=0, q=0)
    states, builds, lands, reqs, snaps, fires, pubs, restarts = [], [], [], [], [], [], [], []

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

    def rec_mask(t):
        if t < 8:
            return bytes(u.mem_read(slab_ad + t * TRAC_A, 8)).hex()
        return bytes(u.mem_read(slab_ad + 0x48D0 + (t - 8) * TRAC_M, 8)).hex()

    def on_ffland(uc, ad, sz, ud):            # a tick landing that fires the track (rl_ffland, d6 = t)
        st["q"] += 1
        t = uc.reg_read(er.eb.UC_M68K_REG_D6)
        lands.append([st["tick"], t, "tick", rd(MSTEP, 2), rd(TICK_CTR, 1), st["q"], rec_mask(t)])

    def on_landall(uc, ad, sz, ud):           # data-only landings: the wrap body, stopped, the target gone
        ctx = st.get("ctx")
        if ctx in ("wrap", "now"):
            m = 0xFFFF if rd(syms["rl_lp"], 1) else rd(syms["rl_lm"], 2)
            st["q"] += 1
            for t in range(16):
                if m >> t & 1:
                    lands.append([st["tick"], t, ctx, rd(MSTEP, 2), rd(TICK_CTR, 1), st["q"], rec_mask(t)])

    def on_wrapin(uc, ad, sz, ud):
        st["ctx"] = "wrap"

    def on_tickin(uc, ad, sz, ud):
        st["ctx"] = "tick"

    def on_uitick(uc, ad, sz, ud):
        st["ctx"] = "now"

    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    u.hook_add(er.eb.UC_HOOK_CODE, on_build, begin=BUILDER_A, end=BUILDER_A)
    u.hook_add(er.eb.UC_HOOK_CODE, on_fire, begin=FIRE_STORE, end=FIRE_STORE)
    u.hook_add(er.eb.UC_HOOK_CODE, on_ffland, begin=syms["rl_ffland"], end=syms["rl_ffland"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_landall, begin=syms["rl_landall"], end=syms["rl_landall"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_wrapin, begin=syms["rl_wrap"], end=syms["rl_wrap"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_tickin, begin=syms["rl_tick"], end=syms["rl_tick"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_uitick, begin=syms["rl_uitick"], end=syms["rl_uitick"])

    # the request = the moment a reload is armed for the tick (rl_arm 0 -> 1): rl_stdone or a chord of a staged
    # generation. Polled after every write to rl_arm (the write hook fires before the store).
    arm = {"was": 0}

    def on_arm_w(uc, acc, ad, sz, val, ud):
        v = val & 0xFF
        if v and not arm["was"]:
            lp = rd(syms["rl_lp"], 1)
            m = 0xFFFF if lp else rd(syms["rl_lm"], 2)
            f = rd(syms["rl_lf"], 2)
            st["q"] += 1
            for t in range(16):
                if m >> t & 1:
                    code = (0x20000 if lp else 0) | (0x10000 if (f >> t & 1) else 0)
                    reqs.append([st["tick"], t, code, 1, rd(MSTEP, 2), rd(TICK_CTR, 1), st["q"]])
        arm["was"] = v
    u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_arm_w, begin=syms["rl_arm"], end=syms["rl_arm"])

    applies = []         # every engine-facing apply, its tick (what changes the SOUND, and when)
    for name, ad in (("TRK_APPLY", 0x40001F18), ("PART_APPLY", 0x40009094), ("PICKUP_SET", 0x40097290),
                     ("rl_pubt", syms.get("rl_pubt")), ("rl_slice", syms.get("rl_slice"))):
        if ad:
            def mk(nm_):
                def f(uc, a_, sz, ud):
                    s_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
                    if nm_ == "rl_pubt":          # d0 = t, rl_defer: 0 now, 1 armed, 2 none
                        args = [uc.reg_read(er.eb.UC_M68K_REG_D0), rd(syms["rl_defer"], 1), 0]
                    else:
                        args = [rd(s_ + 4 * k, 4) for k in (1, 2, 3)]
                    applies.append([st["tick"], nm_, args, rd(SCLK, 4), st["q"]])
                return f
            u.hook_add(er.eb.UC_HOOK_CODE, mk(name), begin=ad, end=ad)
    u.hook_add(er.eb.UC_HOOK_MEM_WRITE, lambda uc, acc, ad, sz, val, ud: applies.append(
        [st["tick"], "ENG_RESTART", [val & 0xFF], rd(SCLK, 4), st["q"]]), begin=0x8000184C, end=0x8000184C)
    cresets = []         # every COND_RESET call: (tick, argument, return address, rl_T, rl_Tres before)
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: cresets.append(
        [st["tick"], rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4), rd(uc.reg_read(er.eb.UC_M68K_REG_A7), 4),
         rd(syms["rl_T"], 4), rd(syms["rl_Tres"], 4)]), begin=0x400A539C, end=0x400A539C)
    purges = []          # (tick, track, the slot mask before / after rl_tpurge, the pending fire times - now)
    pst = {}

    def on_pin(uc, ad, sz, ud):
        t = uc.reg_read(er.eb.UC_M68K_REG_D6)
        mk_ = 0x46C7FE44 + t if t < 8 else 0x46C77BE2 + t - 8
        pst["t"], pst["mk"], pst["b"] = t, mk_, rd(mk_, 1)
        if t < 8:       # the pending events' fire times against the sample clock (the purge's margin)
            now = rd(SCLK, 4)
            pst["dt"] = [((rd(0x80001904 + 4 * (t + 8 * k), 4) - now + (1 << 31)) % (1 << 32)) - (1 << 31)
                         for k in range(3) if pst["b"] >> k & 1]

    def on_pout(uc, ad, sz, ud):
        purges.append([st["tick"], pst["t"], pst["b"], rd(pst["mk"], 1), pst.get("dt")])
    u.hook_add(er.eb.UC_HOOK_CODE, on_pin, begin=syms["rl_tpurge"], end=syms["rl_tpurge"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_pout, begin=syms["pu2_out"], end=syms["pu2_out"])
    if a.dj_mode_at is not None:
        u.mem_write(a.dj_mode_at, (1).to_bytes(4, "big"))
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
    print(f"running {rd(RUNNING, 4)}, DJ {a.dj_mode_at is not None}", flush=True)
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
        elif op[0] in "sfp":
            rt.run(ms=150 + (i * a.stride) % 400)
        nl = len(lands)
        if op == "w":
            settle(1000)
            continue
        if op == "X":                          # STOP (stock's COND_RESET(-1) at 0x400a12b8), then PLAY again
            t_stop = st["tick"]                # (Clyps' diag_clyps_lock.py op x, CL33)
            key(0x27, 1); key(0x27, 0)
            settle(600)
            stopped = rd(RUNNING, 4)
            t_play = st["tick"]
            rt.press_play_live()               # PLAY's own handler (0x4000a200), then the eight tracks
            settle(100)
            how = "PLAY's handler"
            if not rd(RUNNING, 4):             # route A: PLAY's handler alone left the transport stopped
                rt.start_transport_live()      # (measured 2026-11-13) -- FW_TRANSPORT(0) as at the run's start
                how = "PLAY's handler, then start_transport_live"
            settle(200)
            restarts.append([t_stop, t_play])
            print(f"#{i} X: stopped ({stopped}) at tick {t_stop}, PLAY at {t_play} ({how}), running {rd(RUNNING, 4)}; "
                  f"COND_RESET calls since: {[c for c in cresets if c[0] >= t_stop]}; rl_T {rd(syms['rl_T'], 4)} "
                  f"rl_Tres {rd(syms['rl_Tres'], 4)}", flush=True)
            continue
        if op[0] == "x":                       # a live edit of T's trigs: the next reload brings them back
            t = int(op[1:])
            ad = slab_ad + (t * TRAC_A if t < 8 else 0x48D0 + (t - 8) * TRAC_M) + 7
            u.mem_write(ad, bytes([rd(ad, 1) ^ 0x10]))
            continue
        if op[0] == "y":                       # a live edit of audio T's slice (machine page 1, first byte)
            t = int(op[1:])
            ad = bb + PART_OFF + link() * PARTSZ + 0x2A + 30 * t
            u.mem_write(ad, bytes([rd(ad, 1) ^ 0x55]))
            continue
        if op[0] == "W":                       # a FULL reload of audio T landing in the WRAP BODY (diag_reload_quant's W):
            t = int(op[1:])                    # hidden from the tick once armed, the master cut to wrap 2 steps
            hide = {"on": True, "caught": False, "force": False}   # away, re-armed at rl_wrap's entry

            def on_hide(uc, ad, sz, ud):
                if hide["on"] and uc.mem_read(syms["rl_arm"], 1) == b"\x01":
                    uc.mem_write(syms["rl_arm"], b"\x00")
                    arm["was"] = 1
                    hide["caught"] = True

            def on_force(uc, ad, sz, ud):
                if hide["force"]:
                    hide["force"] = False
                    hide["on"] = False
                    uc.mem_write(syms["rl_arm"], b"\x01")
            hh = u.hook_add(er.eb.UC_HOOK_CODE, on_hide, begin=syms["rl_tick"], end=syms["rl_tick"])
            hw = u.hook_add(er.eb.UC_HOOK_CODE, on_force, begin=syms["rl_wrap"], end=syms["rl_wrap"])
            ad = bb + PART_OFF + link() * PARTSZ + 0x2A + 30 * t
            u.mem_write(ad, bytes([rd(ad, 1) ^ 0x55]))
            key(BANK, 1); key(0x10 + t, 1); key(0x10 + t, 0); key(BANK, 0)
            g = 0
            while not hide["caught"] and g < 400:
                rt.run(ms=20)
                g += 1
            ml = rd(slab_ad + 0x8E50, 2)
            u.mem_write(slab_ad + 0x8E50, (rd(MSTEP, 2) + 2).to_bytes(2, "big"))
            hide["force"] = True
            settle(1500)
            u.hook_del(hh)
            u.hook_del(hw)
            u.mem_write(slab_ad + 0x8E50, ml.to_bytes(2, "big"))
            print(f"#{i} {opx}: armed {hide['caught']}, master cut to wrap, length back to {ml}", flush=True)
            snaps.append([st["tick"], params(act)])
            continue
        if op[0] == "s":
            t = int(op[1:])
            key(PTN, 1); key(0x10 + t, 1); key(0x10 + t, 0); key(PTN, 0)
        elif op[0] == "f":
            t = int(op[1:])
            key(BANK, 1); key(0x10 + t, 1); key(0x10 + t, 0); key(BANK, 0)
        elif op == "p":
            key(PTN, 1); key(BANK, 1); key(act, 1); key(act, 0); key(BANK, 0); key(PTN, 0)
        g = 0
        while len(lands) == nl and g < 300:
            settle(68)
            g += 1
        settle(300)
        snaps.append([st["tick"], params(act)])
        l = lands[-1] if len(lands) > nl else None
        print(f"#{i} {opx}: requests {[x[:6] for x in reqs if x[0] >= (l[0] - 400 if l else 0)][-2:]} landing "
              f"{l[:6] if l else None} ({len(lands) - nl} track(s))", flush=True)
    settle(a.tail)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(meta=dict(name=a.name, dj=a.dj_mode_at is not None, chain=None,
                                             pokes=dict(card=a.cpoke, live=a.lpoke), ops=a.ops, pattern=act,
                                             bank=bank),
                                   states=states, builds=builds, fires=fires, lands=lands, reqs=reqs, snaps=snaps,
                                   purges=purges, applies=applies, restarts=restarts,
                                   cresets=cresets)))
    print(f"wrote {out}: ticks {st['tick']}, landings {len(lands)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

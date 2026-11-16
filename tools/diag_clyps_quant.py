#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- card reloads and ORIG restores land in place (emulator; the user, 2026-11-08 / 09; modelled on
RELOAD_FROM_PROJECT's tools/diag_reload_quant.py). With the transport RUNNING, inside Clyps, on a project
that loads on the audio side (OT DEMO), from pattern 1:

  A  SAVE PROJECT, PLAY, open Clyps.
  B  [PTN] + [TRACK 1] (T1 edited): lands in the tick (cl_land), at a step start of T1, its counters as stock
     had them; T1 = the card's; the toast after the landing; nothing left pending.
  C  [BANK] + [TRACK 1] (T1 + its slice + T2's slice edited): T1's slice published in that tick; T2 untouched.
  D  [PTN] + [BANK] + trig 1 (the playing pattern; T1 T2 T5 + the Part edited): one tick, a step start of all;
     every changed track's slice in it; the whole pattern + Part = the card's; still on pattern 1.
  E  NORMAL: the pattern length edited, [PTN] + [TRACK 1]: lands with every track and the master re-phased
     (master step = (t0 / tps) mod len + 1), the length back. PER TRACK: the master length edited, the pattern
     reloaded: the same re-phase.
  G  [PTN] + [TRACK 1] then [TRACK 2]: both land. H  SEQ then FULL of T1: FULL wins (the slice back).
  P  the trig of the pattern you are on (ORIG SEQ, T1 edited; [PAGE] until CL28): in place -- at T1's next
     step, in the tick, not at the CHAIN AFTER point.
  O  [PTN] + [BANK] + [YES] (ORIG PTN+PRT; + [PAGE] until CL28, T1 T3 + the Part edited): together, in the tick; as loaded; no
     stock pattern switch.
  M  a group T1 T2, T1's arrows on its own slot (a restore), T2's on another (a load): [YES] lands both at the
     cued point (CHAIN AFTER 4 steps), not T1 earlier.
  I  on P1, [PTN] + [BANK] + trig P2, then trig P1 300 / 1500 ms later: P2 never plays.
  F  STOP, [PTN] + [TRACK 1]: at once.

  CLYPS_SYMS=out/clyps/kyoti_clNN_syms.txt python3 tools/diag_clyps_quant.py --image IMG --project DIR --name N [--dj]
"""
import argparse, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY, SAVE_PROJECT, TRK_APPLY = 0x40031734, 0x40022850, 0x40001F18
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
PART_OFF, PARTSZ = 0x8ED80, 0x18B2
ACT, RUNNING, MSTEP, TICK_CTR, SCALE_IX = 0x800065BE, 0x800065B8, 0x800065B2, 0x800065B6, 0x8000663D
STEP_ARR, STEPM1_ARR, TICKS_ARR, TSCALE_ARR, LEN_TBL = 0x800064D0, 0x800064E0, 0x800064F0, 0x8000663E, 0x400ABA50
PTN, BANK, YES, NO, PAGE, CUE, UP, DOWN = 0x2E, 0x2F, 0x31, 0x32, 0x1B, 0x2A, 0x33, 0x20
NOSER = {0x899 + k * TRAC_A for k in range(8)} | set(range(0x8E5C, PATSTRIDE))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--dj", action="store_true", help="DIRECT JUMP on for the run (a KYOTI image)")
    ap.add_argument("--only", default="BCDEKGHPOMIF")
    a = ap.parse_args(argv)
    sp = os.environ.get("CLYPS_SYMS", str(ROOT / "out/clyps_syms.txt"))
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(sp).read_text().splitlines())}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_clyps_quant_{a.name}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    fails = []

    def check(ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            fails.append(what)

    def main_call(addr, *args):
        # emu_rtos's call_as_main leaves the arguments on main's stack (it pops only the return address):
        # 8 bytes per 2-argument call. This gate posts a UI-tail message every ~17 ms, so after a few
        # seconds main's stack had grown into its own TCB and the emulator crashed in the scheduler
        # (2026-11-09, found with CLYPS_TCBWATCH). Restore main's SP after every borrowed call.
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=600000)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)
        return r_

    def tail():
        u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
        main_call(er.KERNEL_POST, er.SYS_QUEUE, er.SYS_MSG_SCRATCH)

    def key(code, ev, ms=40):
        if ev and 0x10 <= code <= 0x17:
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))     # no double tap (as diag_clyps_ui.py)
        main_call(SET_KEY, code, ev)
        tail()
        rt.run(ms=ms)

    def tap(code):
        key(code, 1)
        key(code, 0)

    def settle(ms):
        # route A runs no UI tick (cl_uitick, 0x40056c28) nor a UI pass of its own: call / post them
        for _ in range(max(1, ms // 17)):
            rt.run(ms=17)
            main_call(0x40056C28)
            tail()

    if rd(0x80000012, 4):
        tap(0x35)
    tap(0x10)
    bb = BLOB + bank * BANKSTRIDE
    act = rd(ACT, 1)
    slab_ad = bb + act * PATSTRIDE
    slab = lambda: bytes(u.mem_read(slab_ad, PATSTRIDE))
    rec = lambda t: bytes(u.mem_read(slab_ad + t * TRAC_A, TRAC_A))
    link = lambda: rd(slab_ad + 0x8E57, 1) & 3
    part = lambda: bytes(u.mem_read(bb + PART_OFF + link() * PARTSZ, PARTSZ))
    same_rec = lambda x, y: all(x[i] == y[i] for i in range(TRAC_A) if i != 0x899)
    same_slab = lambda x, y: all(x[i] == y[i] for i in range(PATSTRIDE) if i not in NOSER)
    flip = lambda ad, m: u.mem_write(ad, bytes([rd(ad, 1) ^ m]))
    tps = lambda sc: rd(LEN_TBL + 4 * (sc if sc <= 6 else 2), 4)
    mode = rd(slab_ad + 0x8E55, 1)
    print(f"bank {bank + 1} pattern {act + 1} Part {link() + 1}; mode {'PER TRACK' if mode else 'NORMAL'}, "
          f"length {rd(slab_ad + 0x8E53, 1)}, master len {rd(slab_ad + 0x8E50, 2)}", flush=True)
    print("A: SAVE PROJECT, PLAY, open Clyps", flush=True)
    main_call(SAVE_PROJECT)
    rt.run(ms=8000)
    card_slab, card_part = slab(), part()
    orig_slab, orig_part = slab(), part()           # the project was loaded = saved: originals = card

    events = []
    st = {"ctx": None, "applies": 0}

    def snap(where):
        return dict(where=where, ms=rd(MSTEP, 2), tc=rd(TICK_CTR, 1), sc=rd(SCALE_IX, 1),
                    step=list(u.mem_read(STEP_ARR, 16)), stepm1=list(u.mem_read(STEPM1_ARR, 16)),
                    ticks=list(u.mem_read(TICKS_ARR, 16)), tscale=list(u.mem_read(TSCALE_ARR, 16)))

    def on_land_in(uc, ad, sz, ud):
        if rd(syms["cl_nq"], 1):
            st["ctx"] = "tick"

    def on_wrap_in(uc, ad, sz, ud):
        if rd(syms["cl_nq"], 1):
            st["ctx"] = "wrap"

    def on_out(uc, ad, sz, ud):
        if st["ctx"]:
            events.append(dict(snap(st["ctx"] + "_out"), applies=st["applies"]))
            st["ctx"] = None

    def on_apply(uc, ad, sz, ud):
        events.append(dict(snap(st["ctx"] or "now"), t=rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4)))

    def on_trk(uc, ad, sz, ud):
        if st["ctx"]:
            st["applies"] += 1
        events.append(dict(snap("apply"), t=rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 12, 4)))

    u.hook_add(er.eb.UC_HOOK_CODE, on_land_in, begin=syms["cl_land"], end=syms["cl_land"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_out, begin=syms["la_out"], end=syms["la_out"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_wrap_in, begin=syms["cl_wrap"], end=syms["cl_wrap"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_out, begin=syms["wr_out"], end=syms["wr_out"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_apply, begin=syms["cl_apply"], end=syms["cl_apply"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_trk, begin=TRK_APPLY, end=TRK_APPLY)
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: events.append(dict(where="toast")),
               begin=syms["cl_rqtoast"], end=syms["cl_rqtoast"])
    stock_sw = {"n": 0}
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: stock_sw.__setitem__("n", stock_sw["n"] + 1),
               begin=0x400A45BA, end=0x400A45BA)               # stock's real-switch hand-off
    if a.dj and "DJ_MODE" in syms:
        u.mem_write(syms["DJ_MODE"], (1).to_bytes(4, "big"))
        print("DIRECT JUMP ON", flush=True)

    rt.seq_select_live(bank, act)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=600)
    check(rd(RUNNING, 4) == 1, "the transport runs")
    key(PTN, 1)
    key(BANK, 1)
    key(BANK, 0)
    key(PTN, 0)
    check(rd(syms["cl_open"], 1) == 1, "Clyps open")

    def gesture(keys, ms=3000):
        events.clear()
        st["applies"] = 0
        for k, ev in keys:
            key(k, ev)
        settle(ms)

    def landing(label, t_list):
        lands = [i for i, e in enumerate(events) if e["where"] in ("tick", "wrap", "now")]
        if not lands:
            check(False, f"{label}: it landed")
            return None
        i0 = lands[0]
        e = events[i0]
        e["out"] = next((x for x in events[i0:] if x["where"].endswith("_out")), None)
        e["toast_after"] = any(x["where"] == "toast" for x in events[i0:])
        e["toast_before"] = any(x["where"] == "toast" for x in events[:i0])
        e["n"] = len(lands)
        e["one_tick"] = all(events[i]["where"] == e["where"] and events[i]["ms"] == e["ms"] and
                            events[i]["tc"] == e["tc"] for i in lands)
        # CL25: a landing comes on the tick that ENDS a step (t' = t0 + 1 = 0 mod tps), stock's landing tick,
        # and fires the next step at once (until CL24: the tick after, t0 = 0 mod tps, with the look-ahead)
        t0 = (e["ms"] - 1) * tps(e["sc"]) + e["tc"] + 2     # CL26: the tick BEFORE the boundary (t' of the next)
        old_ok = all(t0 % tps(e["tscale"][t]) == 0 for t in t_list)
        print(f"      {label}: {e['n']} landing(s), first in {e['where']} at master step {e['ms']} tick {e['tc']} "
              f"(t0 {t0}); toast after it {e['toast_after']}, before {e['toast_before']}", flush=True)
        return e, t0, old_ok

    pending = lambda: rd(syms["cl_nq"], 1) == 0 and rd(syms["cl_tog"], 2) == 0

    def ftrig(t, k):
        # CL26: steps from k to t's first sample trig (the record's first 8 bytes, big-endian, bit s = step s)
        r = rec(t)
        m_ = int.from_bytes(r[0:8], "big")
        ln_ = r[0x50] if rd(slab_ad + 0x8E55, 1) else rd(slab_ad + 0x8E53, 1)
        return next((dd for dd in range(ln_) if m_ >> ((k + dd) % ln_) & 1), 0)
    pb = lambda: bb + PART_OFF + link() * PARTSZ

    ring = None
    if os.environ.get("CLYPS_RING"):               # a crash hunt: the last instructions executed
        import collections
        ring = collections.deque(maxlen=int(os.environ["CLYPS_RING"]))

    def ring_on():
        if ring is not None:
            u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: ring.append((ad, uc.reg_read(er.eb.UC_M68K_REG_A7))))
    names = sorted((v, k) for k, v in syms.items())
    import bisect

    def where(ad):
        i = bisect.bisect_right([x for x, _ in names], ad) - 1
        return f"{names[i][1]}+{ad - names[i][0]:#x}" if i >= 0 and ad - names[i][0] < 0x400 else f"{ad:#010x}"

    import atexit

    def dump():
        if ring:
            print("last instructions (pc, sp):", flush=True)
            for ad, sp in list(ring)[-120:]:
                print(f"   {ad:#010x} {where(ad):32s} sp {sp:#010x}", flush=True)
    atexit.register(dump)

    if os.environ.get("CLYPS_TCBWATCH"):       # the crash hunt: who writes a bad saved SP into a task record
        sane = lambda v: 0x40000000 <= v < 0x48000000
        def on_tcbw(uc, acc, ad, sz, val, ud):
            if sz == 4 and not sane(val & 0xFFFFFFFF):
                pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
                print(f"  !! bad SP {val & 0xFFFFFFFF:#010x} written to TCB {ad - er.TCB_A7:#010x}+0x48 by pc "
                      f"{pc:#010x} ({where(pc)}), ring tail:", flush=True)
                for ad2, sp2 in list(ring or [])[-60:]:
                    print(f"     {ad2:#010x} {where(ad2)} sp {sp2:#010x}", flush=True)
        for tcb in er.ALL_TCBS:
            u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_tcbw, begin=tcb + er.TCB_A7, end=tcb + er.TCB_A7 + 3)

        def on_disp(uc, ad, sz, ud):
            a0 = uc.reg_read(er.eb.UC_M68K_REG_A0)
            spv = rd(a0 + er.TCB_A7, 4)
            if a0 not in er.ALL_TCBS or not sane(spv):
                print(f"  !! dispatch to {a0:#010x} (a TCB: {a0 in er.ALL_TCBS}), saved SP {spv:#010x}; ready head "
                      f"{rd(0x800068D8, 4):#010x} -> {rd(rd(0x800068D8, 4), 4):#010x}", flush=True)
        u.hook_add(er.eb.UC_HOOK_CODE, on_disp, begin=0x400005A0, end=0x400005A0)

    if os.environ.get("CLYPS_STACK"):          # how deep the tick's landing goes (cl_land entry -> lowest SP)
        sk = {"sp0": None, "min": None, "max_depth": 0, "where": None}
        def on_lin(uc, ad, sz, ud):
            sk["sp0"] = sk["min"] = uc.reg_read(er.eb.UC_M68K_REG_A7)
        def on_any(uc, ad, sz, ud):
            if sk["sp0"] is not None:
                spv = uc.reg_read(er.eb.UC_M68K_REG_A7)
                if spv < sk["min"]:
                    sk["min"] = spv
                    d = sk["sp0"] - spv
                    if d > sk["max_depth"]:
                        sk["max_depth"], sk["where"] = d, (ad, where(ad), rd(syms["cl_tog"], 2))
        def on_lout(uc, ad, sz, ud):
            sk["sp0"] = None
        u.hook_add(er.eb.UC_HOOK_CODE, on_lin, begin=syms["cl_land"], end=syms["cl_land"])
        u.hook_add(er.eb.UC_HOOK_CODE, on_lout, begin=syms["la_out"], end=syms["la_out"])
        u.hook_add(er.eb.UC_HOOK_CODE, on_any)
        import atexit
        atexit.register(lambda: print(f"  STACK: deepest under cl_land {sk['max_depth']} B at {sk['where']}", flush=True))

    if "cl_rlreq" in syms:                      # what the OT plays when a card request arrives
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: print(
            f"  .. cl_rlreq: act {rd(ACT, 1)} pend {rd(0x800065C0, 1)} (master step {rd(MSTEP, 2)} tick "
            f"{rd(TICK_CTR, 1)}) kind {rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4)} pattern "
            f"{rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 8, 4)}", flush=True), begin=syms["cl_rlreq"], end=syms["cl_rlreq"])
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: print(
            f"  .. a pattern landed: act {rd(ACT, 1)} (master step {rd(MSTEP, 2)})", flush=True),
            begin=0x400A45BA, end=0x400A45BA)
    if "pk_go" in syms:                         # the cancel's stock cue (cl_ptncancel) -- when does it run?
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: print(
            f"  .. cl_ptncancel cues: act {rd(ACT, 1)} pend {rd(0x800065C0, 1)} bank {rd(0x800065BD, 1)}/"
            f"{rd(0x800065BF, 1)}", flush=True), begin=syms["pk_go"], end=syms["pk_go"])

    if "B" in a.only:
        if os.environ.get("CLYPS_RINGALL"):
            ring_on()
        print("B: [PTN] + [TRACK 1]", flush=True)
        flip(slab_ad, 0x81)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)])
        res = landing("B", [0])
        if res:
            e, t0, old_ok = res
            out = e["out"]
            check(e["where"] == "tick" and old_ok, "B: in the tick, at a step start of T1")
            if out:
                check(out["step"][0] == e["step"][0] and out["ticks"][0] == 0
                      and e["ticks"][0] == tps(e["tscale"][0]) - 2,
                      f"B: T1's step as stock had it, fired at once (step {e['step'][0]} -> {out['step'][0]}, "
                      f"ticks {e['ticks'][0]} -> {out['ticks'][0]})")
            check(e["toast_after"] and not e["toast_before"], "B: the toast after the landing, not before")
        check(same_rec(rec(0), card_slab[:TRAC_A]), "B: T1's record from the card")
        check(pending(), "B: nothing left pending")

    if "C" in a.only:
        print("C: [BANK] + [TRACK 1]", flush=True)
        p_ = pb()
        flip(slab_ad, 0x81)
        flip(p_ + 0x2A, 0x55)
        flip(p_ + 0x2A + 30, 0x55)
        e2 = bytes(u.mem_read(p_ + 0x2A + 30, 30))
        gesture([(BANK, 1), (0x10, 1), (0x10, 0), (BANK, 0)])
        res = landing("C", [0])
        if res:
            e, t0, old_ok = res
            out = e["out"]
            check(e["where"] == "tick" and old_ok, "C: in the tick, at a step start of T1")
            # the slice reaches the engine when the new sequence sounds: CL25 fires its step in the landing tick,
            # so in that tick (CL23/24: one step of T1 after, the look-ahead)
            ap = [x for x in events if x["where"] == "apply" and x["t"] == 0]
            ta = [(x["ms"] - 1) * tps(x["sc"]) + x["tc"] for x in ap]
            want = t0 + ftrig(0, out["step"][0]) * tps(out["tscale"][0]) if out else None
            print(f"      C: T1 published at t' {[x + 1 for x in ta]} (the boundary {t0}, its first trig {want})", flush=True)
            check(out is not None and [x + 1 for x in ta[:1]] == [want],
                  "C: T1's slice published on the boundary of the new sequence's first trig")
        check(same_rec(rec(0), card_slab[:TRAC_A]) and bytes(u.mem_read(p_ + 0x2A, 30)) == card_part[0x2A:0x2A + 30],
              "C: T1's record and slice from the card")
        check(bytes(u.mem_read(p_ + 0x2A + 30, 30)) == e2, "C: T2's slice untouched")
        u.mem_write(p_ + 0x2A + 30, card_part[0x2A + 30:0x2A + 60])

    if "D" in a.only:
        print("D: [PTN] + [BANK] + trig (the playing pattern)", flush=True)
        p_ = pb()
        for t in (0, 1, 4):
            flip(slab_ad + t * TRAC_A, 0x81)
        flip(p_ + 0x2A + 60, 0x55)
        sw0 = stock_sw["n"]
        print(f"      D: before -- act {rd(ACT, 1)} pend {rd(0x800065C0, 1)} rq_live {rd(syms['rq_live'], 1)} "
              f"rq_busy {rd(syms['rq_busy'], 1)} rq_kind {rd(syms['rq_kind'], 1)} spn {rd(syms['cl_spn'], 1)}", flush=True)
        ring_on()
        gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)])
        res = landing("D", list(range(16)))
        if res:
            e, t0, old_ok = res
            out = e["out"]
            check(e["where"] == "tick" and old_ok and e["one_tick"],
                  f"D: one tick, a step start of every track ({e['n']} tracks)")
            ap = [x for x in events if x["where"] == "apply"]
            late = all((x["ms"] - 1) * tps(x["sc"]) + x["tc"] + 1
                       == t0 + ftrig(x["t"], out["step"][x["t"]]) * tps(out["tscale"][x["t"]]) for x in ap) if out else False
            print(f"      D: slices published {[(x['t'], x['ms'], x['tc']) for x in ap]}", flush=True)
            check(out is not None and 1 <= len(ap) <= 8 and late,          # CL25: in the tick, at its end
                  f"D: the changed tracks' slices published on their first trig's boundary ({len(ap)})")
        check(same_slab(slab(), card_slab) and part() == card_part, "D: the whole pattern and its Part from the card")
        check(rd(ACT, 1) == act and stock_sw["n"] == sw0, "D: still on the pattern, no stock switch")
        check(pending(), "D: nothing left pending")

    if "E" in a.only:
        if mode == 0:
            print("E: NORMAL, length edited, [PTN] + [TRACK 1]", flush=True)
            ln = rd(slab_ad + 0x8E53, 1)
            u.mem_write(slab_ad + 0x8E53, bytes([ln - 1 if ln > 2 else ln + 1]))
            flip(slab_ad, 0x81)
            gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)], ms=6000)
            res = landing("E", list(range(16)))
            if res:
                e, t0, old_ok = res
                out = e["out"]
                if e["where"] == "tick" and out:
                    exp = (t0 // tps(out["sc"])) % ln          # stock's landing: the step it ends, tick tps - 1
                    check(old_ok and out["ms"] == exp and out["tc"] == tps(out["sc"]) - 2,
                          f"E: on a step start of every track, re-phased: master step {out['ms']} (expected {exp})")
                else:
                    check(e["where"] == "wrap", f"E: at the master wrap ({e['where']})")
            check(rd(slab_ad + 0x8E53, 1) == ln and same_rec(rec(0), card_slab[:TRAC_A]),
                  "E: the length and T1 from the card")
        else:
            print("E: PER TRACK, master length edited, the pattern reloaded", flush=True)
            ml = rd(slab_ad + 0x8E50, 2)
            cut = min(ml - 1, rd(MSTEP, 2) + 12)
            u.mem_write(slab_ad + 0x8E50, cut.to_bytes(2, "big"))
            flip(slab_ad, 0x81)
            gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)])
            res = landing("E", list(range(16)))
            if res:
                e, t0, old_ok = res
                out = e["out"]
                exp = (t0 // tps(e["sc"])) % ml
                check(e["where"] == "tick" and old_ok, f"E: on the next common step, master step {e['ms']}")
                check(out is not None and out["ms"] == exp and out["tc"] == tps(out["sc"]) - 2,
                      f"E: re-phased -- master step {out['ms'] if out else '?'} (expected {exp})")
            check(rd(slab_ad + 0x8E50, 2) == ml and same_slab(slab(), card_slab), "E: the pattern from the card")
        check(pending(), "E: nothing left pending")

    if "K" in a.only:
        # a pattern landing that changes the Part link (the user, 2026-11-10: as RELOAD_FROM_PROJECT): the playing
        # pattern is moved to another Part q (and the engine told, so q sounds); the card reload brings the saved
        # link back -- every track lands, a voice restarts where the card's machine differs from q's (the one that
        # SOUNDS), and stock's whole-Part apply runs once, after every slice is out
        L0 = link()
        pa = lambda i: bytes(u.mem_read(bb + PART_OFF + i * PARTSZ, PARTSZ))
        q = next((x for x in range(4) if x != L0 and any(pa(x)[0x22 + t] != card_part[0x22 + t] for t in range(8))),
                 next(x for x in range(4) if x != L0))
        mdiff = [t for t in range(8) if pa(q)[0x22 + t] != card_part[0x22 + t]]
        print(f"K: link {L0 + 1} -> Part {q + 1} (machines differ from the card's on {[t + 1 for t in mdiff]}), "
              f"then the pattern reloaded", flush=True)
        u.mem_write(slab_ad + 0x8E57, bytes([(rd(slab_ad + 0x8E57, 1) & ~3) | q]))
        main_call(0x40009094, bank, q)
        settle(300)
        restarts, papp = set(), []
        def on_rs(uc, acc, ad, sz, val, ud):
            v = val & 0xFF
            restarts.update(t for t in range(8) if v >> t & 1)
        h1 = u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_rs, begin=0x8000184C, end=0x8000184C)
        h2 = u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: papp.append((
            rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4), rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 8, 4),
            rd(syms["cl_spn"], 1))), begin=0x40009094, end=0x40009094)
        gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)])
        u.hook_del(h1)
        u.hook_del(h2)
        lands = [e for e in events if e["where"] in ("tick", "wrap", "now")]
        print(f"      K: {len(lands)} landing(s); restarts {sorted(t + 1 for t in restarts)}; whole-Part applies {papp}",
              flush=True)
        check(link() == L0 and part() == card_part, f"K: the link back to Part {L0 + 1}, its Part from the card")
        check(len(lands) == 16, f"K: every track lands on a link change ({len(lands)})")
        check(set(mdiff) <= restarts, f"K: a voice restart where the card's machine differs from the sounding Part's "
              f"({[t + 1 for t in mdiff]} in {sorted(t + 1 for t in restarts)})")
        check(len(papp) == 1 and papp[0][:2] == (bank, L0) and papp[0][2] == 0,
              "K: stock's whole-Part apply once, for the landed link, after every slice is out")
        check(pending() and rd(syms["cl_lnkp"], 1) == 0, "K: nothing left pending")

    if "G" in a.only:
        print("G: [PTN] + [TRACK 1], then [TRACK 2]", flush=True)
        flip(slab_ad, 0x81)
        flip(slab_ad + TRAC_A, 0x81)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (0x11, 1), (0x11, 0), (PTN, 0)])
        lands = [e for e in events if e["where"] in ("tick", "now", "wrap")]
        print(f"      G: {len(lands)} landing(s): {[(e['where'], e['ms'], e['tc']) for e in lands]}", flush=True)
        check(same_rec(rec(0), card_slab[:TRAC_A]) and same_rec(rec(1), card_slab[TRAC_A:2 * TRAC_A]),
              "G: both T1 and T2 from the card")
        check(pending(), "G: nothing left pending")

    if "H" in a.only:
        print("H: [PTN] + [TRACK 1], then [BANK] + [TRACK 1]", flush=True)
        p_ = pb()
        flip(slab_ad, 0x81)
        flip(p_ + 0x2A, 0x55)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0), (BANK, 1), (0x10, 1), (0x10, 0), (BANK, 0)])
        check(same_rec(rec(0), card_slab[:TRAC_A]) and bytes(u.mem_read(p_ + 0x2A, 30)) == card_part[0x2A:0x2A + 30],
              "H: T1's record and its slice from the card (FULL won)")

    if "P" in a.only:
        print("P: the trig of the pattern you are on = ORIG SEQ of T1, in place", flush=True)
        flip(slab_ad, 0x81)
        gesture([(act, 1), (act, 0)])
        res = landing("P", [0])
        if res:
            e, t0, old_ok = res
            check(e["where"] == "tick" and old_ok, "P: in the tick at T1's next step (not the CHAIN AFTER point)")
        check(same_rec(rec(0), orig_slab[:TRAC_A]), "P: T1 as loaded")

    if "O" in a.only:
        print("O: [PTN] + [BANK] + [YES] = ORIG PTN+PRT, together, in place", flush=True)
        p_ = pb()
        flip(slab_ad, 0x81)
        flip(slab_ad + 2 * TRAC_A, 0x81)
        flip(p_ + 0x2A, 0x55)
        sw0 = stock_sw["n"]
        gesture([(PTN, 1), (BANK, 1), (YES, 1), (YES, 0), (BANK, 0), (PTN, 0)])
        res = landing("O", list(range(16)))
        if res:
            e, t0, old_ok = res
            # the first step start ALL its tracks share may be the master wrap (tracks of other scales: OT DEMO's T3)
            check(e["where"] in ("tick", "wrap") and old_ok and e["one_tick"],
                  f"O: all at one point, a step start of every track ({e['n']}, in the {e['where']})")
        check(same_slab(slab(), orig_slab) and part() == orig_part, "O: the pattern and its Part as loaded")
        check(stock_sw["n"] == sw0 and rd(ACT, 1) == act, "O: no stock pattern switch (not a pattern change)")
        check(pending(), "O: nothing left pending")

    if "M" in a.only:
        print("M: a group T1 + T2, T1 arrows on its own slot (restore), T2 on another (load): [YES]", flush=True)
        qt = [rd(0x400D80DC + 4 * i, 4) for i in range(17)]
        q0 = rd(slab_ad + 0x8E56, 1)
        u.mem_write(slab_ad + 0x8E56, bytes([qt.index(4)]))          # CHAIN AFTER 4 steps
        flip(slab_ad, 0x81)
        key(CUE, 1)
        tap(0x10)
        tap(0x11)
        key(CUE, 0)
        cur = lambda: rd(syms["cl_cur"], 1)
        tap(0x10)                                                    # T1 active: arrows to its own slot
        tap(DOWN)
        while cur() != act:
            tap(DOWN)
        tap(0x11)
        q = next(x for x in range(16) if x != act and bytes(u.mem_read(bb + x * PATSTRIDE + TRAC_A, TRAC_A)) != rec(1))
        tap(DOWN)
        while cur() != q:
            tap(DOWN)
        events.clear()
        tap(YES)
        settle(4000)
        lands = [e for e in events if e["where"] in ("tick", "wrap", "now")]
        when = sorted({(e["ms"], e["tc"]) for e in lands})
        print(f"      M: landings {[(e['where'], e['ms'], e['tc']) for e in lands]}", flush=True)
        check(len(lands) >= 2 and len(when) == 1, "M: both members at the same (cued) point")
        check(same_rec(rec(0), orig_slab[:TRAC_A]), "M: T1 as loaded")
        tap(NO)
        u.mem_write(slab_ad + 0x8E56, bytes([q0]))

    if "I" in a.only:
        q = next(x for x in range(16) if x != act)
        qt = [rd(0x400D80DC + 4 * i, 4) for i in range(17)]
        u.mem_write(0x8000004E, bytes([0]))              # CHAIN AFTER off: the cue waits for the pattern's end, so
        u.mem_write(slab_ad + 0x8E56, bytes([0xFF]))     # it is still pending when P1 is pressed (4 / 16 steps
        print("      CHAIN AFTER off (the pattern's end)", flush=True)   # landed P2 first: not exercised)
        for delay in (300, 1500):
            print(f"I: on {act + 1}, [PTN] + [BANK] + trig {q + 1}, then trig {act + 1} {delay} ms later", flush=True)
            seen = set()
            key(PTN, 1); key(BANK, 1); key(q, 1); key(q, 0)
            settle(delay)
            p_mid = (rd(0x800065BF, 1), rd(0x800065C0, 1))
            pre_ok = rd(ACT, 1) == act and p_mid[1] == q          # P2 cued, not landed yet: the case under test
            key(act, 1); key(act, 0); key(BANK, 0); key(PTN, 0)
            for _ in range(80):
                settle(34)
                seen.add(rd(ACT, 1))
            print(f"      queued when {act + 1} was pressed {p_mid}; patterns played {sorted(x + 1 for x in seen)}",
                  flush=True)
            if a.dj:
                print(f"      I ({delay} ms): DIRECT JUMP lands a cue on the next step -- the cancel window is not "
                      f"reachable here (cued and pending at the press: {pre_ok})", flush=True)
                continue
            check(pre_ok, f"I ({delay} ms): the case is exercised -- pattern {q + 1} cued, not yet landed, at the press")
            check(seen == {act} and rd(0x800065C0, 1) == act, f"I ({delay} ms): pattern {q + 1} never played")

    if "F" in a.only:
        print("F: STOP, [PTN] + [TRACK 1]", flush=True)
        key(0x27, 1); key(0x27, 0)
        settle(400)
        check(rd(RUNNING, 4) == 0, "F: the transport stopped")
        flip(slab_ad, 0x81)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)])
        res = landing("F", [0])
        if res:
            check(res[0]["where"] == "now" and res[0]["toast_after"], "F: stopped: at once, then its toast")
        check(same_rec(rec(0), card_slab[:TRAC_A]), "F: T1's record from the card")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT's quantized landing (emulator, 2026-11-08): with the transport RUNNING, every
reload of the playing pattern lands like CLYPS' temp reload -- at the next step start of the track
(old and new rate), phase-continuous -- and a whole pattern at the next step all its tracks share.
On a project that loads on the audio side (OT DEMO), from pattern 1, DIRECT JUMP as booted (off):

  A  SAVE PROJECT, PLAY.
  B  [PTN] + [TRACK 1] (T1's trigs edited): lands in rl_tick (phase D), on the tick BEFORE a step
     boundary of T1 (2026-11-13, Clyps' rule: t' = t0 + 2 = 0 mod tps), fired for that boundary (its
     step as stock had it, TICKS tps - 2 before -> 0, reload tps - 2 + first fire); T1's record = the
     card's; the toast comes after the landing, not before.
  C  [BANK] + [TRACK 1] (T1's record + machine page 1 + T2's slice edited): no engine apply in the
     landing tick; the slice is published on the tick the incoming sequence's first sample trig sounds
     (the boundary + its distance in steps); T2 untouched.
  D  [PTN] + [BANK] + trig 1, the playing pattern (T1, T2, T5 records + the Part edited): every
     track lands in one tick, the tick before a boundary of all of them; all from the card; each
     changed track's slice published on its first trig's boundary; instructions in that tick, reported.
  E  NORMAL: the pattern length edited, [PTN] + [TRACK 1]; PER TRACK: the master length edited, the
     pattern reloaded: in the tick, every track and the master re-phased (master step = (t' / tps)
     mod len, tick tps - 2), or at the master wrap (rl_wrap).
  G / H / I  two tracks in one step; SEQ then FULL (FULL wins); the cue cancel.
  W  a FULL track reload landing in the wrap body: its slice published when the incoming sequence's
     first trig sounds (its new cycle's step 0 sounds on the wrap tick + tps; + the trig's distance).
  F  STOP, [PTN] + [TRACK 1]: lands at once (no tick).

  python3 tools/diag_reload_quant.py --image out/mainos_reload_from_project.bin \
      --elf out/patch_reload3.elf --project DIR --name NAME
"""
import argparse, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY, SAVE_PROJECT = 0x40031734, 0x40022850
TRK_APPLY = 0x40001F18
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
PART_OFF, PARTSZ = 0x8ED80, 0x18B2
ACT, RUNNING, MSTEP, TICK_CTR, SCALE_IX = 0x800065BE, 0x800065B8, 0x800065B2, 0x800065B6, 0x8000663D
STEP_ARR, STEPM1_ARR, TICKS_ARR, TSCALE_ARR, LEN_TBL = 0x800064D0, 0x800064E0, 0x800064F0, 0x8000663E, 0x400ABA50
TOAST = 0x460D1E70
PTN, BANK, STOP, PLAY = 0x2E, 0x2F, 0x1E, 0x1D
NOSER = {0x899 + k * TRAC_A for k in range(8)} | set(range(0x8E5C, PATSTRIDE))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--elf", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--dj-mode-at", type=lambda x: int(x, 0), default=None,
                    help="DIRECT JUMP KYOTI's DJ_MODE (a KYOTI image): turned ON for the run")
    a = ap.parse_args(argv)
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name,
                                    tree=f"out/_emu_reload_quant_{pathlib.Path(a.image).stem}_{a.name}")
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
        # restore main's SP after every borrowed call (Clyps' diag_clyps_quant.py, 2026-11-09)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=600000)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)
        return r_

    def key(code, ev, ms=40):
        main_call(SET_KEY, code, ev)
        rt.run(ms=ms)

    def worker(fn, ms):
        main_call(fn)
        rt.run(ms=ms)

    if rd(0x80000012, 4):
        key(0x35, 1); key(0x35, 0)
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
    print("A: SAVE PROJECT, PLAY", flush=True)
    worker(SAVE_PROJECT, 8000)
    card_slab, card_part = slab(), part()

    # ---- instrumentation: where each landing happens, and what the sequencer state was then
    events = []
    state = {"in_tick": False, "count": None, "applies": 0, "tick": 0}
    applies = []                              # (tick, track) of every TRK_APPLY (2026-11-09: when it sounds)
    apply_at = []                             # (t' it publishes for, track)
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: state.__setitem__("tick", state["tick"] + 1),
               begin=0x400A1F72, end=0x400A1F72)

    def snap(where):
        return dict(where=where, tick=state["tick"], ms=rd(MSTEP, 2), tc=rd(TICK_CTR, 1), sc=rd(SCALE_IX, 1),
                    step=list(u.mem_read(STEP_ARR, 16)), stepm1=list(u.mem_read(STEPM1_ARR, 16)),
                    ticks=list(u.mem_read(TICKS_ARR, 16)), tscale=list(u.mem_read(TSCALE_ARR, 16)),
                    toast=rd(TOAST, 4))

    def on_put(uc, ad, sz, ud):
        caller = "tick" if state["in_tick"] else ("wrap" if state.get("in_wrap") else "now")
        state["in_wrap"] = False             # one wrap entry, one landing
        events.append(dict(snap(caller), applies_before=state["applies"]))

    def on_tick_in(uc, ad, sz, ud):
        if rd(syms["rl_arm"], 1):
            state["in_tick"] = True

    def on_tick_out(uc, ad, sz, ud):
        if state["in_tick"]:
            state["in_tick"] = False
            events.append(dict(snap("tick_out"), applies=state["applies"], count=state["count"]))
            state["count"] = None

    def on_wrap_in(uc, ad, sz, ud):
        state["in_wrap"] = bool(rd(syms["rl_arm"], 1))

    def on_apply(uc, ad, sz, ud):
        if state["in_tick"]:
            state["applies"] += 1
        applies.append((state["tick"], rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 12, 4)))
        # 2026-11-13: where it happens on the master clock (Clyps' gate: its t0 + 1 is the tick it publishes for)
        apply_at.append(((rd(MSTEP, 2) - 1) * tps(rd(SCALE_IX, 1)) + rd(TICK_CTR, 1) + 1,
                         rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 12, 4)))

    u.hook_add(er.eb.UC_HOOK_CODE, on_put, begin=syms["rl_put"], end=syms["rl_put"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_tick_in, begin=syms["rl_tick"], end=syms["rl_tick"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_tick_out, begin=syms["rt3_out"], end=syms["rt3_out"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_wrap_in, begin=syms["rl_wrap"], end=syms["rl_wrap"])
    u.hook_add(er.eb.UC_HOOK_CODE, on_apply, begin=TRK_APPLY, end=TRK_APPLY)
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: events.append(dict(snap("follow"))),
               begin=syms["rl_follow"], end=syms["rl_follow"])
    dj = a.dj_mode_at is not None
    if dj:
        u.mem_write(a.dj_mode_at, (1).to_bytes(4, "big"))
        print(f"DIRECT JUMP ON (DJ_MODE 0x{a.dj_mode_at:08x})", flush=True)


    rt.seq_select_live(bank, act)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=600)
    check(rd(RUNNING, 4) == 1, "the transport runs")

    def settle(ms):
        # route A runs no UI tick (task 0x40056c40's 1/60 s message, where rl_uitick sits): call the
        # patched site as one tick does, every ~17 ms (as diag_clyps_ui.py does for cl_uitick)
        for _ in range(max(1, ms // 17)):
            rt.run(ms=17)
            main_call(0x40056C28)

    def gesture(keys, ms=3000):
        events.clear()
        applies.clear()
        apply_at.clear()
        state["applies"] = 0
        pre = snap("pre")
        for k, ev in keys:
            key(k, ev)
        settle(ms)
        return pre

    def landing(label, t_list):
        puts = [i for i, e in enumerate(events) if e["where"] in ("tick", "wrap", "now")]
        if not puts:
            check(False, f"{label}: it landed")
            return None
        i0 = puts[0]
        e = events[i0]
        e["out"] = next((x for x in events[i0:] if x["where"] == "tick_out"), None)  # that tick's exit
        e["followed"] = any(x["where"] == "follow" for x in events[i0:])
        # 2026-11-13 (Clyps CL26's rule): a landing comes on the tick BEFORE the boundary it fires for:
        # t0 here is that boundary, t' = (MASTER_STEP - 1) * tps_M + TICK_CTR + 2 of the landing tick
        t0 = (e["ms"] - 1) * tps(e["sc"]) + e["tc"] + 2
        old_ok = t0 >= 0 and all(t0 % tps(e["tscale"][t]) == 0 for t in t_list)
        print(f"      {label}: landed in {e['where']} at master step {e['ms']} tick {e['tc']} (t0 {t0}); "
              f"UI half after it: {e['followed']}", flush=True)
        return e, t0, old_ok

    def ftrig(t, k):
        # steps from k to t's first sample trig (the record's first 8 bytes, big-endian, bit s = step s)
        r = rec(t) if t < 8 else bytes(u.mem_read(slab_ad + 0x48D0 + (t - 8) * 0x8B0, 0x8B0))
        m_ = int.from_bytes(r[0:8], "big")
        lo = 0x50 if t < 8 else 0x28
        ln_ = (r[lo] or 16) if rd(slab_ad + 0x8E55, 1) else rd(slab_ad + 0x8E53, 1)
        return next((dd for dd in range(ln_) if m_ >> ((k + dd) % ln_) & 1), 0)

    def same_t(x, want):
        # two master-cycle times, the same tick of the cycle (MASTER_STEP wraps: t' counts within one cycle)
        if x is None or want is None:
            return False
        if rd(slab_ad + 0x8E55, 1):
            ml = rd(slab_ad + 0x8E50, 2)
            C = None if ml in (0, 0xFFFF) else ml * tps(rd(SCALE_IX, 1))
        else:
            C = rd(slab_ad + 0x8E53, 1) * tps(rd(SCALE_IX, 1))
        return (x - want) % C == 0 if C else x == want

    # ---- B: a track's sequence
    print("B: [PTN] + [TRACK 1]", flush=True)
    flip(slab_ad, 0x81)
    gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)])
    res = landing("B", [0])
    if res:
        e, t0, old_ok = res
        out = e["out"]
        check(e["where"] == "tick" and old_ok, "B: in phase D, the tick before a step boundary of T1")
        if out:
            check(out["step"][0] == e["step"][0] and out["stepm1"][0] == e["stepm1"][0]
                  and out["ticks"][0] == 0 and e["ticks"][0] == tps(e["tscale"][0]) - 2,
                  f"B: T1's step as stock had it, fired for the boundary (step {e['step'][0]} -> {out['step'][0]}, "
                  f"ticks {e['ticks'][0]} -> {out['ticks'][0]})")
        check(e["followed"], "B: the UI half (toast, redraw) runs after the landing")
    check(same_rec(rec(0), card_slab[:TRAC_A]), "B: T1's record from the card")
    check(rd(syms["rl_arm"], 1) == 0 and rd(syms["rl_post"], 1) == 0, "B: nothing left pending")

    # ---- C: a track's sequence + its slice
    print("C: [BANK] + [TRACK 1]", flush=True)
    pb = bb + PART_OFF + link() * PARTSZ
    flip(slab_ad, 0x81)
    flip(pb + 0x2A, 0x55)
    flip(pb + 0x2A + 30, 0x55)
    e2 = bytes(u.mem_read(pb + 0x2A + 30, 30))
    gesture([(BANK, 1), (0x10, 1), (0x10, 0), (BANK, 0)])
    res = landing("C", [0])
    if res:
        e, t0, old_ok = res
        out = e["out"]
        check(e["where"] == "tick" and old_ok, "C: in phase D, the tick before a step boundary of T1")
        want = t0 + ftrig(0, out["step"][0]) * tps(out["tscale"][0]) if out else None
        print(f"      C: landing tick {e['tick']} (boundary t' {t0}); TRK_APPLY at {applies} = t' {apply_at}; "
              f"its first trig at t' {want}", flush=True)
        check(out is not None and out["applies"] == 0, "C: no engine apply in the landing tick")
        check(len(applies) == 1 and apply_at[0][1] == 0 and same_t(apply_at[0][0], want),
              "C: T1's slice published on the boundary of the incoming sequence's first trig (2026-11-13)")
    check(same_rec(rec(0), card_slab[:TRAC_A]) and bytes(u.mem_read(pb + 0x2A, 30)) == card_part[0x2A:0x2A + 30],
          "C: T1's record and slice from the card")
    check(bytes(u.mem_read(pb + 0x2A + 30, 30)) == e2, "C: T2's slice untouched")

    # ---- D: the whole playing pattern: like temp reload, the next step all its tracks share (DJ on or off)
    print("D: [PTN] + [BANK] + trig (the playing pattern)", flush=True)
    for t in (0, 1, 4):
        flip(slab_ad + t * TRAC_A, 0x81)
    flip(pb + 0x2A + 60, 0x55)
    counter = {"n": 0}
    import bisect, collections
    names = sorted((v, k) for k, v in syms.items() if 0x40A955E0 <= v < 0x40AA1D70 and not k.startswith((".", "_")))
    starts = [v for v, _ in names]
    prof = collections.Counter()               # where the landing tick's instructions go (by RELOAD symbol)

    def on_any(uc, ad, sz, ud):
        if state["in_tick"]:
            counter["n"] += 1
            i = bisect.bisect_right(starts, ad) - 1
            prof[names[i][1] if i >= 0 and ad < 0x40AA1D70 else "stock"] += 1
    h = u.hook_add(er.eb.UC_HOOK_CODE, on_any)
    gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)])
    u.hook_del(h)
    res = landing("D", list(range(16)))
    if res:
        e, t0, old_ok = res
        out = e["out"]
        check(e["where"] == "tick" and old_ok, "D: one tick, the tick before a boundary of all 16 tracks")
        late = [(x, k) for x, k in apply_at
                if not same_t(x, t0 + ftrig(k, out["step"][k]) * tps(out["tscale"][k]))] if out else ["?"]
        print(f"      D: landing tick {e['tick']} (boundary t' {t0}); TRK_APPLY at {applies} = t' {apply_at}", flush=True)
        check(out is not None and out["applies"] == 0 and applies and not late,
              f"D: no apply in the landing tick; each changed track's on its first trig's boundary ({late})")
        print(f"      D: instructions in the landing tick's hook: {counter['n']:,}; by routine (RELOAD's labels, "
              f"stock = the OS's own, e.g. FWMEMCPY / TRK_APPLY): {prof.most_common(12)}", flush=True)
    check(same_slab(slab(), card_slab) and part() == card_part, "D: the whole pattern and its Part from the card")
    check(rd(ACT, 1) == act, "D: still on the same pattern")

    # ---- E: NORMAL, the pattern length edited: the master wrap lands it
    if mode == 0:
        print("E: NORMAL, length edited, [PTN] + [TRACK 1]", flush=True)
        ln = rd(slab_ad + 0x8E53, 1)
        u.mem_write(slab_ad + 0x8E53, bytes([ln - 1 if ln > 2 else ln + 1]))
        flip(slab_ad, 0x81)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)], ms=12000)
        res = landing("E", list(range(16)))
        if res:
            e, t0, old_ok = res
            out = e["out"]
            if e["where"] == "tick" and out:
                exp = (t0 // tps(out["sc"])) % rd(slab_ad + 0x8E53, 1)   # stock's landing: tick tps - 2
                check(old_ok and out["ms"] == exp and out["tc"] == tps(out["sc"]) - 2,
                      f"E: in the tick, re-phased: master step {out['ms']} tick {out['tc']} (expected {exp})")
            else:
                check(e["where"] == "wrap", f"E: at the master wrap ({e['where']})")
        check(rd(slab_ad + 0x8E53, 1) == ln and same_rec(rec(0), card_slab[:TRAC_A]),
              "E: the length and T1 from the card")
    else:
        # PER TRACK: the master length edited (so a wrap comes soon), then the whole pattern reloaded:
        # its master length changes back, so it waits for the master wrap (rl_wrap)
        print("E: PER TRACK, master length edited, [PTN] + [BANK] + trig (the playing pattern)", flush=True)
        ml = rd(slab_ad + 0x8E50, 2)
        cut = min(ml - 1, rd(MSTEP, 2) + 12)
        u.mem_write(slab_ad + 0x8E50, cut.to_bytes(2, "big"))
        flip(slab_ad, 0x81)
        gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)], ms=3000)
        res = landing("E", list(range(16)))
        if res:
            e, t0, old_ok = res
            out = e["out"]
            exp = (t0 // tps(e["sc"])) % ml
            check(e["where"] == "tick" and old_ok, f"E: the tick before the next common boundary, master step {e['ms']}")
            check(out is not None and rd(slab_ad + 0x8E50, 2) == ml and out["ms"] == exp
                  and out["tc"] == tps(out["sc"]) - 2,
                  f"E: re-phased -- master step {out['ms'] if out else '?'} tick {out['tc'] if out else '?'} "
                  f"(expected {exp}, tick tps - 2), length back to {ml}")
        check(rd(slab_ad + 0x8E50, 2) == ml and same_slab(slab(), card_slab), "E: the pattern from the card")

    # ---- G: two tracks inside one step: both land, each on its step
    print("G: [PTN] + [TRACK 1], then [PTN] + [TRACK 2] at once", flush=True)
    flip(slab_ad, 0x81)
    flip(slab_ad + TRAC_A, 0x81)
    gesture([(PTN, 1), (0x10, 1), (0x10, 0), (0x11, 1), (0x11, 0), (PTN, 0)])
    puts = [e for e in events if e["where"] in ("tick", "now", "wrap")]
    print(f"      G: {len(puts)} landing(s): {[(e['where'], e['ms'], e['tc']) for e in puts]}", flush=True)
    check(same_rec(rec(0), card_slab[:TRAC_A]) and same_rec(rec(1), card_slab[TRAC_A:2 * TRAC_A]),
          "G: both T1 and T2 from the card")
    check(rd(syms["rl_arm"], 1) == 0, "G: nothing left pending")
    # ---- H: the same track twice, SEQ then FULL: the later kind wins (its slice comes back)
    print("H: [PTN] + [TRACK 1], then [BANK] + [TRACK 1]", flush=True)
    flip(slab_ad, 0x81)
    flip(pb + 0x2A, 0x55)
    gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0), (BANK, 1), (0x10, 1), (0x10, 0), (BANK, 0)])
    check(same_rec(rec(0), card_slab[:TRAC_A]) and bytes(u.mem_read(pb + 0x2A, 30)) == card_part[0x2A:0x2A + 30],
          "H: T1's record and its slice from the card (FULL won)")

    # ---- I: on P1, reload P2 (a pattern change: cued), then reload P1 during the cue: P2 must NOT land
    #      (hardware 2026-11-09). The project's CHAIN AFTER = 4 steps (RAM) so the cue would land soon.
    q = next(x for x in range(16) if x != act)
    qt = [rd(0x400D80DC + 4 * i, 4) for i in range(17)]
    u.mem_write(0x8000004E, bytes([qt.index(16)]))  # 16 steps: 1.5 s is still inside the cue
    u.mem_write(slab_ad + 0x8E56, bytes([0xFF]))           # the pattern follows the project default
    for delay in (300, 1500):                                # P2's card read still running / P2 already cued
        print(f"I: on {act + 1}, [PTN] + [BANK] + trig {q + 1}, then trig {act + 1} {delay} ms later", flush=True)
        seen = set()
        events.clear()
        key(PTN, 1); key(BANK, 1); key(q, 1); key(q, 0)
        settle(delay)
        p_mid = (rd(0x800065BF, 1), rd(0x800065C0, 1))
        check(rd(ACT, 1) == act, f"I ({delay} ms): still on P{act + 1} when it is pressed (inside the cue)")
        key(act, 1); key(act, 0); key(BANK, 0); key(PTN, 0)
        for _ in range(80):                                 # > 8 steps at 1x
            settle(34)
            seen.add(rd(ACT, 1))
        print(f"      queued when P{act + 1} was pressed {p_mid}; patterns played since "
              f"{sorted(x + 1 for x in seen)}; queued now ({rd(0x800065BF, 1)}, {rd(0x800065C0, 1)})", flush=True)
        check(seen == {act} and rd(0x800065C0, 1) == act,
              f"I ({delay} ms): the P{act + 1} reload cancelled P{q + 1} -- it never played")

    # ---- W: a FULL track reload landing at the MASTER WRAP. The tick would land it on T1's next step first,
    #      so once it is armed the gate hides it from the tick (rl_arm = 0), cuts the master length to a wrap two
    #      steps away, and re-arms it at the wrap body's entry -- the real rl_wrap landing then runs. Its slice
    #      must reach the engine at the new cycle's first tick + tps (CLYPS' derived rule), never in the wrap.
    print("W: [BANK] + [TRACK 1] landing at the master wrap", flush=True)
    pb = bb + PART_OFF + link() * PARTSZ
    flip(pb + 0x2A, 0x55)
    ml = rd(slab_ad + 0x8E50, 2)
    force = {"on": False}
    hide = {"on": True, "caught": False}
    wraps = []

    def on_tick_hide(uc, ad, sz, ud):          # the tick's entry: an armed reload is hidden from it
        if hide["on"] and uc.mem_read(syms["rl_arm"], 1) == b"\x01":
            uc.mem_write(syms["rl_arm"], b"\x00")
            hide["caught"] = True
    hh = u.hook_add(er.eb.UC_HOOK_CODE, on_tick_hide, begin=syms["rl_tick"], end=syms["rl_tick"])

    def on_wrap(uc, ad, sz, ud):
        wraps.append(state["tick"])
        if force["on"]:
            force["on"] = False
            hide["on"] = False
            uc.mem_write(syms["rl_arm"], b"\x01")       # the armed reload, back for the wrap body to land
            state["in_wrap"] = True                     # (on_wrap_in ran first and saw it hidden)
    hw = u.hook_add(er.eb.UC_HOOK_CODE, on_wrap, begin=syms["rl_wrap"], end=syms["rl_wrap"])
    events.clear()
    applies.clear()
    apply_at.clear()
    for k, ev in ((BANK, 1), (0x10, 1), (0x10, 0), (BANK, 0)):
        key(k, ev)
    for _ in range(400):                    # until the card read has armed it (the tick hides it)
        if hide["caught"]:
            break
        rt.run(ms=20)
    check(hide["caught"], "W: the reload armed (and hidden from the tick)")
    u.mem_write(slab_ad + 0x8E50, (rd(MSTEP, 2) + 2).to_bytes(2, "big"))   # the master wraps in 2 steps
    force["on"] = True
    settle(2500)
    u.hook_del(hw)
    u.hook_del(hh)
    res = landing("W", [0])
    if res:
        e = res[0]
        wt = next((x for x in wraps if x >= e["tick"]), None)
        tsc = rd(TSCALE_ARR, 1)
        # the wrap body re-homes T1; its new cycle's step 0 is built on the next tick (wt + 1) a step ahead (ahead
        # tps), so it sounds on wt + tps (a build sounds at its tick + ahead - 1: tools/diag_reload_lock.py LW); the
        # slice waits for the first sample trig from step 0 (the count rule until now published at wt + 1 + tps)
        exp = (wt + tps(tsc) * (1 + ftrig(0, 0))) if wt is not None else None
        print(f"      W: landed in {e['where']} at tick {e['tick']}; wrap ticks {wraps[:4]}; T1 scale {tsc}; "
              f"TRK_APPLY at {applies}; expected {exp}", flush=True)
        check(e["where"] == "wrap", "W: landed in the wrap body")
        check(applies == [(exp, 0)], "W: no apply in the wrap; the slice reaches the engine when the incoming "
              "sequence's first trig sounds (the new cycle's step 0 sounds on the wrap tick + tps, + its distance in steps)")
    check(bytes(u.mem_read(pb + 0x2A, 30)) == card_part[0x2A:0x2A + 30], "W: T1's slice from the card")
    u.mem_write(slab_ad + 0x8E50, ml.to_bytes(2, "big"))

    # ---- F: stopped
    print("F: STOP, [PTN] + [TRACK 1]", flush=True)
    key(0x27, 1); key(0x27, 0)              # STOP (diag_clyps_ui.py's code)
    settle(400)
    check(rd(RUNNING, 4) == 0, "F: the transport stopped")
    flip(slab_ad, 0x81)
    gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)])
    res = landing("F", [0])
    if res:
        check(res[0]["where"] == "now", "F: stopped: landed at once")
    check(same_rec(rec(0), card_slab[:TRAC_A]), "F: T1's record from the card")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

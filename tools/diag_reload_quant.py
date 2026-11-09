#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT's quantized landing (emulator, 2026-11-08): with the transport RUNNING, every
reload of the playing pattern lands like CLYPS' temp reload -- at the next step start of the track
(old and new rate), phase-continuous -- and a whole pattern at the next step all its tracks share.
On a project that loads on the audio side (OT DEMO), from pattern 1, DIRECT JUMP as booted (off):

  A  SAVE PROJECT, PLAY.
  B  [PTN] + [TRACK 1] (T1's trigs edited): lands in rl_tick (phase D), at a step start of T1;
     T1's STEP / STEP-1 / TICKS after the landing are what stock had (same rate: no phase jump);
     T1's record = the card's; the toast comes after the landing, not before.
  C  [BANK] + [TRACK 1] (T1's record + machine page 1 + T2's slice edited): the slice is published
     IN THE SAME TICK (stock's TRK_APPLY called from rl_tick); T2 untouched.
  D  [PTN] + [BANK] + trig 1, the playing pattern (T1, T2, T5 records + the Part edited): every
     track lands in one tick, at a step start of all of them; all from the card; the Part's tracks
     published in that tick (8 x TRK_APPLY); instructions spent in that tick's landing, reported.
  E  NORMAL pattern, its length edited, [PTN] + [TRACK 1]: waits for the master wrap (rl_wrap).
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
                                    tree=f"out/_emu_reload_quant_{pathlib.Path(a.image).stem}")
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

    def key(code, ev, ms=40):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY, args=(code, ev), budget=600000)
        rt.run(ms=ms)

    def worker(fn, ms):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(fn, budget=600000)
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
    state = {"in_tick": False, "count": None, "applies": 0}

    def snap(where):
        return dict(where=where, ms=rd(MSTEP, 2), tc=rd(TICK_CTR, 1), sc=rd(SCALE_IX, 1),
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
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(0x40056C28, budget=600000)

    def gesture(keys, ms=3000):
        events.clear()
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
        t0 = (e["ms"] - 1) * tps(e["sc"]) + e["tc"]
        old_ok = all(t0 % tps(e["tscale"][t]) == 0 for t in t_list)
        print(f"      {label}: landed in {e['where']} at master step {e['ms']} tick {e['tc']} (t0 {t0}); "
              f"UI half after it: {e['followed']}", flush=True)
        return e, t0, old_ok

    # ---- B: a track's sequence
    print("B: [PTN] + [TRACK 1]", flush=True)
    flip(slab_ad, 0x81)
    gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)])
    res = landing("B", [0])
    if res:
        e, t0, old_ok = res
        out = e["out"]
        check(e["where"] == "tick" and old_ok, "B: in phase D, at a step start of T1")
        if out:
            check(out["step"][0] == e["step"][0] and out["stepm1"][0] == e["stepm1"][0]
                  and out["ticks"][0] == e["ticks"][0] == 0,
                  f"B: T1's counters as stock had them (step {e['step'][0]} -> {out['step'][0]}, "
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
        check(e["where"] == "tick" and old_ok, "C: in phase D, at a step start of T1")
        check(out is not None and out["applies"] == 1, f"C: T1's slice published in that same tick "
              f"(TRK_APPLY x{out['applies'] if out else '?'})")
    check(same_rec(rec(0), card_slab[:TRAC_A]) and bytes(u.mem_read(pb + 0x2A, 30)) == card_part[0x2A:0x2A + 30],
          "C: T1's record and slice from the card")
    check(bytes(u.mem_read(pb + 0x2A + 30, 30)) == e2, "C: T2's slice untouched")

    # ---- D: the whole playing pattern: like temp reload, the next step all its tracks share (DJ on or off)
    print("D: [PTN] + [BANK] + trig (the playing pattern)", flush=True)
    for t in (0, 1, 4):
        flip(slab_ad + t * TRAC_A, 0x81)
    flip(pb + 0x2A + 60, 0x55)
    counter = {"n": 0}

    def on_any(uc, ad, sz, ud):
        if state["in_tick"]:
            counter["n"] += 1
    h = u.hook_add(er.eb.UC_HOOK_CODE, on_any)
    gesture([(PTN, 1), (BANK, 1), (act, 1), (act, 0), (BANK, 0), (PTN, 0)])
    u.hook_del(h)
    res = landing("D", list(range(16)))
    if res:
        e, t0, old_ok = res
        out = e["out"]
        check(e["where"] == "tick" and old_ok, "D: one tick, a step start of all 16 tracks")

        check(out is not None and out["applies"] == 8, f"D: the Part published track by track in that tick "
              f"(TRK_APPLY x{out['applies'] if out else '?'})")
        print(f"      D: instructions in the landing tick's hook: {counter['n']:,}", flush=True)
    check(same_slab(slab(), card_slab) and part() == card_part, "D: the whole pattern and its Part from the card")
    check(rd(ACT, 1) == act, "D: still on the same pattern")

    # ---- E: NORMAL, the pattern length edited: the master wrap lands it
    if mode == 0:
        print("E: NORMAL, length edited, [PTN] + [TRACK 1]", flush=True)
        ln = rd(slab_ad + 0x8E53, 1)
        u.mem_write(slab_ad + 0x8E53, bytes([ln - 1 if ln > 2 else ln + 1]))
        flip(slab_ad, 0x81)
        gesture([(PTN, 1), (0x10, 1), (0x10, 0), (PTN, 0)], ms=12000)
        res = landing("E", [0])
        if res:
            check(res[0]["where"] == "wrap", "E: landed at the master wrap (rl_wrap)")
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
            exp = (t0 // tps(e["sc"])) % ml + 1
            check(e["where"] == "tick" and old_ok, f"E: on the next common step, in the tick, master step {e['ms']}")
            check(out is not None and rd(slab_ad + 0x8E50, 2) == ml and out["ms"] == exp,
                  f"E: re-phased -- master step {out['ms'] if out else '?'} (expected {exp}), length back to {ml}")
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

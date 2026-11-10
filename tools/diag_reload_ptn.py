#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT's pattern reload, [PTN] + [BANK] + trig N (emulator, 2026-11-08).

CLYPS' pattern reload outside Clyps: pattern N of the playing bank -- its whole slab and its whole
working Part -- from the card, then the OT goes to N. The chord is one state in either key order:
[BANK]'s keymap layer on top (its trig press is ours), [PTN]'s LED layer on top, both releases silent.
On a project that loads on the audio side (OT DEMO), transport stopped (the cue lands at once):

  A  SAVE PROJECT (0x40022850 as the main task): the bank file = RAM now
  B  [PTN] down, [BANK] down, trig q (another pattern, on another Part), up, up
     PASS: q's slab + its Part from the card; the OT is on q; no SELECT window at any point;
           the key dispatch table and the LED layer list are as before the chord
  C  [BANK] down, [PTN] down, trig q (now the playing pattern), up, up -- the other order
     PASS: q's slab + Part from the card, that Part applied (0x40009094), the page redraw ran;
           no window; the dispatch table and LED list as before
  D  [PTN] down, [BANK] down, up, up with no trig: nothing reloads, no window, tables as before
  E  [PTN] + [BANK] + [TRACK 1]: no reload (an edited record stays edited)
  F  control: a plain [PTN] tap still opens SELECT PATTERN

  python3 tools/diag_reload_ptn.py --image out/mainos_reload_from_project.bin \
      --elf out/patch_reload3.elf --project DIR --name NAME
"""
import argparse, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
SAVE_PROJECT = 0x40022850
PART_APPLY, PART_RFRSH, PART_RELOAD = 0x40001F18, 0x4005E0A8, 0x4004AAB4   # PART_APPLY: per track (TRK_APPLY)
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
PART_OFF, PARTSZ = 0x8ED80, 0x18B2
DISPATCH, LED_HEAD, WIN_SLOT, POPUP, TOAST = 0x46C7D8DE, 0x460E7624, 0x460D1E5C, 0x460E5CD0, 0x460D1E70
PTN_LEDL, BANK_TRIG = 0x400BEBFE, 0x4007B2FC
PTN, BANK = 0x2E, 0x2F
NOSER = {0x899 + k * TRAC_A for k in range(8)} | set(range(0x8E5C, PATSTRIDE))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--elf", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--save-ms", type=int, default=8000)
    a = ap.parse_args(argv)
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name,
                                    tree=f"out/_emu_reload_ptn_{pathlib.Path(a.image).stem}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    rt.run(ms=300)
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    fails = []

    def check(ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            fails.append(what)

    windows = []                                     # SHOW_WIN / MLNOTIFY opened during a gesture

    def key(code, ev, ms=60):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY, args=(code, ev), budget=600000)
        rt.run(ms=ms)
        windows.append((code, ev, rd(WIN_SLOT, 4), rd(POPUP, 4)))

    def worker(fn, ms):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(fn, budget=600000)
        rt.run(ms=ms)

    if rd(0x80000012, 4):
        key(0x35, 1); key(0x35, 0)                  # to the audio side
    bb = BLOB + bank * BANKSTRIDE
    slab = lambda q: bytes(u.mem_read(bb + q * PATSTRIDE, PATSTRIDE))
    link = lambda q: rd(bb + q * PATSTRIDE + 0x8E57, 1) & 3
    part = lambda p: bytes(u.mem_read(bb + PART_OFF + p * PARTSZ, PARTSZ))
    same_slab = lambda x, y: all(x[i] == y[i] for i in range(PATSTRIDE) if i not in NOSER)
    dispatch = lambda: bytes(u.mem_read(DISPATCH, 0x34 * 24))
    flip = lambda ad, m: u.mem_write(ad, bytes([rd(ad, 1) ^ m]))
    calls = {"apply": 0, "rfrsh": 0, "part_reload": 0}
    for ad, k in ((PART_APPLY, "apply"), (PART_RFRSH, "rfrsh"), (PART_RELOAD, "part_reload")):
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad_, sz, ud, k=k: calls.__setitem__(k, calls[k] + 1),
                   begin=ad, end=ad)
    jobs = []
    u.hook_add(er.eb.UC_HOOK_CODE,            # a landing of a whole pattern (rl_put, kind 5)
               lambda uc, ad_, sz, ud: jobs.append(1) if uc.reg_read(er.eb.UC_M68K_REG_D0) & 0xFF == 5 else None,
               begin=syms["rl_put"], end=syms["rl_put"])

    ipl = []                                 # 2026-11-09: the interrupt mask when a landing copies (a task
    u.hook_add(er.eb.UC_HOOK_CODE,           # context here: stopped) -- masked = the audio frame held off
               lambda uc, ad_, sz, ud: ipl.append((uc.reg_read(er.eb.UC_M68K_REG_SR) >> 8) & 7),
               begin=syms["rl_landall"], end=syms["rl_landall"])
    act = rd(0x800065BE, 1)
    q = next((x for x in range(16) if x != act and link(x) != link(act)), None)
    if q is None:
        sys.exit("need a pattern on another Part than the playing one")
    print(f"bank {bank + 1}: playing {act + 1} (Part {link(act) + 1}); test pattern {q + 1} (Part {link(q) + 1}); "
          f"transport {'running' if rd(0x800065B8, 4) else 'stopped'}", flush=True)
    print("A: SAVE PROJECT ...", flush=True)
    worker(SAVE_PROJECT, a.save_ms)
    card_q, card_pq, card_pa = slab(q), part(link(q)), part(link(act))
    def led_top():                       # 0x4007e760 appends at the TAIL: the last node is the top
        n = rd(LED_HEAD, 4)
        while n and rd(n, 4):
            n = rd(n, 4)
        return n

    disp0, led0 = dispatch(), led_top()

    def edit(p_):
        flip(bb + p_ * PATSTRIDE, 0x81)                              # T1's first trig-mask byte
        flip(bb + PART_OFF + link(p_) * PARTSZ + 0x2A, 0x55)         # T1's machine page 1
        flip(bb + PART_OFF + link(p_) * PARTSZ + 0x2A + 30, 0x55)    # T2's

    def chord_state(label):
        top = rd(DISPATCH + 0 * 24, 4)
        print(f"      {label}: trig 1 -> 0x{top:08x}, LED top 0x{led_top():08x}, window "
              f"0x{rd(WIN_SLOT, 4):08x}", flush=True)
        check(top == BANK_TRIG and led_top() == PTN_LEDL,
              f"{label}: the trigs go to [BANK]'s layer, the grid is [PTN]'s")

    def after(label):
        w = [x for x in windows if x[2] or x[3]]
        check(not w, f"{label}: no SELECT window / dialog at any step ({w[:3]})")
        check(dispatch() == disp0 and led_top() == led0, f"{label}: dispatch table + LED layers as before")
        windows.clear()

    print(f"B: [PTN] down, [BANK] down, trig {q + 1}", flush=True)
    edit(q)
    windows.clear()
    key(PTN, 1); key(BANK, 1)
    chord_state("B")
    key(q, 1); key(q, 0, ms=5000); key(BANK, 0); key(PTN, 0, ms=1500)
    print(f"      toast 0x{rd(TOAST, 4):08x} '{bytes(u.mem_read(syms['rl3_pline'], 12)).split(b'\0')[0].decode()}'; "
          f"jobs {len(jobs)}; calls {calls}; playing now {rd(0x800065BE, 1) + 1}", flush=True)
    check(same_slab(slab(q), card_q) and part(link(q)) == card_pq, f"B: pattern {q + 1} and its Part from the card")
    check(rd(0x800065BE, 1) == q, f"B: the OT went to pattern {q + 1}")
    check(rd(TOAST, 4) != 0 and calls["part_reload"] == 0, "B: a toast is up; stock's PART RELOAD never ran")
    after("B")

    print(f"C: [BANK] down, [PTN] down, trig {q + 1} (now the playing pattern)", flush=True)
    for k in calls:
        calls[k] = 0
    edit(q)
    key(BANK, 1); key(PTN, 1)
    chord_state("C")
    key(q, 1); key(q, 0, ms=5000); key(PTN, 0); key(BANK, 0, ms=1500)
    print(f"      calls {calls}; CUR_PART {rd(0x80000003, 1) + 1}", flush=True)
    check(same_slab(slab(q), card_q) and part(link(q)) == card_pq, f"C: pattern {q + 1} and its Part from the card")
    check(calls["apply"] >= 1 and calls["rfrsh"] >= 1 and rd(0x80000003, 1) == link(q),
          "C: the playing pattern's Part applied (per track, the changed ones: TRK_APPLY) and current, the redraw ran")
    after("C")

    print("D: the chord with no trig", flush=True)
    n0 = len(jobs)
    key(PTN, 1); key(BANK, 1); key(BANK, 0); key(PTN, 0, ms=1500)
    check(len(jobs) == n0, "D: nothing reloaded")
    after("D")

    print("E: [PTN] + [BANK] + [TRACK 1]", flush=True)
    flip(bb + q * PATSTRIDE, 0x81)
    e = slab(q)
    key(PTN, 1); key(BANK, 1); key(0x10, 1); key(0x10, 0, ms=4000); key(BANK, 0); key(PTN, 0, ms=1500)
    check(slab(q) == e, "E: the TRACK key reloaded nothing")
    after("E")

    print(f"      interrupt mask at each landing: {ipl}", flush=True)
    check(ipl and max(ipl) < 7, "the landings copy with interrupts ON (hardware: a masked 43 KB copy clicked)")
    print("F: a plain [PTN] tap", flush=True)
    key(PTN, 1); key(PTN, 0, ms=300)
    check(rd(WIN_SLOT, 4) != 0, "F: stock's SELECT PATTERN opens on the release")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

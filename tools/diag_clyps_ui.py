#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS phase 2 -- the UI gate (emulator; logic only: route A has no real UI tick or DSP path).

Drives real key events through stock's per-key dispatcher set_key_state(code, event)
(0x40031734; event 1 = press, 0 = release) on the CLYPS image, with a real exported project
loaded and the transport stopped, and checks after every step:
  * Clyps' own state (cl_open / cl_held / cl_loaded / cl_bank / cl_cur, from the build's symbols);
  * the keymap layer list (0x460d165c) and the LED layer list (0x460e7624) return to the baseline
    when Clyps closes -- the RELOAD2 failure class;
  * PTN_CONSUMED / BANK_SEL / the SHOW_WIN slot: no SELECT window on any chord path;
  * the playing pattern's track record after a load equals the source record;
  * stock controls: a lone [PTN] tap and a lone [BANK] tap still open their SELECT windows.
Screens are written as PNGs (the firmware's 1-bpp plane at 0x46c7e0ea, octabam's lcd_view).

  python3 tools/diag_clyps_ui.py --project DIR --name NAME [--image out/mainos_clyps.bin]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
LAYERS, LEDS = 0x460d165c, 0x460e7624
PTN_CONSUMED, BANK_SEL, WIN_SLOT = 0x460d173e, 0x460e73c6, 0x460d1e5c
PLANE = 0x46c7e0ea
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A
PTN, BANK, YES, NO, UP, DOWN, LEFT, RIGHT = 0x2E, 0x2F, 0x31, 0x32, 0x33, 0x20, 0x34, 0x21


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "out/mainos_clyps.bin"))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--shots", default=str(ROOT / "out/clyps/ui"))
    ap.add_argument("--only", default="ABCD", help="scenarios to run, e.g. B")
    ap.add_argument("--budget", type=int, default=4_000_000, help="steps per key call")
    a = ap.parse_args(argv)
    image = str(pathlib.Path(a.image).resolve())
    syms = {k: int(v, 16) for k, v in (l.split() for l in (ROOT / "out/clyps_syms.txt").read_text().splitlines())}
    shots = pathlib.Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    import lcd_view
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree="out/_emu_clyps_ui")
    r, rt = er.attach(image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def chain(head):
        out, p = [], rd(head, 4)
        while p and len(out) < 32:
            out.append(p)
            p = rd(p, 4)
        return out

    def state():
        return dict(open=rd(syms["cl_open"], 1), held=rd(syms["cl_held"], 1), loaded=rd(syms["cl_loaded"], 1),
                    bank=rd(syms["cl_bank"], 1), cur=rd(syms["cl_cur"], 1), win=rd(syms["cl_win"], 4),
                    layers=chain(LAYERS), leds=chain(LEDS), consumed=rd(PTN_CONSUMED, 4),
                    banksel=rd(BANK_SEL, 4), showwin=rd(WIN_SLOT, 4))

    def key(code, ev, settle=60):
        print(f"      key 0x{code:02x} {'down' if ev else 'up'}", flush=True)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        try:
            rt.call_as_main(SET_KEY, args=(code, ev), budget=a.budget)
        except er.RtosFault as e:
            import collections
            pcs = collections.Counter()
            for _ in range(20000):
                rt.step()
                pcs[rt.pc] += 1
            print(f"      STALL: {e}; hottest PCs: " +
                  ", ".join(f"0x{pc:08x}x{n}" for pc, n in pcs.most_common(12)), flush=True)
            raise SystemExit(2)
        rt.run(ms=settle)

    def tap(code):
        key(code, 1)
        key(code, 0)

    def shot(name):
        lcd_view.png(lcd_view.pixels(bytes(u.mem_read(PLANE, 1024))), str(shots / f"{name}.png"))

    def rec(pat, t=None, b=None):
        b = bank if b is None else b
        t = rd(0x80000000, 1) if t is None else t   # the active audio track
        return bytes(u.mem_read(BLOB + b * BANKSTRIDE + pat * PATSTRIDE + t * TRAC_A, TRAC_A))

    fails = []

    def check(cond, what):
        print(f"   {'ok  ' if cond else 'FAIL'} {what}")
        if not cond:
            fails.append(what)

    rt.run(ms=300)
    base = state()
    print(f"baseline: layers {[hex(x) for x in base['layers']]} leds {[hex(x) for x in base['leds']]}")
    act = rd(0x800065BE, 1)
    print(f"playing pattern {act}, bank {bank}, track {rd(0x80000000, 1)}")
    shot("00_base")

    if "A" in a.only:
        # --- A: [PTN] then [BANK], held, trig 4 loads, release closes
        print("A: PTN then BANK; held; trig 4; release")
        src = rec(3)
        key(PTN, 1)
        key(BANK, 1)
        s = state()
        shot("A1_open")
        check(s["open"] == 1 and s["held"] == 1, "Clyps open, held")
        check(syms["cl_layer"] in s["layers"] and s["layers"][-1] == syms["cl_layer"], "our keymap layer is last")
        check(s["leds"] and s["leds"][-1] == syms["cl_led"], "our LED layer is last")
        check(s["showwin"] == 0, "no SELECT window")
        leds = bytes(u.mem_read(0x460BA98C, 17))
        tbl = [rd(0x400A74CE + 4 * n, 4) for n in range(16)]
        bit = lambda die: (leds[die // 8] >> (die % 8)) & 1
        cls = list(bytes(u.mem_read(syms["cl_cls"], 16)))
        red = [n for n in range(16) if bit(tbl[n])]
        grn = [n for n in range(16) if bit(tbl[n] + 1)]
        print(f"      classes {cls}  red {red}  green {grn}", flush=True)
        check(red == [act] and act not in grn, f"grid: red on the playing slot {act + 1} only")
        check(sorted(grn) == [n for n in range(16) if cls[n] and n != act], "grid: green on every slot with data")
        key(3, 1)
        key(3, 0)
        s = state()
        check(s["open"] == 1 and s["loaded"] == 1, "trig 4 in the held state: loaded, still open")
        check(rec(act) == src, "the playing pattern's active-track record == pattern 4's")
        shot("A2_loaded")
        key(BANK, 0)
        key(PTN, 0)
        s = state()
        shot("A3_closed")
        check(s["open"] == 0, "release after a load closes Clyps")
        check(s["layers"] == base["layers"], "keymap layer list back to baseline")
        check(s["leds"] == base["leds"], "LED layer list back to baseline")
        check(s["showwin"] == 0, "no SELECT window after the releases")

    if "B" in a.only:
        # --- B: [BANK] then [PTN], release -> latched, DOWN DOWN, YES
        print("B: BANK then PTN; release -> latched; DOWN x2; YES")
        key(BANK, 1)
        key(PTN, 1)
        s = state()
        check(s["open"] == 1, "Clyps open (BANK first)")
        check(s["showwin"] == 0, "SELECT BANK closed again")
        key(PTN, 0)
        key(BANK, 0)
        s = state()
        check(s["open"] == 1 and s["held"] == 0, "released with no load: latched")
        cur0 = s["cur"]
        tap(DOWN)
        tap(DOWN)
        s = state()
        check(s["cur"] == (cur0 + 2) % 16, f"DOWN x2: cursor {cur0} -> {s['cur']}")
        shot("B1_latched")
        target = s["cur"]
        src = rec(target)
        tap(YES)
        s = state()
        check(s["open"] == 0, "[YES] in latched: closed")
        check(rec(act) == src, f"[YES] loaded slot {target + 1}")
        check(s["layers"] == base["layers"] and s["leds"] == base["leds"], "layer lists back to baseline")

    if "C" in a.only:
        # --- C: chord, LEFT/RIGHT, TRACK 3, NO
        print("C: chord; LEFT; RIGHT; TRACK 3; release; NO")
        key(PTN, 1)
        key(BANK, 1)
        b0 = state()["bank"]
        tap(LEFT)
        check(state()["bank"] == (b0 + 15) % 16, "LEFT: bank - 1 (wraps)")
        shot("C1_left")
        tap(RIGHT)
        check(state()["bank"] == b0, "RIGHT: back")
        before = rec(act, 2)
        tap(0x12)
        check(rd(0x80000000, 1) == 2, "TRACK 3 selects track 3")
        check(rd(0x460FAB40, 4) == 0, "no track key left marked held (0x460fab40)")
        shot("C2_track3")
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1, "latched")
        tap(NO)
        s = state()
        check(s["open"] == 0 and rec(act, 2) == before, "[NO]: closed, nothing loaded")
        check(s["layers"] == base["layers"] and s["leds"] == base["leds"], "layer lists back to baseline")

    if "D" in a.only:
        # --- D: stock controls
        print("D: stock [PTN] tap and [BANK] tap")
        tap(PTN)
        s = state()
        check(s["showwin"] != 0, "[PTN] alone: SELECT PATTERN opens on release")
        shot("D1_selpat")
        tap(NO)
        rt.run(ms=200)
        key(BANK, 1)
        s = state()
        check(s["showwin"] != 0, "[BANK] alone: SELECT BANK opens")
        shot("D2_selbank")
        key(BANK, 0)
        tap(NO)

    print(f"\nscreens: {shots}")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)}): " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

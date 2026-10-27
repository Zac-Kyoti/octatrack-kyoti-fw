#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS phase 2 -- the UI gate (emulator; logic only: route A has no real UI tick or DSP path).

Drives real key events through stock's per-key dispatcher set_key_state(code, event)
(0x40031734; event 1 = press, 0 = release) on the CLYPS image, with a real exported project
loaded and the transport stopped, and checks after every step:
  * Clyps' own state (cl_open / cl_bank / cl_sbank / cl_cur, from the build's symbols);
  * the keymap layer list (0x460d165c) and the LED layer list (0x460e7624) return to the baseline
    when Clyps closes -- the RELOAD2 failure class;
  * PTN_CONSUMED / BANK_SEL / the SHOW_WIN slot: no SELECT window on any chord path;
  * the playing pattern's track record after a load equals the source record;
  * stock controls: a lone [PTN] tap and a lone [BANK] tap still open their SELECT windows;
  * E: saved sequences ([FUNC]+[YES] / [FUNC]+[NO]) and originals (the bank as loaded: always
    there, the ORIG cursor entry, [PAGE] after a load AND after a grid edit, [FUNC]+[PAGE]),
    byte for byte;
  * G: the source label on your pattern's slot after a load / a saved load (screens);
  * N: a NORMAL pattern converted to PER TRACK by a load, and the restore that undoes it: the
    whole slab comes back byte for byte;
  * P: a project load drops the saved sequences and retakes the originals;
  * Y: [YES] with the chord held does nothing; [PTN]+[YES] in Clyps mode never loads.
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
FUNC, PAGE = 0x2D, 0x1B


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
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_clyps_ui_{a.name}")
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
        return dict(open=rd(syms["cl_open"], 1), sbank=rd(syms["cl_sbank"], 1),
                    bank=rd(syms["cl_bank"], 1), cur=rd(syms["cl_cur"], 1), win=rd(syms["cl_win"], 4),
                    flash=rd(syms["cl_flash"], 1),
                    layers=chain(LAYERS), leds=chain(LEDS), consumed=rd(PTN_CONSUMED, 4),
                    banksel=rd(BANK_SEL, 4), showwin=rd(WIN_SLOT, 4))

    def key(code, ev, settle=60):
        print(f"      key 0x{code:02x} {'down' if ev else 'up'}", flush=True)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        if ev and 0x10 <= code <= 0x17:
            # stock's TRACK press (0x40040250) reads a second press of the same key as a DOUBLE TAP
            # while its timer 0x460d5de0 is <= 14; route A has no UI tick, so the timer never
            # advances and every repeat press would be one (it opens a window that evicts Clyps).
            # Age it, as the time between this gate's taps would on hardware.
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))
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
    slab = lambda pat, b=None: bytes(u.mem_read(BLOB + (bank if b is None else b) * BANKSTRIDE + pat * PATSTRIDE, PATSTRIDE))
    BANKSZ = 0x9B340
    snapok = lambda: rd(syms["cl_snapok"], 2)
    oslot = lambda pat, t, b=None: bytes(u.mem_read(syms["cl_bss"] + (bank if b is None else b) * BANKSZ
                                                    + pat * PATSTRIDE + t * TRAC_A, TRAC_A))
    oslab = lambda pat, b=None: bytes(u.mem_read(syms["cl_bss"] + (bank if b is None else b) * BANKSZ + pat * PATSTRIDE, PATSTRIDE))
    saved = lambda t: bytes(u.mem_read(syms["cl_bss"] + 16 * BANKSZ + t * TRAC_A, TRAC_A))
    led_tbl = [rd(0x400A74CE + 4 * n, 4) for n in range(16)]

    def led(n):
        leds = bytes(u.mem_read(0x460BA98C, 17))
        bit = lambda die: (leds[die // 8] >> (die % 8)) & 1
        return bit(led_tbl[n]), bit(led_tbl[n] + 1)       # (red, green)
    svalid = lambda: list(bytes(u.mem_read(syms["cl_svalid"], 16)))

    def check(cond, what):
        print(f"   {'ok  ' if cond else 'FAIL'} {what}")
        if not cond:
            fails.append(what)

    rt.run(ms=300)
    base = state()
    print(f"baseline: layers {[hex(x) for x in base['layers']]} leds {[hex(x) for x in base['leds']]}")
    act = rd(0x800065BE, 1)
    print(f"playing pattern {act}, bank {bank}, track {rd(0x80000000, 1)}; project loads seen by Clyps: "
          f"{rd(syms['cl_nproj'], 1)}; snapshots 0x{snapok():04x}")
    shot("00_base")

    def closed_ok(what):
        s_ = state()
        check(s_["open"] == 0 and s_["layers"] == base["layers"] and s_["leds"] == base["leds"]
              and s_["showwin"] == 0, what + ": closed, layer lists at baseline, no SELECT window")

    if "A" in a.only:
        # --- A: open; the highlight / red = the pattern you are on; releases do not close; [NO] does
        print("A: PTN then BANK; opens on your pattern; release: stays; NO closes")
        key(PTN, 1)
        key(BANK, 1)
        s = state()
        shot("A1_open")
        check(s["open"] == 1, "Clyps open")
        check(s["layers"][-1] == syms["cl_layer"] and s["leds"][-1] == syms["cl_led"], "our keymap and LED layers are last")
        check(s["bank"] == bank and s["sbank"] == bank and s["cur"] == act, "the view and the box start on your pattern")
        check(led(act) == (1, 0), f"slot {act + 1} (your pattern) is red, red wins over the box")
        cls = list(bytes(u.mem_read(syms["cl_cls"], 16)))
        check(all(led(n)[0] == 0 and led(n)[1] == (1 if cls[n] else 0) for n in range(16) if n != act),
              "every other slot: green where there is data, no red")
        key(BANK, 0)
        key(PTN, 0)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0, "releasing the chord: Clyps stays, no SELECT window")
        tap(NO)
        closed_ok("[NO]")

    if "B" in a.only:
        # --- B: BANK first; a trig selects AND loads; Clyps stays; the box LED is yellow
        print("B: BANK then PTN; trig 4 selects + loads; stays; NO")
        src = rec(3)
        key(BANK, 1)
        key(PTN, 1)
        check(state()["open"] == 1 and state()["showwin"] == 0, "Clyps open (BANK first), SELECT BANK closed again")
        key(PTN, 0)
        key(BANK, 0)
        key(3, 1)
        key(3, 0)
        s = state()
        check(s["open"] == 1 and s["cur"] == 3 and s["sbank"] == bank, "trig 4: the box on slot 4, Clyps stays")
        check(rec(act) == src, "trig 4 loaded pattern 4's sequence")
        check(led(3) == (1, 1), "slot 4 (the box) is yellow")
        check(led(act) == (1, 0), "your pattern is still red")
        shot("B1_loaded")
        tap(NO)
        closed_ok("[NO]")

    if "C" in a.only:
        # --- C: the box moves with the arrows; [BANK] held + arrows page the banks; TRACK keys
        print("C: arrows move the box; BANK+arrows page; highlight / box only in their bank; TRACK 3; NO")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        s0 = state()
        tap(DOWN)
        tap(DOWN)
        s = state()
        check(s["cur"] == (s0["cur"] + 2) % 16 and s["bank"] == s0["bank"], "DOWN x2: the box moves, bank kept")
        c1 = s["cur"]
        tap(LEFT)
        check(state()["cur"] == c1 ^ 8, "LEFT: the other column")
        tap(RIGHT)
        check(state()["cur"] == c1, "RIGHT: back")
        check(led(c1) == (1, 1) or c1 == act, "the box's slot is yellow")
        shot("C1_box")
        key(BANK, 1)
        tap(RIGHT)
        check(state()["bank"] == (s0["bank"] + 1) % 16 and state()["cur"] == c1, "[BANK]+RIGHT: next bank, box kept")
        tap(DOWN)
        check(state()["bank"] == (s0["bank"] + 2) % 16, "[BANK]+DOWN: next bank")
        tap(UP)
        tap(LEFT)
        check(state()["bank"] == s0["bank"], "[BANK]+UP, [BANK]+LEFT: back")
        tap(LEFT)
        b2 = state()["bank"]
        check(b2 == (s0["bank"] + 15) % 16, "[BANK]+LEFT wraps A -> P")
        key(BANK, 0)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0, "[BANK] released: still in Clyps, no SELECT BANK")
        check(all(led(n) != (1, 0) for n in range(16)) and all(led(n) != (1, 1) for n in range(16)),
              "another bank: no red (your pattern) and no yellow (the box) on the grid")
        shot("C2_otherbank")
        tap(DOWN)
        s = state()
        check(s["sbank"] == b2 and s["cur"] == (c1 + 1) % 16, "an arrow in another bank brings the box into it")
        key(BANK, 1)
        tap(RIGHT)
        key(BANK, 0)
        before = rec(act, 2)
        tap(0x12)
        check(rd(0x80000000, 1) == 2, "TRACK 3 selects track 3")
        check(rd(0x460FAB40, 4) == 0, "no track key left marked held (0x460fab40)")
        check(state()["open"] == 1 and rec(act, 2) == before, "Clyps stays, nothing loaded")
        tap(NO)
        closed_ok("[NO]")
        tap(0x10)

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

    if "M" in a.only:
        # --- M: the MIDI side (needs a project with MIDI trigs on pattern 1, e.g. JAM2)
        print("M: MIDI key; TRACK 2; chord; slots; trig 2 loads pattern 2's M2; NO")
        print(f"      MKI/MKII probe 0x46c8d18c = 0x{rd(0x46C8D18C, 4):08x}", flush=True)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        if rd(0x80000012, 4) == 0:         # some projects load with the MIDI tracks showing
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(0x40055548, args=(0x35, 0), budget=600000)
            rt.run(ms=60)
        check(rd(0x80000012, 4) != 0, "stock's toggle switched to the MIDI tracks (0x80000012)")
        tap(0x11)
        check(rd(0x80000000, 1) == 1, "TRACK 2 selects M2")
        mrec = lambda pat, m: bytes(u.mem_read(BLOB + bank * BANKSTRIDE + pat * PATSTRIDE + 0x48D0 + m * 0x8B0, 0x8B0))
        key(PTN, 1)
        key(BANK, 1)
        cls = list(bytes(u.mem_read(syms["cl_cls"], 16)))
        trigs = [bin(int.from_bytes(mrec(p, 1)[:8], "big")).count("1") for p in range(16)]
        print(f"      M2 trigs per pattern {trigs}  classes {cls}", flush=True)
        check(all((cls[p] == 2) == (trigs[p] > 0) for p in range(16)), "slots classify the MIDI records")
        key(BANK, 0)
        key(PTN, 0)
        src = mrec(1, 1)
        key(0x01, 1)
        key(0x01, 0)
        check(mrec(act, 1) == src, "trig 2 loaded pattern 2's M2 onto the playing pattern's M2")
        tap(NO)
        closed_ok("[NO]")

    if "Y" in a.only:
        # --- Y: [YES] loads the box; the chord + [YES] and [PTN]+[YES] never load
        print("Y: chord + YES: nothing; PTN+YES: nothing; YES loads the box; NO")
        before = rec(act)
        key(PTN, 1)
        key(BANK, 1)
        tap(YES)
        check(state()["open"] == 1 and rec(act) == before, "chord held, [YES]: nothing")
        key(BANK, 0)
        tap(YES)
        check(state()["open"] == 1 and rec(act) == before, "[PTN]+[YES]: no load, Clyps stays")
        key(PTN, 0)
        q = next(n for n in range(16) if n != act and rec(n) != before)
        while state()["cur"] != q:
            tap(DOWN)
        tap(YES)
        check(state()["open"] == 1 and rec(act) == rec(q), f"[YES]: the box's slot {q + 1} loaded, Clyps stays")
        tap(NO)
        closed_ok("[NO]")

    if "E" in a.only:
        # --- E: originals (the bank as loaded) and saved sequences
        print("E: ORIG always there; [PAGE] undoes a load and a grid edit; [FUNC]+[YES] / [FUNC]+[NO]; restore-all")
        tap(0x10)
        act = rd(0x800065BE, 1)
        key(PTN, 1)                        # earlier scenarios loaded onto tracks: every track back first
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        key(FUNC, 1)
        tap(PAGE)
        key(FUNC, 0)
        tap(NO)
        pre = {t: rec(act, t) for t in range(3)}
        p = next(q for q in range(16) if q != act and all(rec(q, t) != pre[t] for t in range(3)))
        print(f"      playing {act}, source slot {p}, snapshots 0x{snapok():04x}", flush=True)
        check(snapok() == 0xFFFF, "every bank has its load snapshot")
        check(all(oslot(act, t) == pre[t] for t in range(3)), "T1-T3 equal their originals")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        while state()["cur"] != 0:
            tap(UP)
        tap(UP)
        check(state()["cur"] == 16, "ORIG is in the cycle with no load made (UP from slot 1)")
        shot("E0_orig")
        tap(PAGE)
        check(state()["open"] == 1 and rec(act, 0) == pre[0], "[PAGE] on an original track: nothing")
        key(FUNC, 1)
        tap(YES)
        s = state()
        check(svalid()[0] == 1 and saved(0) == pre[0], "[FUNC]+[YES]: T1's sequence saved, byte for byte")
        check(s["open"] == 1 and s["flash"] == 1, "Clyps stays; the header shows SAVED")
        key(FUNC, 0)
        key(p, 1)
        key(p, 0)
        check(rec(act, 0) == rec(p, 0) and oslot(act, 0) == pre[0], f"trig {p + 1}: loaded; the original untouched")
        shot("E1_loaded")
        key(FUNC, 1)
        tap(NO)
        key(FUNC, 0)
        check(state()["open"] == 1 and rec(act, 0) == pre[0], "[FUNC]+[NO]: the saved sequence is back, Clyps stays")
        shot("E2_saved_back")
        tap(NO)
        ad = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        u.mem_write(ad, bytes([rd(ad, 1) ^ 0x80]))
        check(rec(act, 0) != pre[0], "edited (a trig bit flipped)")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        tap(PAGE)
        check(rec(act, 0) == pre[0] and state()["open"] == 1, "[PAGE] undoes the edit; Clyps stays")
        for t in range(3):
            tap(0x10 + t)
            key(p, 1)
            key(p, 0)
        check(all(rec(act, t) == rec(p, t) for t in range(3)), "T1-T3 loaded")
        key(FUNC, 1)
        tap(PAGE)
        key(FUNC, 0)
        check(all(rec(act, t) == pre[t] for t in range(3)), "[FUNC]+[PAGE]: all three back")
        check(state()["open"] == 1, "Clyps stays")
        tap(NO)
        closed_ok("[NO]")
        tap(0x10)

    if "G" in a.only:
        # --- G: the source label on your pattern's slot (screens; the label text is drawn there)
        print("G: load slot 3 onto T1: your slot reads 'A3 n TRG'; FUNC+NO saved: 'SAVED'; PAGE: plain")
        tap(0x10)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        key(FUNC, 1)
        tap(YES)
        key(FUNC, 0)
        key(2, 1)
        key(2, 0)
        shot("G1_source")
        key(FUNC, 1)
        tap(NO)
        key(FUNC, 0)
        shot("G2_saved")
        tap(PAGE)
        shot("G3_plain")
        tap(NO)
        closed_ok("[NO]")

    if "N" in a.only:
        # --- N: a NORMAL destination converted by a load, undone by the restore
        nrm = next((q for q in range(16) if slab(q)[0x8E55] == 0), None)
        src = next((q for q in range(16) if slab(q)[0x8E55] and slab(q)[0x50] != slab(nrm)[0x8E53]), None) if nrm is not None else None
        print(f"N: NORMAL pattern {nrm}; T1 from PER TRACK pattern {src} (length {slab(src)[0x50] if src is not None else '-'})")
        if nrm is None or src is None:
            check(False, "N: this project has no NORMAL pattern / no PER TRACK source of another length")
        else:
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.seq_select_live(bank, nrm)
            rt.run(ms=300)
            check(rd(0x800065BE, 1) == nrm, f"playing pattern {nrm}")
            tap(0x10)
            before = slab(nrm)
            check(before == oslab(nrm), f"pattern {nrm} equals its original")
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)
            key(PTN, 0)
            key(src, 1)
            key(src, 0)
            tap(NO)
            s9 = slab(nrm)
            plen = before[0x8E53]
            check(s9[0x8E55] == 1 and int.from_bytes(s9[0x8E50:0x8E52], "big") == plen
                  and s9[0x50] == slab(src)[0x50]
                  and all(s9[t * TRAC_A + 0x50] == plen for t in range(1, 8))
                  and all(s9[0x48D0 + m * 0x8B0 + 0x28] == plen for m in range(8)),
                  f"converted: PER TRACK, master {plen}, T1 {s9[0x50]}, every other track {plen}")
            key(PTN, 1)
            key(BANK, 1)
            tap(PAGE)
            key(BANK, 0)
            key(PTN, 0)
            tap(NO)
            after = slab(nrm)
            diff = [i for i in range(PATSTRIDE) if after[i] != before[i]]
            check(not diff, f"[PAGE]: the whole slab is back, byte for byte ({len(diff)} bytes differ"
                  + (f", first at +0x{diff[0]:x})" if diff else ")"))
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.seq_select_live(bank, act)
            rt.run(ms=300)

    if "P" in a.only:
        # --- P: a project load drops the saved sequences and retakes the originals. The edit before
        # the load is made in RAM, not through a Clyps load: a load marks the bank dirty, and a
        # reload with unsaved changes takes a path this harness does not drive to its end (measured:
        # the banks are reset to defaults by 0x4000fd34 and never read back).
        print("P: save, a RAM edit, then LOAD PROJECT again")
        tap(0x10)
        act = rd(0x800065BE, 1)
        key(PTN, 1)
        key(BANK, 1)
        key(FUNC, 1)
        tap(YES)
        key(FUNC, 0)
        key(BANK, 0)
        key(PTN, 0)
        tap(NO)
        ad = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        u.mem_write(ad, bytes([rd(ad, 1) ^ 0x80]))
        n0 = rd(syms["cl_nproj"], 1)
        check(svalid()[0] == 1 and rec(act, 0) != oslot(act, 0), "a saved sequence is held; T1 differs from its original")
        trace = []
        def on_call(uc, addr, size, user):
            sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
            trace.append(f"{names.get(addr, hex(addr))}({', '.join(hex(rd(sp + 4 * k, 4)) for k in range(1, 3))}) "
                         f"ret 0x{rd(sp, 4):08x} @{rt.sample}")
        names = {0x4000FD34: "reset_all_banks", 0x4000FC78: "init_bank", 0x400905D4: "masked_loader",
                 syms["cl_ldexit"]: "cl_ldexit(snapshot)", 0x4000FBB4: "sram_to_ram", 0x4000FAF0: "ram_to_sram",
                 0x4008DED0: "bank_reader"}
        hooks = [u.hook_add(er.eb.UC_HOOK_CODE, on_call, begin=ad_, end=ad_) for ad_ in names]
        rt.load_project_live("OCTABAM", staged, run_ms=6000)
        for waited in range(1, 16):
            rt.run(ms=1000)
            if snapok() == 0xFFFF and all(oslab(0, b) == slab(0, b) for b in range(16)):
                break
        print(f"      settled after {waited} s more; dialog up: 0x{rd(0x460E5CD0, 4):08x}", flush=True)
        for h_ in hooks:
            u.hook_del(h_)
        print("      calls during the load:\n        " + "\n        ".join(trace[:60]), flush=True)
        check(rd(syms["cl_nproj"], 1) >= n0 + 1, f"the project load went through cl_projload ({rd(syms['cl_nproj'], 1) - n0} pass(es))")
        check(not any(svalid()), "after the load: no saved sequence")
        check(snapok() == 0xFFFF, f"every bank has its snapshot again (0x{snapok():04x})")
        same = [b for b in range(16) if oslab(0, b) == slab(0, b)]
        print(f"      banks whose pattern 1 equals its snapshot after the load: {same}", flush=True)
        for b in (0, 1):
            x, y = slab(0, b), oslab(0, b)
            d = [k for k in range(PATSTRIDE) if x[k] != y[k]]
            if d:
                print(f"      bank {b} pattern 1: {len(d)} bytes differ, first +0x{d[0]:x}: ram {x[d[0]:d[0]+8].hex()} "
                      f"snapshot {y[d[0]:d[0]+8].hex()}", flush=True)
        check(len(same) == 16, "the snapshot is the bank as it is after the load (all 16 banks)")
        check(rec(act, 0) == oslot(act, 0), "T1 equals its original after the load")
        check(state()["open"] == 0, "Clyps closed")

    print(f"\nscreens: {shots}")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)}): " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

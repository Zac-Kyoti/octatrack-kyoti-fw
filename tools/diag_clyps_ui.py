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
  * stock controls: a lone [PTN] tap and a lone [BANK] tap still open their SELECT windows;
  * E: saved sequences ([FUNC]+[YES] / [FUNC]+[NO]) and originals (first one wins, the ORIG
    cursor entry, [PAGE], [FUNC]+[PAGE] restore-all), byte for byte;
  * N: a NORMAL pattern converted to PER TRACK by a load, and the restore that undoes it: the
    whole slab comes back byte for byte;
  * P: a project load drops the saved sequences and the originals;
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
        return dict(open=rd(syms["cl_open"], 1), held=rd(syms["cl_held"], 1), loaded=rd(syms["cl_loaded"], 1),
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
    ovw = lambda pat: rd(syms["cl_ovalid"] + 2 * (bank * 16 + pat), 2)
    oslot = lambda pat, t: bytes(u.mem_read(syms["cl_bss"] + ((bank * 16 + pat) * 16 + t) * TRAC_A, TRAC_A))
    saved = lambda t: bytes(u.mem_read(syms["cl_bss"] + 4096 * TRAC_A + t * TRAC_A, TRAC_A))
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
          f"{rd(syms['cl_nproj'], 1)}")
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

    if "M" in a.only:
        # --- M: the MIDI side (needs a project with MIDI trigs on pattern 1, e.g. JAM2)
        print("M: MIDI key; TRACK 2; chord; slots; trig 2 loads pattern 2's M2; release")
        print(f"      MKI/MKII probe 0x46c8d18c = 0x{rd(0x46C8D18C, 4):08x}", flush=True)
        # stock's own audio <-> MIDI toggle, 0x40055548 -- what the MKI [MIDI] release reaches
        # (the emulator's probe word skips that path on a key tap)
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
        atrigs = [bin(int.from_bytes(rec(p, 1)[:8], "big")).count("1") for p in range(16)]
        print(f"      (audio T2 trigs per pattern {atrigs}: must NOT be what the slots show)", flush=True)
        print(f"      M2 trigs per pattern {trigs}  classes {cls}", flush=True)
        check(all((cls[p] == 2) == (trigs[p] > 0) for p in range(16)), "slots classify the MIDI records")
        src = mrec(1, 1)
        key(0x01, 1)
        key(0x01, 0)
        check(mrec(act, 1) == src, "trig 2 loaded pattern 2's M2 onto the playing pattern's M2")
        key(BANK, 0)
        key(PTN, 0)
        s = state()
        check(s["open"] == 0 and s["layers"] == base["layers"] and s["leds"] == base["leds"], "closed, layer lists at baseline")

    if "Y" in a.only:
        # --- Y: [YES] and DIRECT JUMP's toggle (the user, 2026-10-25): with the chord held [YES] does
        # nothing; latched, [PTN]+[YES] is the toggle (none in this image) and never loads
        print("Y: chord held + YES: nothing; latched [PTN]+[YES]: no load; then [YES] loads")
        before = rec(act)
        key(PTN, 1)
        key(BANK, 1)
        tap(YES)
        s = state()
        check(s["open"] == 1 and s["loaded"] == 0 and rec(act) == before, "chord held, [YES]: nothing")
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1, "latched")
        key(PTN, 1)
        tap(YES)
        s = state()
        check(s["open"] == 1 and rec(act) == before, "[PTN]+[YES] in Clyps: no load, Clyps stays")
        key(PTN, 0)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0, "[PTN] released: still latched, no SELECT PATTERN")
        tap(NO)
        s = state()
        check(s["open"] == 0 and s["layers"] == base["layers"] and s["leds"] == base["leds"], "[NO]: closed, layer lists at baseline")

    if "E" in a.only:
        # --- E: saved sequences and originals, transport stopped (PER TRACK playing pattern)
        print("E: [FUNC]+[YES] save; trig load keeps the original; ORIG entry; [FUNC]+[NO]; [PAGE]; restore-all")
        tap(0x10)
        act = rd(0x800065BE, 1)
        pre = {t: rec(act, t) for t in range(3)}
        p = next(q for q in range(16) if q != act and all(rec(q, t) != pre[t] for t in range(3)))
        print(f"      playing {act}, source slot {p}, originals word 0x{ovw(act):04x}", flush=True)
        check((ovw(act) & 7) == 0, "no original yet for T1-T3 on the playing pattern")
        key(PTN, 1)
        key(BANK, 1)
        key(FUNC, 1)
        tap(YES)
        s = state()
        check(svalid()[0] == 1 and saved(0) == pre[0], "[FUNC]+[YES]: T1's sequence saved, byte for byte")
        check(s["open"] == 1 and s["flash"] == 1, "Clyps stays; the header shows SAVED")
        shot("E1_saved")
        key(FUNC, 0)
        check(state()["flash"] == 1, "SAVED still shown after [FUNC] is released")
        key(p, 1)
        key(p, 0)
        check(rec(act, 0) == rec(p, 0), f"trig {p + 1}: loaded")
        check(ovw(act) & 1 and oslot(act, 0) == pre[0], "the load kept T1's original, byte for byte")
        for _ in range(16 - p):
            tap(DOWN)
        check(state()["cur"] == 16, "DOWN past slot 16: the ORIG entry")
        shot("E2_orig")
        tap(DOWN)
        check(state()["cur"] == 0, "DOWN from ORIG wraps to slot 1")
        tap(UP)
        check(state()["cur"] == 16, "UP from slot 1: ORIG")
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 0, "release after a load closes")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1, "latched")
        key(FUNC, 1)
        tap(NO)
        key(FUNC, 0)
        s = state()
        check(s["open"] == 0, "[FUNC]+[NO] in latched: loaded, closed")
        check(rec(act, 0) == pre[0], "[FUNC]+[NO]: the saved sequence is back on T1")
        check(ovw(act) & 1 and oslot(act, 0) == pre[0], "the original is still the first one")
        key(PTN, 1)
        key(BANK, 1)
        key(p, 1)
        key(p, 0)
        tap(PAGE)
        s = state()
        check(rec(act, 0) == pre[0] and not (ovw(act) & 1), "held: trig, then [PAGE]: the original is back and dropped")
        check(s["open"] == 1 and s["loaded"] == 1, "held: Clyps stays")
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 0, "released: closed")
        key(PTN, 1)
        key(BANK, 1)
        tap(PAGE)
        s = state()
        check(s["open"] == 1 and s["loaded"] == 0, "[PAGE] with no original: nothing")
        key(BANK, 0)
        key(PTN, 0)
        tap(NO)
        key(PTN, 1)
        key(BANK, 1)
        for t in range(3):
            tap(0x10 + t)
            key(p, 1)
            key(p, 0)
        check((ovw(act) & 7) == 7 and all(oslot(act, t) == pre[t] for t in range(3)), "T1-T3 loaded: three originals")
        key(FUNC, 1)
        tap(PAGE)
        key(FUNC, 0)
        check((ovw(act) & 7) == 0 and all(rec(act, t) == pre[t] for t in range(3)), "[FUNC]+[PAGE]: all three back")
        key(BANK, 0)
        key(PTN, 0)
        s = state()
        check(s["open"] == 0 and s["layers"] == base["layers"] and s["leds"] == base["leds"], "closed, layer lists at baseline")
        tap(0x10)

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
            key(PTN, 1)
            key(BANK, 1)
            key(src, 1)
            key(src, 0)
            key(BANK, 0)
            key(PTN, 0)
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
            after = slab(nrm)
            diff = [i for i in range(PATSTRIDE) if after[i] != before[i]]
            check(not diff and ovw(nrm) == 0, f"[PAGE]: the whole slab is back, byte for byte ({len(diff)} bytes differ"
                  + (f", first at +0x{diff[0]:x})" if diff else ")"))
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.seq_select_live(bank, act)
            rt.run(ms=300)

    if "P" in a.only:
        # --- P: a project load drops the saved sequences and the originals
        print("P: save + load, then LOAD PROJECT again")
        tap(0x10)
        act = rd(0x800065BE, 1)
        p = next(q for q in range(16) if q != act and rec(q, 0) != rec(act, 0))
        key(PTN, 1)
        key(BANK, 1)
        key(FUNC, 1)
        tap(YES)
        key(FUNC, 0)
        key(p, 1)
        key(p, 0)
        key(BANK, 0)
        key(PTN, 0)
        n0 = rd(syms["cl_nproj"], 1)
        check(svalid()[0] == 1 and ovw(act) & 1, "a saved sequence and an original are held")
        rt.load_project_live("OCTABAM", staged, run_ms=6000)
        rt.run(ms=300)
        ov = bytes(u.mem_read(syms["cl_ovalid"], 512))
        check(rd(syms["cl_nproj"], 1) == n0 + 1, "the project load went through cl_projload")
        check(not any(ov) and not any(svalid()), "after the load: no original, no saved sequence")
        check(state()["open"] == 0, "Clyps closed")

    print(f"\nscreens: {shots}")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)}): " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

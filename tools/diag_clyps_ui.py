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
  * R: naming ([FUNC]+[BANK] in Clyps): stock's editor; the name follows loads, temp saves, ORIG;
  * S: names on the card: SAVE PROJECT / CARD SYNC / RELOAD PROJECT / LOAD PROJECT round trips;
  * T: temp save / reload outside Clyps ([YES] / [NO] + TRACK), ARM / DISARM on a quick tap only;
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
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(os.environ.get("CLYPS_SYMS", ROOT / "out/clyps_syms.txt")).read_text().splitlines())}
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

    # The type-0 tail posts below are made only in the scenarios that test what Clyps does from the
    # UI tail (K, M). Emulator only: with them in every scenario, S faulted at its first key ('rte
    # ... not a 4-word frame' / an unmapped frame read) once enough had run before it (A..T+G..R;
    # every shorter prefix passes, and the full run passes without them).
    posttail = [False]

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
        # on hardware every key event is a message of the SYS task's loop, and Clyps' UI tail
        # (0x40062d1c) runs after each one; here set_key_state is called directly. Post a type-0
        # message: the loop's range check sends it straight to that tail, nothing else runs.
        if posttail[0] and not os.environ.get("CLYPS_NOTAIL"):     # CLYPS_NOTAIL: the pre-CLYPG harness
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
            rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
        rt.run(ms=settle)

    def tailmsg():
        # one type-0 SYS message: the UI tail runs (it follows held flags), as after a key on hardware
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
        rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
        rt.run(ms=60)

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
    # FULL loads (scope §1.7): a track's Part slice (as patch_clyps.s cl_slA / cl_slM)
    PART_OFF, PARTSZ = 0x8ED80, 0x18B2
    # one bank of the originals: CL8 and later 16 slabs + 4 Parts; CL7 and older images: CLYPS_SNAP_BANK=0x9b340
    SNAP_BANK = int(os.environ.get("CLYPS_SNAP_BANK", "0x95048"), 0)
    SLA = [(0x000, 1, 1, 1, 0), (0x008, 1, 1, 1, 0), (0x012, 2, 2, 1, 0), (0x022, 1, 1, 1, 0),
           (0x02A, 30, 30, 1, 0), (0x1DA, 30, 30, 1, 0), (0x11A, 24, 24, 1, 0), (0x2F2, 30, 30, 1, 0),
           (0x2CA, 5, 5, 1, 0), (0x602, 12, 12, 1, 0), (0x662, 32, 32, 16, 0x100), (0x1662, 1, 1, 16, 10),
           (0x1702, 16, 16, 1, 0), (0x1782, 2, 2, 1, 0)]
    SLM = [(0x3E2, 32, 32, 1, 0), (0x4E2, 36, 36, 1, 0), (0x1792, 16, 16, 1, 0), (0x1812, 2, 2, 1, 0)]

    def partbase(b, pat, img=None):
        img = BLOB if img is None else img
        st = SNAP_BANK if img == syms["cl_bss"] else BANKSTRIDE   # the originals' banks are shorter
        pi = rd(img + b * st + pat * PATSTRIDE + 0x8E57, 1) & 3
        return img + b * st + PART_OFF + pi * PARTSZ

    def pslice(t, base):
        segs, k = (SLA, t) if t < 8 else (SLM, t - 8)
        out = b""
        for off, stride, size, count, step in segs:
            o = off + stride * k
            for _ in range(count):
                out += bytes(u.mem_read(base + o, size))
                o += step
        return out
    slab = lambda pat, b=None: bytes(u.mem_read(BLOB + (bank if b is None else b) * BANKSTRIDE + pat * PATSTRIDE, PATSTRIDE))
    BANKSZ = SNAP_BANK
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
    # the emulator boots with the SET DATE/TIME dialog up (its layer 0x400d0ed6): [NO] dismisses it
    # first, or the first stock [NO] of a scenario would, and the baseline would be wrong
    tap(NO)
    rt.run(ms=200)
    base = state()
    print(f"baseline: layers {[hex(x) for x in base['layers']]} leds {[hex(x) for x in base['leds']]}")
    act = rd(0x800065BE, 1)
    print(f"playing pattern {act}, bank {bank}, track {rd(0x80000000, 1)}; project loads seen by Clyps: "
          f"{rd(syms['cl_nproj'], 1)}; snapshots 0x{snapok():04x}")
    shot("00_base")

    def closed_ok(what):
        s_ = state()
        if s_["layers"] != base["layers"] or s_["leds"] != base["leds"]:
            print(f"      layers {[hex(x) for x in s_['layers']]} leds {[hex(x) for x in s_['leds']]} "
                  f"(cl_tlayer 0x{syms['cl_tlayer']:08x}, cl_layer 0x{syms['cl_layer']:08x})", flush=True)
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
        check(led(3) == (1, 0), "slot 4 (the box) is red (cl_blink flashes it on hardware)")
        check(led(act) == (1, 0), "your pattern is still red")
        flk = lambda: (rd(syms["cl_flk"], 1), rd(syms["cl_fph"], 1))
        f0 = flk()
        check(f0[0] > 0, f"the load confirmation runs after the load (ticks left, phase) = {f0}")
        # route A runs no UI tick (task 0x40056c40's 1/60 s message): call the tick's patched site
        # (0x40056c28 -> cl_uitick -> stock's toast countdown) as one tick does
        seen, trace = set(), []
        for _ in range(35):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(0x40056C28, budget=600000)
            seen.add(rd(syms["cl_fph"], 1))
            trace.append(rd(syms["cl_fph"], 1))
        flips = sum(1 for i in range(1, len(trace)) if trace[i] != trace[i - 1])
        print(f"      phases per tick: {''.join(map(str, trace))} ({flips} changes)", flush=True)
        # sampled after each tick: the first inverted span starts at the load (tick 0), so it shows 4
        check(trace[:30].count(1) == 14 and flips == 5, "... 3 inverted / normal cycles of 5 ticks each")
        check(flk() == (0, 0) and seen == {0, 1}, f"... flashes (phases seen {sorted(seen)}) and ends by "
              f"itself within 30 ticks = 0.5 s (now {flk()})")
        key(3, 1)
        key(3, 0)
        tap(DOWN)
        check(flk() == (0, 0), "an arrow during the confirmation stops it at once")
        tap(UP)
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
        check(led(c1) == (1, 1), "the box's slot (not the track's sequence) is solid yellow (the user, 2026-11-04)")
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
        # [FUNC]+TRACK: stock's FUNC sub-map mute 0x40083dfc (it toggles through 0x4007d6a4 /
        # 0x4007d7b0); our FUNC sub-map no longer shadows it. (0x40033970 is NOT a readable mute
        # state -- it did not change with a real mute: measured.)
        def mute_press():
            hits = []
            hs = [u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: hits.append(ad), begin=x, end=x)
                  for x in (0x40083DFC, 0x4007D6A4, 0x4007D7B0)]
            key(FUNC, 1)
            tap(0x11)
            key(FUNC, 0)
            for h_ in hs:
                u.hook_del(h_)
            return hits
        h1 = mute_press()
        check(0x40083DFC in h1 and (0x4007D6A4 in h1 or 0x4007D7B0 in h1) and state()["open"] == 1
              and rd(0x80000000, 1) == 2,
              f"[FUNC]+TRACK 2 in Clyps: stock's mute handler runs ({[hex(x) for x in h1]}); Clyps stays, track kept")
        h2 = mute_press()
        check(0x40083DFC in h2, f"... and again ({[hex(x) for x in h2]})")
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
        check(state()["showwin"] == 0, "[BANK] alone, pressed: no window yet (SELECT BANK on release)")
        key(BANK, 0)
        s = state()
        check(s["showwin"] != 0, "[BANK] alone, released: SELECT BANK opens")
        shot("D2_selbank")
        tap(NO)
        check(state()["showwin"] == 0 and state()["layers"] == base["layers"], "[NO]: closed, layers at baseline")

    if "M" in a.only:
        # --- M: the MIDI side (needs a project with MIDI trigs on pattern 1, e.g. JAM2)
        print("M: MIDI key; TRACK 2; chord; slots; trig 2 loads pattern 2's M2; [MIDI] in Clyps; NO")
        posttail[0] = True
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
        msl = pslice(9, partbase(bank, 1))
        dsl = pslice(9, partbase(bank, act))
        msl_same = msl == dsl
        key(0x01, 1)
        key(0x01, 0)
        check(mrec(act, 1) == src, "trig 2 loaded pattern 2's M2 onto the playing pattern's M2")
        check(pslice(9, partbase(bank, act)) == dsl, "... the sequence only: M2's track settings stay (SEQ)")
        key(FUNC, 1)
        key(0x01, 1)
        key(0x01, 0)
        key(FUNC, 0)
        check(pslice(9, partbase(bank, act)) == msl, "[FUNC] + trig 2: with pattern 2's track settings (ALL)"
              + (" -- the two Parts' M2 slices were already equal" if msl_same else ""))
        # the [MIDI] key inside Clyps (not ours): the view and the grid follow the side
        lastt = lambda: rd(syms["cl_lastt"], 1)
        trk = lambda: (rd(0x80000000, 1) & 7) + (8 if rd(0x80000012, 4) else 0)
        for side in ("audio", "MIDI"):
            m0 = rd(0x80000012, 4)
            key(0x35, 1)
            key(0x35, 0)
            check(state()["open"] == 1 and (rd(0x80000012, 4) != 0) != (m0 != 0) and lastt() == trk(),
                  f"[MIDI] in Clyps: on the {side} side, the view and grid follow (track {trk()}, "
                  f"redrawn for {lastt()})")
            shot(f"M_side_{side}")
        tap(NO)
        closed_ok("[NO]")
        posttail[0] = False

    if "Y" in a.only:
        # --- Y: [YES] loads the box; the chord + [YES] and [PTN]+[YES] never load
        print("Y: chord + YES = ORIG PTN+PART (closes if the chord opened Clyps); PTN+YES: nothing; YES loads the box; NO")
        key(PTN, 1)
        key(BANK, 1)
        tap(YES)
        check(state()["open"] == 0 and slab(act) == oslab(act),
              "chord (begun outside) + [YES]: the pattern as loaded (ORIG PTN+PART), Clyps closes")
        key(BANK, 0)
        key(PTN, 0)
        closed_ok("... keys released")
        before = rec(act)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        tap(YES)
        check(state()["open"] == 1 and rec(act) == before, "[PTN]+[YES]: no load, Clyps stays")
        key(PTN, 0)
        key(PTN, 1)
        key(BANK, 1)
        tap(YES)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1 and slab(act) == oslab(act), "the chord pressed inside + [YES]: restore, Clyps stays")
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
        key(BANK, 1)                       # (chord + [PAGE] = ORIG PTN + PART; begun outside: closes)
        tap(PAGE)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 0, "chord + [PAGE], the chord begun outside: Clyps closes")
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
        check(state()["cur"] == 15, "16 slots: UP from slot 1 wraps to slot 16 (no 17th ORIG entry, 2026-11-02)")
        while state()["cur"] != act:
            tap(UP)
        check(rd(syms["cl_hdrst"], 1) == 0 and state()["cur"] == act and state()["sbank"] == bank,
              "the box on your own pattern's slot = the ORIG entry")
        shot("E0_orig")
        tap(PAGE)
        check(state()["open"] == 1 and rec(act, 0) == pre[0], "[PAGE] on an original track: nothing")
        key(p, 1)
        key(p, 0)
        check(rec(act, 0) == rec(p, 0) and oslot(act, 0) == pre[0], f"trig {p + 1}: loaded; the original untouched")
        shot("E1_loaded")
        tap(PAGE)
        check(state()["open"] == 1 and rec(act, 0) == pre[0], "[PAGE]: the load undone, Clyps stays")
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
        key(PTN, 1)                        # the chord pressed inside Clyps
        key(BANK, 1)
        tailmsg()
        check(rd(syms["cl_hdrst"], 1) == 2, "chord held: the header shows ORIG PTN + PART")
        tap(PAGE)
        key(BANK, 0)
        key(PTN, 0)
        check(all(rec(act, t) == pre[t] for t in range(3)), "chord + [PAGE]: all three back")
        check(state()["open"] == 1, "begun inside Clyps: Clyps stays")
        tap(NO)
        closed_ok("[NO]")
        tap(0x10)

    if "G" in a.only:
        # --- G: the source label on your pattern's slot (screens; the label text is drawn there)
        print("G: temp save T1; load slot 3: your slot reads 'A3 n TRG'; T1+NO reload: 'SAVED TRK'; PAGE: plain")
        tap(0x10)
        key(0x10, 1)
        tap(YES)
        key(0x10, 0)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        key(2, 1)
        key(2, 0)
        shot("G1_source")
        tap(NO)
        key(0x10, 1)
        tap(NO)
        key(0x10, 0)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        shot("G2_saved")
        tap(PAGE)
        shot("G3_plain")
        tap(NO)
        closed_ok("[NO]")

    if "T" in a.only:
        # --- T: temp save / reload (the user, 2026-11-02): TRACK held + [YES] = save, + [NO] = reload, outside
        # and inside Clyps; stock ARM / DISARM REC TRK only while the Recording Setup menu is open
        print("T: T2+YES save; edit; T2+NO reload (stopped, then twice while playing); T3+NO nothing saved; "
              "T2+T4 together; inside Clyps; Recording Setup open: stock ARM")
        ARMA, ARMB = 0x46C7FF64, 0x46C803D4
        arm = lambda: (rd(ARMA, 2), rd(ARMB, 2))

        def chord(trk, k):                  # TRACK(s) held first, then [YES] / [NO]
            for t_ in trk:
                key(0x10 + t_, 1)
            tap(k)
            for t_ in trk:
                key(0x10 + t_, 0)
        tap(0x10)
        act = rd(0x800065BE, 1)
        pre2 = rec(act, 1)
        m0 = arm()
        chord([1], YES)
        check(svalid()[1] == 1 and saved(1) == pre2, "T2 + [YES]: T2 saved, byte for byte")
        check(arm() == m0, f"... and nothing armed (stock's ARM is off outside Recording Setup: {m0} -> {arm()})")
        check(rd(0x80000000, 1) == 0, f"... and T1 stays the active track: releasing T2 after the chord selects "
              f"nothing (now T{rd(0x80000000, 1) + 1}; the user, 2026-11-02)")
        ad = BLOB + bank * BANKSTRIDE + act * PATSTRIDE + TRAC_A
        edit = lambda: u.mem_write(ad, bytes([rd(ad, 1) ^ 0x80]))
        edit()
        check(rec(act, 1) != pre2, "T2 edited")
        tpart = partbase(bank, act)
        psl2 = pslice(1, tpart)
        mp = tpart + 0x2A + 30 * 1             # T2's machine page 1, first value
        u.mem_write(mp, bytes([rd(mp, 1) ^ 0x55]))
        chord([1], NO)
        check(rec(act, 1) == pre2, "T2 + [NO]: T2's temp save is back (stopped: at once)")
        check(pslice(1, tpart) == psl2, "... with its machine / FX / pages as saved (ALL)")
        check(arm() == m0, "... and nothing disarmed")
        pre3 = rec(act, 2)
        check(svalid()[2] == 1 and saved(2) == oslot(act, 2), "T3's temp save is preloaded with its original")
        a3 = BLOB + bank * BANKSTRIDE + act * PATSTRIDE + 2 * TRAC_A
        u.mem_write(a3, bytes([rd(a3, 1) ^ 0x80]))
        chord([2], NO)
        check(rec(act, 2) == pre3, "T3 edited, T3 + [NO] with no temp save made: its original back (preloaded)")
        pre4 = rec(act, 3)
        chord([1, 3], YES)
        check(svalid()[3] == 1 and saved(3) == pre4 and saved(1) == pre2, "T2 + T4 + [YES]: both saved")
        # playing: each reload is a cue landing at the track's next step -- twice, an edit before each
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.internal_clock()
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.start_transport_live()
        rt.run(ms=300)
        for n_ in (1, 2):
            edit()
            chord([1], NO)
            rt.run(ms=600)
            check(rec(act, 1) == pre2, f"playing: T2 + [NO] reload #{n_} lands the temp save "
                  f"(cue 0x{rd(syms['cl_cue'] + 2, 2):04x})")
        key(0x27, 1)
        key(0x27, 0)
        rt.run(ms=300)
        # inside Clyps: the same chords
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        edit()
        chord([1], NO)
        check(state()["open"] == 1 and rec(act, 1) == pre2, "inside Clyps: T2 + [NO] reloads, Clyps stays")
        edit()
        e2 = rec(act, 1)
        chord([1], YES)
        check(saved(1) == e2, "inside Clyps: T2 + [YES] saves")
        edit()
        chord([1], NO)
        check(rec(act, 1) == e2, "... and that save reloads")
        # the Recording Setup menu over Clyps: its keys are stock's, TRACK + [YES] / [NO] = ARM / DISARM
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(0x4002FEC4, budget=600000)
        rt.run(ms=100)
        rs = rd(0x460D10CC, 4)
        sv = saved(1)
        calls = {"arm": 0, "disarm": 0}       # stock's ARM / DISARM REC TRK reached (a code hook: the
        def on_arm(uc, ad, sz, ud):           # masks they write are per-frame state, cleared in between)
            calls["arm" if ad == 0x400834D8 else "disarm"] += 1
        hk = [u.hook_add(er.eb.UC_HOOK_CODE, on_arm, begin=x_, end=x_) for x_ in (0x400834D8, 0x40083488)]
        chord([1], YES)
        a1_ = dict(calls)
        chord([1], NO)
        for h_ in hk:
            u.hook_del(h_)
        check(rs != 0 and a1_["arm"] >= 1 and a1_["disarm"] == 0 and saved(1) == sv,
              f"Recording Setup open: T2 + [YES] reaches stock's ARM REC TRK ({a1_}), no temp save")
        check(calls["disarm"] >= 1, f"... T2 + [NO] reaches stock's DISARM ({calls})")
        c0, b0 = state()["cur"], state()["bank"]
        r0 = rec(act, 0)
        tap(DOWN)
        tap(4)
        check(state()["cur"] == c0 and state()["bank"] == b0 and rec(act, 0) == r0,
              f"... DOWN and a trig leave Clyps alone")
        tap(NO)                                # closes the menu (its layer's [NO])
        rt.run(ms=100)
        check(rd(0x460D10CC, 4) == 0 and state()["open"] == 1, "[NO] closes Recording Setup; Clyps still open")
        tap(DOWN)
        check(state()["cur"] == (c0 + 1) % 16, "... and Clyps has its keys back")
        tap(NO)
        closed_ok("[NO]")

    if "R" in a.only:
        # --- R: naming ([FUNC]+[BANK] = EDIT in Clyps): stock's editor on the box's sequence
        print("R: name slot 3 'BASS1'; YES stores, Clyps stays; NO keeps; the name follows a load, a temp save, ORIG")
        EDITOR = 0x460E7612
        nidx = lambda b, pt, t: (b * 16 + pt) * 16 + t
        name = lambda base_, i: bytes(u.mem_read(base_ + i * 10, 10)).split(b"\0")[0]
        NAMES = syms["cl_bss"] + 16 * BANKSZ + 16 * TRAC_A
        SNAMES = NAMES + 4096 * 10
        tap(0x10)
        act = rd(0x800065BE, 1)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        while state()["cur"] != 2:
            tap(DOWN)
        key(FUNC, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(FUNC, 0)
        check(rd(EDITOR, 4) != 0, "[FUNC]+[BANK]: the name editor is up")
        check(rd(0x400D0730, 4) == 9, f"its input limit is 9 characters (max-length word {rd(0x400D0730, 4)})")
        shot("R1_editor")
        # type into the editor's own working copy (space-padded, 0x460e743c; it copies it back on [YES])
        u.mem_write(0x460E743C, b"BASS1".ljust(9, b" "))
        tap(YES)
        s = state()
        check(rd(EDITOR, 4) == 0 and s["open"] == 1, "[YES]: the editor closed, Clyps still open")
        check(name(NAMES, nidx(bank, 2, 0)) == b"BASS1", f"slot 3 of T1 is named 'BASS1' ({name(NAMES, nidx(bank, 2, 0))})")
        key(FUNC, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(FUNC, 0)
        u.mem_write(0x460E743C, b"XXXX".ljust(9, b" "))
        tap(NO)
        s = state()
        check(rd(EDITOR, 4) == 0 and s["open"] == 1 and name(NAMES, nidx(bank, 2, 0)) == b"BASS1",
              "[NO] in the editor: the old name kept, Clyps still open")
        key(2, 1)
        key(2, 0)
        check(name(NAMES, nidx(bank, act, 0)) == b"BASS1", "loading slot 3: your slot now carries 'BASS1'")
        tap(NO)
        closed_ok("[NO]")
        key(0x10, 1)
        tap(YES)
        key(0x10, 0)
        check(name(SNAMES, 0) == b"BASS1", "a temp save of T1 carries the name")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        tap(PAGE)
        check(name(NAMES, nidx(bank, act, 0)) == b"", "[PAGE]: back to the name it had when loaded (none)")
        tap(NO)
        closed_ok("[NO]")

    if "S" in a.only:
        # --- S: names on the card (clypsNN.work / .strd), round trips through stock's own operations
        print("S: name 'BASS1'; SAVE PROJECT; rename 'TEMP' + CARD SYNC; RELOAD PROJECT -> 'BASS1'; LOAD PROJECT -> 'BASS1'")
        NAMES = syms["cl_bss"] + 16 * BANKSZ + 16 * TRAC_A
        nm = lambda pt, t=0: bytes(u.mem_read(NAMES + ((bank * 16 + pt) * 16 + t) * 10, 10)).split(b"\0")[0]

        def name_slot3(text):
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)
            key(PTN, 0)
            while state()["cur"] != 2:
                tap(DOWN)
            key(FUNC, 1)
            key(BANK, 1)
            key(BANK, 0)
            key(FUNC, 0)
            u.mem_write(0x460E743C, text.ljust(9, b" "))
            tap(YES)
            tap(NO)

        trace = []
        if os.environ.get("CLYPS_TRACE"):
            tnames = {syms[k]: k for k in ("cl_hwrite", "cl_nwrite", "cl_hstorep", "cl_ncopy", "cl_hrestp",
                                           "cl_hstoreb", "cl_hrestb", "cl_nread", "cl_ldexit", "cl_named")}
            tnames.update({0x40016864: "FOPEN", 0x400166b8: "FWRITE", 0x4001677c: "FCLOSE", 0x40016388: "FCOPY",
                           0x400919de: "writer.resume", 0x4008f0aa: "store.resume", 0x400005a6: "sched.rte"})

            def thk(uc, addr, size, user):
                sp_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
                trace.append(f"{tnames[addr]:14} sp={sp_:08x} task={rt._name(rt._cur()) if hasattr(rt, '_cur') else '?'}")
                del trace[:-80]
            for ad_ in tnames:
                u.hook_add(er.eb.UC_HOOK_CODE, thk, begin=ad_, end=ad_)

        def dump_fault():
            # who was being switched to, and what each task's saved frame holds
            sp_ = u.reg_read(er.eb.UC_M68K_REG_A7)
            print(f"      fault: a7=0x{sp_:08x} pc=0x{rt.pc:08x} cur TCB 0x{rt._cur():08x} ({rt._name(rt._cur())})", flush=True)
            print("      bytes at a7-16: " + bytes(u.mem_read(sp_ - 16, 48)).hex(" ", 4), flush=True)
            for tcb, nm_ in ((0x460ddde4, "worker"), (0x460bcc2c, "storage"), (0x460d59d4, "UI"), (0x460d4f80, "keyrep"),
                             (0x46c7bed8, "sys"), (0x46c7ae84, "main"), (0x46c7fb0c, "midi"), (0x460fab80, "p2a"),
                             (0x460ffd44, "p2b"), (0x460e0e38, "p2c"), (0x46105508, "p1b")):
                a7_ = rd(tcb + 0x48, 4)
                try:
                    fr = bytes(u.mem_read(a7_, 8)).hex(" ", 2)
                except Exception:
                    fr = "unreadable"
                print(f"        {nm_:8} TCB 0x{tcb:08x}: saved a7 0x{a7_:08x} frame {fr}", flush=True)

        def worker(fn, ms, args=()):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(fn, args=args, budget=600000)
            try:
                rt.run(ms=ms)
            except Exception:
                print("      trace:\n        " + "\n        ".join(trace[-60:]), flush=True)
                dump_fault()
                raise

        if os.environ.get("CLYPS_SETTLE"):
            rt.run(ms=int(os.environ["CLYPS_SETTLE"]))   # bisect: let the boot load's worker finish first
        tap(0x10)
        name_slot3(b"BASS1")
        check(nm(2) == b"BASS1", "slot 3 named 'BASS1'")
        ae = BLOB + bank * BANKSTRIDE + rd(0x800065BE, 1) * PATSTRIDE + TRAC_A
        u.mem_write(ae, bytes([rd(ae, 1) ^ 0x80]))      # an unsaved edit on T2 before the save
        worker(0x40022850, 8000)          # SAVE PROJECT (op 17): bank .work + .strd copies
        a_ = rd(0x800065BE, 1)
        check(oslot(a_, 1) == rec(a_, 1) and saved(1) == rec(a_, 1),
              "SAVE PROJECT: T2's original and temp save = T2 as saved (the user, 2026-11-02)")
        name_slot3(b"TEMP")
        # CARD SYNC (op 7): the current bank's .work -> clyps01.work = TEMP. Entered past its own
        # project-folder check (0x400255ec does card FAT lookups, which block the main task the
        # harness runs posters on -- emu_rtos.load_project_live's warning; it crashed this gate)
        worker(0x40022CFC, 8000, args=(0,))
        check(nm(2) == b"TEMP", "renamed 'TEMP' (and synced to clyps01.work)")
        rt.load_project_live("OCTABAM", staged, run_ms=6000)
        rt.run(ms=2000)
        check(nm(2) == b"TEMP", f"LOAD PROJECT after the sync reads 'TEMP': clyps01.work was written ({nm(2)})")
        n0 = rd(syms["cl_nproj"], 1)
        worker(0x400227C8, 8000)          # RELOAD PROJECT (op 19: .strd -> .work), then its op-4 load
        for waited in range(1, 16):
            if rd(syms["cl_nproj"], 1) != n0 and snapok() == 0xFFFF:
                break
            rt.run(ms=1000)
        print(f"      reload: project loads {n0} -> {rd(syms['cl_nproj'], 1)} after {waited} s", flush=True)
        if rd(syms["cl_nproj"], 1) == n0:
            print("      (the reload's own load was not posted here: LOAD PROJECT instead)", flush=True)
            rt.load_project_live("OCTABAM", staged, run_ms=6000)
            rt.run(ms=2000)
        check(nm(2) == b"BASS1", f"after RELOAD PROJECT: 'BASS1' again, from clyps01.strd ({nm(2)})")
        rt.load_project_live("OCTABAM", staged, run_ms=6000)
        rt.run(ms=2000)
        check(nm(2) == b"BASS1", f"after LOAD PROJECT: 'BASS1' from clyps01.work ({nm(2)})")
        # the bank path: SAVE BANK (op 18: .work + clyps01.work -> .strd), RELOAD BANK (op 20 + op 6)
        name_slot3(b"BANKX")
        worker(0x40022808, 8000, args=(1,))      # SAVE BANK: its argument is the bank mask (1 << bank A)
        name_slot3(b"TEMP2")
        worker(0x40022CFC, 8000, args=(0,))      # CARD SYNC: clyps01.work = TEMP2
        n0 = rd(syms["cl_nproj"], 1)
        worker(0x40022778, 8000, args=(1,))      # RELOAD BANK A: .strd -> .work, then its op-6 load
        for waited in range(1, 16):
            if nm(2) == b"BANKX":
                break
            rt.run(ms=1000)
        check(nm(2) == b"BANKX", f"after SAVE BANK, a sync and RELOAD BANK: 'BANKX' from clyps01.strd ({nm(2)})")
        check(state()["open"] == 0, "Clyps closed")

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
            if rd(0x80000002, 1) == bank:
                mm = bytes(u.mem_read(0x1001614E + nrm * PATSTRIDE, PATSTRIDE))
                md = [hex(i) for i in range(PATSTRIDE) if mm[i] != s9[i]]
                check(not md, f"... the NVRAM mirror has the whole converted slab ({len(md)} bytes differ {md[:6]})")
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
        key(0x10, 1)                        # temp save T1, outside Clyps
        tap(YES)
        key(0x10, 0)
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
        a2 = rd(0x800065BE, 1)
        check(all(svalid()) and all(saved(t_) == rec(a2, t_) for t_ in range(8)),
              "after the load: every temp save = the track as loaded (its original; the user, 2026-11-02)")
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


    if "L" in a.only:
        # --- L: reloads from the card (scope §1.8): SAVE PROJECT, edit in RAM, reload, compare
        print("L: [PTN]+TRACK = card SEQ; [BANK]+TRACK = card ALL (track slice); chord+TRACK nothing; chord+trig = pattern")
        ndl0 = rd(syms["rq_ndir"], 4) if "rq_ndir" in syms else None
        print(f"      side at start: {'MIDI' if rd(0x80000012, 4) else 'audio'}", flush=True)
        if rd(0x80000012, 4):              # L reloads audio T1: start on the audio side (as U)
            tap(0x35)
        def worker(fn, ms, args=()):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(fn, args=args, budget=600000)
            rt.run(ms=ms)
        tap(0x10)
        act = rd(0x800065BE, 1)
        worker(0x40022850, int(os.environ.get("CLYPS_SAVE_MS", "8000")))   # SAVE PROJECT: the .strd = RAM now
        dst = partbase(bank, act)
        # bytes the bank file never holds (scope §10.1): an audio record's pad +0x899 and the slab tail
        # +0x8e5c..: a card reload legitimately differs there from RAM
        NOSER = {0x899 + k * TRAC_A for k in range(8)} | set(range(0x8E5C, PATSTRIDE))
        same_rec = lambda x, y: all(x[i] == y[i] for i in range(len(x)) if i != 0x899)
        same_slab = lambda x, y: all(x[i] == y[i] for i in range(len(x)) if i not in NOSER)
        pre0, pre1, preslab = rec(act, 0), rec(act, 1), slab(act)
        psl0, psl1 = pslice(0, dst), pslice(1, dst)
        prepart = bytes(u.mem_read(dst, PARTSZ))
        ad0 = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        def edit_rec(t):
            a_ = ad0 + t * TRAC_A
            u.mem_write(a_, bytes([rd(a_, 1) ^ 0x81]))
        def edit_slice(t):
            a_ = dst + 0x2A + 30 * t
            u.mem_write(a_, bytes([rd(a_, 1) ^ 0x55]))
        def settle():
            rt.run(ms=6000)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        s0 = state()
        edit_rec(0)
        edit_slice(0)
        hits = []
        def hk(name):
            ad_ = syms[name]
            return u.hook_add(er.eb.UC_HOOK_CODE,
                              lambda uc, ad, sz, ud: hits.append((name, uc.reg_read(er.eb.UC_M68K_REG_D0) & 0xFFFFFFFF)),
                              begin=ad_, end=ad_)
        hks = [hk(n) for n in ("cl_rlreq", "cl_rljob", "rj_ours", "rj_opened", "rj_parsed", "rj_fail", "rj_exit",
                               "rj_ok", "cl_rldone", "rd_ours") if n in syms]
        key(PTN, 1)
        key(0x10, 1)
        settle()
        key(0x10, 0)
        key(PTN, 0)
        for h_ in hks:
            u.hook_del(h_)
        print(f"      path: {[(n, hex(v)) for n, v in hits]}", flush=True)
        print(f"      toast 0x{rd(0x460D1E70, 4):08x} line1 {bytes(u.mem_read(syms['rq_line1'], 12))}", flush=True)
        dd = lambda x, y: [hex(i) for i in range(len(x)) if x[i] != y[i]][:12]
        print(f"      T1 record differs at {dd(rec(act, 0), pre0)}; slice differs at {dd(pslice(0, dst), psl0)}", flush=True)
        check(same_rec(rec(act, 0), pre0) and pslice(0, dst) != psl0 and state()["open"] == 1,
              "[PTN] + TRACK 1: T1's sequence from the card; its machine / FX stay; Clyps stays")
        edit_rec(0)
        edit_slice(1)
        key(BANK, 1)
        key(0x10, 1)
        settle()
        key(0x10, 0)
        key(BANK, 0)
        print(f"      ALL: T1 record differs at {dd(rec(act, 0), pre0)}; slice differs at {dd(pslice(0, dst), psl0)}", flush=True)
        check(same_rec(rec(act, 0), pre0) and pslice(0, dst) == psl0, "[BANK] + TRACK 1: T1's sequence AND its Part slice from the card")
        check(pslice(1, dst) != psl1, "... T2's slice untouched (not the whole Part)")
        check(state()["open"] == 1 and state()["showwin"] == 0, "... Clyps stays, no SELECT BANK")
        edit_rec(0)
        e0 = rec(act, 0)
        key(PTN, 1)
        key(BANK, 1)
        key(0x10, 1)
        settle()
        key(0x10, 0)
        key(BANK, 0)
        key(PTN, 0)
        check(rec(act, 0) == e0, "[PTN]+[BANK] + TRACK 1: no reload")
        edit_rec(2)
        key(PTN, 1)
        key(BANK, 1)
        key(act, 1)
        settle()
        key(act, 0)
        key(BANK, 0)
        key(PTN, 0)
        print(f"      toast 0x{rd(0x460D1E70, 4):08x} line1 {bytes(u.mem_read(syms['rq_line1'], 20))}", flush=True)
        print(f"      slab differs at {dd(slab(act), preslab)}; Part differs at {dd(bytes(u.mem_read(dst, PARTSZ)), prepart)}", flush=True)
        check(same_slab(slab(act), preslab) and bytes(u.mem_read(dst, PARTSZ)) == prepart,
              f"chord + trig {act + 1}: the whole pattern and its whole Part from the card")
        check(state()["open"] == 1, "... begun inside Clyps: Clyps stays")
        # another pattern, on a Part that is not sounding: that Part from the card, its edited mark follows
        # (equal to its SAVE PART copy -> cleared), and no other Part touched (the user, 2026-11-02)
        bb = BLOB + bank * BANKSTRIDE
        plink = lambda q_: rd(bb + q_ * PATSTRIDE + 0x8E57, 1) & 3
        q = next((x for x in range(16) if x != act and plink(x) != plink(act)), None)
        if q is None:
            check(False, "OT DEMO has a pattern on another Part than the playing one")
        else:
            pq = plink(q)
            pbase = bb + 0x8ED80 + pq * PARTSZ
            cardq = bytes(u.mem_read(pbase, PARTSZ))            # untouched since the SAVE PROJECT above
            u.mem_write(bb + 0x9504A + pq * PARTSZ, cardq)      # its SAVE PART copy = the card's Part
            u.mem_write(bb + 0x9B312 + pq, b"\x01")
            u.mem_write(pbase + 0x2A, bytes([rd(pbase + 0x2A, 1) ^ 0x55]))   # an edit, marked edited
            u.mem_write(bb + 0x95048, bytes([rd(bb + 0x95048, 1) | (1 << pq)]))
            others = {k: bytes(u.mem_read(bb + 0x8ED80 + k * PARTSZ, PARTSZ)) for k in range(4) if k != pq}
            key(PTN, 1)
            key(BANK, 1)
            key(q, 1)
            settle()
            key(q, 0)
            key(BANK, 0)
            key(PTN, 0)
            check(bytes(u.mem_read(pbase, PARTSZ)) == cardq and not rd(bb + 0x95048, 1) >> pq & 1,
                  f"chord + trig {q + 1} (Part {pq + 1}, not sounding): its Part from the card, edited mark cleared")
            check(all(bytes(u.mem_read(bb + 0x8ED80 + k * PARTSZ, PARTSZ)) == v for k, v in others.items()),
                  "... and no other Part touched")
        if ndl0 is not None:
            ndl = rd(syms["rq_ndir"], 4) - ndl0
            check(ndl >= 4, f"every card reload above read its chunks directly (the seek path: {ndl} direct reloads)")
        tap(NO)
        closed_ok("[NO]")

    if "Q" in a.only:
        # --- Q: [FUNC]+[MIDI] (the Parts menu) inside Clyps
        print("Q: Parts menu from Clyps")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        s0 = state()
        key(FUNC, 1)
        tap(0x35)
        key(FUNC, 0)
        s1 = state()
        print(f"      after [FUNC]+[MIDI]: open {s1['open']} win 0x{s1['win']:08x} layers {[hex(x) for x in s1['layers']]} "
              f"popup 0x{rd(0x460E5CD0, 4):08x}", flush=True)
        check(s1["layers"] != s0["layers"], "[FUNC]+[MIDI] in Clyps: stock's Parts menu takes the keys (a layer went up)")
        shot("Q1_parts")
        tap(NO)
        s2 = state()
        print(f"      after [NO]: open {s2['open']} layers {[hex(x) for x in s2['layers']]}", flush=True)
        check(s2["open"] == s1["open"], f"[NO] leaves the Parts menu (Clyps open: {s2['open']})")
        if s2["open"]:
            check(s2["layers"] == s0["layers"], "... back in Clyps, its layers on top again")
            tap(NO)
        closed_ok("closed")

    if "F" in a.only:
        # --- F: FULL loads ([FUNC] + trig; [FUNC]+[YES] on ORIG = ORIG SEQ+MCH/FX), stopped transport
        print("F: [FUNC]+trig loads the sequence + its Part slice; a plain trig does not; ORIG SEQ+MCH/FX")
        tap(0x10)
        act = rd(0x800065BE, 1)
        t = 0
        dst = partbase(bank, act)
        dsl0 = pslice(t, dst)
        others0 = [pslice(k, dst) for k in range(16) if k != t]
        cand = [(b, q) for b in range(16) for q in range(16)
                if (b, q) != (bank, act) and pslice(t, partbase(b, q)) != dsl0 and rec(q, 0, b) != rec(act, 0)]
        check(bool(cand), f"a source with another T1 slice exists ({len(cand)})")
        sb, sq = cand[0]
        ssl, srec = pslice(t, partbase(sb, sq)), rec(sq, 0, sb)
        print(f"      source bank {sb} pattern {sq + 1}; dest Part @0x{dst:08x}", flush=True)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        if (sb - bank) % 16:               # a [BANK] tap with no arrow would open SELECT BANK
            key(BANK, 1)
            for _ in range((sb - bank) % 16):
                tap(RIGHT)
            key(BANK, 0)
        # a plain trig first, on a slot with another slice: the Part stays
        plain = next((q for q in range(16) if q != sq and (sb, q) != (bank, act)
                      and pslice(t, partbase(sb, q)) != dsl0), None)
        if plain is not None:
            tap(plain)
            check(pslice(t, dst) == dsl0, f"plain trig {plain + 1}: the sequence only, the Part slice stays")
        key(FUNC, 1)
        print(f"      [FUNC] down: cl_fn {rd(syms['cl_fn'], 1)} layers {[hex(x) for x in state()['layers']]}", flush=True)
        r0 = rec(act, 0)
        key(sq, 1)
        print(f"      trig down: cur {state()['cur']} sbank {state()['sbank']} rec changed {rec(act, 0) != r0} "
              f"== src {rec(act, 0) == srec} slice == src {pslice(t, dst) == ssl} postf {list(bytes(u.mem_read(syms['cl_postf'], 16)))} "
              f"layers {[hex(x) for x in state()['layers']]}", flush=True)
        key(sq, 0)
        key(FUNC, 0)
        print(f"      [FUNC] up: cl_fn {rd(syms['cl_fn'], 1)} layers {[hex(x) for x in state()['layers']]}", flush=True)
        s = state()
        check(s["open"] == 1, "[FUNC]+trig: Clyps stays open")
        check(rec(act, 0) == srec, f"[FUNC]+trig {sq + 1}: the sequence")
        check(pslice(t, dst) == ssl, "... and T1's Part slice (machine, FX, pages, scene locks, designer)")
        check([pslice(k, dst) for k in range(16) if k != t] == others0, "... every other track's slice untouched")
        pi = rd(BLOB + bank * BANKSTRIDE + act * PATSTRIDE + 0x8E57, 1) & 3
        check(rd(BLOB + bank * BANKSTRIDE + 0x95048, 1) >> pi & 1, f"Part {pi + 1} marked edited")
        # back to ORIG with [FUNC]: the original sequence AND the original slice
        if (bank - sb) % 16:
            key(BANK, 1)
            for _ in range((bank - sb) % 16):
                tap(RIGHT)
            key(BANK, 0)
        n = 0
        while state()["cur"] != act and n < 20:
            tap(UP)
            n += 1
        check(state()["cur"] == act and state()["sbank"] == bank, "the box on ORIG (your own pattern's slot)")
        tap(YES)
        check(rec(act, 0) == oslot(act, 0) and pslice(t, dst) == ssl, "ORIG SEQ ([YES]): the sequence, not the slice")
        # make the Part's SAVE PART copy equal the Part as loaded, so the restore below makes the Part
        # equal to it: the edited mark must then clear (the user, 2026-10-30)
        bb0 = BLOB + bank * BANKSTRIDE
        pi0 = rd(bb0 + act * PATSTRIDE + 0x8E57, 1) & 3
        u.mem_write(bb0 + 0x9504A + pi0 * PARTSZ, bytes(u.mem_read(partbase(bank, act, syms["cl_bss"]), PARTSZ)))
        u.mem_write(bb0 + 0x9B312 + pi0, b"\x01")
        key(FUNC, 1)
        tap(YES)
        key(FUNC, 0)
        osl = pslice(t, partbase(bank, act, syms["cl_bss"]))
        check(rec(act, 0) == oslot(act, 0) and pslice(t, dst) == osl == dsl0,
              "ORIG SEQ+MCH/FX ([FUNC]+[YES]): the original sequence and slice")
        bb = BLOB + bank * BANKSTRIDE
        scopy = bytes(u.mem_read(bb + 0x9504A + pi * PARTSZ, PARTSZ))
        eq = bool(rd(bb + 0x9B312 + pi, 1)) and bytes(u.mem_read(dst, PARTSZ)) == scopy
        check(bool(rd(bb + 0x95048, 1) >> pi & 1) == (not eq),
              f"Part {pi + 1}'s edited flag follows its SAVE PART copy (equal now: {eq})")
        def ledbit(die):
            b_ = bytes(u.mem_read(0x460BA98C, 17))
            return (b_[die // 8] >> (die % 8)) & 1
        pled = lambda: rd(syms["cl_pled"], 1)
        check(pled() == 1 and all(ledbit(0x48 + 2 * k) and not ledbit(0x49 + 2 * k) for k in range(4)),
              "box on ORIG, the track original: all four page LEDs red")
        key(FUNC, 1)
        tap(sq)
        key(FUNC, 0)
        check(pslice(t, dst) == ssl and pled() == 0, "[FUNC]+trig again: ALL; the box left ORIG: page LEDs stock's")
        tap(PAGE)
        check(rec(act, 0) == oslot(act, 0) and pslice(t, dst) == ssl, "[PAGE] = ORIG SEQ: the sequence only")
        key(FUNC, 1)
        tap(PAGE)
        key(FUNC, 0)
        check(pslice(t, dst) == dsl0, "[FUNC]+[PAGE] = ORIG SEQ+MCH/FX: the slice too")
        key(FUNC, 1)                       # change T1 (FULL) and T2 (sequence), then chord + [PAGE]
        tap(sq)
        key(FUNC, 0)
        tap(0x11)
        tap(sq)
        tap(NO)
        key(PTN, 1)
        key(BANK, 1)
        tailmsg()
        check(state()["open"] == 1 and rd(syms["cl_hdrst"], 1) == 2 and pled() == 3,
              "the chord from outside: Clyps opens showing ORIG PTN + PART; page LEDs flashing red")
        tap(PAGE)
        key(BANK, 0)
        key(PTN, 0)
        opart = bytes(u.mem_read(partbase(bank, act, syms["cl_bss"]), PARTSZ))
        check(slab(act) == oslab(act) and bytes(u.mem_read(dst, PARTSZ)) == opart,
              "chord + [PAGE] = ORIG PTN + PART: the whole pattern and its whole Part as loaded")
        closed_ok("... and Clyps closes (the chord began outside)")
        tap(0x10)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        # while playing (the tick path): CHAIN AFTER = 1 step, so the cue lands at the next step
        sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        q0 = rd(sl + 0x8E56, 1)
        u.mem_write(sl + 0x8E56, bytes([1]))
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.internal_clock()                # the sequencer clock, as diag_clyps_landing.py drives it
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.start_transport_live()
        rt.run(ms=200)
        running = rd(0x800065B8, 4)
        key(FUNC, 1)
        tap(sq)
        key(FUNC, 0)
        cue = lambda: rd(syms["cl_cue"], 2)
        n = 0
        while cue() != 0xFFFF and n < 60:
            rt.run(ms=50)
            n += 1
            if n % 10 == 1:
                print(f"      t+{n * 50} ms: master step {rd(0x800065B2, 2)} tick {rd(0x800065B6, 1)} "
                      f"arm {rd(syms['cl_arm'], 1)} nq {rd(syms['cl_nq'], 1)} cuef {rd(syms['cl_cuef'], 1)} "
                      f"quant {rd(sl + 0x8E56, 1)} proj {rd(0x8000004E, 1)} act {rd(0x800065BE, 1)}", flush=True)
        # KYOTI: SIDE-CHAIN's sc_norm (tools/patch_sidechain.s) turns a playing COMPRESSOR's MON (FX page 2,
        # slot 2: Part +0x2f2 + 30t + 13 / + 19) from an older 0 / 1 into 2 = OFF -- not Clyps' doing
        def slice_ok(now_, src_):
            if now_ == src_:
                return True
            offs = []
            for off, stride, size_, count, step in SLA:
                o_ = off + stride * t
                for _ in range(count):
                    offs += [o_ + j for j in range(size_)]
                    o_ += step
            mon = {0x2F2 + 30 * t + 13: rd(dst + t, 1), 0x2F2 + 30 * t + 19: rd(dst + 8 + t, 1)}
            return all(offs[i] in mon and mon[offs[i]] == 0x18 and src_[i] in (0, 1) and now_[i] == 2
                       for i in range(len(now_)) if now_[i] != src_[i])
        check(running == 1 and cue() == 0xFFFF and rec(act, 0) == srec and slice_ok(pslice(t, dst), ssl),
              f"playing: [FUNC]+trig lands at the next step with its slice (running {running}, "
              f"cue 0x{cue():04x} after {n * 50} ms; record == source {rec(act, 0) == srec}, slice == "
              f"source {pslice(t, dst) == ssl}, record == original {rec(act, 0) == oslot(act, 0)}; "
              f"source {sb}/{sq + 1}, act {act + 1}, playing {rd(0x800065BE, 1) + 1})")
        if pslice(t, dst) != ssl:          # which slice bytes, by Part offset
            segs, offs = SLA, []
            for off, stride, size_, count, step in segs:
                o_ = off + stride * t
                for _ in range(count):
                    offs += [o_ + j for j in range(size_)]
                    o_ += step
            now_, src_ = pslice(t, dst), ssl
            bad = [(hex(offs[i]), src_[i], now_[i]) for i in range(len(now_)) if now_[i] != src_[i]]
            print(f"      slice differs at (Part offset, source, now): {bad[:12]} ({len(bad)} B)", flush=True)
        check([pslice(k, dst) for k in range(16) if k != t] == others0, "... every other track's slice untouched")
        check(state()["open"] == 1, "... Clyps stays open")
        key(0x27, 1)                       # STOP (not ours)
        key(0x27, 0)
        rt.run(ms=300)
        u.mem_write(sl + 0x8E56, bytes([q0]))
        check(rd(0x800065B8, 4) == 0, "stopped again")
        tap(NO)
        closed_ok("[NO]")

    if "J" in a.only:
        # --- J: DIRECT JUMP in KYOTI (scope §1.10): an image built with build_kyoti.py --with CLYPS
        print("J: DIRECT JUMP: [PTN]+[YES] in Clyps toggles it; DJ on: a cue lands at the next master "
              "step; a DJ jump drops the cues")
        if "DJ_MODE" not in syms:
            check(False, "this image has no DIRECT JUMP (build_kyoti.py --with CLYPS)")
        else:
            djm, djs = syms["DJ_MODE"], syms["DJ_STATE"]
            tap(0x10)
            act = rd(0x800065BE, 1)
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)                    # [PTN] still held: [PTN]+[YES] = DIRECT JUMP's toggle
            r0, m0 = rec(act, 0), rd(djm, 4)
            tap(YES)
            check(rd(djm, 4) == (m0 ^ 1) and rec(act, 0) == r0 and state()["open"] == 1,
                  f"[PTN]+[YES] in Clyps: DIRECT JUMP {m0} -> {rd(djm, 4)}, no load, Clyps stays")
            key(PTN, 0)
            check(state()["open"] == 1 and state()["showwin"] == 0, "... [PTN] released: Clyps stays, no SELECT")
            if rd(djm, 4) == 0:
                key(PTN, 1)
                tap(YES)
                key(PTN, 0)
            check(rd(djm, 4) == 1, "DIRECT JUMP on")
            # running, CHAIN AFTER at the project default (off: without DJ only the master wrap lands)
            sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
            q0 = rd(sl + 0x8E56, 1)
            u.mem_write(sl + 0x8E56, b"\xff")
            mlen = rd(sl + 0x8E50, 2)
            q = next(x for x in range(16) if x != act and rec(x, 0) != rec(act, 0))
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.internal_clock()
            rt.frame = True
            rt.next_frame = rt.sample + er.FRAME_PERIOD
            rt.exact_clock()
            rt.start_transport_live()
            rt.run(ms=300)
            cue = lambda: rd(syms["cl_cue"], 2)
            s0 = rd(0x800065B2, 2)
            key(q, 1, 0)
            key(q, 0, 0)
            s1 = rd(0x800065B2, 2)
            steps, n = [s1], 0
            while cue() != 0xFFFF and n < 400:
                rt.run(ms=5)
                n += 1
                if rd(0x800065B2, 2) != steps[-1]:
                    steps.append(rd(0x800065B2, 2))
            print(f"      master length {mlen}, cue at master step {s0}->{s1}, landed after {n * 5} ms, "
                  f"steps seen {steps}", flush=True)
            check(rd(0x800065B8, 4) == 1 and cue() == 0xFFFF and rec(act, 0) == rec(q, 0) and len(steps) <= 3,
                  f"DJ on: the cue lands within a master step ({len(steps) - 1} step change(s), {n * 5} ms)")
            # a DIRECT JUMP pending: the Clyps cue is dropped, the jump lands the new pattern as it is.
            # The pattern cue is written as stock's [PTN]+trig writes it (a real pick closes Clyps).
            p2 = next(x for x in range(16) if x not in (act, q))
            q2 = next(x for x in range(16) if x not in (act, p2) and rec(x, 0) != rec(act, 0))
            tgt0, cur0 = rec(p2, 0), rec(act, 0)
            key(q2, 1, 0)
            key(q2, 0, 0)
            u.mem_write(0x800065C0, bytes([p2]))              # PEND_PAT: DIRECT JUMP arms on it
            c1 = cue()
            n = 0
            while rd(0x800065BE, 1) != p2 and n < 400:
                rt.run(ms=5)
                n += 1
            print(f"      jump to pattern {p2 + 1} after {n * 5} ms; Clyps cue was 0x{c1:04x}, now "
                  f"0x{cue():04x}; DJ state {rd(djs, 1)}", flush=True)
            check(rd(0x800065BE, 1) == p2 and cue() == 0xFFFF and rd(syms["cl_nq"], 1) == 0,
                  f"a DIRECT JUMP to pattern {p2 + 1} lands and drops the pending Clyps cue")
            check(rec(p2, 0) == tgt0 and rec(act, 0) == cur0,
                  "... the cue never landed: both patterns' T1 as they were")
            key(0x27, 1)                       # STOP
            key(0x27, 0)
            rt.run(ms=300)
            u.mem_write(sl + 0x8E56, bytes([q0]))
            check(rd(0x800065B8, 4) == 0, "stopped again")
            if state()["open"]:
                tap(NO)
            closed_ok("closed")

    if "W" in a.only:
        # --- W: the SRAM mirror (battery NVRAM: the live cache of the UI bank) after each kind of load
        # equals RAM where RAM changed, and what each load writes there (stock's memcpy, dst in NVRAM)
        # (the user, 2026-11-04: CL8 writes only what changed -- records + trailer, the touched Part)
        print("W: the NVRAM mirror after every kind of load, and the bytes each load writes into it")
        SRAM_PAT_, SRAM_PART_ = 0x1001614E, 0x100A4ECE
        def mdiff(pat):
            if rd(0x80000002, 1) != bank:
                return None
            m_ = bytes(u.mem_read(SRAM_PAT_ + pat * PATSTRIDE, PATSTRIDE))
            l_ = slab(pat)
            mp = bytes(u.mem_read(SRAM_PART_, 4 * PARTSZ))
            lp = bytes(u.mem_read(BLOB + bank * BANKSTRIDE + PART_OFF, 4 * PARTSZ))
            return ({i for i in range(PATSTRIDE) if m_[i] != l_[i]}, {i for i in range(4 * PARTSZ) if mp[i] != lp[i]})
        wr = []
        def on_mc(uc, ad, sz, ud):
            sp_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
            dst_, n_ = rd(sp_ + 4, 4), rd(sp_ + 12, 4)
            if 0x10000000 <= dst_ < 0x10200000:
                wr.append(n_)
        hmc = u.hook_add(er.eb.UC_HOOK_CODE, on_mc, begin=0x40020898, end=0x40020898)
        tap(0x10)
        act = rd(0x800065BE, 1)
        base = mdiff(act)
        check(base is not None, f"the playing bank is the mirror's (UI bank {rd(0x80000002, 1)})")
        b_s, b_p = base if base else (set(), set())
        print(f"      baseline: mirror differs from RAM at {len(b_s)} slab / {len(b_p)} Part bytes", flush=True)
        def mcheck(what, pat=None):
            d_ = mdiff(act if pat is None else pat)
            n_ = sum(wr)
            wr.clear()
            if d_ is None:
                check(False, f"{what}: the playing bank is not the mirror's")
                return
            ns, np_ = d_[0] - b_s, d_[1] - b_p
            check(not ns and not np_, f"{what}: the mirror follows ({n_:,} B written into it; new differences: "
                  f"slab {sorted(hex(x) for x in ns)[:6]}, Part {sorted(hex(x) for x in np_)[:6]})")
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        wr.clear()
        q = next(x for x in range(16) if x != act and rec(x, 0) != rec(act, 0))
        tap(q)
        mcheck(f"trig {q + 1} (TRK SEQ)")
        key(FUNC, 1)
        tap(q)
        key(FUNC, 0)
        mcheck(f"[FUNC]+trig {q + 1} (TRK FULL)")
        tap(PAGE)
        mcheck("[PAGE] (ORIG TRK SEQ)")
        key(CUE := 0x2A, 1)
        tap(0x11)
        tap(0x12)
        key(CUE, 0)
        wr.clear()
        tap(q)
        mcheck(f"a group of T2 T3, trig {q + 1}")
        tap(NO)
        wr.clear()
        key(PTN, 1)
        key(BANK, 1)
        tap(PAGE)
        key(BANK, 0)
        key(PTN, 0)
        mcheck("[PTN]+[BANK]+[PAGE] (ORIG PTN+PART, 16 tracks + the Part)")
        key(PTN, 1)
        key(0x10, 1)
        rt.run(ms=6000)
        key(0x10, 0)
        key(PTN, 0)
        tailmsg()
        mcheck("[PTN]+TRACK 1 (card TRK SEQ)")
        key(BANK, 1)
        key(0x10, 1)
        rt.run(ms=6000)
        key(0x10, 0)
        key(BANK, 0)
        tailmsg()
        mcheck("[BANK]+TRACK 1 (card TRK FULL)")
        p2 = next(x for x in range(16) if x != act)
        key(PTN, 1)
        key(BANK, 1)
        key(p2, 1)
        rt.run(ms=6000)
        key(p2, 0)
        key(BANK, 0)
        key(PTN, 0)
        tailmsg()
        mcheck(f"[PTN]+[BANK]+trig {p2 + 1} (card pattern {p2 + 1}, not the playing one)", pat=p2)
        u.hook_del(hmc)
        tap(NO)

    if "I" in a.only:
        # --- I: card reloads of a fully saved project undo a Clyps load: no "x", the box / LEDs back on the
        # pattern's own slot (the user, 2026-11-05)
        print("I: SAVE PROJECT, a Clyps load, then the card reloads: no edited mark, the box home")
        def worker(fn, ms, args=()):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(fn, args=args, budget=600000)
            rt.run(ms=ms)
        if rd(0x80000012, 4):
            tap(0x35)
        tap(0x10)
        act = rd(0x800065BE, 1)
        NAMES_ = syms["cl_bss"] + 16 * BANKSZ + 16 * TRAC_A
        nadr = lambda t: NAMES_ + ((bank * 16 + act) * 16 + t) * 10
        nm = lambda t: bytes(u.mem_read(nadr(t), 10)).split(b"\0")[0]
        u.mem_write(nadr(0), b"SAVEDNM\0\0\0")        # T1 named before the save, T2 not
        u.mem_write(nadr(1), b"\0" * 10)
        worker(0x40022850, int(os.environ.get("CLYPS_SAVE_MS", "8000")))
        sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        def edited(t=0):
            # cl_edited for the active track's slot of the playing pattern: the record (length / scale bytes
            # aside) or its effective length / scale differ from the original
            r_, o_ = rec(act, t), oslot(act, t)
            ls, os_ = slab(act), oslab(act)
            def eff(slab_, rec_):
                return (slab_[0x8E53], slab_[0x8E54]) if slab_[0x8E55] == 0 else (rec_[0x50], rec_[0x51])
            dr = [hex(i) for i in range(len(r_)) if r_[i] != o_[i] and i not in (0x50, 0x51)]
            return dr[:6], eff(ls, r_), eff(os_, o_), ls[0x8E55], os_[0x8E55]
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        e0 = edited()
        print(f"      saved, T1: record diffs {e0[0]}, eff len/scale {e0[1]} vs {e0[2]}, mode {e0[3]} vs {e0[4]}", flush=True)
        for kind, keys_ in (("[PTN]+TRACK 1 (TRK SEQ)", (PTN,)), ("[BANK]+TRACK 1 (TRK FULL)", (BANK,)),
                            ("[PTN]+[BANK]+trig (the pattern)", None)):
            q = next(x for x in range(16) if x != act and (rec(x, 0) != rec(act, 0) or slab(x)[0x50] != slab(act)[0x8E53]))
            while state()["cur"] != q:
                tap(DOWN)
            tap(YES)
            u.mem_write(nadr(0), b"CHANGED\0\0\0")    # renamed since the save; T2 named, never saved
            u.mem_write(nadr(1), b"T2NAME\0\0\0\0")
            e1 = edited()
            print(f"      loaded {q + 1}: record diffs {e1[0][:3]}, eff {e1[1]} vs {e1[2]}, mode {e1[3]} vs {e1[4]}; box "
                  f"{state()['cur'] + 1}; home 0x{rd(syms['cl_home'], 2):04x}", flush=True)
            if keys_:
                key(keys_[0], 1)
                key(0x10, 1)
                rt.run(ms=6000)
                key(0x10, 0)
                key(keys_[0], 0)
            else:
                key(PTN, 1)
                key(BANK, 1)
                key(act, 1)
                rt.run(ms=6000)
                key(act, 0)
                key(BANK, 0)
                key(PTN, 0)
            tailmsg()
            e2 = edited()
            print(f"      {kind}: record diffs {e2[0]}, eff {e2[1]} vs {e2[2]}, mode {e2[3]} vs {e2[4]}; box "
                  f"{state()['cur'] + 1}; home 0x{rd(syms['cl_home'], 2):04x}", flush=True)
            check(not e2[0] and e2[1] == e2[2], f"{kind}: T1 equals its original (no edited mark)")
            check(state()["cur"] == act and rd(syms["cl_home"], 2) == 0xFFFF,
                  f"... the box back on your pattern {act + 1}, no Clyps source left (box {state()['cur'] + 1})")
            whole = keys_ is None
            check(nm(0) == b"SAVEDNM" and (nm(1) == (b"" if whole else b"T2NAME")),
                  f"... T1's name as saved ({nm(0)}); T2's {'gone (never saved)' if whole else 'untouched'} ({nm(1)})")
        tap(NO)
        # a NORMAL pattern: the load converts it to PER TRACK; the card's TRK SEQ undoes that (cl_back)
        nrm = next((x for x in range(16) if slab(x)[0x8E55] == 0), None)
        src = next((x for x in range(16) if slab(x)[0x8E55] and slab(x)[0x50] != slab(nrm)[0x8E53]), None) if nrm is not None else None
        if nrm is None or src is None:
            print("      (no NORMAL pattern / no PER TRACK source of another length: conversion case skipped)", flush=True)
        else:
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.seq_select_live(bank, nrm)
            rt.run(ms=300)
            act = rd(0x800065BE, 1)
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)
            key(PTN, 0)
            key(src, 1)
            key(src, 0)
            e1 = edited()
            print(f"      NORMAL pattern {act + 1}, T1 from {src + 1}: mode {e1[3]} (saved {e1[4]}), eff {e1[1]} vs {e1[2]}", flush=True)
            key(PTN, 1)
            key(0x10, 1)
            rt.run(ms=6000)
            key(0x10, 0)
            key(PTN, 0)
            tailmsg()
            e2 = edited()
            mm = bytes(u.mem_read(0x1001614E + act * PATSTRIDE, PATSTRIDE)) if rd(0x80000002, 1) == bank else None
            md = [hex(i) for i in range(PATSTRIDE) if mm is not None and mm[i] != slab(act)[i]][:6]
            print(f"      [PTN]+TRACK 1: record diffs {e2[0]}, eff {e2[1]} vs {e2[2]}, mode {e2[3]} vs {e2[4]}; box "
                  f"{state()['cur'] + 1}; mirror diffs {md}", flush=True)
            check(not e2[0] and e2[1] == e2[2] and e2[3] == e2[4] and slab(act)[:0x8E5C] == oslab(act)[:0x8E5C],
                  "NORMAL pattern: the card's TRK SEQ undoes the conversion (no edited mark, the slab as loaded)")
            check(state()["cur"] == act and not md, "... the box on your pattern; the NVRAM mirror follows the whole slab")
            tap(NO)

    if "V" in a.only:
        # --- V: each track's box (the user, 2026-11-04): Clyps opens / a track change puts the box on that
        # track's sequence (where what it plays was loaded from; its own slot for an original); moving it is
        # free within a view; LEDs: the sequence red (+ a 3-tick green flash), the box elsewhere solid
        # yellow, a cued slot yellow flashing half the period (cl_blink's LED_FLASH calls)
        print("V: the box per track, the sequence / box / cued LEDs")
        led_tbl_ = [rd(0x400A74CE + 4 * k, 4) for k in range(16)]
        def flashes():
            got = []
            h = u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: got.append(
                (rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4), rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 8, 4))),
                begin=0x40013784, end=0x40013784)
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(syms["cl_blink"], budget=600000)
            u.hook_del(h)
            return got
        def repaint():
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(0x4007E998, args=(0,), budget=600000)
        tap(0x10)
        act = rd(0x800065BE, 1)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1 and state()["cur"] == act, f"open on T1: the box on its sequence, your pattern {act + 1}")
        q = next(x for x in range(16) if x != act and rec(x, 0) != rec(act, 0))
        r = next(x for x in range(16) if x not in (act, q))
        tap(q)
        check(state()["cur"] == q and rec(act, 0) == rec(q, 0), f"trig {q + 1}: loaded, the box there")
        while state()["cur"] != r:
            tap(DOWN)
        repaint()
        fl = flashes()
        check(led(r) == (1, 1) and led(q) == (1, 0) and led(act) == (1, 0),
              f"box on {r + 1}: solid yellow; the sequence ({q + 1}) red; your pattern red "
              f"(box {led(r)}, seq {led(q)}, yours {led(act)})")
        check((led_tbl_[q] + 1, 3) in fl and not any(d in (led_tbl_[r], led_tbl_[r] + 1) for d, _ in fl),
              f"... cl_blink: the sequence's green die 3 ticks; the box not flashed ({fl})")
        tap(0x11)
        check(state()["cur"] == act, f"T2: the box on T2's sequence (its original: your pattern {act + 1}; cur {state()['cur'] + 1})")
        tap(0x10)
        check(state()["cur"] == q, f"back to T1: the box on its sequence {q + 1}, not where it was left ({r + 1}); "
              f"cur {state()['cur'] + 1}")
        tap(PAGE)
        tap(0x11)
        tap(0x10)
        check(state()["cur"] == act, f"[PAGE] (T1's original), T2, back: the box on your pattern {act + 1}")
        # running: a cue flashes yellow
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.internal_clock()
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.start_transport_live()
        rt.run(ms=300)
        key(q, 1, 0)
        key(q, 0, 0)
        cued = rd(syms["cl_cue"], 2)
        repaint()
        fl = flashes()
        half = max(n for _, n in fl) if fl else 0
        check(cued != 0xFFFF and led(q) == (1, 1) and (led_tbl_[q], half) in fl and (led_tbl_[q] + 1, half) in fl
              and half > 3, f"cued {q + 1}: yellow, both dies flashed {half} ticks ({fl}, cue 0x{cued:04x})")
        key(0x27, 1)
        key(0x27, 0)
        rt.run(ms=300)
        tap(NO)
        closed_ok("[NO]")

    if "Z" in a.only:
        # --- Z: ORIG PTN+PART while playing = a pattern change to itself (the user, 2026-11-04). DIRECT JUMP off:
        # stock's switch (CHAIN AFTER point, d6 hand-off 0x400a45ba, COND_RESET -1); on: DJ's jump (next
        # landing point, its hand-off, no stock real switch). The originals come back at that point only.
        print("Z: [PTN]+[BANK]+[PAGE] playing: a switch to the pattern as loaded (DJ off: stock's, DJ on: a jump)")
        djm = syms.get("DJ_MODE")
        act = rd(0x800065BE, 1)
        sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
        q0 = rd(sl + 0x8E56, 1)
        def edit():
            u.mem_write(sl, bytes([rd(sl, 1) ^ 0x81]))                       # T1's record
            pb = partbase(bank, act)
            u.mem_write(pb + 0x2A, bytes([rd(pb + 0x2A, 1) ^ 0x55]))           # its Part (T1's slice)
        def restored():
            pb, ob = partbase(bank, act), partbase(bank, act, syms["cl_bss"])
            ls, os_ = slab(act)[:0x8E5C], oslab(act)[:0x8E5C]
            lp, op = bytes(u.mem_read(pb, PARTSZ)), bytes(u.mem_read(ob, PARTSZ))
            # KYOTI: SIDE-CHAIN's sc_norm turns a COMPRESSOR's MON (Part +0x2f2 + 30t + 13 / + 19; FX1 / FX2
            # type at +t / +8 + t == 0x18) from an older 0 / 1 into 2 when the Part is applied (as gate F)
            def scnorm(i):
                for t_ in range(8):
                    for k_, fx in ((13, t_), (19, 8 + t_)):
                        if i == 0x2F2 + 30 * t_ + k_ and lp[fx] == 0x18 and op[i] in (0, 1) and lp[i] == 2:
                            return True
                return False
            return ([hex(i) for i in range(len(ls)) if ls[i] != os_[i]][:6],
                    [hex(i) for i in range(PARTSZ) if lp[i] != op[i] and not scnorm(i)][:6])
        d0_ = restored()
        print(f"      before: differences from the originals {d0_} (earlier scenarios may have loaded)", flush=True)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1, "Clyps open")
        for dj in ([0, 1] if djm is not None else [0]):
            if djm is not None and rd(djm, 4) != dj:
                key(PTN, 1)
                tap(YES)
                key(PTN, 0)
            u.mem_write(sl + 0x8E56, bytes([4 if not dj else 0xFF]))    # CHAIN AFTER 4 steps / the default
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.internal_clock()
            rt.frame = True
            rt.next_frame = rt.sample + er.FRAME_PERIOD
            rt.exact_clock()
            rt.start_transport_live()
            rt.run(ms=300)
            edit()
            hits = {"real": 0, "cond": [], "commit_ms": None}
            h1 = u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: hits.__setitem__("real", hits["real"] + 1),
                            begin=0x400A45BA, end=0x400A45BA)
            h2 = u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: hits["cond"].append(
                rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4)), begin=0x400A539C, end=0x400A539C)
            key(PTN, 1, 0)
            key(BANK, 1, 0)
            key(PAGE, 1, 0)
            s0 = rd(0x800065B2, 2)
            pend = rd(syms["cl_self"], 1)
            still = restored() != ([], [])
            key(PAGE, 0, 0)
            key(BANK, 0, 0)
            key(PTN, 0, 0)
            n = 0
            while rd(syms["cl_self"], 1) and n < 800:
                rt.run(ms=5)
                n += 1
            s1 = rd(0x800065B2, 2)
            rt.run(ms=50)
            tailmsg()
            u.hook_del(h1)
            u.hook_del(h2)
            d1_ = restored()
            print(f"      DJ {dj}: request {pend}, edited until the switch {still}; landed after {n * 5} ms (master step "
                  f"{s0} -> {s1}); stock real switch x{hits['real']}, COND_RESET {[hex(x) for x in hits['cond']]}; "
                  f"differences now {d1_}", flush=True)
            check(pend == 1 and still and rd(syms["cl_self"], 1) == 0 and d1_ == ([], []),
                  f"DJ {dj}: requested, nothing restored before the switch, then the pattern + Part as loaded")
            if dj:
                check(hits["real"] == 0 and 0xFFFFFFFF in hits["cond"],
                      "... by DIRECT JUMP's jump (no stock real switch; its hand-off reset the conditions)")
            else:
                check(hits["real"] >= 1 and 0xFFFFFFFF in hits["cond"],
                      "... by stock's real switch (the d6 hand-off ran, the conditions reset)")
            key(0x27, 1)
            key(0x27, 0)
            rt.run(ms=300)
        u.mem_write(sl + 0x8E56, bytes([q0]))
        if djm is not None and rd(djm, 4):
            key(PTN, 1)
            tap(YES)
            key(PTN, 0)
        tap(NO)

    if "X" in a.only:
        # --- X: a card reload of a saved pattern marks nothing (the user, 2026-11-04: after a fully saved
        # project, [PTN]+[BANK] + the trig of pattern P put the "x" on slot P in the ACTIVE track's view).
        # Lists, per track, where the record differs from Clyps' original (cl_edited's comparison).
        print("X: SAVE PROJECT, then the card reload of the playing pattern: no record differs from its original")
        def worker(fn, ms, args=()):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(fn, args=args, budget=600000)
            rt.run(ms=ms)
        TRAC_M_, MIDI_BASE_ = 0x8B0, 0x48D0
        def recoff(t):
            return (t * TRAC_A, TRAC_A) if t < 8 else (MIDI_BASE_ + (t - 8) * TRAC_M_, TRAC_M_)
        def diffs(pat):
            sl_, os_ = slab(pat), oslab(pat)
            out = {}
            for t in range(16):
                o_, n_ = recoff(t)
                d_ = [i for i in range(n_) if sl_[o_ + i] != os_[o_ + i]]
                if d_:
                    out[t + 1] = [(hex(i), sl_[o_ + i], os_[o_ + i]) for i in d_[:6]] + ([f"+{len(d_) - 6}"] if len(d_) > 6 else [])
            rest = [hex(i) for i in range(MIDI_BASE_ + 8 * TRAC_M_, PATSTRIDE) if sl_[i] != os_[i]]
            return out, rest[:12]
        act = rd(0x800065BE, 1)
        tap(0x12)                                  # T3 active
        worker(0x40022850, 8000)                   # SAVE PROJECT: the .strd = RAM, the originals retaken
        print(f"      active T{rd(0x80000000, 1) + 1}, pattern {act + 1}, snapshots 0x{snapok():04x}", flush=True)
        d0_, r0_ = diffs(act)
        print(f"      after SAVE PROJECT: records differing {d0_}; slab tail {r0_}", flush=True)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        check(state()["open"] == 1, "Clyps open")
        ndir = lambda: rd(syms["rq_ndir"], 4) if "rq_ndir" in syms else -1
        nd0 = ndir()
        trace_ = []
        R = er.eb
        def reg(uc, r): return uc.reg_read(r) & 0xFFFFFFFF
        def hk_(name, fn):
            if name in syms:
                return u.hook_add(R.UC_HOOK_CODE, fn, begin=syms[name], end=syms[name])
        hx = [h for h in (
            hk_("rj_st", lambda uc, ad, sz, ud: trace_.append(f"rj_st ver d6=0x{reg(uc, R.UC_M68K_REG_D6):x} P d5={reg(uc, R.UC_M68K_REG_D5)} st d4=0x{reg(uc, R.UC_M68K_REG_D4):x}")),
            hk_("rj_seq", lambda uc, ad, sz, ud: trace_.append(f"rj_seq d0=0x{reg(uc, R.UC_M68K_REG_D0):x}")),
            hk_("rj_dok", lambda uc, ad, sz, ud: trace_.append("rj_dok")),
            u.hook_add(R.UC_HOOK_CODE, lambda uc, ad, sz, ud: trace_.append(
                f"FSEEK(h=0x{rd(reg(uc, R.UC_M68K_REG_A7) + 4, 4):x}, off=0x{rd(reg(uc, R.UC_M68K_REG_A7) + 8, 4):x})"),
                begin=0x4001660C, end=0x4001660C),
        ) if h is not None]
        key(PTN, 1)
        key(BANK, 1)
        key(act, 1)
        rt.run(ms=6000)
        key(act, 0)
        key(BANK, 0)
        key(PTN, 0)
        print(f"      toast line1 {bytes(u.mem_read(syms['rq_line1'], 12))}", flush=True)
        for h_ in hx:
            u.hook_del(h_)
        print(f"      the card path: {trace_}", flush=True)
        d1_, r1_ = diffs(act)
        print(f"      after the card reload: records differing (offset, now, original) {d1_}; slab tail {r1_}", flush=True)
        check(not d1_, f"the card reload of a saved pattern: every record equals its original ({sorted(d1_)})")
        check(nd0 < 0 or ndir() == nd0 + 1, f"... read straight from pattern {act + 1}'s chunk and its Part's "
              f"(the seek path: {nd0} -> {ndir()} direct reloads)")
        tap(NO)

    if "O" in a.only:
        # --- O: ORIG PTN+PART's flash with DIRECT JUMP on, running (the user, 2026-11-04: on hardware
        # the flash is very slow with DJ on, right with it off). Route A runs no UI tick and no UI tail
        # by itself, so this measures what can starve them: how often the landing posts reach the UI
        # tail during the 0.5 s flash, and what each one costs in instructions.
        print("O: [PTN]+[BANK]+[PAGE] with DIRECT JUMP on, running: landings and UI-tail cost during the flash")
        if "DJ_MODE" not in syms:
            check(False, "this image has no DIRECT JUMP (build_kyoti.py --with CLYPS)")
        else:
            djm = syms["DJ_MODE"]
            posttail[0] = True
            act = rd(0x800065BE, 1)
            sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
            q0 = rd(sl + 0x8E56, 1)
            u.mem_write(sl + 0x8E56, b"\xff")
            want = int(os.environ.get("CLYPS_O_DJ", "1"))
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)
            if rd(djm, 4) != want:
                tap(YES)
            key(PTN, 0)
            check(state()["open"] == 1 and rd(djm, 4) == want, f"Clyps open, DIRECT JUMP {want}")
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.internal_clock()
            rt.frame = True
            rt.next_frame = rt.sample + er.FRAME_PERIOD
            rt.exact_clock()
            rt.start_transport_live()
            rt.run(ms=300)
            cnt = {"post_ui": 0, "flhdr": 0, "flstop": 0, "refresh": 0}
            names = {syms["cl_post_ui"]: "post_ui", syms["cl_flhdr"]: "flhdr", syms["cl_flstop"]: "flstop",
                     syms["cl_refresh"]: "refresh"}
            def on_call(uc, ad, sz, ud):
                cnt[names[ad]] += 1
            hk = [u.hook_add(er.eb.UC_HOOK_CODE, on_call, begin=ad_, end=ad_) for ad_ in names]
            key(PTN, 1)
            key(BANK, 1)
            tap(PAGE)
            c0 = dict(cnt)
            print(f"      after [PAGE]: {c0}, cl_nq {rd(syms['cl_nq'], 1)}, cl_flk {rd(syms['cl_flk'], 1)}", flush=True)
            # 60 UI ticks (1 s): between ticks the system runs 16 ms; a pending landing post goes through
            # the UI tail (as the SYS loop would), its instructions counted
            trace, posts, costs = [], [], []
            ninstr, inside = [0], [False]
            u_in, u_out = syms["ut_post"], syms["ut_out"]
            def on_any(uc, ad, sz, ud):
                if ad == u_in:
                    inside[0] = True
                elif ad == u_out:
                    inside[0] = False
                if inside[0]:
                    ninstr[0] += 1
            for i in range(60):
                rt.run(ms=16)
                pend = rd(syms["cl_post"], 2)
                if pend:
                    posts.append((i, pend))
                    ninstr[0] = 0
                    ha = u.hook_add(er.eb.UC_HOOK_CODE, on_any)
                    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
                    u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
                    rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
                    rt.run(ms=20)
                    u.hook_del(ha)
                    costs.append(ninstr[0])
                rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
                rt.call_as_main(0x40056C28, budget=600000)
                trace.append(rd(syms["cl_fph"], 1))
            for h_ in hk:
                u.hook_del(h_)
            flips = sum(1 for i in range(1, len(trace)) if trace[i] != trace[i - 1])
            print(f"      phases: {''.join(map(str, trace))} ({flips} changes); calls {cnt}", flush=True)
            print(f"      landing posts reaching the UI tail (tick, mask): {[(i, hex(m)) for i, m in posts]}", flush=True)
            print(f"      instructions from ut_post to ut_out (the landing's UI pass): {costs}", flush=True)
            key(BANK, 0)
            key(PTN, 0)
            key(0x27, 1)
            key(0x27, 0)
            rt.run(ms=300)
            u.mem_write(sl + 0x8E56, bytes([q0]))
            check(len(posts) <= 1, f"one landing for one ORIG PTN+PART ({len(posts)} posts)")
            check(flips == 5, f"the flash: 3 cycles ({flips} changes)")
            posttail[0] = False

    if "U" in a.only:
        # --- U: the [CUE] group (scope §1.9), stopped transport
        print("U: [CUE] group: sidebar tabs, track LEDs, loads into every member, ORIG per member, [NO]")
        CUE, MIDIK = 0x2A, 0x35
        trk_die = [rd(0x400A9670 + 4 * k, 4) for k in range(8)]

        def ledbit(die):
            b_ = bytes(u.mem_read(0x460BA98C, 17))
            return (b_[die // 8] >> (die % 8)) & 1
        tled = lambda: [(ledbit(d), ledbit(d + 1)) for d in trk_die]

        def callm(addr, *args):
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.call_as_main(addr, args=args, budget=600000)

        def tabs():
            # stock's sidebars 0x4003fed8: 0x40052200 runs them on every pass on hardware, route A never
            # does. An inverted tab fills its 8 x 8 edge cell; a plain one holds only its glyph.
            callm(0x4003FED8)
            px = lcd_view.pixels(bytes(u.mem_read(PLANE, 1024)))
            n = []
            for k in range(8):
                xs = range(0, 8) if k < 4 else range(120, 128)
                y0 = 63 - (61 - 15 * (k & 3))
                n.append(sum(px[y][x] for y in range(y0, y0 + 8) for x in xs))
            return [k for k in range(8) if n[k] >= 32], n
        grp = lambda: rd(syms["cl_grp"], 2)
        gmask = lambda: rd(syms["cl_gmask"], 4)
        if rd(0x80000012, 4):              # M leaves the MIDI side showing: U starts on the audio side
            tap(MIDIK)
        a0 = rd(0x80000000, 1)
        # stock's colours for each track when active and when not (the painter run with 0x80000000 set)
        lact, lnone = [], None
        for k in range(8):
            u.mem_write(0x80000000, bytes([k]))
            callm(0x4007E998, 6)
            lact.append(tled()[k])
        u.mem_write(0x80000000, b"\xff")
        callm(0x4007E998, 6)
        lnone = tled()
        u.mem_write(0x80000000, bytes([a0]))
        callm(0x4007E998, 6)
        m = [k for k in (1, 3, 5, 0, 2) if k != a0][:2]
        print(f"      active T{a0 + 1}, members T{m[0] + 1} T{m[1] + 1}; colours active {lact} none {lnone}", flush=True)
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        act = rd(0x800065BE, 1)
        t0, n0 = tabs()
        check(state()["open"] == 1 and gmask() == 0 and t0 == [a0] and tled()[a0] == lact[a0],
              f"open, no group: the tab and the active colours on T{a0 + 1} (tabs {t0}, cells {n0})")
        q = next(q for q in range(16) if q != act and all(rec(q, k) != rec(act, k) for k in m))
        before = [rec(act, k) for k in range(8)]
        key(CUE, 1)
        t1, n1 = tabs()
        check(rd(syms["cl_cuh"], 1) != 0 and gmask() == 0x10000 and t1 == [] and tled() == lnone,
              f"[CUE] held: no tab, no active colours (tabs {t1}, cells {n1})")
        tap(q)
        check([rec(act, k) for k in range(8)] == before, f"[CUE] held, no member: trig {q + 1} loads nothing")
        for k in m:
            tap(0x10 + k)
        bits = sum(1 << k for k in m)
        t2, n2 = tabs()
        led2 = tled()
        check(grp() == bits and t2 == sorted(m), f"[CUE]+TRACK: members {m} have the tabs (tabs {t2}, cells {n2})")
        check(rd(0x80000000, 1) == m[1], f"... and the view follows the last added, T{m[1] + 1} ({rd(0x80000000, 1)})")
        check(all(led2[k] == (lact[k] if k in m else lnone[k]) for k in range(8)),
              f"... and the active colours, the others plain ({led2})")
        tap(0x10 + m[1])
        check(rd(0x80000000, 1) == m[0], f"[CUE]+TRACK {m[1] + 1} out: the view falls back to T{m[0] + 1}")
        tap(0x10 + m[1])
        check(grp() == bits and rd(0x80000000, 1) == m[1], "[CUE]+TRACK twice: out, then in again (the view with it)")
        key(CUE, 0)
        check(gmask() == 0x10000 | bits and tabs()[0] == sorted(m), "[CUE] released: the group stays")
        shot("U1_group")
        tap(q)
        check(all(rec(act, k) == rec(q, k) for k in m) and rec(act, a0) == before[a0],
              f"trig {q + 1}: every member its own sequence of pattern {q + 1}; T{a0 + 1} untouched")
        tap(PAGE)
        check(all(rec(act, k) == oslot(act, k) for k in m), "[PAGE]: every member its own original")
        dst = partbase(bank, act)
        sl_a0 = pslice(a0, dst)
        key(FUNC, 1)
        tap(q)
        key(FUNC, 0)
        check(all(rec(act, k) == rec(q, k) and pslice(k, dst) == pslice(k, partbase(bank, q)) for k in m)
              and pslice(a0, dst) == sl_a0, f"[FUNC]+trig: ALL into every member; T{a0 + 1}'s slice untouched")
        key(FUNC, 1)
        tap(PAGE)
        key(FUNC, 0)
        osrc = partbase(bank, act, syms["cl_bss"])
        check(all(rec(act, k) == oslot(act, k) and pslice(k, dst) == pslice(k, osrc) for k in m),
              "[FUNC]+[PAGE]: every member its original sequence and slice")
        tap(DOWN)
        cg = state()["cur"]
        tap(0x10 + m[0])
        check(rd(0x80000000, 1) == m[0] and grp() == bits and state()["open"] == 1 and state()["cur"] == cg,
              f"plain TRACK {m[0] + 1}: the view's track changes, the group stays, the pre-select box stays "
              f"({cg + 1} -> {state()['cur'] + 1}; the user, 2026-11-05)")
        key(CUE, 1)
        tap(MIDIK)
        tap(0x10)
        check(rd(0x80000012, 4) != 0 and rd(0x80000000, 1) == 0, "... the view on MIDI track 1, on the MIDI side")
        tap(MIDIK)
        key(CUE, 0)
        check(grp() == bits | 0x100 and rd(0x80000012, 4) == 0, "[CUE]+[MIDI]+TRACK 1: MIDI track 1 joins")
        aview = rd(0x80000000, 1)
        mrec = lambda pat: bytes(u.mem_read(BLOB + bank * BANKSTRIDE + pat * PATSTRIDE + 0x48D0, 0x8B0))
        q2 = next((x for x in range(16) if x != act and mrec(x) != mrec(act)), q)
        differs = mrec(q2) != mrec(act)
        tap(q2)
        check(mrec(act) == mrec(q2) and all(rec(act, k) == rec(q2, k) for k in m),
              f"trig {q2 + 1}: the MIDI member too (its source record differs: {differs})")
        tap(PAGE)
        key(CUE, 1)
        tap(0x10 + m[1])
        check(rd(0x80000012, 4) == 0 and rd(0x80000000, 1) == m[0],
              f"[CUE]+TRACK {m[1] + 1} out: the newest audio member T{m[0] + 1}, not MIDI 1 (was T{aview + 1})")
        tap(0x10 + m[0])
        check(rd(0x80000012, 4) == 0 and rd(0x80000000, 1) == a0 and grp() == 0x100,
              f"... T{m[0] + 1} out too: no audio member, back to T{a0 + 1} (before the group)")
        tap(0x10 + m[0])
        key(CUE, 0)
        check(rd(0x80000000, 1) == m[0] and grp() == 0x100 | (1 << m[0]), f"... T{m[0] + 1} in again: the view on it")
        tap(NO)
        t3, _ = tabs()
        check(state()["open"] == 1 and grp() == 0 and gmask() == 0 and t3 == [m[0]]
              and tled()[m[0]] == lact[m[0]] and rd(0x80000000, 1) == m[0],
              "[NO]: the group is gone, Clyps stays, the view and the tab stay on the active track")
        tap(NO)
        closed_ok("[NO] again")
        check(gmask() == 0, "closed: no group")

    if "K" in a.only:
        # --- K: stock [PTN] / [BANK] inside Clyps (scope §1.0 step 2). Changes the playing pattern:
        # it runs last and puts the pattern back.
        posttail[0] = True
        print("K: [BANK] in Clyps: box while held, SELECT BANK on a tap's release, bank pick stays, "
              "bank + pattern closes; [PTN] tap / [PTN] + trig")
        BANK_LAYER, WIN_ONCLOSE = 0x400CFF14, 0x460D1E60
        tap(0x10)
        act = rd(0x800065BE, 1)
        pbank = rd(0x800065BD, 1)

        def enter():
            key(PTN, 1)
            key(BANK, 1)
            key(BANK, 0)
            key(PTN, 0)
            return state()
        s0 = enter()
        bkbox = lambda: rd(syms["cl_hdrst"], 1) & 1
        check(s0["open"] == 1 and bkbox() == 0, "Clyps open; [BANK] released: no BANK box")
        key(BANK, 1)
        s = state()
        shot("K1_bank_held")
        check(s["showwin"] == 0 and BANK_LAYER in s["layers"], "[BANK] pressed in Clyps: no SELECT BANK yet, "
              "its trig overlay is up")
        check(bkbox() != 0, "[BANK] held: the header boxes BANK A")
        key(BANK, 0)
        s = state()
        shot("K2_bank_tap")
        check(s["open"] == 1 and s["showwin"] != 0 and rd(WIN_ONCLOSE, 4) == 0x4007B408,
              "a [BANK] tap's release: SELECT BANK, over Clyps")
        check(bkbox() == 0, "[BANK] released: the box goes")
        tap(NO)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0 and s["layers"] == s0["layers"] and s["leds"] == s0["leds"],
              "[NO] on SELECT BANK: it closes, Clyps stays, our layers on top again")
        key(BANK, 1)
        tap(RIGHT)
        key(BANK, 0)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0 and s["layers"] == s0["layers"] and s["bank"] == (s0["bank"] + 1) % 16,
              "[BANK] + RIGHT: pages, no SELECT BANK on release, overlay gone")
        # [BANK] held + trig 2 (bank B) -> pending, Clyps stays; trig 3 -> bank B pattern 3, Clyps closes
        nb = (pbank + 1) % 16
        key(BANK, 1)
        tap(nb)
        s = state()
        shot("K3_bank_picked")
        check(s["open"] == 1 and s["banksel"] == 1 and rd(0x800065BD, 1) == pbank,
              f"[BANK] + trig {nb + 1}: bank pending (stock), Clyps stays, the bank has not changed")
        tap(2)
        rt.run(ms=300)
        check(state()["open"] == 0, "... then trig 3: a bank + pattern selection, Clyps closes")
        key(BANK, 0)
        rt.run(ms=300)
        closed_ok("[BANK] released after the pick")
        check((rd(0x800065BD, 1), rd(0x800065BE, 1)) == (nb, 2), f"now on bank {nb}, pattern 3 "
              f"(read {rd(0x800065BD, 1)}, {rd(0x800065BE, 1)})")
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.seq_select_live(pbank, act)
        rt.run(ms=300)
        # a [BANK] tap (latched SELECT BANK), trig = bank, trig = pattern: closes
        s0 = enter()
        tap(BANK)
        tap(pbank)
        check(state()["open"] == 1 and state()["showwin"] != 0, "latched SELECT BANK, trig picks the bank: Clyps stays")
        tap((act + 1) % 16)
        rt.run(ms=300)
        closed_ok("... and a trig picks the pattern: Clyps closes")
        check(rd(0x800065BE, 1) == (act + 1) % 16, f"now on pattern {(act + 1) % 16 + 1}")
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.seq_select_live(pbank, act)
        rt.run(ms=300)
        # [PTN] tap: SELECT PATTERN over Clyps; [NO] closes it; [PTN] + trig: a pattern change, closes
        s0 = enter()
        tap(PTN)
        s = state()
        shot("K4_ptn_tap")
        check(s["open"] == 1 and s["showwin"] != 0, "a [PTN] tap in Clyps: SELECT PATTERN, Clyps stays")
        tap(NO)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0 and s["layers"] == s0["layers"],
              "[NO] on SELECT PATTERN: it closes, Clyps stays")
        key(PTN, 1)
        tap((act + 2) % 16)
        rt.run(ms=300)
        check(state()["open"] == 0, "[PTN] + trig: a pattern selection, Clyps closes")
        key(PTN, 0)
        closed_ok("[PTN] released")
        check(rd(0x800065BE, 1) == (act + 2) % 16, f"now on pattern {(act + 2) % 16 + 1}")
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.seq_select_live(pbank, act)
        rt.run(ms=300)
        # the chord again inside Clyps: nothing
        s0 = enter()
        key(PTN, 1)
        key(BANK, 1)
        key(BANK, 0)
        key(PTN, 0)
        s = state()
        check(s["open"] == 1 and s["showwin"] == 0 and s["layers"] == s0["layers"],
              "the chord pressed again in Clyps: nothing, no SELECT window")
        # the chord inside Clyps, either order: never the bank view; the pattern view (the user)
        PTNL = 0x400BF0F2
        act = rd(0x800065BE, 1)
        def pview_ok():
            return led(act) == (1, 0) and rd(syms["cl_hdrst"], 1) == 2
        key(BANK, 1)
        key(PTN, 1)
        s = state()
        check(BANK_LAYER not in s["layers"] and pview_ok(),
              "[BANK] then [PTN] in Clyps: the bank overlay off, the pattern view (your pattern red)")
        key(PTN, 0)
        key(BANK, 0)
        check(state()["layers"] == s0["layers"] and state()["showwin"] == 0, "... released: layers back, no window")
        key(PTN, 1)
        key(BANK, 1)
        s = state()
        check(PTNL not in s["layers"] and BANK_LAYER not in s["layers"] and pview_ok(),
              "[PTN] then [BANK] in Clyps: stock's pattern overlay off, the same pattern view")
        key(BANK, 0)
        check(PTNL in state()["layers"], "... [BANK] let go first: [PTN]'s overlay back")
        key(PTN, 0)
        check(state()["layers"] == s0["layers"] and state()["showwin"] == 0, "... [PTN] let go: layers back, no window")
        tap(NO)
        closed_ok("[NO]")

    print(f"\nscreens: {shots}")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)}): " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

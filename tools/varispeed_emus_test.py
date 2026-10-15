#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
VARISPEED_EMUS -- tests of the new behaviour (spec §5, the EMUS scope's §6.4 / §8.3), run
in ot_emu on the built image (out/mainos_varispeed_emus.bin, or VEM_IMG) with the REAL
hardware-exported project OTDEMO (T1-T7 FLEX, part 1). Everything is set by RUNTIME
pokes and direct calls; no project file is edited. The SETUP page is never drawn in the
emulator, so the EMUS UI is tested by calling P2EDIT (0x4003a474) and the widgets
themselves; KNOB (0x400479b4) is replaced at runtime by a capture stub for the widget
calls only, then restored.

  python3 tools/varispeed_emus_test.py [--only NAME] [--jobs N]

Tests (one forked scenario each):
  swap      both pairs swap together, fresh parks (QUAN 1/1, EMUS OT), round trip
  fresh0    a TSNS of 0 survives a VARI round trip (TSNS back verbatim)
  adopt     a forgotten rp_prev adopts a Part already in VARI (no swap), both machines
  p2edit    EMUS through P2EDIT (direct calls): six detents in one direction per stop, a
            reversal restarts the count, a pushed (x7) report counts one detent, a report of
            12 detents moves two stops, 1/64/127 only, snapping, the count restarts on
            another track and at SRC SETUP's open (emus_open); gate off = stock;
            TSTR 0..4 through P2EDIT and the swap it starts
  widget    emus_widget / quant_widget arguments (snapped value, formatter), captions;
            emus_fmt, tstr_fmt, quant_fmt strings
  item11    FL -> PICKUP -> FL, FL -> THRU -> FL, FL -> STATIC -> FL (each its own VARI
            state): no swap on a machine change, no poll on PICKUP
  latch     an EMUS change mid-note does not switch the engine until the next trig (DSP)
  o2        SRC page paste + undo, track paste, PART paste / clear / undo, RELOAD PART:
            the target adopts what was written, nothing swaps
  old56     TSTR 5/6 and TSMODE 5/6 (projects saved with REPITCH_REPEAT98_KYOTI) do not crash
  panel_*   EMUS through the REAL panel path, transport stopped: SRC SETUP opened with its
            keys, encoder F reports into the panel UART (the parser, its coalescing, the UI
            task, the page's encoder table, P2EDIT), every stored value logged at P2EDIT's
            store (0x4003a5ba). slow / fast / multi / jitter / bounce / held turns, and
            reset (the page closed and re-opened, a track change and back, mid-count). The
            first hardware build (140C_VEM1) fails these: one stop per report, any sign.

EMUS order (2026-10-14): OT (stored 1, left), S950 (64, middle), SP12 (127, right).
"""
import argparse, json, os, pathlib, struct, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCR = ROOT / "out/vem"
EMU = pathlib.Path(os.environ.get("VEM_EMU", SCR / "octabam/out/emu/ot_emu"))
IMG = pathlib.Path(os.environ.get("VEM_IMG", ROOT / "out/mainos_varispeed_emus.bin"))
SYMS = pathlib.Path(os.environ.get("VEM_SYMS", ROOT / "out/varispeed_emus_syms.json"))
EM = {"OT": 1, "S950": 64, "SP12": 127}           # EMUS stops, left to right
EM_NAME = {v: k for k, v in EM.items()}
CARD = SCR / "img/otdemo.img"
OUTD = pathlib.Path(os.environ.get("VEM_TEST_OUT", SCR / "tests"))
S = json.loads(SYMS.read_text())["syms"]

DB, PSTRIDE, PART = 0x400e21e0, 0x18b2, 1
PBASE = DB + 0x8ed80 + PART * PSTRIDE            # the current part's block
SHBASE = 0x100a4ece + PART * PSTRIDE             # its SRAM copy
O_MACH, O_P1, O_P2, O_SLOT5 = 0x22, 0x2a, 0x1da, 0x2ca
LIVE_P1, LIVE_P2, BASE_W = 0x80000810, 0x80000830, 0x80000a50
UI_TRACK, PAGE_M = 0x80000000, 0x460d5c30
P2EDIT, SET_MACHINE, KNOB = 0x4003a474, 0x400972fc, 0x400479b4
P2_STORE = 0x4003a5ba                            # P2EDIT's DB store (d2 = the value stored)
ENC_F_HELD = 0x46c7d8ee + 24 * (0x38 + 5)        # encoder F's push (P2EDIT's x7 test)
ENC_SETUP_ARGS = (0x400d31ae, 0xffffffff, 0x400bb704)   # SRC SETUP's open -> 0x400326d4(P, -1, recs)
SETUP_OPEN_SITE = 0x400585f4                     # that call (R2: jsr emus_open)
KNOB_STOCK = bytes.fromhex("4fefffd048d7")
DESC = (0x400d3000, 0x300)                       # STATIC/FLEX descriptor heads (the captions)
NAME0 = {0: 0x400d3032, 1: 0x400d31c4}
NAME11 = {0: 0x400d3074, 1: 0x400d3206}
FL, ST, PU, THRU = 1, 0, 4, 2
PARK1 = {ST: 18, FL: 23}
PARK2 = {ST: 23, FL: 21}
CAP_AT, CAP_BUF, FMT_BUF = 0x400d7800, 0x400d7900, 0x400d7a00   # zero cave tail of this image
STATIC0_BPM = 0x100d5b30 + 0x114                # static slot 0 (T1's STATIC slot): 120 BPM


def b(a, v):
    return f"{a:#x}={v & 0xff:#x}"


def part_byte(off, v):
    return [b(PBASE + off, v), b(SHBASE + off, v)]


def p1(t, m, slot, v, live=True):
    out = part_byte(O_P1 + 30 * t + 6 * m + slot, v)
    if live:
        out += [b(LIVE_P1 + 72 * t + slot, v), b(BASE_W + 64 * t + 2 * slot, v), b(BASE_W + 64 * t + 2 * slot + 1, 0)]
    return out


def p2(t, m, slot, v, live=True):
    out = part_byte(O_P2 + 30 * t + 6 * m + slot, v)
    if live:
        out.append(b(LIVE_P2 + 72 * t + slot, v))
    return out


def park(t, which, m, v):
    return part_byte((O_P1 + 30 * t + PARK1[m]) if which == 1 else (O_P2 + 30 * t + PARK2[m]), v)


def poke(frame, items):
    return f"{frame}:poke:" + ";".join(items)


def call(frame, fn, *args):
    return f"{frame}:call:{fn:#x}" + "".join(f",{a & 0xffffffff:#x}" for a in args)


def machine(frame, t, m):
    return [poke(frame, part_byte(O_MACH + t, m)), call(frame, SET_MACHINE, PART, t)]


def cap_stub():
    """KNOB -> capture its 7 arguments + a call count. Assembled here, poked at runtime."""
    src = ["        .text", f"        lea     ({CAP_BUF:#x}).l,%a0"] + \
        [f"        move.l  {4 + 4 * i}(%sp),%d0\n        move.l  %d0,(%a0)+" for i in range(7)] + \
        ["        move.l  (%a0),%d0", "        addq.l  #1,%d0", "        move.l  %d0,(%a0)", "        rts"]
    w = OUTD / "cap"
    w.mkdir(parents=True, exist_ok=True)
    (w / "cap.s").write_text("\n".join(src) + "\n")
    for c in (["m68k-elf-as", "-mcpu=54455", "-o", w / "cap.o", w / "cap.s"],
              ["m68k-elf-ld", f"-Ttext={CAP_AT:#x}", "-e", "0", "-o", w / "cap.elf", w / "cap.o"],
              ["m68k-elf-objcopy", "-O", "binary", w / "cap.elf", w / "cap.bin"]):
        subprocess.run([str(x) for x in c], check=True, capture_output=True)
    code = (w / "cap.bin").read_bytes()
    jmp = b"\x4e\xf9" + CAP_AT.to_bytes(4, "big")
    install = [b(CAP_AT + i, x) for i, x in enumerate(code)] + [b(CAP_BUF + i, 0) for i in range(32)] + \
              [b(KNOB + i, x) for i, x in enumerate(jmp)]
    restore = [b(KNOB + i, x) for i, x in enumerate(KNOB_STOCK)]
    return install, restore


class Scn:
    def __init__(self, name, frames, live=None):
        self.name, self.frames, self.steps, self.cps = name, frames, [], []
        self.live = live                 # panel scenarios: [(emulated ms, live line)], no transport

    def add(self, *s):
        for x in s:
            if isinstance(x, list):
                self.steps += x
            else:
                self.steps.append(x)

    def cp(self, frame, tag):
        """a checkpoint: Part + shadow + rp_prev + descriptor heads + live + base words"""
        d = OUTD / self.name
        self.cps.append(tag)
        self.add(f"{frame}:dump:{PBASE:#x},{PSTRIDE:#x}={d / (tag + '.part')};"
                 f"{SHBASE:#x},{PSTRIDE:#x}={d / (tag + '.shadow')};"
                 f"{S['rp_prev']:#x},20={d / (tag + '.prev')};"
                 f"{DESC[0]:#x},{DESC[1]:#x}={d / (tag + '.desc')};"
                 f"{LIVE_P1:#x},0x240={d / (tag + '.live')};{BASE_W:#x},0x200={d / (tag + '.base')}")

    def dump(self, frame, addr, n, tag):
        self.add(f"{frame}:dump:{addr:#x},{n:#x}={OUTD / self.name / tag}")


class CP:
    def __init__(self, d, tag):
        self.part = (d / f"{tag}.part").read_bytes()
        self.shadow = (d / f"{tag}.shadow").read_bytes()
        self.prev = (d / f"{tag}.prev").read_bytes()
        self.desc = (d / f"{tag}.desc").read_bytes()
        self.live = (d / f"{tag}.live").read_bytes()
        self.base = (d / f"{tag}.base").read_bytes()

    def p1(self, t, m, s=0):
        return self.part[O_P1 + 30 * t + 6 * m + s]

    def p2(self, t, m, s=5):
        return self.part[O_P2 + 30 * t + 6 * m + s]

    def park(self, t, which, m):
        return self.part[(O_P1 + 30 * t + PARK1[m]) if which == 1 else (O_P2 + 30 * t + PARK2[m])]

    def rp(self, t, m):
        return self.prev[2 * t + m]

    def name(self, a):
        return self.desc[a - DESC[0]:a - DESC[0] + 4].decode("latin1")

    def mach(self, t):
        return self.part[O_MACH + t]

    def shadow_ok(self):
        return self.part == self.shadow


# ------------------------------------------------------------------------- scenarios
def scenarios():
    sc = {}
    install, restore = cap_stub()

    # swap: PTCH 70 / TSNS 30 -> VARI (fresh parks) -> QUAN 109 / EMUS 127 -> BEAT -> VARI
    s = Scn("swap", 90)
    s.add(poke(1, [b(UI_TRACK, 0)]),
          poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, 0)))
    s.cp(10, "a")
    s.add(poke(12, p2(0, FL, 4, 4)))
    for f in (12, 13, 14):
        s.cp(f, f"edge{f}")
    s.cp(30, "b")
    s.add(poke(32, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)))
    s.add(poke(40, p2(0, FL, 4, 3)))
    s.cp(60, "c")
    s.add(poke(62, p2(0, FL, 4, 4)))
    s.cp(80, "d")
    sc[s.name] = s

    s = Scn("fresh0", 60)
    s.add(poke(1, [b(UI_TRACK, 0)]),
          poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 0) + park(0, 1, FL, 0) + park(0, 2, FL, 0)),
          poke(10, p2(0, FL, 4, 4)), poke(30, p2(0, FL, 4, 0)))
    s.cp(25, "in")
    s.cp(50, "out")
    sc[s.name] = s

    # adopt: the Part already in VARI with QUAN/EMUS in the slots and PTCH/TSNS parked, rp_prev
    # forgotten (as after a load or an apply) -> adopt, no swap; the other machine adopted too
    s = Scn("adopt", 40)
    s.add(poke(2, p2(0, FL, 4, 4) + p1(0, FL, 0, 109) + p2(0, FL, 5, 127) + park(0, 1, FL, 70) +
               park(0, 2, FL, 30) + [b(S["rp_prev"] + i, 0xff) for i in range(16)]))
    s.cp(30, "a")
    sc[s.name] = s

    # p2edit: EMUS through the editor (direct P2EDIT calls); TSTR through the editor
    s = Scn("p2edit", 60)
    tsns = PBASE + O_P2 + 30 * 0 + 6 * FL + 5
    s.add(poke(2, p2(0, FL, 4, 4) + p2(1, FL, 4, 1) + p2(1, FL, 5, 64) + p2(2, FL, 4, 3) +
               park(0, 2, FL, 0)))
    s.add(poke(20, [b(UI_TRACK, 0), b(PAGE_M, 0), b(PAGE_M + 1, 0), b(PAGE_M + 2, 0), b(PAGE_M + 3, FL)]))
    held = lambda v: poke(20, [b(ENC_F_HELD + i, x) for i, x in enumerate(v.to_bytes(4, "big"))])
    ed = lambda *ds: [call(20, P2EDIT, 5, d) for d in ds]
    s.dump(20, tsns, 1, "e0")                                  # fresh park: OT
    s.add(ed(1, 1, 1, 1, 1)); s.dump(20, tsns, 1, "e5")        # five detents: no step yet
    s.add(ed(1)); s.dump(20, tsns, 1, "e6")                    # the sixth: S950
    s.add(ed(-1)); s.dump(20, tsns, 1, "e7")                   # turned back: restart, no step
    s.add(ed(1)); s.dump(20, tsns, 1, "e8")                    # and again
    s.add(ed(-1, 1, -1, 1)); s.dump(20, tsns, 1, "e9")         # jitter: nothing moves
    s.add(ed(12)); s.dump(20, tsns, 1, "e10")                  # 12 detents in one report: two stops (SP12)
    s.add(held(1), ed(1, 1, 1, 1)); s.dump(20, tsns, 1, "e11") # pushed: x7 units = one detent each
    s.add(ed(-1, -1, -1, -1, -1)); s.dump(20, tsns, 1, "e12")  # pushed, turned back: five
    s.add(ed(-1)); s.dump(20, tsns, 1, "e13")                  # the sixth pushed detent: S950
    s.add(held(0))
    s.add(poke(20, p2(0, FL, 5, 30)), ed(-1)); s.dump(20, tsns, 1, "e14")    # 30 snaps to OT (1)
    s.add(poke(20, p2(0, FL, 5, 100)), ed(1)); s.dump(20, tsns, 1, "e15")    # 100 snaps to SP12 (127)
    s.add(ed(-1, -1, -1, -1, -1)); s.dump(20, tsns, 1, "e16")  # five back: no step
    s.add(poke(20, [b(UI_TRACK, 1)]), call(20, P2EDIT, 5, 1))  # T2 (not VARI): stock, and the count's owner changes
    s.dump(20, PBASE + O_P2 + 30 * 1 + 6 * FL + 5, 1, "gateoff")
    s.add(poke(20, [b(UI_TRACK, 0)]), ed(-1)); s.dump(20, tsns, 1, "e17")    # back on T1: counting from 0
    s.add(ed(-1, -1, -1, -1)); s.dump(20, tsns, 1, "e18")      # five
    s.add(call(20, S.get("emus_open", 0x400326d4), *ENC_SETUP_ARGS))          # SRC SETUP opens
    s.add(ed(-1)); s.dump(20, tsns, 1, "e19")                  # counting from 0 again
    s.add(ed(-1, -1, -1, -1, -1)); s.dump(20, tsns, 1, "e20")  # the sixth since the open: S950
    s.add(poke(20, [b(UI_TRACK, 2)]), call(20, P2EDIT, 4, 1))
    s.dump(20, PBASE + O_P2 + 30 * 2 + 6 * FL + 4, 1, "tstr1")
    s.add(call(20, P2EDIT, 4, 1))
    s.dump(20, PBASE + O_P2 + 30 * 2 + 6 * FL + 4, 1, "tstr2")
    s.cp(40, "after")
    sc[s.name] = s

    # widget: captured KNOB arguments; formatters
    s = Scn("widget", 40)
    s.add(poke(2, p2(0, FL, 4, 4)), poke(20, [b(UI_TRACK, 0)]))
    calls = [("ew30", "emus_widget", 30, 0), ("ew100", "emus_widget", 100, 0), ("ew64", "emus_widget", 64, 0),
             ("ew1", "emus_widget", 1, 0), ("ewneg", "emus_widget", -1, 0),
             ("qw50", "quant_widget", 50, 0x4003b4b0), ("qw124", "quant_widget", 124, 0x4003b4b0)]
    s.add(poke(20, install))
    for tag, fn, val, fmt in calls:
        s.add(call(20, S[fn], 10, 20, 11, val, 0, fmt, 0x12345678))
        s.dump(20, CAP_BUF, 32, tag)
    s.cp(20, "on")
    s.add(poke(20, [b(UI_TRACK, 1)]), call(20, S["emus_widget"], 10, 20, 11, 30, 0, 0, 0x12345678))
    s.dump(20, CAP_BUF, 32, "ewoff")
    s.add(call(20, S["quant_widget"], 10, 20, 0, 77, 0, 0x4003b4b0, 0x12345678))
    s.dump(20, CAP_BUF, 32, "qwoff")
    s.cp(20, "off")
    s.add(poke(20, restore))
    for v in (1, 42, 43, 64, 85, 86, 127, -1):
        s.add(poke(21, [b(FMT_BUF + i, 0) for i in range(8)]), call(21, S["emus_fmt"], FMT_BUF, v))
        s.dump(21, FMT_BUF, 8, f"ef{v}")
    for v in range(7):
        s.add(poke(21, [b(FMT_BUF + i, 0) for i in range(8)]), call(21, S["tstr_fmt"], FMT_BUF, v))
        s.dump(21, FMT_BUF, 8, f"tf{v}")
    for v in (4, 64, 124):
        s.add(poke(21, [b(FMT_BUF + i, 0) for i in range(8)]), call(21, S["quant_fmt"], FMT_BUF, v))
        s.dump(21, FMT_BUF, 8, f"qf{v}")
    sc[s.name] = s

    # item 11: machine round trips
    s = Scn("item11", 420)
    s.add(poke(1, [b(UI_TRACK, 0)]),
          poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, 0) +
               park(0, 1, ST, 0) + park(0, 2, ST, 0) + p1(0, ST, 0, 80, False) + p2(0, ST, 5, 40, False)),
          poke(4, p2(0, FL, 4, 4)), poke(20, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)))
    s.cp(30, "x0")
    s.add(machine(32, 0, PU))
    s.add(poke(40, install), call(40, S["quant_widget"], 10, 20, 0, 77, 0, 0x4003b4b0, 0x12345678))
    s.dump(40, CAP_BUF, 32, "pu_qw")
    s.add(call(40, S["emus_widget"], 10, 20, 11, 33, 0, 0, 0x12345678))
    s.dump(40, CAP_BUF, 32, "pu_ew")
    s.add(poke(40, restore))
    s.cp(80, "x1")                       # on PICKUP
    s.add(machine(82, 0, FL))
    s.cp(120, "x2")                      # back on FLEX
    s.add(machine(122, 0, THRU))
    s.cp(160, "x3")
    s.add(machine(162, 0, FL))
    s.cp(200, "x4")
    s.add(machine(202, 0, ST))           # STATIC: TSTR AUTO, static slot 0 TSMODE 0 -> not VARI
    s.cp(240, "x5")
    s.add(poke(242, p2(0, ST, 4, 4)))    # STATIC in VARI too (slot 0 is 120 BPM)
    s.cp(280, "x6")
    s.add(machine(282, 0, FL))
    s.cp(320, "x7")
    s.add(machine(322, 0, ST))
    s.cp(360, "x8")
    s.add(machine(362, 0, FL))
    s.cp(400, "x9")
    sc[s.name] = s

    # latch: T1 VARI from frame 2 (mid-note: OT until its next trig); EMUS -> SP12 mid-note,
    # then -> S950 mid-note after the next trig; the DSP log shows the engine per pass
    s = Scn("latch", 4000)
    s.add(poke(2, p2(0, FL, 4, 4) + park(0, 2, FL, 0)), poke(500, p2(0, FL, 5, 127)))
    s.latch = True
    sc[s.name] = s

    # o2: the bulk writers. T1 VARI (QUAN 109 / EMUS 127, PTCH 70 / TSNS 30 parked); T2 not
    s = Scn("o2", 400)
    s.add(poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, 0) +
               p1(1, FL, 0, 50) + p2(1, FL, 5, 20) + park(1, 1, FL, 0) + park(1, 2, FL, 0) +
               park(2, 1, FL, 0) + park(2, 2, FL, 0)),
          poke(4, p2(0, FL, 4, 4)), poke(20, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)))
    s.cp(30, "o0")
    # SRC page: copy T1 (page case 0: machine, slot, 6 + 6 bytes) to the clipboard, snapshot
    # T2's page into the undo buffer, paste on T2 (the wrapped writer), then undo it
    # (the snapshot first: its wrapper clears the clipboard's type word)
    s.add(call(40, 0x40027d38, PART, 1, 0, 0), call(40, 0x40026314, 0x460bf218, PART, 0, 0, 0),
          call(40, 0x40027e4c, 0x460bf218, PART, 1, 0, 0))
    s.cp(60, "srcpaste")
    s.add(call(62, 0x40028fc4, PART, 1, 0, 0))
    s.cp(80, "srcundo")
    # track paste: T1's whole track (the playing pattern 4, whose part is part 1) onto T3
    s.add(call(82, 0x40029754, 0x460bf218, 4, 0), call(82, 0x4002b654, 0x460bf218, 4, 2))
    s.cp(100, "trkpaste")
    # PART menu: snapshot + CLEAR, then UNDO (kind 0x24, as the menu does)
    s.add(call(102, 0x400292a0, 0x24, PART), call(102, 0x4004a9d0, PART))
    s.cp(140, "clear")
    s.add(call(142, 0x40029b08, 0x24, PART))
    s.cp(142, "cu142")
    s.cp(143, "cu143")
    s.cp(150, "cu150")
    s.cp(180, "clearundo")
    # PART menu: COPY part 1, CLEAR, PASTE (part paste core 0x40029a4c through 0x40029b78)
    s.add(call(182, 0x4002932c, PART), call(182, 0x400292a0, 0x24, PART), call(182, 0x4004a9d0, PART))
    s.cp(220, "clear2")
    s.add(call(222, 0x400292a0, 0x23, PART), call(222, 0x40029b78, PART))
    s.cp(260, "partpaste")
    # RELOAD PART: back to the saved part (T1 not VARI there)
    s.add(call(262, 0x4004aab4, PART))
    s.cp(300, "reload")
    sc[s.name] = s

    # o2late: the SRC paste of o2, then T2 plays (its first trig): H1 adopts, still no swap
    s = Scn("o2late", 1500)
    s.add(poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, 0) +
               p1(1, FL, 0, 50) + p2(1, FL, 5, 20) + park(1, 1, FL, 0) + park(1, 2, FL, 0)),
          poke(4, p2(0, FL, 4, 4)), poke(20, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)),
          call(40, 0x40027d38, PART, 1, 0, 0), call(40, 0x40026314, 0x460bf218, PART, 0, 0, 0),
          call(40, 0x40027e4c, 0x460bf218, PART, 1, 0, 0))
    s.cp(1400, "late")
    sc[s.name] = s

    # o2rev: paste a non-VARI page (T2: PTCH 50 / TSNS 20, AUTO) over the VARI T1 (rp_prev 1):
    # the pasted values must stay -- a poll that took it for a live edit would swap T1's
    # parks (70 / 30) back in and park the pasted 50 / 20
    s = Scn("o2rev", 80)
    s.add(poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, 0) +
               p1(1, FL, 0, 50) + p2(1, FL, 5, 20) + p2(1, FL, 4, 1)),
          poke(4, p2(0, FL, 4, 4)), poke(20, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)))
    s.cp(30, "r0")
    s.add(call(40, 0x40027d38, PART, 0, 0, 0), call(40, 0x40026314, 0x460bf218, PART, 1, 0, 0),
          call(40, 0x40027e4c, 0x460bf218, PART, 0, 0, 0))
    # the PLAYBACK page's PTCH dial polls the panel's track (KNOB captured, then restored)
    s.add(poke(50, [b(UI_TRACK, 0)] + install), call(50, S["quant_widget"], 10, 20, 0, 50, 0, 0x4003b4b0, 0),
          poke(50, restore))
    s.cp(60, "r1")
    sc[s.name] = s

    # old56: TSTR 5/6, TSMODE 5/6 under AUTO
    s = Scn("old56", 1500)
    s.add(poke(2, p2(0, FL, 4, 5) + p2(1, FL, 4, 6) + p2(2, FL, 4, 1) + p2(3, FL, 4, 1) +
               [b(0x100b14f0 + 3 * 0x448 + 0x113, 5), b(0x100b14f0 + 10 * 0x448 + 0x113, 6)]))
    s.cp(1400, "end")
    sc[s.name] = s

    # panel_*: the real panel path, transport stopped. T1 FLEX on VARI, EMUS OT (1), TSNS 30
    # parked, rp_prev 1 (in the domain already); SRC SETUP opened with its keys on T1.
    for name, (lines, want) in PANEL.items():
        s = Scn(f"panel_{name}", 0, live=OPEN_SETUP + lines)
        s.add("-:poke:" + ";".join([b(UI_TRACK, 0)] + p2(0, FL, 4, 4) + p2(0, FL, 5, EM["OT"]) +
                                   park(0, 2, FL, 30) + [b(S["rp_prev"] + 2 * 0 + FL, 1)]))
        s.want = want
        sc[s.name] = s
    return sc


# SRC SETUP on the panel's track: [SRC] pressed twice (0x22), as on the unit
OPEN_SETUP = [(1000, "key 0x22 down"), (1100, "key 0x22 up"), (1150, "key 0x22 down"), (1250, "key 0x22 up")]
CLOSE_SETUP = lambda t: [(t, "key 0x22 down"), (t + 100, "key 0x22 up")]
REOPEN_SETUP = lambda t: [(t, "key 0x22 down"), (t + 100, "key 0x22 up"), (t + 150, "key 0x22 down"),
                          (t + 250, "key 0x22 up")]
TRACK_KEY = lambda t, k: [(t, f"key {0x10 + k:#x} down"), (t + 100, f"key {0x10 + k:#x} up")]
ENC = lambda t0, dt, ds: [(t0 + dt * i, f"enc 5 {d}") for i, d in enumerate(ds)]
O, S9, SP = "OT", "S950", "SP12"
PANEL = {
    # single detents, 150 ms apart: seven right, seven left
    "slow": (ENC(1500, 150, [1] * 7 + [-1] * 7), [O] * 5 + [S9] * 2 + [S9] * 5 + [O] * 2),
    # a fast spin, a report every 3 ms: twelve right, twelve left -- never more than one stop per six
    "fast": (ENC(1500, 3, [1] * 12) + ENC(1900, 3, [-1] * 12), [O] * 5 + [S9] * 6 + [SP] + [SP] * 5 + [S9] * 6 + [O]),
    # reports carrying several detents (the panel's count, or the parser's coalescing)
    "multi": (ENC(1500, 150, [3, 3, 6, -2, -4, -12]), [O, S9, SP, SP, S9, O]),
    # an encoder at rest bouncing +1 / -1: nothing moves
    "jitter": (ENC(1500, 40, [1, -1] * 6), [O] * 12),
    # a right turn with a back-bounce every third report: each bounce restarts the count
    "bounce": (ENC(1500, 40, [1, 1, -1] * 6), [O] * 18),
    # the encoder pushed while turning (P2EDIT's x7): still six detents per stop
    "held": ([(1400, "key 0x3d down")] + ENC(1500, 150, [1] * 7 + [-1] * 7) + [(3700, "key 0x3d up")],
             [O] * 5 + [S9] * 2 + [S9] * 5 + [O] * 2),
    # half a count, then the page closed and re-opened; then half a count, a track change
    # and back (each re-opens the page): the count restarts every time
    "reset": (ENC(1500, 150, [1] * 3) + CLOSE_SETUP(2200) + REOPEN_SETUP(2700) + ENC(3300, 150, [1] * 9)
              + TRACK_KEY(4800, 1) + TRACK_KEY(5300, 0) + ENC(5900, 150, [1] * 6),
              [O] * 3 + [O] * 5 + [S9] + [S9] * 3 + [S9] * 5 + [SP]),
}


def run(sc, jobs):
    OUTD.mkdir(parents=True, exist_ok=True)
    seq = [s for s in sc.values() if s.live is None]
    pan = [s for s in sc.values() if s.live is not None]
    base = [str(EMU), "--image", str(IMG), "--card", str(CARD), "--set", "KYOTI", "--project", "OTDEMO",
            "--load-ms", "20000"]
    if seq:
        args = base + ["--dsp", "--main-level", "64", "--scenario-jobs", str(jobs)]
        for s in seq:
            (OUTD / s.name).mkdir(parents=True, exist_ok=True)
            a = f"{OUTD / s.name / 'log.txt'} --sequencer --internal-clock --frames {s.frames}"
            for st in s.steps:
                a += f" --step {st}"
            args += ["--scenario", a]
        with open(OUTD / "parent.log", "w") as f:
            subprocess.run(args, env=dict(os.environ, OT_VEM_LOG="%o"), stdout=f, stderr=subprocess.STDOUT,
                           timeout=7200)
    if pan:
        # the panel group: a watch at P2EDIT's entry, its store and SRC SETUP's open site
        args = base + ["--watch-pc", f"{P2EDIT:#x},{P2_STORE:#x},{SETUP_OPEN_SITE:#x}", "--scenario-jobs", str(jobs)]
        for s in pan:
            d = OUTD / s.name
            d.mkdir(parents=True, exist_ok=True)
            end = max(t for t, _ in s.live) + 500
            (d / "panel.script").write_text("".join(f"{t} {l}\n" for t, l in sorted(s.live, key=lambda x: x[0]))
                                            + f"{end} quit\n")
            a = f"{d / 'log.txt'} --live-script {d / 'panel.script'}"
            for st in s.steps:
                a += f" --step {st}"
            args += ["--scenario", a]
        with open(OUTD / "parent_panel.log", "w") as f:
            subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, timeout=7200)


# ------------------------------------------------------------------------- checks
class T:
    def __init__(self, name):
        self.name, self.fails, self.notes = name, [], []

    def eq(self, what, got, want):
        if got != want:
            self.fails.append(f"{what}: got {got!r}, want {want!r}")
        else:
            self.notes.append(f"{what} = {got!r}")


def captured(d, tag):
    w = struct.unpack(">8I", (d / tag).read_bytes())
    return dict(x=w[0], y=w[1], idx=w[2], value=struct.unpack(">i", struct.pack(">I", w[3]))[0],
                flags=w[4], fmt=w[5], canvas=w[6], calls=w[7])


def check(name, s):
    d = OUTD / name
    t = T(name)
    log = (d / "log.txt").read_text() if (d / "log.txt").exists() else ""
    if getattr(s, "live", None) is not None:
        return panel_check(t, s, log)
    t.eq("run reached its frame count", "run ended REACHED" in log, True)
    t.eq("no call failed to return", "DID NOT RETURN" in log, False)
    if not t.fails or name == "old56":
        pass
    try:
        cp = {c: CP(d, c) for c in s.cps}
    except FileNotFoundError as e:
        t.fails.append(f"missing dump {e.filename}")
        return t
    if name == "swap":
        a, bb, c, dd = cp["a"], cp["b"], cp["c"], cp["d"]
        t.eq("before: PTCH / TSNS / parks", (a.p1(0, FL), a.p2(0, FL), a.park(0, 1, FL), a.park(0, 2, FL)), (70, 30, 0, 0))
        t.eq("before: rp_prev[T1][FL]", a.rp(0, FL), 0)
        t.eq("VARI: QUAN / EMUS / parks (fresh: 1/1 = 64 / OT = 1)", (bb.p1(0, FL), bb.p2(0, FL), bb.park(0, 1, FL), bb.park(0, 2, FL)), (64, 1, 70, 30))
        t.eq("VARI: rp_prev[T1][FL]", bb.rp(0, FL), 1)
        t.eq("VARI: live PTCH / base word / live TSNS", (bb.live[0], bb.base[0:2], bb.live[0x25]), (64, b"\x40\x00", 1))
        t.eq("VARI: SRAM copy follows", bb.shadow_ok(), True)
        t.eq("VARI: captions (FLEX)", (bb.name(NAME0[FL]), bb.name(NAME11[FL])), ("QUAN", "EMUS"))
        t.eq("VARI: STATIC untouched (parks, rp_prev)", (bb.park(0, 1, ST), bb.park(0, 2, ST), bb.rp(0, ST)), (0, 0, 0))
        for f in (12, 13, 14):
            e = cp[f"edge{f}"]
            pair = (e.p1(0, FL), e.p2(0, FL))
            t.eq(f"frame {f}: the two pairs together", pair in ((70, 30), (64, 1)), True)
        t.eq("left (BEAT): PTCH / TSNS back, QUAN / EMUS parked", (c.p1(0, FL), c.p2(0, FL), c.park(0, 1, FL), c.park(0, 2, FL)), (70, 30, 109, 127))
        t.eq("left: rp_prev, captions", (c.rp(0, FL), c.name(NAME0[FL]), c.name(NAME11[FL])), (0, "PTCH", "TSNS"))
        t.eq("left: live PTCH / TSNS", (c.live[0], c.base[0:2], c.live[0x25]), (70, b"\x46\x00", 30))
        t.eq("back in VARI: QUAN / EMUS / parks", (dd.p1(0, FL), dd.p2(0, FL), dd.park(0, 1, FL), dd.park(0, 2, FL)), (109, 127, 70, 30))
        t.eq("back in VARI: SRAM copy follows", dd.shadow_ok(), True)
    elif name == "fresh0":
        i, o = cp["in"], cp["out"]
        t.eq("TSNS 0 -> EMUS enters as OT (1), 0 parked", (i.p2(0, FL), i.park(0, 2, FL)), (1, 0))
        t.eq("left: TSNS back verbatim (0)", (o.p2(0, FL), o.park(0, 2, FL)), (0, 1))
    elif name == "adopt":
        a = cp["a"]
        t.eq("adopted: slots and parks unchanged", (a.p1(0, FL), a.p2(0, FL), a.park(0, 1, FL), a.park(0, 2, FL)), (109, 127, 70, 30))
        t.eq("adopted: rp_prev[T1] FL / ST", (a.rp(0, FL), a.rp(0, ST)), (1, 0))
    elif name == "p2edit":
        want = {"e0": "OT", "e5": "OT", "e6": "S950", "e7": "S950", "e8": "S950", "e9": "S950", "e10": "SP12",
                "e11": "SP12", "e12": "SP12", "e13": "S950", "e14": "OT", "e15": "SP12", "e16": "SP12",
                "e17": "SP12", "e18": "SP12", "e19": "SP12", "e20": "S950"}
        got = {k: EM_NAME.get((d / k).read_bytes()[0], (d / k).read_bytes()[0]) for k in want}
        t.eq("EMUS through P2EDIT: +1x5 | +1 | -1 | +1 | -1 +1 -1 +1 | +12 | pushed +1x4 | pushed -1x5 | pushed -1 | "
             "30 -1 | 100 +1 | -1x5 | (T2) -1 | -1x4 | (open) -1 | -1x5", got, want)
        t.eq("gate off: stock step (64 + 1)", (d / "gateoff").read_bytes()[0], 65)
        t.eq("TSTR through P2EDIT: BEAT +1 -> VARI, +1 stays", ((d / "tstr1").read_bytes()[0], (d / "tstr2").read_bytes()[0]), (4, 4))
        a = cp["after"]
        t.eq("T3 entered VARI from the editor: EMUS OT (1), TSNS 64 parked, rp_prev 1", (a.p2(2, FL), a.park(2, 2, FL), a.rp(2, FL)), (1, 64, 1))
    elif name == "widget":
        ef = S["emus_fmt"]
        qf = S["quant_fmt"]
        for tag, val, fmt in (("ew30", EM["OT"], ef), ("ew100", EM["SP12"], ef), ("ew64", EM["S950"], ef),
                              ("ew1", EM["OT"], ef), ("ewneg", -1, ef),
                              ("qw50", 49, qf), ("qw124", 124, qf)):
            c = captured(d, tag)
            t.eq(f"{tag}: KNOB(x, y, idx, value, flags, fmt, canvas)",
                 (c["x"], c["y"], c["value"], c["fmt"], c["canvas"]), (10, 20, val, fmt, 0x12345678))
        on, off = cp["on"], cp["off"]
        t.eq("VARI track: captions", (on.name(NAME0[FL]), on.name(NAME11[FL])), ("QUAN", "EMUS"))
        c = captured(d, "ewoff")
        t.eq("off VARI: EMUS widget passes the stock dial through", (c["value"], c["fmt"]), (30, 0))
        c = captured(d, "qwoff")
        t.eq("off VARI: PTCH widget passes the stock dial through", (c["value"], c["fmt"]), (77, 0x4003b4b0))
        t.eq("off VARI: captions", (off.name(NAME0[FL]), off.name(NAME11[FL])), ("PTCH", "TSNS"))
        ef_ = {v: (d / f"ef{v}").read_bytes().split(b"\0")[0].decode() for v in (1, 42, 43, 64, 85, 86, 127, -1)}
        t.eq("emus_fmt", ef_, {1: "OT", 42: "OT", 43: "S950", 64: "S950", 85: "S950", 86: "SP12", 127: "SP12", -1: "???"})
        tf = [(d / f"tf{v}").read_bytes().split(b"\0")[0].decode() for v in range(7)]
        t.eq("tstr_fmt 0..6", tf, ["OFF", "AUTO", "NORM", "BEAT", "VARI", "???", "???"])
        qf_ = [(d / f"qf{v}").read_bytes().split(b"\0")[0].decode() for v in (4, 64, 124)]
        t.eq("quant_fmt 4 / 64 / 124", qf_, ["1/2", "1/1", "2/1"])
    elif name == "item11":
        x = cp
        fl = lambda c: (c.p1(0, FL), c.p2(0, FL), c.park(0, 1, FL), c.park(0, 2, FL), c.rp(0, FL))
        stv = lambda c: (c.p1(0, ST), c.p2(0, ST), c.park(0, 1, ST), c.park(0, 2, ST))
        pu = lambda c: bytes(c.part[O_P1 + 6 * PU:O_P1 + 6 * PU + 6]) + bytes(c.part[O_P2 + 6 * PU:O_P2 + 6 * PU + 6])
        t.eq("x0 FLEX in VARI", fl(x["x0"]), (109, 127, 70, 30, 1))
        for k, what in (("x1", "on PICKUP"), ("x2", "back on FLEX"), ("x3", "on THRU"), ("x4", "back on FLEX"),
                        ("x5", "on STATIC"), ("x7", "FLEX after STATIC VARI"), ("x9", "FLEX again")):
            t.eq(f"{k} {what}: FLEX slots, parks, rp_prev unchanged", fl(x[k]), (109, 127, 70, 30, 1))
        t.eq("x1 on PICKUP: its own Part bytes unchanged", pu(x["x1"]), pu(x["x0"]))
        t.eq("x1 machine bytes", (x["x1"].mach(0), x["x3"].mach(0), x["x5"].mach(0)), (PU, THRU, ST))
        c = captured(d, "pu_qw")
        t.eq("PICKUP: PTCH widget = stock dial, no poll", (c["value"], c["fmt"]), (77, 0x4003b4b0))
        c = captured(d, "pu_ew")
        t.eq("PICKUP: EMUS widget = stock dial, no poll", (c["value"], c["fmt"]), (33, 0))
        t.eq("x5 STATIC (not VARI): its bytes untouched", stv(x["x5"]), (80, 40, 0, 0))
        t.eq("x6 STATIC entered VARI: QUAN / EMUS fresh (1/1, OT), its own parks", stv(x["x6"]), (64, 1, 80, 40))
        t.eq("x7 back on FLEX: STATIC kept", stv(x["x7"]), (64, 1, 80, 40))
        t.eq("x8 STATIC again: unchanged", stv(x["x8"]), (64, 1, 80, 40))
        t.eq("rp_prev T1 ST / FL at the end", (x["x9"].rp(0, ST), x["x9"].rp(0, FL)), (1, 1))
    elif name == "o2":
        o0 = cp["o0"]
        t.eq("o0: T1 VARI, T2 not (rp_prev 0, or 0xff: never rendered yet)",
             (o0.p1(0, FL), o0.p2(0, FL), o0.p1(1, FL), o0.p2(1, FL), o0.rp(0, FL), o0.rp(1, FL) in (0, 0xff)),
             (109, 127, 50, 20, 1, True))
        sp = cp["srcpaste"]
        t.eq("SRC paste T1 -> T2: TSTR / QUAN / EMUS adopted, T2's parks untouched, rp_prev 1",
             (sp.p2(1, FL, 4), sp.p1(1, FL), sp.p2(1, FL), sp.park(1, 1, FL), sp.park(1, 2, FL), sp.rp(1, FL) in (1, 0xff)),
             (4, 109, 127, 0, 0, True))
        su = cp["srcundo"]
        t.eq("SRC paste undone: T2 back, adopted (0, or 0xff: not rendered)",
             (su.p2(1, FL, 4), su.p1(1, FL), su.p2(1, FL), su.park(1, 1, FL), su.rp(1, FL) in (0, 0xff)),
             (o0.p2(1, FL, 4), 50, 20, 0, True))
        tp = cp["trkpaste"]
        t.eq("track paste T1 -> T3: the whole block, parks included, adopted",
             (tp.p2(2, FL, 4), tp.p1(2, FL), tp.p2(2, FL), tp.park(2, 1, FL), tp.park(2, 2, FL), tp.rp(2, FL)),
             (4, 109, 127, 70, 30, 1))
        cl = cp["clear"]
        t.eq("PART CLEAR: T1 back to defaults, nothing swapped in", (cl.p2(0, FL, 4), cl.park(0, 1, FL), cl.park(0, 2, FL), cl.rp(0, FL)),
             (cl.p2(0, FL, 4), 0, 0, 0))
        t.eq("PART CLEAR: T1's slots hold the defaults, not a park", (cl.p1(0, FL), cl.p2(0, FL)), (64, 64))
        cu = cp["clearundo"]
        t.eq("PART CLEAR undone: T1 VARI again, adopted", (cu.p2(0, FL, 4), cu.p1(0, FL), cu.p2(0, FL), cu.park(0, 1, FL), cu.park(0, 2, FL), cu.rp(0, FL)),
             (4, 109, 127, 70, 30, 1))
        pp = cp["partpaste"]
        t.eq("PART PASTE: T1 as copied, adopted", (pp.p2(0, FL, 4), pp.p1(0, FL), pp.p2(0, FL), pp.park(0, 1, FL), pp.park(0, 2, FL), pp.rp(0, FL)),
             (4, 109, 127, 70, 30, 1))
        rl = cp["reload"]
        t.eq("RELOAD PART: the saved T1 (not VARI), adopted, no swap", (rl.p2(0, FL, 4), rl.p1(0, FL), rl.p2(0, FL), rl.rp(0, FL)),
             (1, 64, 64, 0))
        t.eq("no HOLD left behind", [x for x in rl.prev[:16] if x == 0xfe], [])
        t.eq("hold depth back to 0", rl.prev[16], 0)
    elif name == "o2rev":
        r0, r1 = cp["r0"], cp["r1"]
        t.eq("r0: T1 VARI, rp_prev 1", (r0.p2(0, FL, 4), r0.p1(0, FL), r0.p2(0, FL), r0.rp(0, FL)), (4, 109, 127, 1))
        t.eq("pasted over: T1 = T2's page (AUTO, 50, 20), parks untouched, adopted 0",
             (r1.p2(0, FL, 4), r1.p1(0, FL), r1.p2(0, FL), r1.park(0, 1, FL), r1.park(0, 2, FL), r1.rp(0, FL)),
             (1, 50, 20, 70, 30, 0))
    elif name == "o2late":
        l = cp["late"]
        t.eq("T2 after its trigs: QUAN / EMUS kept, parks untouched, rp_prev 1",
             (l.p2(1, FL, 4), l.p1(1, FL), l.p2(1, FL), l.park(1, 1, FL), l.park(1, 2, FL), l.rp(1, FL)),
             (4, 109, 127, 0, 0, 1))
    elif name == "old56":
        e = cp["end"]
        t.eq("old values still there (stock does nothing with them)", (e.p2(0, FL, 4), e.p2(1, FL, 4)), (5, 6))
        t.eq("not VARI: rp_prev T1..T4", [e.rp(k, FL) for k in range(4)], [0, 0, 0, 0])
    if getattr(s, "latch", False):
        latch_check(t, d)
    return t


def panel_trace(log):
    """watch hits -> [(delta, stored)] per P2EDIT call, and the SRC SETUP opens."""
    import re
    rows, cur, opens = [], None, 0
    sgn = lambda x: (int(x, 16) ^ 0x80000000) - 0x80000000
    for l in log.splitlines():
        m = re.match(r"\s+\[\s*\d+\] at (0x[0-9a-f]+) d0=\S+ .*\[sp \S+ (\S+) (\S+) (\S+) \S+ \S+\] d2-7 (\S+)", l)
        if not m:
            continue
        pc = int(m[1], 16)
        if pc == P2EDIT:
            cur = sgn(m[4])
        elif pc == P2_STORE and cur is not None:
            rows.append((cur, sgn(m[5])))
            cur = None
        elif pc == SETUP_OPEN_SITE:
            opens += 1
    return rows, opens


def panel_check(t, s, log):
    t.eq("live script ran to its end", "ended on quit" in log, True)
    rows, opens = panel_trace(log)
    got = [EM_NAME.get(v, v) for _, v in rows]
    t.notes.append("reports " + " ".join(f"{dl:+d}" for dl, _ in rows))
    t.eq(f"{s.name}: the value after each report (EMUS OT / S950 / SP12)", got, s.want)
    if s.name == "panel_reset":
        t.eq("SRC SETUP opens (keys, re-open, track away and back)", opens, 4)
    return t


def latch_check(t, d):
    """T1 = core 1, track offset 0. tag = y:$40 bits 0-1 (0 OT, 1 S950, 2 SP12)."""
    passes = []
    for line in open(d / "log.txt.vem"):
        f = line.split()
        if int(f[0]) != 1:
            continue
        e = (int(f[2], 16), int(f[3], 16), int(f[5], 16) & 3, (int(f[7], 16) >> 12) & 1)
        if passes and passes[-1][:2] == e[:2]:
            passes[-1] = e
        else:
            passes.append(e)
    ntrk = len({p[0] for p in passes[:200]})
    t1 = [(i // (2 * ntrk), p) for i, p in enumerate(passes) if p[0] == 0]
    trigs = [fr for fr, p in t1 if p[3] and p[1] == 1]
    t.notes.append(f"T1 trig frames {trigs}")
    # the expected engine per pass: OT until the first trig after frame 500 (VARI came on
    # mid-note at frame 2, EMUS was 64 then; EMUS -> 127 at frame 500), SP12 from that trig's
    # SECOND pass (LC 1) on
    after = [fr for fr in trigs if fr > 505]
    if not after:
        t.fails.append("no T1 trig after the EMUS change: the run is too short")
        return
    k = after[0]
    bad = []
    for fr, (off, lc, tag, trig) in t1:
        if fr < 10:
            continue
        want = 0 if (fr < k or (fr == k and lc == 2)) else 2
        if tag != want:
            bad.append((fr, lc, tag, want))
    t.eq(f"engine latched at T1's trig (frame {k}): OT before, SP12 from its second pass", bad[:5], [])
    pre = sorted({tag for fr, (off, lc, tag, trig) in t1 if 505 < fr < k})
    t.eq("mid-note EMUS change (frame 500): engine unchanged until the trig", pre, [0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sc = scenarios()
    if a.only:
        sc = {k: v for k, v in sc.items() if k in a.only.split(",")}
    if not a.reuse:
        print(f"running {len(sc)} scenarios on {IMG.name} ...", flush=True)
        run(sc, a.jobs)
    res = []
    for n, s in sc.items():
        t = check(n, s)
        res.append(t)
        print(f"{'PASS' if not t.fails else 'FAIL'}  {n}")
        for f in t.fails:
            print(f"      FAIL {f}")
        for x in t.notes:
            print(f"      ok   {x}")
    (OUTD / "results.json").write_text(json.dumps({t.name: dict(fails=t.fails, notes=t.notes) for t in res}, indent=1))
    bad = [t for t in res if t.fails]
    print(f"\n{len(res) - len(bad)}/{len(res)} tests pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

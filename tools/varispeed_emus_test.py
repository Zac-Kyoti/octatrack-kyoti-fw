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
  guard_*   the DSP load guard (spec §6), on the REAL export MMTESTDT (T1-T8 STATIC, part 0):
            T5-T8 (DSP core 0) on VARI SP12 on slot 0's sample, trigs poked into the
            playing pattern at steps 1/3/5/7, FX2 DARK x4, FX1 DJ EQ x2 or x3 -- all by
            runtime pokes. x2: nothing steps down (and the DSP increments equal VEM3's,
            VEM_IMG_REF); x3: the latch steps the later sounds down; mid-note: a third DJ EQ
            steps the most recently started down at once, a silent voice before them;
            restore only at the next trig. The readout (spec §6a item 1): the dial stays on
            the EMUS choice, the readout names the engine played, marked (emus_fmt_ot_dn /
            emus_fmt_s95_dn: OT! / S95!). No toast from any of it. EVERY expectation comes
            from GuardModel, an independent model of the rules fed with the VG_* block read
            from varispeed_emus.s, and each scenario checks that it still discriminates (it
            steps something down; the oldest-first / silence-ignoring rules would differ).
  toast_*   the guard's toast (spec §6a item 2), MMTESTDT, T5-T7 VARI SP12 + DJ EQ: the user's
            own action on T8 -- EMUS turned through P2EDIT (toast_emus: S950 fits, SP12 does
            not; toast_emus_ot: neither fits), TSTR BEAT -> VARI through P2EDIT (toast_tstr),
            ATTR TIMESTRETCH BEAT -> VARI under AUTO through the value-up key handler
            (toast_attr). NOTIFY captured (and still run) per action: the text, 0x30, the
            stock toast open; no toast where the model says the engine fits.
  panel_*   EMUS through the REAL panel path, transport stopped: SRC SETUP opened with its
            keys, encoder F reports into the panel UART (the parser, its coalescing, the UI
            task, the page's encoder table, P2EDIT), every stored value logged at P2EDIT's
            store (0x4003a5ba). slow / fast / multi / jitter / bounce / held turns, and
            reset (the page closed and re-opened, a track change and back, mid-count). The
            first hardware build (140C_VEM1) fails these: one stop per report, any sign.

EMUS order (2026-10-14): OT (stored 1, left), S950 (64, middle), SP12 (127, right).
"""
import argparse, json, os, pathlib, re, struct, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCR = ROOT / "out/vem"
EMU = pathlib.Path(os.environ.get("VEM_EMU", SCR / "octabam/out/emu/ot_emu"))
IMG = pathlib.Path(os.environ.get("VEM_IMG", ROOT / "out/mainos_varispeed_emus.bin"))
SYMS = pathlib.Path(os.environ.get("VEM_SYMS", ROOT / "out/varispeed_emus_syms.json"))
EM = {"OT": 1, "S950": 64, "SP12": 127}           # EMUS stops, left to right
EM_NAME = {v: k for k, v in EM.items()}
CARD = SCR / "img/otdemo.img"
# the guard tests: a second REAL hardware export (T1-T8 STATIC, part 0, pattern 0, 120 BPM)
MM = dict(card=SCR / "img/mmtestdt.img", set="MMTESTDT", project="test")
OTD = dict(card=CARD, set="KYOTI", project="OTDEMO")
# the image the guard's under-budget runs are compared with, pass for pass (VEM3)
IMG_REF = pathlib.Path(os.environ.get("VEM_IMG_REF", ROOT / "out/vem_variants/mainos_varispeed_emus_vem3.bin"))
SRC = ROOT / "octabam-modules/varispeed-emus/varispeed_emus.s"
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
NCAP_AT, NCAP_BUF = 0x400d7b00, 0x400d7b80        # the NOTIFY capture (count, text, dur), same tail
NOTIFY, NOTIF_H, NOTIF_T = 0x4005a2b8, 0x460d1e70, 0x460d1e6c    # the stock toast, its handle, countdown
NOTIFY_STOCK = bytes.fromhex("2f032f02242f000c")  # its first 8 bytes (the stub replays them)
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


def ncap_stub():
    """NOTIFY -> count the call, keep its (text, dur), then run stock's NOTIFY unchanged (the
    stub replays the 8 bytes its jmp displaces): the toast still opens. Poked at runtime."""
    src = ["        .text", f"        lea     ({NCAP_BUF:#x}).l,%a0", "        move.l  (%a0),%d0",
           "        addq.l  #1,%d0", "        move.l  %d0,(%a0)", "        move.l  4(%sp),%d0",
           "        move.l  %d0,4(%a0)", "        move.l  8(%sp),%d0", "        move.l  %d0,8(%a0)",
           "        move.l  %d3,-(%sp)", "        move.l  %d2,-(%sp)", "        move.l  12(%sp),%d2",
           f"        jmp     ({NOTIFY + 8:#x}).l"]
    w = OUTD / "ncap"
    w.mkdir(parents=True, exist_ok=True)
    (w / "ncap.s").write_text("\n".join(src) + "\n")
    for c in (["m68k-elf-as", "-mcpu=54455", "-o", w / "ncap.o", w / "ncap.s"],
              ["m68k-elf-ld", f"-Ttext={NCAP_AT:#x}", "-e", "0", "-o", w / "ncap.elf", w / "ncap.o"],
              ["m68k-elf-objcopy", "-O", "binary", w / "ncap.elf", w / "ncap.bin"]):
        subprocess.run([str(x) for x in c], check=True, capture_output=True)
    code = (w / "ncap.bin").read_bytes()
    jmp = b"\x4e\xf9" + NCAP_AT.to_bytes(4, "big")
    return [b(NCAP_AT + i, x) for i, x in enumerate(code)] + [b(NCAP_BUF + i, 0) for i in range(12)] + \
           [b(NOTIFY + i, x) for i, x in enumerate(jmp)]


def ncap_reset():
    return [b(NCAP_BUF + i, 0) for i in range(12)]


class Scn:
    def __init__(self, name, frames, live=None, proj=OTD, img=None):
        self.name, self.frames, self.steps, self.cps = name, frames, [], []
        self.live = live                 # panel scenarios: [(emulated ms, live line)], no transport
        self.proj, self.img = proj, img  # the card / project; another image (the guard's reference run)

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

    # ---- the DSP load guard: MMTESTDT, T5-T8 (DSP core 0) on VARI, FX2 DARK x4
    SP = {t: "SP12" for t in GT}
    X2 = {4: "DJEQ", 5: "DJEQ"}
    X3 = {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"}
    # x2: 4 x SP12 + DARK x4 + DJ EQ x2 fits: nothing steps down, the increments are VEM3's
    for nm, img in (("guard_x2", None), ("guard_x2_ref", IMG_REF)):
        s = guard_scn(nm, SP, X2, img=img)
        g_dump(s, G_F1, "f1")
        g_dump(s, G_FRAMES - 20, "end")
        sc[s.name] = s
    # x3: over budget from the start: the latch steps the later sounds down (and no toast:
    # the guard acting on its own says nothing)
    s = guard_scn("guard_x3", SP, X3)
    s.add("-:poke:" + ";".join(ncap_stub()))
    g_dump(s, G_F1, "f1")
    g_dump(s, G_FRAMES - 20, "end")
    s.dump(G_FRAMES - 20, NCAP_BUF, 12, "end.ncap")
    sc[s.name] = s
    # the latch's S950 -> OT as well: EMUS SP12 SP12 S950 S950, FX1 DJ EQ x3 + FILTER; the
    # readout of the stepped-down tracks (dial on their choice, the playing engine marked)
    s = guard_scn("guard_latch", {4: "SP12", 5: "SP12", 6: "S950", 7: "S950"},
                  {4: "DJEQ", 5: "DJEQ", 6: "DJEQ", 7: "FILTER"})
    g_dump(s, G_F1, "f1")
    w = G_F1 + 1
    s.add(poke(w, install))
    for tag, t in (("w5", 4), ("w6", 5), ("w7", 6), ("w8", 7)):
        s.add(poke(w, [b(UI_TRACK, t)]), call(w, S["emus_widget"], 10, 20, 11, EM[s.guard["emus"][t]], 0, 0, 0x12345678))
        s.dump(w, CAP_BUF, 32, tag)
    s.add(poke(w, restore))
    sc[s.name] = s
    # mid-note: x2 (all SP12), a third DJ EQ at G_F1 -> the most recently started step down
    # at once; the readout marker; the DJ EQ removed at G_F2 -> nothing restores until each
    # stepped-down track's next trig
    for nm, silent in (("guard_mid", None), ("guard_silent", 5)):
        s = guard_scn(nm, SP, X2)
        s.add("-:poke:" + ";".join(ncap_stub()))     # the guard's own step-down: no toast
        if silent is not None:                       # T6's voice stops (stock's voice reset)
            s.add(call(G_F1 - 4, 0x40006820, silent))
        g_dump(s, G_F1 - 1, "pre")
        s.add(poke(G_F1, mm_fx({6: "DJEQ"}, {})))
        g_dump(s, G_F1 + 3, "mid")
        if silent is None:
            w = G_F1 + 20
            s.add(poke(w, install))
            for tag, t in (("w8", 7), ("w7", 6), ("w5", 4)):
                s.add(poke(w, [b(UI_TRACK, t)]), call(w, S["emus_widget"], 10, 20, 11, EM["SP12"], 0, 0, 0x12345678))
                s.dump(w, CAP_BUF, 32, tag)
            s.add(poke(w, restore))
            for fn in ("emus_fmt_ot_dn", "emus_fmt_s95_dn"):
                s.add(poke(w + 1, [b(FMT_BUF + i, 0) for i in range(8)]), call(w + 1, S[fn], FMT_BUF, EM["SP12"]))
                s.dump(w + 1, FMT_BUF, 8, fn)
        s.add(poke(G_F2, mm_fx({6: "NONE"}, {})))
        g_dump(s, G_F2 + 3, "rm")
        g_dump(s, G_FRAMES - 20, "end")
        s.dump(G_FRAMES - 20, NCAP_BUF, 12, "end.ncap")
        if silent is None:
            w = G_FRAMES - 10
            s.add(poke(w, install + [b(UI_TRACK, 7)]), call(w, S["emus_widget"], 10, 20, 11, EM["SP12"], 0, 0, 0x12345678))
            s.dump(w, CAP_BUF, 32, "w8end")
            s.add(poke(w, restore))
        s.silent = silent
        sc[s.name] = s

    # ---- the guard's toast (spec §6a item 2): the user's own actions on T8, T5-T7 VARI SP12
    T3 = {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"}
    ed2 = lambda fr, slot, d: call(fr, P2EDIT, slot, d)
    emus_turns = [(T_F0, "a1", [ed2(T_F0, 5, 6)], "S950"),          # OT -> S950 (six detents)
                  (T_F0 + 1, "a2", [ed2(T_F0 + 1, 5, 6)], "SP12"),  # S950 -> SP12
                  (T_F0 + 2, "a3", [ed2(T_F0 + 2, 5, -6)], "S950"), # back to S950
                  (T_F0 + 3, "a4", [ed2(T_F0 + 3, 5, -6)], "OT"),   # back to OT
                  (T_F0 + 4, "a5", [ed2(T_F0 + 4, 5, 3)], None)]    # half a stop: no new stop, nothing
    # EMUS on T8 (OT, VARI), FX1 NONE: S950 fits, SP12 does not -> "MAX DSP: S950 USED"
    sc["toast_emus"] = toast_scn("toast_emus", {4: "SP12", 5: "SP12", 6: "SP12", 7: "OT"}, T3, emus_turns)
    # the same with SPATIALIZER on T8's FX1: neither fits -> "MAX DSP: OT USED"
    sc["toast_emus_ot"] = toast_scn("toast_emus_ot", {4: "SP12", 5: "SP12", 6: "SP12", 7: "OT"},
                                    {**T3, 7: "SPATIALIZER"}, emus_turns)
    # TSTR on T8 (BEAT, EMUS SP12 parked) -> VARI: does not fit; back to BEAT: nothing; EMUS
    # S950 parked, -> VARI again: fits, nothing
    tstr_steps = [(T_F0, "t1", [ed2(T_F0, 4, 1)], "SP12"),
                  (T_F0 + 10, "t2", [ed2(T_F0 + 10, 4, -1)], None),
                  (T_F0 + 20, "t3", [poke(T_F0 + 20, mm_byte(O_P2 + 30 * 7 + PARK2[ST], EM["S950"])),
                                     ed2(T_F0 + 20, 4, 1)], "S950")]
    sc["toast_tstr"] = toast_scn("toast_tstr", {4: "SP12", 5: "SP12", 6: "SP12"}, T3, tstr_steps,
                                 tstr={7: 3}, park={7: "SP12"})
    # ATTR TIMESTRETCH BEAT -> VARI on T8's sample (STATIC slot 1) with T8 on AUTO, EMUS SP12
    # parked: the value-up key handler, the audio editor set on that sample's row 2
    tsm = STATIC_SET + 0x448 * G_SLOT[7] + 0x110
    attr = [(T_F0, "r1", [poke(T_F0, lpoke(ATTR_SLOT, G_SLOT[7]) + lpoke(ATTR_MACH, 0) + lpoke(ATTR_ROW, 2) +
                               lpoke(ATTR_MODE, 0)), call(T_F0, ATTR_UP)], "SP12")]
    sc["toast_attr"] = toast_scn("toast_attr", {4: "SP12", 5: "SP12", 6: "SP12"}, T3, attr,
                                 tstr={7: 1}, park={7: "SP12"}, extra=lpoke(tsm, 3))

    # panel_*: the real panel path, transport stopped. T1 FLEX on VARI, EMUS OT (1), TSNS 30
    # parked, rp_prev 1 (in the domain already); SRC SETUP opened with its keys on T1.
    for name, (lines, want) in PANEL.items():
        s = Scn(f"panel_{name}", 0, live=OPEN_SETUP + lines)
        s.add("-:poke:" + ";".join([b(UI_TRACK, 0)] + p2(0, FL, 4, 4) + p2(0, FL, 5, EM["OT"]) +
                                   park(0, 2, FL, 30) + [b(S["rp_prev"] + 2 * 0 + FL, 1)]))
        s.want = want
        sc[s.name] = s
    return sc


# ------------------------------------------------------------------------- the DSP load guard
def vg_constants():
    """The VG_* block of varispeed_emus.s: the one source of every price and budget."""
    return {k: int(v, 0) for k, v in re.findall(r"^\s*\.equ\s+(VG_\w+),\s*(0x[0-9a-fA-F]+|\d+)", SRC.read_text(), re.M)}


VG = vg_constants()
FXID = {"NONE": 0x00, "FILTER": 0x04, "SPATIALIZER": 0x05, "DELAY": 0x08, "EQ": 0x0c, "DJEQ": 0x0d,
        "PHASER": 0x10, "FLANGER": 0x11, "CHORUS": 0x12, "COMB": 0x13, "PLATE": 0x14, "SPRING": 0x15,
        "DARK": 0x16, "COMPRESSOR": 0x18, "LOFI": 0x1c}
ENG = {"OT": 0, "S950": 1, "SP12": 2}
ENG_NAME = {v: k for k, v in ENG.items()}


def fx_price(name):
    return VG["VG_FX_SPRING_HERE"] if name == "SPRING" else VG[f"VG_FX_{name}"]


def eng_price(e):
    return (0, VG["VG_S950"], VG["VG_SP12"], VG["VG_S950"])[e]


class GuardModel:
    """An independent model of spec §6 / IMPL §10.2 for ONE DSP core (T5-T8 = core 0 here),
    built from the VG_* block alone: the estimate, the latch, the mid-note step-down (silent
    first, then the most recently started) and the UI's "does it fit" (spec §6a). The rule
    switches (oldest, silent_first) model the deliberately wrong builds: a scenario must
    tell them apart from the right rule, or it cannot catch them."""
    def __init__(self, core0=True):
        self.base = VG["VG_BASE_C0" if core0 else "VG_BASE_C1"] + VG["VG_SC"]
        self.budget = VG["VG_BUDGET_C0" if core0 else "VG_BUDGET_C1"]
        self.eng, self.stamp, self.clock = {}, {}, 0

    def copy(self):
        m = GuardModel()
        m.base, m.budget, m.eng, m.stamp, m.clock = self.base, self.budget, dict(self.eng), dict(self.stamp), self.clock
        return m

    @staticmethod
    def fxsum(fx):
        return sum(fx_price(f) for pair in fx for f in pair)

    def est(self, fx):
        return self.base + self.fxsum(fx) + sum(eng_price(e) for e in self.eng.values())

    def free(self, fx):
        return self.base + self.fxsum(fx) + 4 * VG["VG_SP12"] <= self.budget

    def latch(self, fx, t, want):
        self.eng[t] = 0
        e = want
        while e and self.est(fx) + eng_price(e) > self.budget:
            e -= 1
        self.eng[t] = e
        self.clock += 1
        self.stamp[t] = self.clock
        return e

    def mid(self, fx, silent=(), oldest=False, silent_first=True):
        if self.free(fx):
            return
        while self.est(fx) > self.budget:
            cands = [t for t, e in self.eng.items() if e]
            if not cands:
                return
            age = (lambda t: -self.stamp.get(t, 0)) if oldest else (lambda t: self.stamp.get(t, 0))
            v = max(cands, key=lambda t: ((t in silent) and silent_first, age(t), t))
            self.eng[v] -= 1

    def ask(self, fx, t, want):
        """spec §6a: the engine the guard would use for track t asking `want` now (the core's
        estimate with t counted on that engine, the latch's step-down) -- the toast's word."""
        room = self.budget - self.base - self.fxsum(fx) - sum(eng_price(e) for k, e in self.eng.items() if k != t)
        e = want
        while e and eng_price(e) > room:
            e -= 1
        return e


MMDB = 0x400e21e0
MMP, MMSH = MMDB + 0x8ed80, 0x100a4ece         # MMTESTDT's part 0 (the playing one) and its SRAM copy
MM_LIVE_SLOT = 0x8000082f                      # the live sample-slot byte, + 72t (the voice loop's own)
GT = (4, 5, 6, 7)                              # T5-T8: DSP core 0
G_STEPS = {4: 1, 5: 3, 6: 5, 7: 7}             # their trigs, poked into pattern 0 (16 steps, 120 BPM)
G_SLOT = {4: 0, 5: 1, 6: 0, 7: 1}              # the two STATIC slots with a sample (146.6 / 120 BPM)
G_F1, G_F2, G_FRAMES = 2600, 3500, 8200        # mid-bar: after T8's first trig; bar 2 from ~5512


def mm_byte(off, v):
    return [b(MMP + off, v), b(MMSH + off, v)]


def mm_fx(fx1, fx2):
    """{t: name} -> the Part's FX ids and the live ones (0x80000ec4 / 0x80000ecc)."""
    out = []
    for t, n in fx1.items():
        out += mm_byte(t, FXID[n]) + [b(0x80000ec4 + t, FXID[n])]
    for t, n in fx2.items():
        out += mm_byte(8 + t, FXID[n]) + [b(0x80000ecc + t, FXID[n])]
    return out


def mm_setup(emus, fx1, tstr=None, park=None, extra=()):
    """Before the transport: T5-T8 VARI on a sample (or the TSTR given per track), EMUS per
    track (or parked: STATIC's TSNS park, for a track that is not on VARI yet), trigs, FX2
    DARK x4, FX1 as given (the rest NONE)."""
    pk = list(extra)
    tstr, park = tstr or {}, park or {}
    for t in GT:
        ts = tstr.get(t, 4)
        pk += mm_byte(O_P2 + 30 * t + 4, ts) + [b(LIVE_P2 + 72 * t + 4, ts)]           # TSTR (VARI)
        if t in emus:
            pk += mm_byte(O_P2 + 30 * t + 5, EM[emus[t]]) + [b(LIVE_P2 + 72 * t + 5, EM[emus[t]])]
        if t in park:
            pk += mm_byte(O_P2 + 30 * t + PARK2[ST], EM[park[t]])
        pk += mm_byte(O_SLOT5 + 5 * t, G_SLOT[t]) + [b(MM_LIVE_SLOT + 72 * t, G_SLOT[t])]
        st = G_STEPS[t] - 1
        pk.append(b(MMDB + t * 0x91a + 7 - st // 8, 1 << (st % 8)))                       # trig mask
    pk += mm_fx({t: fx1.get(t, "NONE") for t in GT}, {t: "DARK" for t in GT})
    return "-:poke:" + ";".join(pk)


def guard_scn(name, emus, fx1, frames=G_FRAMES, img=None):
    s = Scn(name, frames, proj=MM, img=img)
    s.add(mm_setup(emus, fx1))
    s.guard = dict(emus=emus, fx1=fx1)
    return s


# the toast tests (spec §6a item 2): T5-T7 on VARI SP12 with DJ EQ on their FX1 (latched in
# bar 1 by frame ~2,000), then the user's own action on T8 at T_F0..: EMUS turned through
# P2EDIT, TSTR onto VARI through P2EDIT, ATTR TIMESTRETCH BEAT -> VARI under AUTO through
# the ATTR value-up key handler. NOTIFY is captured (and still runs) from the start.
T_F0 = 2600
STATIC_SET = 0x100d5b30                          # STATIC sample settings records, stride 0x448
ATTR_UP = 0x4006edc8                             # the audio editor's value-up key handler
ATTR_SLOT, ATTR_MACH, ATTR_ROW, ATTR_MODE = 0x46c8d19c, 0x46c8d1a0, 0x460e5e74, 0x460e5e5c


def lpoke(a, v):
    return [b(a + i, x) for i, x in enumerate((v & 0xffffffff).to_bytes(4, "big"))]


def toast_scn(name, emus, fx1, actions, tstr=None, park=None, extra=()):
    """actions: [(frame, tag, [steps], (track, engine asked))]; each runs with the capture
    reset first and dumps it after (tag.ncap), with T8's EMUS / TSTR bytes and the toast pair."""
    s = Scn(name, 4200, proj=MM)
    s.add(mm_setup(emus, fx1, tstr, park, extra), "-:poke:" + ";".join(ncap_stub()))
    g_dump(s, T_F0 - 1, "pre")
    s.add(poke(T_F0 - 1, [b(UI_TRACK, 7)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)))
    for fr, tag, steps, _ in actions:
        s.add(poke(fr, ncap_reset()))
        s.add(*steps)
        s.dump(fr, NCAP_BUF, 12, f"{tag}.ncap")
        s.dump(fr, NOTIF_T, 8, f"{tag}.toast")     # 0x460d1e6c countdown, 0x460d1e70 handle
        s.dump(fr, MMP + O_P2 + 30 * 7, 30, f"{tag}.p2")
        s.dump(fr, STATIC_SET + 0x448 * G_SLOT[7] + 0x110, 4, f"{tag}.tsmode")
    s.toast = dict(emus=emus, fx1=fx1, actions=actions)
    return s


def g_dump(s, frame, tag):
    """voice +0 (sounding), render +36 (the carried engine), the guard's state"""
    d = OUTD / s.name
    s.add(f"{frame}:dump:0x800049d8,{168 * 8:#x}={d / (tag + '.voice')};0x80004898,{40 * 8:#x}={d / (tag + '.render')};"
          f"{S['vg_down']:#x},8={d / (tag + '.down')};{S['vg_stamp']:#x},32={d / (tag + '.stamp')};"
          f"{S['vg_est']:#x},4={d / (tag + '.est')}")


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
    def base(proj=OTD, img=None):
        return [str(EMU), "--image", str(img or IMG), "--card", str(proj["card"]), "--set", proj["set"],
                "--project", proj["project"], "--load-ms", "20000"]
    groups = {}
    for s in seq:                        # one load per card / project / image, forked per scenario
        groups.setdefault((s.proj["project"], str(s.img or IMG)), []).append(s)
    procs = []
    for (pname, img), ss in groups.items():
        args = base(ss[0].proj, ss[0].img) + ["--dsp", "--main-level", "64", "--scenario-jobs", str(jobs)]
        for s in ss:
            (OUTD / s.name).mkdir(parents=True, exist_ok=True)
            a = f"{OUTD / s.name / 'log.txt'} --sequencer --internal-clock --frames {s.frames}"
            for st in s.steps:
                a += f" --step {st}"
            args += ["--scenario", a]
        tag = "" if (pname, img) == ("OTDEMO", str(IMG)) else f"_{pname}_{pathlib.Path(img).stem}"
        procs.append(subprocess.Popen(args, env=dict(os.environ, OT_VEM_LOG="%o"),
                                      stdout=open(OUTD / f"parent{tag}.log", "w"), stderr=subprocess.STDOUT))
    for pr in procs:
        pr.wait(timeout=7200)
    if pan:
        # the panel group: a watch at P2EDIT's entry, its store and SRC SETUP's open site
        args = base() + ["--watch-pc", f"{P2EDIT:#x},{P2_STORE:#x},{SETUP_OPEN_SITE:#x}", "--scenario-jobs", str(jobs)]
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
    if hasattr(s, "guard"):
        guard_check(t, s, d)
    if hasattr(s, "toast"):
        toast_check(t, s, d)
    return t


def vem_passes(path):
    """The VEM log -> {core: [(x418, lc, x40, y40, trig)]}, one entry per voice pass."""
    out = {0: [], 1: []}
    for line in open(path):
        f = line.split()
        if len(f) < 8:
            continue
        e = (int(f[2], 16), int(f[3], 16), int(f[4], 16), int(f[5], 16), (int(f[7], 16) >> 12) & 1)
        L = out[int(f[0])]
        if L and L[-1][:2] == e[:2]:     # an interrupt at the kernel entry: one pass logged twice
            L[-1] = e
        else:
            L.append(e)
    return out


def core0_engines(d):
    """T5-T8's second passes: {t: [(frame, engine, trig)]} (core 0, track offset / 0x20)."""
    P = vem_passes(d / "log.txt.vem")[0]
    ntrk = len({p[0] for p in P[:200]}) or 1
    per = {}
    for i, p in enumerate(P):
        if p[1] == 1:
            per.setdefault(4 + p[0] // 0x20, []).append((i // (2 * ntrk), p[3] & 3, p[4]))
    return per


def g_state(d, tag):
    v = (d / f"{tag}.voice").read_bytes()
    r = (d / f"{tag}.render").read_bytes()
    return dict(sounding={t: v[168 * t] != 0 for t in range(8)},
                eng={t: (struct.unpack(">I", r[40 * t + 36:40 * t + 40])[0] >> 2) & 3 for t in range(8)},
                down=list((d / f"{tag}.down").read_bytes()),
                stamp=struct.unpack(">8I", (d / f"{tag}.stamp").read_bytes()),
                est=struct.unpack(">I", (d / f"{tag}.est").read_bytes())[0])


def seg(per, t, lo, hi):
    """the engines track t played on its second passes in frames lo..hi"""
    return sorted({e for fr, e, _ in per.get(t, []) if lo <= fr <= hi})


def ncap(d, tag):
    c, txt, dur = struct.unpack(">3I", (d / tag).read_bytes())
    return c, txt, dur


def img_str(addr):
    """A string in the built image (the toast texts are the unit's own)."""
    img = IMG.read_bytes()
    return img[addr - 0x40000400:addr - 0x40000400 + 64].split(b"\0")[0].decode("latin1")


def toast_px(text):
    """The text's width in the stock toast font 0x400ba862, as stock's measure 0x40012f30
    computes it (fixed width +0, per-char widths at [+8], glyph map at [+12], 1 px apart)."""
    img = IMG.read_bytes()
    rd = lambda a, n: img[a - 0x40000400:a - 0x40000400 + n]
    L = lambda a: struct.unpack(">I", rd(a, 4))[0]
    f = 0x400ba862
    fixed, wt, gi = L(f), L(f + 8), L(f + 12)
    w = 0
    for ch in text.encode():
        if struct.unpack(">h", rd(gi + 2 * ch, 2))[0] < 0:
            continue
        w += 1 if w else 0
        x = struct.unpack("b", rd(wt + ch, 1))[0]
        w += x if x else fixed
    return w


def toast_name(e):
    return None if e is None else {0: "MAX DSP: OT USED", 1: "MAX DSP: S950 USED"}[e]


def guard_check(t, s, d):
    """Every expectation derives from the VG_* block through GuardModel (the spec's rules),
    never from hand-written engines: a price change moves the expectations with it. Each
    scenario also checks that it still DISCRIMINATES -- that it steps something down, and
    that the wrong rules (oldest first, silence ignored) would give another result -- so a
    price change that makes it toothless fails loudly instead of passing quietly."""
    per = core0_engines(d)
    g = s.guard
    trigs = {k: [fr for fr, _, tr in per.get(k, []) if tr] for k in GT}
    t.notes.append("trig frames " + " ".join(f"T{k + 1}:{v[:3]}" for k, v in trigs.items()))
    if any(len(trigs[k]) < 2 for k in GT):
        t.fails.append("each of T5-T8 must trigger twice (bars 1 and 2): the run is too short or the trigs were not set")
        return
    first_done = max(trigs[k][0] for k in GT)
    fx0 = [(g["fx1"].get(k, "NONE"), "DARK") for k in GT]
    # the latch, bar 1 (in trig order) and bar 2 (same FX unless changed)
    m = GuardModel()
    order = sorted(GT, key=lambda k: trigs[k][0])
    want = {k: ENG[g["emus"][k]] for k in GT}
    bar1 = {k: m.latch(fx0, k, want[k]) for k in order}
    nm = lambda e: ENG_NAME[e]
    t.notes.append("the model's latch, bar 1: " + " ".join(f"T{k + 1} {nm(bar1[k])}" for k in GT) +
                   f" (est {m.est(fx0)}, budget {m.budget})")
    name = s.name
    if name in ("guard_x2", "guard_x2_ref", "guard_x3", "guard_latch"):
        down = {k: bar1[k] < want[k] for k in GT}
        if name in ("guard_x2", "guard_x2_ref"):
            t.eq("spec §6 item 6: 4 x SP12 + DARK x4 + DJ EQ x2 does not step down (the model)", any(down.values()), False)
        elif name == "guard_x3":
            t.eq("spec §6 item 6: 4 x SP12 + DARK x4 + DJ EQ x3 steps down at the latch (the model)", any(down.values()), True)
        else:
            t.eq("the scenario steps an S950 voice to OT at the latch (the model)",
                 any(want[k] == 1 and bar1[k] == 0 for k in GT), True)
        for k in GT:
            lo, hi = trigs[k][0] + 1, trigs[k][1] - 1
            t.eq(f"T{k + 1} bar 1: the engine it plays, from its first trig (the model's latch)",
                 [nm(e) for e in seg(per, k, lo, hi)], [nm(bar1[k])])
            t.eq(f"T{k + 1} bar 2: the same at its next trig", [nm(e) for e in seg(per, k, trigs[k][1], s.frames - 30)],
                 [nm(bar1[k])])
        if name != "guard_x2_ref":
            st = g_state(d, "f1")
            t.eq("vg_down T5..T8 (stepped down at the latch)", st["down"][4:8], [int(down[k]) for k in GT])
            if not m.free(fx0):              # a free core keeps no estimate (nothing can overrun)
                t.eq("the estimate (vg_est) = the model's", st["est"], m.est(fx0))
        if name == "guard_x3":
            t.eq("no toast: the guard acting on its own at the latch says nothing", ncap(d, "end.ncap")[0], 0)
        if name == "guard_latch":
            # spec §6a item 1: the dial stays on the user's choice, the readout names the
            # engine played, marked
            ef = S["emus_fmt"]
            fdn = {0: S["emus_fmt_ot_dn"], 1: S["emus_fmt_s95_dn"]}
            for tag, k in (("w5", 4), ("w6", 5), ("w7", 6), ("w8", 7)):
                c = captured(d, tag)
                exp = (EM[g["emus"][k]], fdn[bar1[k]] if down[k] else ef)
                t.eq(f"{tag}: T{k + 1} EMUS {g['emus'][k]}, playing {nm(bar1[k])}: the dial on the choice, "
                     f"the readout {'marked' if down[k] else 'plain'}", (c["value"], c["fmt"]), exp)
            t.eq("the scenario shows an OT! readout", any(down[k] and bar1[k] == 0 for k in GT), True)
        if name == "guard_x2":
            ref = vem_passes(OUTD / "guard_x2_ref" / "log.txt.vem")
            new = vem_passes(d / "log.txt.vem")
            for c in (0, 1):
                n = min(len(ref[c]), len(new[c]))
                diff = [i for i in range(n) if new[c][i][:4] != ref[c][i][:4]]
                t.eq(f"core {c}: every pass (l:$40, LC, track) equals VEM3's ({n} passes)", (diff[:3], len(ref[c]) == len(new[c])), ([], True))
        return
    # mid-note: x2 at the start, a third DJ EQ at G_F1
    pre, mid, rm, end = (g_state(d, k) for k in ("pre", "mid", "rm", "end"))
    t.eq("bar 1: the model's latch (x2)", {k + 1: nm(pre["eng"][k]) for k in GT}, {k + 1: nm(bar1[k]) for k in GT})
    silent = {k for k in GT if not pre["sounding"][k]}
    t.notes.append(f"sounding at G_F1: {[k + 1 for k in GT if pre['sounding'][k]]}, silent {[k + 1 for k in sorted(silent)]}")
    fx1 = [(("DJEQ" if k == 6 else g["fx1"].get(k, "NONE")), "DARK") for k in GT]
    wrong_old, wrong_sil = m.copy(), m.copy()
    m.mid(fx1, silent)
    wrong_old.mid(fx1, silent, oldest=True)
    wrong_sil.mid(fx1, silent, silent_first=False)
    exp = dict(m.eng)
    stepped = [k for k in GT if exp[k] < bar1[k]]
    t.notes.append("the model, mid-note: " + " ".join(f"T{k + 1} {nm(exp[k])}" for k in GT) +
                   f" | oldest first: {' '.join(nm(wrong_old.eng[k]) for k in GT)}"
                   f" | silence ignored: {' '.join(nm(wrong_sil.eng[k]) for k in GT)}")
    t.eq("the scenario steps something down mid-note (the model)", bool(stepped), True)
    if name == "guard_mid":
        t.eq("the scenario tells most-recent-first from oldest-first (the models differ)", exp != wrong_old.eng, True)
    if name == "guard_silent":
        t.eq("T6 silent (its voice stopped at G_F1 - 4)", 5 in silent, True)
        t.eq("the scenario tells silent-first from silence ignored (the models differ)", exp != wrong_sil.eng, True)
    t.eq("mid-note: the core's engines = the model's (silent first, then the most recently started)",
         {k + 1: nm(mid["eng"][k]) for k in GT}, {k + 1: nm(exp[k]) for k in GT})
    t.eq("mid-note: vg_down = the stepped-down tracks", mid["down"][4:8], [int(exp[k] < want[k]) for k in GT])
    t.eq("mid-note: vg_est = the model's estimate", mid["est"], m.est(fx1))
    # at once: the DSP sees it within three frames of the poke, and before that nothing moved
    for k in stepped:
        first = min((fr for fr, e, _ in per[k] if fr >= G_F1 - 50 and e != bar1[k]), default=None)
        t.eq(f"T{k + 1}: stepped down at once (first cheaper pass within 3 frames of the poke at {G_F1})",
             first is not None and G_F1 <= first <= G_F1 + 3, True)
        t.notes.append(f"T{k + 1} first cheaper pass at frame {first}")
    t.eq("before the third DJ EQ: no step-down", {k + 1: seg(per, k, first_done + 1, G_F1 - 1) for k in GT},
         {k + 1: [bar1[k]] for k in GT})
    # removed at G_F2: nothing comes back until each track's next trig
    t.eq("DJ EQ removed: the stepped-down engines stay (no restore mid-note)", {k + 1: nm(rm["eng"][k]) for k in GT},
         {k + 1: nm(exp[k]) for k in GT})
    m2 = m.copy()                                    # bar 2: each trig latches again, x2
    bar2 = {k: m2.latch(fx0, k, want[k]) for k in sorted(GT, key=lambda k: trigs[k][1])}
    for k in stepped:
        nxt = trigs[k][1]
        t.eq(f"T{k + 1}: cheaper until its next trig (frame {nxt})", seg(per, k, G_F1 + 4, nxt - 1), [exp[k]])
        t.eq(f"T{k + 1}: back on {nm(bar2[k])} (the model's bar-2 latch) from its next trig on",
             seg(per, k, nxt, s.frames - 30), [bar2[k]])
    t.eq("end: the model's bar-2 engines, nothing marked", ({k + 1: nm(end["eng"][k]) for k in GT}, end["down"][4:8]),
         ({k + 1: nm(bar2[k]) for k in GT}, [int(bar2[k] < want[k]) for k in GT]))
    t.eq("no toast: the guard's own step-down (mid-note) and its restore say nothing", ncap(d, "end.ncap")[0], 0)
    if name == "guard_mid":
        ef, fdn = S["emus_fmt"], {0: S["emus_fmt_ot_dn"], 1: S["emus_fmt_s95_dn"]}
        for tag, k in (("w8", 7), ("w7", 6), ("w5", 4)):
            c = captured(d, tag)
            down = exp[k] < want[k]
            t.eq(f"{tag}: T{k + 1} (EMUS SP12, playing {nm(exp[k])}): the dial stays on SP12, the readout "
                 f"{'marked' if down else 'plain'}", (c["value"], c["fmt"]), (EM["SP12"], fdn[exp[k]] if down else ef))
        t.eq("the scenario shows an S95! readout", any(exp[k] == 1 for k in stepped), True)
        fd = {fn: (d / fn).read_bytes().split(b"\0")[0].decode() for fn in ("emus_fmt_ot_dn", "emus_fmt_s95_dn")}
        t.eq("the marked readouts (the choice's value passed in)", fd, {"emus_fmt_ot_dn": "OT!", "emus_fmt_s95_dn": "S95!"})
        c = captured(d, "w8end")
        t.eq(f"w8end: T8 back on {nm(bar2[7])}, the plain readout", (c["value"], c["fmt"]), (EM["SP12"], ef))


def toast_check(t, s, d):
    """spec §6a item 2. The expected toast of every action comes from GuardModel.ask on the
    model's own bar-1 latch (checked against the image's carried engines first)."""
    g = s.toast
    fx = [(g["fx1"].get(k, "NONE"), "DARK") for k in GT]
    m = GuardModel()
    for k in GT:                                     # bar 1 in trig order: T5..T8 (steps 1/3/5/7)
        if k in g["emus"]:
            m.latch(fx, k, ENG[g["emus"][k]])
    pre = g_state(d, "pre")
    t.eq("before the actions: the carried engines = the model's latch",
         {k + 1: ENG_NAME[pre["eng"][k]] for k in GT}, {k + 1: ENG_NAME[m.eng.get(k, 0)] for k in GT})
    texts = {S["str_max_s950"]: img_str(S["str_max_s950"]), S["str_max_ot"]: img_str(S["str_max_ot"])}
    t.eq("the toast texts in the image", sorted(texts.values()), ["MAX DSP: OT USED", "MAX DSP: S950 USED"])
    t.eq("their width in the stock toast font: the box (text + 15 px) fits the 128 px screen",
         {v: toast_px(v) + 15 <= 128 for v in texts.values()}, {v: True for v in texts.values()})
    seen = []
    for fr, tag, _, asked in g["actions"]:
        e = None if asked is None else m.ask(fx, 7, ENG[asked])
        exp = toast_name(e) if (e is not None and e < ENG[asked]) else None
        seen.append((asked, exp))
        c, txt, dur = ncap(d, f"{tag}.ncap")
        got = None if c == 0 else (texts.get(txt, f"text @{txt:#x}") if c == 1 else f"{c} toasts")
        t.eq(f"{tag} (frame {fr}, asks {asked}): the toast", got, exp)
        if exp:
            cd, h = struct.unpack(">2I", (d / f"{tag}.toast").read_bytes())
            t.eq(f"{tag}: NOTIFY(text, 0x30), the stock toast open (handle, countdown)", (dur, h != 0, cd), (0x30, True, 0x30))
        p2b = (d / f"{tag}.p2").read_bytes()
        tsm = struct.unpack(">I", (d / f"{tag}.tsmode").read_bytes())[0]
        if s.name.startswith("toast_emus"):
            t.eq(f"{tag}: the stored EMUS", EM_NAME.get(p2b[5], p2b[5]), asked or "OT")
        elif s.name == "toast_tstr":
            t.eq(f"{tag}: T8's TSTR", p2b[4], 3 if asked is None else 4)
        elif s.name == "toast_attr":
            t.eq(f"{tag}: the sample's TIMESTRETCH", tsm, 4)
    kinds = {x for _, x in seen if x}
    quiet = [a for a, x in seen if a not in (None, "OT") and x is None]
    want_kind = {"toast_emus": "MAX DSP: S950 USED", "toast_emus_ot": "MAX DSP: OT USED",
                 "toast_tstr": "MAX DSP: S950 USED", "toast_attr": "MAX DSP: S950 USED"}[s.name]
    t.eq(f"the scenario raises '{want_kind}' (the model)", want_kind in kinds, True)
    if s.name in ("toast_emus", "toast_tstr"):
        t.eq("the scenario has an emu engine that fits: no toast (the model)", bool(quiet), True)


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


def cost(frames=3000):
    """The guard's own ColdFire cost (spec §6 item 5), measured. ot_emu --coverage counts every
    ColdFire PC executed from the transport start; summed per frame over the unit (VEM4G and
    VEM3, each with its own symbols) and over the guard's routines (vg_core .. emus_idx: the
    per-core pass and the latch). The guard's inline part (reading the carried engine, the two
    calls) is in vem_frame: the unit's VEM4G - VEM3 difference includes it."""
    import varispeed_emus_harness as H
    ref_syms = json.loads((IMG_REF.parent / "varispeed_emus_vem3_syms.json").read_text())
    imgs = {"VEM4G": (IMG, json.loads(SYMS.read_text())), "VEM3": (IMG_REF, ref_syms)}
    cases = {
        "otdemo_stock": (OTD, []),                       # no VARI track: the guard never runs
        "otdemo_7sp12": (OTD, H.scenario_steps(dict(tempo=None, pre=True,
                                tracks={t: dict(mode="VARI", emus="SP12") for t in range(7)}), "new")),
        "mm_x2": (MM, [mm_setup({t: "SP12" for t in GT}, {4: "DJEQ", 5: "DJEQ"})]),
        "mm_x3": (MM, [mm_setup({t: "SP12" for t in GT}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"})]),
    }
    d = OUTD / "cost"
    d.mkdir(parents=True, exist_ok=True)
    procs = {}
    for c, (proj, steps) in cases.items():
        for i, (img, _) in imgs.items():
            a = [str(EMU), "--image", str(img), "--card", str(proj["card"]), "--set", proj["set"], "--project",
                 proj["project"], "--load-ms", "20000", "--sequencer", "--internal-clock", "--frames", str(frames),
                 "--dsp", "--main-level", "64", "--coverage", str(d / f"{c}_{i}.cov")]
            for st in steps:
                a += ["--step", st]
            procs[(c, i)] = subprocess.Popen(a, stdout=open(d / f"{c}_{i}.log", "w"), stderr=subprocess.STDOUT)
    for p in procs.values():
        p.wait(timeout=7200)
    rows = {}
    for (c, i), _ in procs.items():
        sy = imgs[i][1]
        cov = [l.split() for l in open(d / f"{c}_{i}.cov")]
        cov = [(int(a, 16), int(n)) for a, n in cov]
        log = (d / f"{c}_{i}.log").read_text()
        n = int(re.search(r"frames run : (\d+)", log).group(1))
        unit = sum(k for a, k in cov if sy["cave"] <= a < sy["end"]) / n
        g = sy["syms"]
        guard = sum(k for a, k in cov if g.get("vg_core", 0) <= a < g.get("emus_idx", 0)) / n if "vg_core" in g else 0.0
        total = sum(k for a, k in cov) / n
        rows[(c, i)] = (unit, guard, total)
    print(f"{'scenario':16} {'image':6} {'unit/frame':>11} {'vg_*/frame':>11} {'all CF/frame':>13}")
    for c in cases:
        for i in imgs:
            u, gg, tt = rows[(c, i)]
            print(f"{c:16} {i:6} {u:11.1f} {gg:11.1f} {tt:13.1f}")
        print(f"{'':16} {'delta':6} {rows[(c, 'VEM4G')][0] - rows[(c, 'VEM3')][0]:11.1f} {'':11} "
              f"{rows[(c, 'VEM4G')][2] - rows[(c, 'VEM3')][2]:13.1f}")
    (d / "cost.json").write_text(json.dumps({f"{c} {i}": v for (c, i), v in rows.items()}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--cost", action="store_true", help="the guard's ColdFire cost per frame (VEM4G vs VEM3)")
    a = ap.parse_args()
    if a.cost:
        return cost()
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

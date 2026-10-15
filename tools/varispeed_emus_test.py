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
  p2edit    EMUS through P2EDIT (direct calls): four detents in one direction per stop, a
            reversal restarts the count, a pushed (x7) report counts one detent, a report of
            8 detents moves two stops, 1/64/127 only, snapping, the count restarts on
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
  net_*     the DSP load guard's safety net (spec §6b, "6b simplified"), on the REAL export
            MMTESTDT (T1-T8 STATIC, part 0), T5-T8 = DSP core 0, all by runtime pokes: settings
            over budget at the start (net_load), a sequencer Part change (net_part, with the
            rp_sync check of the switched Part's PTCH), RELOAD PART (net_reload), a track paste
            (net_paste), a machine change (net_machine), a sample attribute turning a gate on
            (net_gate): just enough EMUS to OT, SP12 first, then S950, highest track first;
            SETUP TSTR (net_tstr, net_tstr_order, net_tstr_fit) and ATTR TIMESTRETCH (net_attr,
            net_attr_order) onto VARI over budget: THE ENTERING track's EMUS to OT (VEM7, spec
            "6b, answers"; among several entering, the net's order), the net's order for what
            is still over; the engine each plays from its next trig; one toast
  ref_*     the two refusals: EMUS through P2EDIT (ref_emus, ref_emus_ot: stops at the highest
            stop that fits), the FX choosers' YES (ref_fx; ref_fx_alone on a test build whose
            core-0 budget is 2600: stock FX alone over is not refused)
  under     under budget nothing is refused or changed, no toast
            EVERY expectation comes from NetModel, an independent model fed with the VG_* block
            read from varispeed_emus.s; each scenario checks that it tells the right rule from
            the wrong ones it names. NOTIFY is captured (and still run) and watched: MAX DSP:
            EMU LIMIT must come from vg_tick, on the UI task's stack.
  panel_*   EMUS through the REAL panel path, transport stopped: SRC SETUP opened with its
            keys, encoder F reports into the panel UART (the parser, its coalescing, the UI
            task, the page's encoder table, P2EDIT), every stored value logged at P2EDIT's
            store (0x4003a5ba). slow / fast / multi / jitter / bounce / held turns, and
            reset (the page closed and re-opened, a track change and back, mid-count). The
            first hardware build (140C_VEM1) fails these (one stop per report, any sign), and
            VEM2-VEM5 (six detents per stop) too.

Test builds (--build-variants): lowbudget (VG_BUDGET_C0 2600, for ref_fx_alone) and the
deliberately wrong builds w_* (out/vem_variants/), each of which must fail its tests
(w_enter_net: a track entering VARI by TSTR / ATTR gets the net's order, as VEM6 did).

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
# the test stubs: in the zero cave tail behind the unit (the classic cave ends 0x400d7c3c)
_TAIL = max(0x400d7800, (json.loads(SYMS.read_text())["end"] + 0x3f) & ~0x3f)
CAP_AT, CAP_BUF, FMT_BUF = _TAIL, _TAIL + 0x60, _TAIL + 0x80
NCAP_AT, NCAP_BUF = _TAIL + 0x90, _TAIL + 0xe0      # the NOTIFY capture (count, text, dur)
assert NCAP_BUF + 12 <= 0x400d7c3c, "no room for the test stubs behind the unit"
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
    s.add(ed(8)); s.dump(20, tsns, 1, "e8")                    # 8 detents in one report: two stops (SP12)
    s.add(ed(-1, -1, -1)); s.dump(20, tsns, 1, "e9")           # three back: no step yet
    s.add(ed(-1)); s.dump(20, tsns, 1, "e10")                  # the fourth: S950
    s.add(ed(1)); s.dump(20, tsns, 1, "e11")                   # turned back: restart, no step
    s.add(ed(-1, 1, -1, 1)); s.dump(20, tsns, 1, "e12")        # jitter: nothing moves
    s.add(held(1), ed(1, 1, 1)); s.dump(20, tsns, 1, "e13")    # pushed: x7 units = one detent each; with
                                                               # the jitter's last +1, the fourth: SP12
    s.add(ed(1)); s.dump(20, tsns, 1, "e14")                   # one more pushed: no step (SP12 is the end)
    s.add(ed(-1, -1, -1)); s.dump(20, tsns, 1, "e15")          # pushed, turned back: three
    s.add(ed(-1)); s.dump(20, tsns, 1, "e16")                  # the fourth: S950
    s.add(held(0))
    s.add(poke(20, p2(0, FL, 5, 30)), ed(-1)); s.dump(20, tsns, 1, "e17")    # 30 snaps to OT (1)
    s.add(poke(20, p2(0, FL, 5, 100)), ed(1)); s.dump(20, tsns, 1, "e18")    # 100 snaps to SP12 (127)
    s.add(ed(-1, -1, -1)); s.dump(20, tsns, 1, "e19")          # three back: no step
    s.add(poke(20, [b(UI_TRACK, 1)]), call(20, P2EDIT, 5, 1))  # T2 (not VARI): stock, and the count's owner changes
    s.dump(20, PBASE + O_P2 + 30 * 1 + 6 * FL + 5, 1, "gateoff")
    s.add(poke(20, [b(UI_TRACK, 0)]), ed(-1)); s.dump(20, tsns, 1, "e20")    # back on T1: counting from 0
    s.add(ed(-1, -1)); s.dump(20, tsns, 1, "e21")              # three
    s.add(call(20, S.get("emus_open", 0x400326d4), *ENC_SETUP_ARGS))          # SRC SETUP opens
    s.add(ed(-1)); s.dump(20, tsns, 1, "e22")                  # counting from 0 again
    s.add(ed(-1, -1, -1)); s.dump(20, tsns, 1, "e23")          # the fourth since the open: S950
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

    # ---- the DSP load guard (spec §6b, "6b simplified"): MMTESTDT, T5-T8 = DSP core 0.
    # Every expectation comes from NetModel (the VG_* block of varispeed_emus.s), and each
    # scenario checks that the model tells the right rule from the wrong ones it names.
    SP4 = {t: "SP12" for t in GT}
    # the safety net at the start: settings over budget when the run begins (as a loaded
    # project would be): S950 on T5, SP12 on T6-T8, DJ EQ x4 -> T8, T7 to OT (SP12 first,
    # highest first), T5 S950 and T6 SP12 kept
    s = net_scn("net_load", {4: "S950", 5: "SP12", 6: "SP12", 7: "SP12"},
                {4: "DJEQ", 5: "DJEQ", 6: "DJEQ", 7: "DJEQ"})
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="load")
    sc[s.name] = s
    # a sequencer Part change: part 0 fits (SP12 x4, DJ EQ x2); pattern 1, poked to use part 1,
    # is cued at frame 100 and plays from bar 2. Part 1 (poked, consistent as a saved Part):
    # T5 NOT VARI (TSTR OFF, PTCH 70 with a QUAN 109 parked, TSNS 30 with EMUS 127 parked),
    # T6-T8 VARI SP12, DJ EQ x4 -> T8, T7 to OT in part 1 before it plays; T5's PTCH stays 70
    # (until VEM5 the poll swapped it: rp_sync)
    s = net_scn("net_part", SP4, {4: "DJEQ", 5: "DJEQ"}, frames=8400,
                extra=part1_setup() + [b(MMDB + 1 * 0x8ed8 + 0x8e57, 1)] + trig_masks(1))
    s.add(call(100, 0x400a1030, 0, 1))                    # cue bank 0 pattern 1 (seq_goto_pattern)
    g_dump(s, 5000, "pre")
    for f in (5200, 8300):
        s.dump(f, mmpart(1), PSTRIDE, f"p1_{f}.part")
        s.dump(f, mmpart(0), PSTRIDE, f"p0_{f}.part")
    s.dump(8300, 0x80000000, 8, "ui.end")
    s.net = dict(kind="part")
    sc[s.name] = s
    # RELOAD PART: part 0 fits (SP12 x4, DJ EQ x2); its saved copy (poked, flagged saved) has
    # S950 on T5 and DJ EQ x4 -> after the reload T8, T7 to OT
    s = net_scn("net_reload", SP4, {4: "DJEQ", 5: "DJEQ"},
                extra=saved_setup({4: "S950", 5: "SP12", 6: "SP12", 7: "SP12"},
                                  {t: "DJEQ" for t in GT}))
    s.add(call(2600, RELOAD, 0))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="reload")
    sc[s.name] = s
    # a track paste: T5-T7 VARI SP12 + DJ EQ (fits, 3240); T8 not VARI (AUTO on a BEAT-less
    # slot). T5's whole track pasted onto T8 -> 4 x SP12 + DJ EQ x4: T8, T7, T6 to OT
    s = net_scn("net_paste", {4: "SP12", 5: "SP12", 6: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={7: 1}, slots={7: 7})
    s.add(call(2600, 0x40029754, 0x460bf218, 0, 4), call(2600, 0x4002b654, 0x460bf218, 0, 7))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="paste")
    sc[s.name] = s
    # a machine change: T5-T7 VARI SP12 + DJ EQ x3; T8 STATIC, not VARI, its FLEX side stored
    # VARI with EMUS SP12 (rp_prev forgotten, as after a load). T8 -> FLEX: T8 (FLEX) to OT
    s = net_scn("net_machine", {4: "SP12", 5: "SP12", 6: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={7: 1}, slots={7: 7}, extra=flex_side(7, "SP12"))
    s.add(poke(2600, mm_byte(O_MACH + 7, FL)), call(2600, SET_MACHINE3, 0, 7, ST))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="machine")
    sc[s.name] = s
    # a sample change turning a gate on (no UI): T8 AUTO on STATIC slot 1 (TIMESTRETCH NORMAL),
    # EMUS SP12 parked; slot 1's TIMESTRETCH poked to VARI at 2600 -> T8 enters, to OT
    s = net_scn("net_gate", {4: "SP12", 5: "SP12", 6: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={7: 1}, park={7: "SP12"})
    s.add(poke(2600, lpoke(STATIC_SET + 0x448 * G_SLOT[7] + 0x110, 4)))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="gate")
    sc[s.name] = s
    # SETUP TSTR onto VARI through P2EDIT: T8 BEAT, EMUS SP12 parked -> T8 enters on OT. Then
    # (net_tstr_order) T6 enters with T8 already on SP12: T6 itself goes to OT, T8 keeps SP12
    # (VEM7; VEM6 stepped T8, the net's order)
    s = net_scn("net_tstr", {4: "SP12", 5: "SP12", 6: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={7: 3}, park={7: "SP12"})
    s.add(poke(2599, [b(UI_TRACK, 7)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)), call(2600, P2EDIT, 4, 1))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="tstr", enter=7)
    sc[s.name] = s
    s = net_scn("net_tstr_order", {4: "SP12", 6: "SP12", 7: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={5: 3}, park={5: "SP12"})
    s.add(poke(2599, [b(UI_TRACK, 5)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)), call(2600, P2EDIT, 4, 1))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="tstr", enter=5)
    sc[s.name] = s
    # SETUP TSTR onto VARI that fits: T8 BEAT, S950 parked -> enters on S950, nothing changes
    s = net_scn("net_tstr_fit", {4: "SP12", 5: "SP12", 6: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={7: 3}, park={7: "S950"})
    s.add(poke(2599, [b(UI_TRACK, 7)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)), call(2600, P2EDIT, 4, 1))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="tstr", enter=7)
    sc[s.name] = s
    # ATTR TIMESTRETCH BEAT -> VARI (the value-up key handler) on STATIC slot 1 with T7, T8 on
    # AUTO there, both SP12 parked; T5, T6 VARI SP12 -> both enter, T8 to OT, T7 keeps SP12
    s = net_scn("net_attr", {4: "SP12", 5: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={6: 1, 7: 1}, park={6: "SP12", 7: "SP12"}, slots={6: 1, 7: 1},
                extra=lpoke(STATIC_SET + 0x448 * 1 + 0x110, 3))
    s.add(poke(2600, lpoke(ATTR_SLOT, 1) + lpoke(ATTR_MACH, 0) + lpoke(ATTR_ROW, 2) + lpoke(ATTR_MODE, 0)),
          call(2600, ATTR_UP))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.dump(2800, STATIC_SET + 0x448 * 1 + 0x110, 4, "after.tsmode")
    s.net = dict(kind="attr")
    sc[s.name] = s
    # the same edit where the net's order and the entering tracks' own step differ: T5, T8 VARI
    # SP12; T6, T7 on AUTO on STATIC slot 1 (BEAT), both SP12 parked -> both enter, one step
    # is needed: T7 (the highest ENTERING track) to OT; the net's order would take T8
    s = net_scn("net_attr_order", {4: "SP12", 7: "SP12"}, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ"},
                tstr={5: 1, 6: 1}, park={5: "SP12", 6: "SP12"}, slots={5: 1, 6: 1},
                extra=lpoke(STATIC_SET + 0x448 * 1 + 0x110, 3))
    s.add(poke(2600, lpoke(ATTR_SLOT, 1) + lpoke(ATTR_MACH, 0) + lpoke(ATTR_ROW, 2) + lpoke(ATTR_MODE, 0)),
          call(2600, ATTR_UP))
    s.dump(2800, mmpart(0), PSTRIDE, "after.part")
    s.dump(2800, STATIC_SET + 0x448 * 1 + 0x110, 4, "after.tsmode")
    s.net = dict(kind="attr")
    sc[s.name] = s
    # the EMUS refusal (P2EDIT): T5-T7 SP12 + DJ EQ x3, T8 VARI on OT. +4 S950 (fits), +4 SP12
    # (refused: stays S950), -4 OT, +8 (two stops asked: S950); with SPATIALIZER on T8's FX1
    # S950 does not fit either
    for nm, fx8 in (("ref_emus", "NONE"), ("ref_emus_ot", "SPATIALIZER")):
        acts = [("a1", 5, 4), ("a2", 5, 4), ("a3", 5, -4), ("a4", 5, 8)]
        s = net_scn(nm, {4: "SP12", 5: "SP12", 6: "SP12", 7: "OT"},
                    {4: "DJEQ", 5: "DJEQ", 6: "DJEQ", 7: fx8})
        s.add(poke(2599, [b(UI_TRACK, 7)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)))
        for i, (tag, slot, d) in enumerate(acts):
            fr = 2600 + 100 * i
            s.add(poke(fr, ncap_reset()), call(fr, P2EDIT, slot, d))
            s.dump(fr + 90, NCAP_BUF, 12, f"{tag}.ncap")        # after the UI loop's next passes
            s.dump(fr + 90, mmpart(0) + O_P2 + 30 * 7, 30, f"{tag}.p2")
        s.net = dict(kind="emus", acts=acts)
        sc[s.name] = s
    # the FX refusal (the choosers' YES): T5-T8 SP12, FX1 DJ EQ on T5-T7, FX2 DARK on T5-T7,
    # T8's FX1 / FX2 NONE (3191). FX2 DARK on T8 (refused), FX2 SPATIALIZER (lands), FX1
    # COMPRESSOR (refused), FX1 SPATIALIZER (lands)
    fxa = [("f1", 2, "DARK"), ("f2", 2, "SPATIALIZER"), ("f3", 1, "COMPRESSOR"), ("f4", 1, "SPATIALIZER")]
    s = net_scn("ref_fx", SP4, {4: "DJEQ", 5: "DJEQ", 6: "DJEQ", 7: "NONE"}, fx2={7: "NONE"})
    fx_actions(s, 7, fxa)
    sc[s.name] = s
    # the same rules where stock FX alone are over the budget (a test build whose core-0
    # budget is 2600, VEM_IMG_LOW): T8 VARI S950, FX1 DJ EQ on T5, T6, FX2 DARK x4 (2338).
    # T7 FX1 DJ EQ: refused (2685; stock alone 2586 fits); T8 FX1 SPATIALIZER: lands; T7 FX1
    # DJ EQ again: stock alone 2663 > 2600, NOT refused -- and the net then steps T8 to OT,
    # and nothing more (2663 is still over)
    low_syms = IMG_LOW.parent / "varispeed_emus_lowbudget_syms.json"
    same = lambda a, b: {k: v for k, v in a.items() if not k.startswith("VG_")} == \
        {k: v for k, v in b.items() if not k.startswith("VG_")}
    if IMG_LOW.exists() and same(json.loads(low_syms.read_text())["syms"], S):   # the same unit, one .equ apart
        s = net_scn("ref_fx_alone", {7: "S950"}, {4: "DJEQ", 5: "DJEQ"}, img=IMG_LOW,
                    tstr={4: 0, 5: 0, 6: 0})
        fx_actions(s, None, [("f1", 1, "DJEQ", 6), ("f2", 1, "SPATIALIZER", 7), ("f3", 1, "DJEQ", 6)])
        s.budget0 = LOW_BUDGET
        sc[s.name] = s
    # under budget, nothing refused or changed: SP12 x4 + DJ EQ x2 (3111): EMUS T8 SP12 -> S950
    # -> SP12, FX1 SPATIALIZER on T8 (3188), the heavy Part apply of the same Part, RELOAD
    # PART (nothing saved: a no-op); no toast, every EMUS as set
    s = net_scn("under", SP4, {4: "DJEQ", 5: "DJEQ"})
    s.add(poke(2599, [b(UI_TRACK, 7)] + lpoke(PAGE_M, ST) + lpoke(ENC_F_HELD, 0)),
          call(2600, P2EDIT, 5, -4), call(2700, P2EDIT, 5, 4))
    s.add(poke(2800, lpoke(FX_CUR[1], fx_row(1, "SPATIALIZER"))), call(2800, FX_YES[1], 0x31, 1))
    s.add(call(2900, 0x40009094, 0, 0), call(3000, RELOAD, 0))
    s.dump(3100, mmpart(0), PSTRIDE, "after.part")
    s.net = dict(kind="under")
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


# ------------------------------------------------------------------------- the DSP load guard
def vg_constants(src=SRC):
    """The VG_* block of varispeed_emus.s: the one source of every price and budget."""
    return {k: int(v, 0) for k, v in re.findall(r"^\s*\.equ\s+(VG_\w+),\s*(0x[0-9a-fA-F]+|\d+)", src.read_text(), re.M)}


VG = vg_constants()
FXID = {"NONE": 0x00, "FILTER": 0x04, "SPATIALIZER": 0x05, "DELAY": 0x08, "EQ": 0x0c, "DJEQ": 0x0d,
        "PHASER": 0x10, "FLANGER": 0x11, "CHORUS": 0x12, "COMB": 0x13, "PLATE": 0x14, "SPRING": 0x15,
        "DARK": 0x16, "COMPRESSOR": 0x18, "LOFI": 0x1c}
ENG = {"OT": 0, "S950": 1, "SP12": 2}
ENG_NAME = {v: k for k, v in ENG.items()}
# the test build whose core-0 budget is lowered (the "stock FX alone over" branch): built from
# this source by the test itself (VEM_VARIANT=lowbudget), see main()
LOW_BUDGET = 2600
IMG_LOW = ROOT / "out/vem_variants/mainos_varispeed_emus_lowbudget.bin"


def fx_price(name):
    return VG["VG_FX_SPRING_HERE"] if name == "SPRING" else VG[f"VG_FX_{name}"]


def eng_price(e):
    return (0, VG["VG_S950"], VG["VG_SP12"], VG["VG_S950"])[e]


class NetModel:
    """An independent model of spec §6b / "6b simplified" for DSP core 0 (T5-T8), built from
    the VG_* block alone. The estimate is a property of the settings: base + the FX1 / FX2
    prices + the engine of every VARI track's EMUS. fix(): just enough tracks to OT, SP12
    first, then S950, highest track number first (`order` names the wrong rules the tests
    must tell apart). cap(): EMUS stops at the highest stop that fits. fx_refused(): an FX
    type is refused when the estimate with it is over and stock FX alone fit."""
    def __init__(self, budget=None):
        self.base = VG["VG_BASE_C0"] + VG["VG_SC"]
        self.budget = budget or VG["VG_BUDGET_C0"]

    def stock(self, fx):
        return self.base + sum(fx_price(a) + fx_price(b) for a, b in fx.values())

    def est(self, fx, eng):
        return self.stock(fx) + sum(eng_price(e) for e in eng.values())

    def fix(self, fx, eng, order="right"):
        eng, stepped = dict(eng), []
        while self.est(fx, eng) > self.budget:
            c = [t for t, e in eng.items() if e]
            if not c:
                break
            if order == "right":
                v = max(c, key=lambda t: (eng[t], t))          # SP12 first, then the highest track
            elif order == "low_first":
                v = max(c, key=lambda t: (eng[t], -t))
            elif order == "s950_first":
                v = max(c, key=lambda t: (-eng[t], t))
            eng[v] = 0
            stepped.append(v)
        return eng, stepped

    def enter_fix(self, fx, eng, entering):
        """VEM7 (spec "6b, answers"): a TSTR / ATTR edit put `entering` on VARI. While over,
        THEIR EMUS goes to OT first (SP12 first, then S950, highest track first among them);
        whatever is still over, the net's order."""
        eng, stepped = dict(eng), []
        while self.est(fx, eng) > self.budget:
            c = [t for t in entering if eng.get(t)]
            if not c:
                break
            v = max(c, key=lambda t: (eng[t], t))
            eng[v] = 0
            stepped.append(v)
        eng, rest = self.fix(fx, eng)
        return eng, stepped + rest

    def cap(self, fx, eng, t, want):
        room = self.budget - self.est(fx, {k: e for k, e in eng.items() if k != t})
        e = want
        while e > eng.get(t, 0) and eng_price(e) > room:
            e -= 1
        return e

    def fx_refused(self, fx, eng):
        return self.est(fx, eng) > self.budget and self.stock(fx) <= self.budget


MMDB = 0x400e21e0
MMP, MMSH = MMDB + 0x8ed80, 0x100a4ece         # MMTESTDT's part 0 (the playing one) and its SRAM copy
MM_LIVE_SLOT = 0x8000082f                      # the live sample-slot byte, + 72t (the voice loop's own)
GT = (4, 5, 6, 7)                              # T5-T8: DSP core 0
G_STEPS = {4: 1, 5: 3, 6: 5, 7: 7}             # their trigs, poked into the pattern (16 steps, 120 BPM)
G_SLOT = {4: 0, 5: 1, 6: 0, 7: 1}              # the two STATIC slots with a sample (146.6 / 120 BPM)
G_FRAMES = 8200                                # bar 2 from ~5512
STATIC_SET = 0x100d5b30                        # STATIC sample settings records, stride 0x448
ATTR_UP = 0x4006edc8                           # the audio editor's value-up key handler
ATTR_SLOT, ATTR_MACH, ATTR_ROW, ATTR_MODE = 0x46c8d19c, 0x46c8d1a0, 0x460e5e74, 0x460e5e5c
RELOAD, SET_MACHINE3 = 0x4004aab4, 0x400972fc
FX_YES = {1: 0x400526e4, 2: 0x40052474}        # the FX choosers' YES handlers (key handlers)
FX_CUR = {1: 0x460d5c94, 2: 0x460d5ca8}        # their cursor rows
FX_LIST = {1: 0x400d6060, 2: 0x400d6090}       # their rows (-> P, whose long is the type id)


def mmpart(part):
    return MMDB + 0x8ed80 + part * PSTRIDE


def mm_byte(off, v, part=0):
    return [b(mmpart(part) + off, v), b(MMSH + part * PSTRIDE + off, v)]


def lpoke(a, v):
    return [b(a + i, x) for i, x in enumerate((v & 0xffffffff).to_bytes(4, "big"))]


def fx_row(bus, name):
    """the chooser row of an FX type in THIS image (the DSP install edits FX2's rows)"""
    img = IMG.read_bytes()
    L = lambda a: struct.unpack(">I", img[a - 0x40000400:a - 0x40000400 + 4])[0]
    i = 0
    while (p := L(FX_LIST[bus] + 4 * i)):
        if L(p) == FXID[name]:
            return i
        i += 1
    raise KeyError(f"FX{bus} offers no {name}")


def trig_masks(pattern):
    out = []
    for t in GT:
        st = G_STEPS[t] - 1
        out.append(b(MMDB + pattern * 0x8ed8 + t * 0x91a + 7 - st // 8, 1 << (st % 8)))
    return out


def track_cfg(t, part, emus=None, tstr=4, park=None, slot=None, m=ST, live=False):
    """track t's STATIC (m) row: TSTR, EMUS in the TSNS slot (on VARI) or parked, the slot"""
    pk = mm_byte(O_P2 + 30 * t + 6 * m + 4, tstr, part)
    if live:
        pk.append(b(LIVE_P2 + 72 * t + 4, tstr))
    if emus is not None:
        pk += mm_byte(O_P2 + 30 * t + 6 * m + 5, EM[emus], part)
        if live:
            pk.append(b(LIVE_P2 + 72 * t + 5, EM[emus]))
    if park is not None:
        pk += mm_byte(O_P2 + 30 * t + PARK2[m], EM[park], part)
    sl = G_SLOT[t] if slot is None else slot
    pk += mm_byte(O_SLOT5 + 5 * t + m, sl, part)
    if live:
        pk.append(b(MM_LIVE_SLOT + 72 * t, sl))
    return pk


def fx_cfg(fx1, fx2, part=0, live=False):
    out = []
    for t in GT:
        for off, n in ((t, fx1.get(t, "NONE")), (8 + t, fx2.get(t, "DARK"))):
            out += mm_byte(off, FXID[n], part)
            if live:
                out.append(b((0x80000ec4 if off < 8 else 0x80000ecc) + t, FXID[n]))
    return out


def part1_setup():
    """part 1 (not playing), consistent as a saved Part: T5 not VARI (PTCH 70, QUAN 109
    parked; TSNS 30, EMUS 127 parked), T6-T8 VARI SP12, FX1 DJ EQ x4, FX2 DARK x4"""
    pk = mm_byte(O_P1 + 30 * 4 + 0, 70, 1) + mm_byte(O_P1 + 30 * 4 + PARK1[ST], 109, 1)
    pk += track_cfg(4, 1, tstr=0, park="SP12") + mm_byte(O_P2 + 30 * 4 + 5, 30, 1)
    for t in (5, 6, 7):
        pk += track_cfg(t, 1, emus="SP12")
    pk += [x for t in GT for x in mm_byte(O_MACH + t, ST, 1)]
    return pk + fx_cfg({t: "DJEQ" for t in GT}, {}, part=1)


SAVED = MMDB + 0x9504a                          # the saved copy of part 0 (RELOAD's source)


def saved_setup(emus, fx1):
    """part 0's saved copy (poked, and flagged saved): T5-T8 VARI on emus, FX1 fx1, FX2 DARK"""
    pk = [b(MMDB + 0x9b312 + 0, 1)]
    for t in GT:
        for off, v in ((O_P2 + 30 * t + 4, 4), (O_P2 + 30 * t + 5, EM[emus[t]]), (O_SLOT5 + 5 * t, G_SLOT[t]),
                       (O_MACH + t, ST), (t, FXID[fx1.get(t, "NONE")]), (8 + t, FXID["DARK"])):
            pk.append(b(SAVED + off, v))
    return pk


def flex_side(t, emus):
    """track t's FLEX row stored on VARI with EMUS in the slot (FLEX slot 7, 120 BPM)"""
    return (mm_byte(O_P2 + 30 * t + 6 * FL + 4, 4) + mm_byte(O_P2 + 30 * t + 6 * FL + 5, EM[emus]) +
            mm_byte(O_SLOT5 + 5 * t + FL, 7))


def net_scn(name, emus, fx1, fx2=None, tstr=None, park=None, slots=None, extra=(), frames=G_FRAMES, img=None):
    """Before the transport (rp_prev forgotten, so the first polls adopt): T5-T8 on the
    settings given -- a track in `emus` on VARI (or the TSTR in `tstr`) with that EMUS in its
    slot, any other on the TSTR in `tstr` (else OFF); parks; slots; trigs at steps 1/3/5/7;
    FX1 as given, FX2 DARK unless given. NOTIFY captured (and still run) from the start."""
    tstr, park, slots, fx2 = tstr or {}, park or {}, slots or {}, fx2 or {}
    pk = list(extra)
    for t in GT:
        ts = tstr.get(t, 4 if t in emus else 0)
        pk += track_cfg(t, 0, emus=emus.get(t), tstr=ts, park=park.get(t), slot=slots.get(t), live=True)
    pk += trig_masks(0) + fx_cfg(fx1, fx2, live=True)
    s = Scn(name, frames, proj=MM, img=img)
    s.add("-:poke:" + ";".join(pk), "-:poke:" + ";".join(ncap_stub()))
    s.cfg = dict(emus=emus, fx1=fx1, fx2=fx2, tstr=tstr, park=park)
    s.dump(frames - 20, NCAP_BUF, 12, "end.ncap")
    s.dump(frames - 20, mmpart(0), PSTRIDE, "end.part")
    g_dump(s, frames - 20, "end")
    return s


def fx_actions(s, track, acts):
    """the FX choosers' YES on `track` (or each action's own), the cursor on the type named"""
    s.add(poke(2599, ncap_reset()))
    out = []
    for i, a in enumerate(acts):
        tag, bus, name = a[:3]
        t = a[3] if len(a) > 3 else track
        fr = 2600 + 100 * i
        s.add(poke(fr, ncap_reset() + [b(UI_TRACK, t)] + lpoke(FX_CUR[bus], fx_row(bus, name))),
              call(fr, FX_YES[bus], 0x31, 1))
        s.dump(fr + 90, NCAP_BUF, 12, f"{tag}.ncap")
        s.dump(fr + 90, mmpart(0), 16, f"{tag}.fx")
        out.append((tag, bus, name, t))
    s.net = dict(kind="fx", acts=out)


def g_dump(s, frame, tag):
    """voice +0 (sounding), render +36 (the carried engine)"""
    d = OUTD / s.name
    s.add(f"{frame}:dump:0x800049d8,{168 * 8:#x}={d / (tag + '.voice')};0x80004898,{40 * 8:#x}={d / (tag + '.render')}")


# SRC SETUP on the panel's track: [SRC] pressed twice (0x22), as on the unit
OPEN_SETUP = [(1000, "key 0x22 down"), (1100, "key 0x22 up"), (1150, "key 0x22 down"), (1250, "key 0x22 up")]
CLOSE_SETUP = lambda t: [(t, "key 0x22 down"), (t + 100, "key 0x22 up")]
REOPEN_SETUP = lambda t: [(t, "key 0x22 down"), (t + 100, "key 0x22 up"), (t + 150, "key 0x22 down"),
                          (t + 250, "key 0x22 up")]
TRACK_KEY = lambda t, k: [(t, f"key {0x10 + k:#x} down"), (t + 100, f"key {0x10 + k:#x} up")]
ENC = lambda t0, dt, ds: [(t0 + dt * i, f"enc 5 {d}") for i, d in enumerate(ds)]
O, S9, SP = "OT", "S950", "SP12"
PANEL = {
    # single detents, 150 ms apart: seven right, seven left (four detents per stop)
    "slow": (ENC(1500, 150, [1] * 7 + [-1] * 7), [O] * 3 + [S9] * 4 + [S9] * 3 + [O] * 4),
    # a fast spin, a report every 3 ms: twelve right, twelve left -- never more than one stop per four
    "fast": (ENC(1500, 3, [1] * 12) + ENC(1900, 3, [-1] * 12),
             [O] * 3 + [S9] * 4 + [SP] * 5 + [SP] * 3 + [S9] * 4 + [O] * 5),
    # reports carrying several detents (the panel's count, or the parser's coalescing)
    "multi": (ENC(1500, 150, [3, 3, 6, -2, -4, -12]), [O, S9, SP, SP, S9, O]),
    # an encoder at rest bouncing +1 / -1: nothing moves
    "jitter": (ENC(1500, 40, [1, -1] * 6), [O] * 12),
    # a right turn with a back-bounce every third report: each bounce restarts the count
    "bounce": (ENC(1500, 40, [1, 1, -1] * 6), [O] * 18),
    # the encoder pushed while turning (P2EDIT's x7): still four detents per stop
    "held": ([(1400, "key 0x3d down")] + ENC(1500, 150, [1] * 7 + [-1] * 7) + [(3700, "key 0x3d up")],
             [O] * 3 + [S9] * 4 + [S9] * 3 + [O] * 4),
    # three detents, then the page closed and re-opened; then five, a track change and back
    # (each re-opens the page), then four: the count restarts every time
    "reset": (ENC(1500, 150, [1] * 3) + CLOSE_SETUP(2200) + REOPEN_SETUP(2700) + ENC(3300, 150, [1] * 5)
              + TRACK_KEY(4300, 1) + TRACK_KEY(4800, 0) + ENC(5400, 150, [1] * 4),
              [O] * 3 + [O] * 3 + [S9] * 2 + [S9] * 3 + [SP]),
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
        args = base(ss[0].proj, ss[0].img) + ["--dsp", "--main-level", "64", "--scenario-jobs", str(jobs),
                                              "--watch-pc", f"{NOTIFY:#x}"]
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
        want = {"e0": "OT", "e8": "SP12", "e9": "SP12", "e10": "S950", "e11": "S950", "e12": "S950",
                "e13": "SP12", "e14": "SP12", "e15": "SP12", "e16": "S950", "e17": "OT", "e18": "SP12",
                "e19": "SP12", "e20": "SP12", "e21": "SP12", "e22": "SP12", "e23": "S950"}
        got = {k: EM_NAME.get((d / k).read_bytes()[0], (d / k).read_bytes()[0]) for k in want}
        t.eq("EMUS through P2EDIT, FOUR detents per stop: +8 | -1x3 | -1 | +1 | -1 +1 -1 +1 | pushed +1x3 | "
             "pushed +1 | pushed -1x3 | pushed -1 | 30 -1 | 100 +1 | -1x3 | (T2) -1 | -1x2 | (open) -1 | -1x3",
             got, want)
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
    if hasattr(s, "net"):
        net_check(t, s, d, log)
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
                eng={t: (struct.unpack(">I", r[40 * t + 36:40 * t + 40])[0] >> 2) & 3 for t in range(8)})


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


def emus_at(part, t, m=ST):
    """the byte in track t's machine-m TSNS slot (EMUS on VARI) and its park"""
    return part[O_P2 + 30 * t + 6 * m + 5], part[O_P2 + 30 * t + PARK2[m]]


def notify_hits(log):
    """--watch-pc 0x4005a2b8 hits -> [(ret, text, dur, sp)]"""
    out = []
    for l in log.splitlines():
        m = re.match(r"\s+\[\s*\d+\] at 0x4005a2b8 .*\[sp (\S+): (\S+) (\S+) (\S+)", l)
        if m:
            out.append((int(m[2], 16), int(m[3], 16), int(m[4], 16), int(m[1], 16)))
    return out


UI_STACK = (0x460d6de4, 0x460d8de4)              # the UI task's stack (its TCB's, 0x2000 B)


def toast_ctx(t, log):
    """spec §6b item 4: MAX DSP: EMU LIMIT only from the UI task's message loop (vg_tick)"""
    if "str_emu_limit" not in S:                 # an older build (VEM5): no such toast
        return []
    ours = [h for h in notify_hits(log) if h[1] == S["str_emu_limit"]]
    bad = [h for h in ours if not (S["vg_tick"] <= h[0] < S["vg_sig"] and UI_STACK[0] <= h[3] < UI_STACK[1])]
    t.eq("every MAX DSP: EMU LIMIT came from vg_tick, on the UI task's stack", [hex(h[0]) for h in bad], [])
    t.eq("... with 1.2 s (0x48)", sorted({h[2] for h in ours}), [0x48] if ours else [])
    txt = img_str(S["str_emu_limit"])
    t.eq("the text, and its box (text + 15 px in the stock toast font) fits the 128 px screen",
         (txt, toast_px(txt) + 15 <= 128), ("MAX DSP: EMU LIMIT", True))
    return ours


def net_check(t, s, d, log):
    """The safety net and the refusals, every expectation from NetModel."""
    c, n = s.cfg, s.net
    m = NetModel(getattr(s, "budget0", None))
    fx = {k: (c["fx1"].get(k, "NONE"), c["fx2"].get(k, "DARK")) for k in GT}
    eng0 = {k: ENG[e] for k, e in c["emus"].items()}
    ours = toast_ctx(t, log)
    end_count = ncap(d, "end.ncap")[0] if (d / "end.ncap").exists() else None
    kind = n["kind"]
    per = core0_engines(d)
    trigs = {k: [fr for fr, _, tr in per.get(k, []) if tr] for k in GT}
    t.notes.append("trig frames " + " ".join(f"T{k + 1}:{v[:3]}" for k, v in trigs.items()))
    nm = lambda e: ENG_NAME[e]

    def after(eng_after, dump="after.part", partno=0):
        p = (d / dump).read_bytes()
        mach = lambda k: p[O_MACH + k] if p[O_MACH + k] in (ST, FL) else ST
        got = {k + 1: EM_NAME.get(emus_at(p, k, mach(k))[0], emus_at(p, k, mach(k))[0]) for k in eng_after}
        t.eq(f"EMUS after ({dump}, each track's current machine)", got, {k + 1: nm(e) for k, e in eng_after.items()})
        return p

    def played(eng_after, lo):
        for k, e in eng_after.items():
            nxt = [fr for fr in trigs[k] if fr >= lo]
            if not nxt:
                t.fails.append(f"T{k + 1}: no trig after frame {lo}")
                continue
            t.eq(f"T{k + 1} plays {nm(e)} from its trig at frame {nxt[0]}",
                 [nm(x) for x in seg(per, k, nxt[0], s.frames - 30)], [nm(e)])

    def discriminates(eng_in, fxx, wrong=("low_first", "s950_first")):
        right = m.fix(fxx, eng_in)[0]
        t.eq("the model steps something here", right != eng_in, True)
        for w in wrong:
            t.eq(f"the right order differs from '{w}' here", m.fix(fxx, eng_in, w)[0] != right, True)
        return right

    if kind in ("load", "reload", "paste", "machine", "gate", "tstr", "attr", "part"):
        if kind == "load":
            fxx, eng_in = fx, eng0
        elif kind == "reload":
            fxx = {k: ("DJEQ", "DARK") for k in GT}
            eng_in = {4: 1, 5: 2, 6: 2, 7: 2}
        elif kind == "paste":
            fxx = {**fx, 7: fx[4]}
            eng_in = {**eng0, 7: eng0[4]}
        elif kind == "machine":
            fxx, eng_in = fx, {**eng0, 7: ENG["SP12"]}
        elif kind in ("gate", "attr"):
            fxx = fx
            eng_in = {**eng0, **{k: ENG[c["park"][k]] for k in c["park"]}}
        elif kind == "tstr":
            fxx, eng_in = fx, {**eng0, n["enter"]: ENG[c["park"][n["enter"]]]}
        else:                                   # part: part 1
            fxx = {k: ("DJEQ", "DARK") for k in GT}
            eng_in = {5: 2, 6: 2, 7: 2}
        entering = [n["enter"]] if kind == "tstr" else sorted(c["park"]) if kind == "attr" else None
        if s.name == "net_tstr_fit":
            want = m.fix(fxx, eng_in)[0]
            t.eq("the model: it fits, nothing steps", want, eng_in)
        elif kind in ("tstr", "attr"):
            # VEM7: the entering track's own EMUS first; the net's order is the wrong rule
            # wherever it would step another track (the *_order scenarios)
            want = m.enter_fix(fxx, eng_in, entering)[0]
            t.eq("the model steps something here", want != eng_in, True)
            net = m.fix(fxx, eng_in)[0]
            if s.name.endswith("_order"):
                t.eq("the model: the entering track steps, not the net's choice (the right rule "
                     "differs from the net's order here)",
                     ([k for k in entering if want[k] == 0 and eng_in[k]] != [], want != net), (True, True))
            else:
                t.eq("the model: here the entering track is also the net's choice", want, net)
        elif kind == "machine" or kind == "gate":
            want = discriminates(eng_in, fxx, ("low_first",))
        else:
            want = discriminates(eng_in, fxx, ("low_first", "s950_first") if 1 in eng_in.values() else ("low_first",))
        t.notes.append(f"the model: est {m.est(fxx, eng_in)} -> {m.est(fxx, want)} (budget {m.budget}): "
                       + " ".join(f"T{k + 1} {nm(e)}" for k, e in sorted(want.items())))
        stepped = want != eng_in
        if kind == "part":
            p1 = (d / "p1_8300.part").read_bytes()
            got = {k + 1: EM_NAME.get(emus_at(p1, k)[0], emus_at(p1, k)[0]) for k in (5, 6, 7)}
            t.eq("part 1's EMUS after the switch", got, {k + 1: nm(want[k]) for k in (5, 6, 7)})
            t.eq("part 1's T5 (not VARI): PTCH 70 / QUAN 109 parked, TSNS 30 / EMUS 127 parked, untouched",
                 (p1[O_P1 + 30 * 4], p1[O_P1 + 30 * 4 + PARK1[ST]], p1[O_P2 + 30 * 4 + 5], p1[O_P2 + 30 * 4 + PARK2[ST]]),
                 (70, 109, 30, 127))
            p0 = (d / "p0_8300.part").read_bytes()
            t.eq("part 0 untouched (EMUS SP12 x4)", [EM_NAME.get(emus_at(p0, k)[0]) for k in GT], ["SP12"] * 4)
            ui = (d / "ui.end").read_bytes()
            t.eq("part 1 is current at the end", ui[3], 1)
            played({k: want[k] for k in (5, 6, 7)}, 5400)
            played({4: 0}, 5400)
        else:
            p = after(want)
            if kind == "attr":
                t.eq("slot 1's TIMESTRETCH is VARI", struct.unpack(">I", (d / "after.tsmode").read_bytes())[0], 4)
            if kind in ("tstr", "machine", "paste"):
                k = n.get("enter", 7)
                if kind == "machine":
                    t.eq("T8 on FLEX", p[O_MACH + 7], FL)
                    t.eq("T8's FLEX EMUS", EM_NAME.get(emus_at(p, 7, FL)[0]), nm(want[7]))
                else:
                    t.eq(f"T{k + 1} on VARI", p[O_P2 + 30 * k + 4], 4)
            played({k: e for k, e in want.items() if kind != "machine" or k != 7}, 5400)
        t.eq("toasts by the end", end_count, 1 if stepped else 0)
        t.eq("MAX DSP: EMU LIMIT raised", len(ours), 1 if stepped else 0)
    elif kind == "emus":
        eng = dict(eng0)
        stop = eng.get(7, 0)
        nt = 0
        for tag, slot, dl in n["acts"]:
            asked = max(0, min(2, stop + (1 if dl > 0 else -1) * (abs(dl) // 4)))
            got_stop = m.cap(fx, {**eng, 7: stop}, 7, asked) if asked > stop else asked
            refused = got_stop < asked
            p2b = (d / f"{tag}.p2").read_bytes()
            cn = ncap(d, f"{tag}.ncap")[0]
            t.eq(f"{tag} ({dl:+d} detents, asks {nm(asked)}): stored", EM_NAME.get(p2b[5], p2b[5]), nm(got_stop))
            t.eq(f"{tag}: toast", cn, 1 if refused else 0)
            nt += refused
            stop = got_stop
        t.eq("MAX DSP: EMU LIMIT raised, once per refusal", len(ours), nt)
        t.eq("the scenario refuses a dearer stop (the model)", m.cap(fx, eng0, 7, 2) < 2, True)
    elif kind == "fx":
        fxs = dict(fx)
        eng = dict(eng0)
        seen = []
        for tag, bus, name, k in n["acts"]:
            new = dict(fxs)
            new[k] = (name, fxs[k][1]) if bus == 1 else (fxs[k][0], name)
            refused = m.fx_refused(new, eng)
            fxb = (d / f"{tag}.fx").read_bytes()
            have = fxb[k] if bus == 1 else fxb[8 + k]
            t.eq(f"{tag} T{k + 1} FX{bus} -> {name} (est {m.est(new, eng)}, stock alone {m.stock(new)}): "
                 f"{'refused' if refused else 'lands'}", have, FXID[fxs[k][bus - 1]] if refused else FXID[name])
            stepped = False
            if not refused:
                fxs = new
                eng2, st = m.fix(fxs, eng)
                stepped = bool(st)
                eng = eng2
            t.eq(f"{tag}: toast", ncap(d, f"{tag}.ncap")[0], 1 if (refused or stepped) else 0)
            seen.append((refused, stepped))
        t.eq("MAX DSP: EMU LIMIT raised, once per refusal or step-down", len(ours),
             sum(1 for r, st in seen if r or st))
        t.eq("the scenario refuses an FX type and lands another (the model)",
             (any(r for r, _ in seen), any(not r for r, _ in seen)), (True, True))
        if s.name == "ref_fx_alone":
            t.eq("stock FX alone over: not refused, and the net then steps the emu track (the model)",
                 seen[-1], (False, True))
            t.eq("the end: every emu track on OT, nothing more (the model)", {k + 1: nm(e) for k, e in eng.items()},
                 {k + 1: "OT" for k in eng})
            pe = (d / "end.part").read_bytes()
            t.eq("the end: T8's EMUS in the image", EM_NAME.get(emus_at(pe, 7)[0]), "OT")
    elif kind == "under":
        p = (d / "after.part").read_bytes()
        t.eq("under budget: EMUS SP12 x4 kept", [EM_NAME.get(emus_at(p, k)[0]) for k in GT], ["SP12"] * 4)
        t.eq("under budget: T8's FX1 SPATIALIZER landed", p[7], FXID["SPATIALIZER"])
        t.eq("under budget: no toast", (end_count, len(ours)), (0, 0))
        t.eq("under budget: the model fits throughout",
             (m.est(fx, eng0) <= m.budget, m.est({**fx, 7: ("SPATIALIZER", "DARK")}, eng0) <= m.budget), (True, True))
        played({k: 2 for k in GT}, 2)



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
    """The guard's ColdFire cost (spec §6 item 5), measured. ot_emu --coverage counts every
    ColdFire PC executed from the transport start; summed per frame over the unit (this image
    and VEM3, each with its own symbols) and, for this image, over the guard's parts: the UI
    loop's tail (vg_tick) with the signature (vg_sig) -- once per UI message, ~60 Hz -- and
    the estimate / step-down (vg_scan .. vg_step_ot), run only when the signature changed;
    its cost per change event = those instructions / the calls of vg_fix. The frame hook's
    own share is the unit minus both."""
    import varispeed_emus_harness as H
    ref_syms = json.loads((IMG_REF.parent / "varispeed_emus_vem3_syms.json").read_text())
    imgs = {"new": (IMG, json.loads(SYMS.read_text())), "VEM3": (IMG_REF, ref_syms)}
    fit = net_scn("cost_fit", {t: "SP12" for t in GT}, {4: "DJEQ", 5: "DJEQ"})
    over = net_scn("cost_over", {4: "S950", 5: "SP12", 6: "SP12", 7: "SP12"}, {t: "DJEQ" for t in GT})
    cases = {
        "otdemo_stock": (OTD, []),                       # no VARI track
        "otdemo_7sp12": (OTD, H.scenario_steps(dict(tempo=None, pre=True,
                                tracks={t: dict(mode="VARI", emus="SP12") for t in range(7)}), "new")),
        "mm_4sp12_fit": (MM, fit.steps[:1]),             # SP12 x4 + DJ EQ x2: fits, nothing steps
        "mm_over": (MM, over.steps[:1]),                 # over at the start: the net steps T8, T7 once
    }
    d = OUTD / "cost"
    d.mkdir(parents=True, exist_ok=True)
    procs = {}
    for c, (proj, steps) in cases.items():
        for i, (img, _) in imgs.items():
            if os.environ.get("VEM_COST_REUSE") and (d / f"{c}_{i}.cov").exists():
                procs[(c, i)] = None
                continue
            a = [str(EMU), "--image", str(img), "--card", str(proj["card"]), "--set", proj["set"], "--project",
                 proj["project"], "--load-ms", "20000", "--sequencer", "--internal-clock", "--frames", str(frames),
                 "--dsp", "--main-level", "64", "--coverage", str(d / f"{c}_{i}.cov")]
            for st in steps:
                a += ["--step", st]
            procs[(c, i)] = subprocess.Popen(a, stdout=open(d / f"{c}_{i}.log", "w"), stderr=subprocess.STDOUT)
    for p in procs.values():
        if p:
            p.wait(timeout=7200)
    rows = {}
    for (c, i), _ in procs.items():
        sy = imgs[i][1]
        g = sy["syms"]
        cov = [l.split() for l in open(d / f"{c}_{i}.cov")]
        cov = [(int(a, 16), int(n)) for a, n in cov]
        log = (d / f"{c}_{i}.log").read_text()
        n = int(re.search(r"frames run : (\d+)", log).group(1))
        rng = lambda lo, hi: sum(k for a, k in cov if lo <= a < hi)
        unit = rng(sy["cave"], sy["end"])
        if "vg_tick" in g and "vg_sig" in g:
            nxt = min(v for k, v in g.items() if v > g["vg_sig"] and not k.startswith("."))
            tail = rng(g["vg_tick"], nxt)               # vg_tick + vg_sig
            nsync = min(v for k, v in g.items() if v > g["rp_sync"] and not k.startswith("."))
            sync = rng(g["rp_sync"], nsync)
            net = rng(g["vg_scan"], g["vg_fx_try"])
            fixes = dict(cov).get(g["vg_fix"], 0)
            ticks = dict(cov).get(g["vg_tick"], 0)
        else:
            tail = net = fixes = ticks = sync = 0
        rows[(c, i)] = dict(unit=unit / n, tail=tail / n, net=net / n, frame=(unit - tail - net) / n, sync=sync / n,
                            fixes=fixes, ticks=ticks, net_total=net, total=sum(k for a, k in cov) / n,
                            tail_per_tick=tail / ticks if ticks else 0)
    print(f"{'scenario':14} {'image':5} {'unit/fr':>8} {'frame/fr':>9} {'sync/fr':>8} {'tail/fr':>8} {'net/fr':>7} "
          f"{'ticks':>6} {'tail/tick':>9} {'fixes':>6} {'net/fix':>8} {'allCF/fr':>9}")
    for c in cases:
        for i in imgs:
            r = rows[(c, i)]
            print(f"{c:14} {i:5} {r['unit']:8.1f} {r['frame']:9.1f} {r['sync']:8.1f} {r['tail']:8.1f} {r['net']:7.1f} "
                  f"{r['ticks']:6d} {r['tail_per_tick']:9.1f} {r['fixes']:6d} "
                  f"{(r['net_total'] / r['fixes'] if r['fixes'] else 0):8.1f} {r['total']:9.1f}")
        print(f"{'':14} {'delta':5} {rows[(c, 'new')]['unit'] - rows[(c, 'VEM3')]['unit']:8.1f} "
              f"{rows[(c, 'new')]['frame'] - rows[(c, 'VEM3')]['frame']:9.1f}")
    (d / "cost.json").write_text(json.dumps({f"{c} {i}": v for (c, i), v in rows.items()}, indent=1))


# deliberately wrong builds (and the low-budget test build): edits of varispeed_emus.s
VARIANTS = {
    "lowbudget": [(".equ    VG_BUDGET_C0, 3350", ".equ    VG_BUDGET_C0, 2600")],
    "w_low_first": [("2:      move.l  %d4,%d1\n        add.l   %d2,%d1",
                     "2:      moveq   #3,%d1\n        sub.l   %d2,%d1\n        add.l   %d4,%d1")],
    "w_s950_first": [("        moveq   #2,%d3                  | SP12 first, then S950",
                      "        moveq   #1,%d3"),
                     ("        subq.l  #1,%d3\n        bne.s   1b\n        bra.s   .vx_next",
                      "        addq.l  #1,%d3\n        moveq   #3,%d0\n        cmp.l   %d0,%d3\n"
                      "        bne.s   1b\n        bra.s   .vx_next")],
    "w_no_cap": [("        bsr     vg_cap                  | dearer: the highest stop up to it that fits\n",
                  "        nop\n")],
    "w_no_fxref": [("        bsr     vg_fx_try\n", "        moveq   #0,%d0\n")],
    "w_no_sync": [("rp_sync:\n        lea     -12(%sp),%sp", "rp_sync:\n        rts\n        lea     -12(%sp),%sp")],
    "w_6det": [(".equ    EM_DETENTS, 4", ".equ    EM_DETENTS, 6")],
    "w_toast_direct": [("        move.b  %d4,(vg_toast).l        | refused (as far as it went): MAX DSP: EMU LIMIT",
                        "        move.l  %d0,-(%sp)\n        pea     (TOAST_DUR).w\n        pea     str_emu_limit(%pc)\n"
                        "        jsr     (NOTIFY).l\n        addq.l  #8,%sp\n        move.l  (%sp)+,%d0\n"
                        "        lea     vg_engp(%pc),%a0")],
    "w_enter_net": [("        bsr     vg_entered              | the tracks it put on VARI\n        tst.l   %d0\n"
                     "        beq.s   1f\n        bsr     vg_fix                  | over budget: THEIR EMUS to OT first",
                     "        moveq   #0,%d0\n        tst.l   %d0\n        beq.s   1f\n        nop")],
    "w_no_net": [("        moveq   #-1,%d0\n        bsr     vg_fix\n        tst.l   %d0\n        beq.s   2f",
                  "        moveq   #0,%d0\n        tst.l   %d0\n        beq.s   2f")],
}


def build_variants(tags):
    out = ROOT / "out/vem_variants"
    (out / "src").mkdir(parents=True, exist_ok=True)
    for tag in tags:
        txt = SRC.read_text()
        for old, new in VARIANTS[tag]:
            if txt.count(old) < 1:
                sys.exit(f"variant {tag}: the source has no {old[:50]!r}")
            txt = txt.replace(old, new)
        src = out / "src" / f"{tag}.s"
        src.write_text(txt)
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_varispeed_emus.py")], cwd=ROOT,
                           env=dict(os.environ, KYOTI_ALLOW_WIP="1", VEM_VARIANT=tag, VEM_VARIANT_SRC=str(src)),
                           capture_output=True, text=True)
        print(f"variant {tag}: {'built' if r.returncode == 0 else 'FAILED'}")
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--cost", action="store_true", help="the guard's ColdFire cost per frame (this image vs VEM3)")
    ap.add_argument("--build-variants", default="", help="build test images: all, or tags (comma-separated)")
    a = ap.parse_args()
    if a.build_variants:
        return build_variants(list(VARIANTS) if a.build_variants == "all" else a.build_variants.split(","))
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

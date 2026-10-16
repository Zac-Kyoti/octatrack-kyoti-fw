#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
VARISPEED (the plain build, spec §7) -- its tests, run in ot_emu on the built image
(out/mainos_varispeed.bin, or VEM_IMG) with the REAL hardware-exported project OTDEMO
(T1-T7 FLEX, part 1). Everything is set by RUNTIME pokes and direct calls; no project file
is edited. The machinery (scenarios, checkpoints, the KNOB capture) is
tools/varispeed_emus_test.py's; the expectations are VARISPEED's: PTCH <-> QUAN only, TSNS
stays TSNS (no second park pair), nothing emulated, SPRING REVERB stock.

  python3 tools/varispeed_test.py [--only NAME] [--jobs N]

Tests:
  static    no emulator: the DSP payloads, the FX choosers (SPRING REVERB offered on FX2)
            and every EMUS / guard site byte-identical to stock; the TSNS widgets stock (0);
            every byte that differs from stock is the unit's, a detour's or a poke's; the
            unit carries none of VARISPEED_EMUS's symbols
  swap      PTCH <-> QUAN swap with a fresh park (QUAN 1/1), round trip; TSNS, its live
            byte and the NEIGHBOR byte VARISPEED_EMUS parks TSNS in never move; captions
            QUAN / stock TSNS
  adopt     a forgotten rp_prev adopts a Part already in VARI (no swap)
  p2edit    TSNS through P2EDIT on a VARI track = stock's step; TSTR 0..4 through P2EDIT
            and the swap it starts (QUAN fresh, TSNS untouched)
  widget    quant_widget's arguments (snapped value, formatter), the captions;
            tstr_fmt, quant_fmt strings
  item11    FL -> PICKUP -> FL, FL -> THRU -> FL, FL -> STATIC -> FL (each its own VARI
            state): no swap on a machine change, no poll on PICKUP
  o2        SRC page paste + undo, track paste, PART paste / clear / undo, RELOAD PART:
            the target adopts what was written, nothing swaps
  o2late    after the paste the target plays: still unswapped
  o2rev     a non-VARI page pasted over a VARI track: the pasted PTCH stays
  old56     TSTR 5/6 and TSMODE 5/6 do not crash, stay as they are
  spring    FX2 SPRING REVERB chosen on T1 (the chooser's YES): it lands, Part and live id

The increments (VARI tracks against VARISPEED_EMUS on OT, stock tracks against stock 1.40C,
every bit) are tools/varispeed_emus_harness.py --plain.

Deliberately wrong builds (--build-variants, out/vari_variants/; run them through the harness
with VEM_IMG_NEW=<image> --plain): w_mask (stock tracks' increments masked as in
VARISPEED_EMUS: the stock group must differ) and w_lowbits (a VARI increment's bits 0-3 not
cleared: the VARI group must differ).
"""
import argparse, json, os, pathlib, struct, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("VEM_IMG", str(ROOT / "out/mainos_varispeed.bin"))
os.environ.setdefault("VEM_SYMS", str(ROOT / "out/varispeed_syms.json"))
os.environ.setdefault("VEM_TEST_OUT", str(ROOT / "out/vari/tests"))
sys.path.insert(0, str(ROOT / "tools"))
import varispeed_emus_test as E                                       # noqa: E402

S, IMG, OUTD = E.S, E.IMG, E.OUTD
Scn, CP, T = E.Scn, E.CP, E.T
b, p1, p2, park, poke, call, machine, lpoke = E.b, E.p1, E.p2, E.park, E.poke, E.call, E.machine, E.lpoke
FL, ST, PU, THRU = E.FL, E.ST, E.PU, E.THRU
UI_TRACK, PAGE_M, P2EDIT, PBASE = E.UI_TRACK, E.PAGE_M, E.P2EDIT, E.PBASE
O_P2, NAME0, NAME11 = E.O_P2, E.NAME0, E.NAME11
PTCH_FMT = 0x4003b4b0
STOCK = (ROOT / "out/raw/section_3_MAIN_OS.bin").read_bytes()
BASE = 0x40000400
SENT = 99                       # a sentinel in the NEIGHBOR byte VARISPEED_EMUS parks TSNS in
EMUS_SITES = {0x4003a566: 6, 0x400585f4: 6, 0x40062d1c: 6, 0x400526e4: 8, 0x40052474: 8}


def stock_name(a):
    return STOCK[a - BASE:a - BASE + 4].decode("latin1")


# ------------------------------------------------------------------------- scenarios
def scenarios():
    sc = {}
    install, restore = E.cap_stub()

    s = Scn("swap", 90)
    s.add(poke(1, [b(UI_TRACK, 0)]),
          poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, SENT)))
    s.cp(10, "a")
    s.add(poke(12, p2(0, FL, 4, 4)))
    for f in (12, 13, 14):
        s.cp(f, f"edge{f}")
    s.cp(30, "b")
    s.add(poke(32, p1(0, FL, 0, 109) + p2(0, FL, 5, 127)))     # QUAN 3/2; a TSNS edit
    s.add(poke(40, p2(0, FL, 4, 3)))
    s.cp(60, "c")
    s.add(poke(62, p2(0, FL, 4, 4)))
    s.cp(80, "d")
    sc[s.name] = s

    s = Scn("adopt", 40)
    s.add(poke(2, p2(0, FL, 4, 4) + p1(0, FL, 0, 109) + p2(0, FL, 5, 30) + park(0, 1, FL, 70) +
               park(0, 2, FL, SENT) + [b(S["rp_prev"] + i, 0xff) for i in range(16)]))
    s.cp(30, "a")
    sc[s.name] = s

    s = Scn("p2edit", 60)
    tsns = PBASE + O_P2 + 30 * 0 + 6 * FL + 5
    s.add(poke(2, p2(0, FL, 4, 4) + p2(0, FL, 5, 64) + p2(2, FL, 4, 3) + p1(2, FL, 0, 70) +
               park(2, 1, FL, 0) + park(2, 2, FL, SENT)))
    s.cp(15, "before")
    s.add(poke(20, [b(UI_TRACK, 0)] + lpoke(PAGE_M, FL)))
    s.add(call(20, P2EDIT, 5, 1)); s.dump(20, tsns, 1, "t1")
    s.add(call(20, P2EDIT, 5, -1), call(20, P2EDIT, 5, -1)); s.dump(20, tsns, 1, "t2")
    s.add(call(20, P2EDIT, 5, 8)); s.dump(20, tsns, 1, "t3")
    s.add(poke(20, [b(UI_TRACK, 2)]), call(20, P2EDIT, 4, 1))
    s.dump(20, PBASE + O_P2 + 30 * 2 + 6 * FL + 4, 1, "tstr1")
    s.add(call(20, P2EDIT, 4, 1))
    s.dump(20, PBASE + O_P2 + 30 * 2 + 6 * FL + 4, 1, "tstr2")
    s.cp(40, "after")
    sc[s.name] = s

    s = Scn("widget", 40)
    s.add(poke(2, p2(0, FL, 4, 4)), poke(20, [b(UI_TRACK, 0)]))
    s.add(poke(20, install))
    for tag, val in (("qw50", 50), ("qw124", 124), ("qwneg", -1)):
        s.add(call(20, S["quant_widget"], 10, 20, 0, val, 0, PTCH_FMT, 0x12345678))
        s.dump(20, E.CAP_BUF, 32, tag)
    s.cp(20, "on")
    s.add(poke(20, [b(UI_TRACK, 1)]), call(20, S["quant_widget"], 10, 20, 0, 77, 0, PTCH_FMT, 0x12345678))
    s.dump(20, E.CAP_BUF, 32, "qwoff")
    s.cp(20, "off")
    s.add(poke(20, restore))
    for v in range(7):
        s.add(poke(21, [b(E.FMT_BUF + i, 0) for i in range(8)]), call(21, S["tstr_fmt"], E.FMT_BUF, v))
        s.dump(21, E.FMT_BUF, 8, f"tf{v}")
    for v in (4, 64, 124):
        s.add(poke(21, [b(E.FMT_BUF + i, 0) for i in range(8)]), call(21, S["quant_fmt"], E.FMT_BUF, v))
        s.dump(21, E.FMT_BUF, 8, f"qf{v}")
    sc[s.name] = s

    s = Scn("item11", 420)
    s.add(poke(1, [b(UI_TRACK, 0)]),
          poke(2, p1(0, FL, 0, 70) + p2(0, FL, 5, 30) + park(0, 1, FL, 0) + park(0, 2, FL, SENT) +
               park(0, 1, ST, 0) + park(0, 2, ST, SENT - 1) + p1(0, ST, 0, 80, False) + p2(0, ST, 5, 40, False)),
          poke(4, p2(0, FL, 4, 4)), poke(20, p1(0, FL, 0, 109)))
    s.cp(30, "x0")
    s.add(machine(32, 0, PU))
    s.add(poke(40, install), call(40, S["quant_widget"], 10, 20, 0, 77, 0, PTCH_FMT, 0x12345678))
    s.dump(40, E.CAP_BUF, 32, "pu_qw")
    s.add(poke(40, restore))
    s.cp(80, "x1")
    s.add(machine(82, 0, FL)); s.cp(120, "x2")
    s.add(machine(122, 0, THRU)); s.cp(160, "x3")
    s.add(machine(162, 0, FL)); s.cp(200, "x4")
    s.add(machine(202, 0, ST)); s.cp(240, "x5")
    s.add(poke(242, p2(0, ST, 4, 4))); s.cp(280, "x6")
    s.add(machine(282, 0, FL)); s.cp(320, "x7")
    s.add(machine(322, 0, ST)); s.cp(360, "x8")
    s.add(machine(362, 0, FL)); s.cp(400, "x9")
    sc[s.name] = s

    # o2 / o2late / o2rev / old56: VARISPEED_EMUS's scenarios (the same pokes and calls; the
    # TSNS bytes poked there are plain TSNS here)
    sc.update(_emus_scenarios(("o2", "o2late", "o2rev", "old56")))

    s = Scn("spring", 200)
    s.add(poke(100, [b(UI_TRACK, 0)] + lpoke(E.FX_CUR[2], E.fx_row(2, "SPRING"))), call(100, E.FX_YES[2], 0x31, 1))
    s.dump(150, PBASE, 16, "fx")
    s.dump(150, 0x80000ec4, 16, "live")
    s.dump(90, PBASE, 16, "fx0")
    sc[s.name] = s
    return sc


def _emus_scenarios(names):
    """VARISPEED_EMUS's scenarios that call no EMUS symbol, built by its own code (the
    others need placeholders to build, and are not taken)."""
    keep = E.S
    try:
        E.S = dict(keep, emus_widget=0, emus_fmt=0, vg_gon=0)
        all_ = E.scenarios()
    finally:
        E.S = keep
    return {n: all_[n] for n in names}


# ------------------------------------------------------------------------- checks
def static_checks():
    t = T("static")
    img = IMG.read_bytes()
    import build_sidechain_compressor as sc3          # (its own FINAL banner prints)
    for tag, d in sc3.DSP.items():
        lo = d["va"] - BASE
        t.eq(f"DSP payload {tag} (0x{d['va']:08x} + 0x{d['ln']:x}) byte-identical to stock",
             img[lo:lo + d["ln"]] == STOCK[lo:lo + d["ln"]], True)
    for bus in sc3.FX_BUSES:
        for k, n in (("lst", 0x80), ("id2pos", 0x80), ("id2e", 0x80)):
            lo = bus[k] - BASE
            t.eq(f"{bus['tag']} chooser table {k} stock", img[lo:lo + n] == STOCK[lo:lo + n], True)
    try:
        row = E.fx_row(2, "SPRING")
    except KeyError:
        row = None
    t.eq("FX2 offers SPRING REVERB (a chooser row)", row is not None, True)
    for a, n in EMUS_SITES.items():
        t.eq(f"0x{a:08x} (a VARISPEED_EMUS-only site) stock", img[a - BASE:a - BASE + n] == STOCK[a - BASE:a - BASE + n], True)
    for a in (0x400d3142, 0x400d32d4):
        t.eq(f"TSNS widget 0x{a:08x} stock (0)", img[a - BASE:a - BASE + 4], b"\0\0\0\0")
    j = json.loads(pathlib.Path(os.environ["VEM_SYMS"]).read_text())
    owned = set(range(j["cave"] - BASE, j["end"] - BASE))
    for k, (sym, kind, n) in j["detours"].items():
        owned |= set(range(int(k, 16) - BASE, int(k, 16) - BASE + n))
    for k in j["pokes"]:
        owned |= set(range(int(k, 16) - BASE, int(k, 16) - BASE + 4))
    stray = [i for i in range(len(STOCK)) if STOCK[i] != img[i] and i not in owned]
    t.eq("every changed byte is the unit's, a detour's or a poke's", stray[:4], [])
    t.eq("17 detours, 10 pokes", (len(j["detours"]), len(j["pokes"])), (17, 10))
    emus = [k for k in S if k.startswith(("emus_", "vg_", "em_", "vh_fx")) or k == "str_emu_limit"]
    t.eq("no VARISPEED_EMUS symbol in the unit", emus, [])
    return t


def check(name, s):
    d = OUTD / name
    t = T(name)
    log = (d / "log.txt").read_text() if (d / "log.txt").exists() else ""
    t.eq("run reached its frame count", "run ended REACHED" in log, True)
    t.eq("no call failed to return", "DID NOT RETURN" in log, False)
    try:
        cp = {c: CP(d, c) for c in s.cps}
    except FileNotFoundError as e:
        t.fails.append(f"missing dump {e.filename}")
        return t
    TSNS_FL = stock_name(NAME11[FL])
    if name == "swap":
        a, bb, c, dd = cp["a"], cp["b"], cp["c"], cp["d"]
        q = lambda x: (x.p1(0, FL), x.p2(0, FL), x.park(0, 1, FL), x.park(0, 2, FL))
        t.eq("before: PTCH / TSNS / PTCH park / the NEIGHBOR byte", q(a), (70, 30, 0, SENT))
        t.eq("before: rp_prev[T1][FL]", a.rp(0, FL), 0)
        t.eq("VARI: QUAN 64 (fresh: 1/1) / TSNS kept / PTCH parked / NEIGHBOR byte untouched", q(bb), (64, 30, 70, SENT))
        t.eq("VARI: rp_prev[T1][FL]", bb.rp(0, FL), 1)
        t.eq("VARI: live PTCH / base word / live TSNS", (bb.live[0], bb.base[0:2], bb.live[0x25]), (64, b"\x40\x00", 30))
        t.eq("VARI: SRAM copy follows", bb.shadow_ok(), True)
        t.eq("VARI: captions (FLEX): QUAN, and stock's TSNS caption", (bb.name(NAME0[FL]), bb.name(NAME11[FL])),
             ("QUAN", TSNS_FL))
        for f in (12, 13, 14):
            e = cp[f"edge{f}"]
            t.eq(f"frame {f}: PTCH or QUAN in the slot, TSNS 30", (e.p1(0, FL) in (70, 64), e.p2(0, FL)), (True, 30))
        t.eq("left (BEAT): PTCH back, QUAN parked, TSNS as edited (127), NEIGHBOR byte untouched", q(c), (70, 127, 109, SENT))
        t.eq("left: rp_prev, captions", (c.rp(0, FL), c.name(NAME0[FL]), c.name(NAME11[FL])), (0, "PTCH", TSNS_FL))
        t.eq("left: live PTCH / base / live TSNS", (c.live[0], c.base[0:2], c.live[0x25]), (70, b"\x46\x00", 127))
        t.eq("back in VARI: QUAN / TSNS / PTCH park / NEIGHBOR byte", q(dd), (109, 127, 70, SENT))
        t.eq("back in VARI: SRAM copy follows", dd.shadow_ok(), True)
    elif name == "adopt":
        a = cp["a"]
        t.eq("adopted: slots and parks unchanged", (a.p1(0, FL), a.p2(0, FL), a.park(0, 1, FL), a.park(0, 2, FL)),
             (109, 30, 70, SENT))
        t.eq("adopted: rp_prev[T1] FL / ST", (a.rp(0, FL), a.rp(0, ST)), (1, 0))
    elif name == "p2edit":
        rd = lambda k: (d / k).read_bytes()[0]
        t.eq("TSNS through P2EDIT on a VARI track: stock's steps (64 +1, -1 -1, +8)",
             (rd("t1"), rd("t2"), rd("t3")), (65, 63, 71))
        t.eq("TSTR through P2EDIT: BEAT +1 -> VARI, +1 stays (five positions)", (rd("tstr1"), rd("tstr2")), (4, 4))
        a, bf = cp["after"], cp["before"]
        t.eq("T3 entered VARI from the editor: QUAN 64, PTCH 70 parked, TSNS and the NEIGHBOR byte "
             "untouched, rp_prev 1", (a.p1(2, FL), a.park(2, 1, FL), a.p2(2, FL), a.park(2, 2, FL), a.rp(2, FL)),
             (64, 70, bf.p2(2, FL), SENT, 1))
    elif name == "widget":
        qf = S["quant_fmt"]
        for tag, val, fmt in (("qw50", 49, qf), ("qw124", 124, qf), ("qwneg", -1, qf)):
            c = E.captured(d, tag)
            t.eq(f"{tag}: KNOB(x, y, value, fmt, canvas)", (c["x"], c["y"], c["value"], c["fmt"], c["canvas"]),
                 (10, 20, val, fmt, 0x12345678))
        on, off = cp["on"], cp["off"]
        t.eq("VARI track: captions", (on.name(NAME0[FL]), on.name(NAME11[FL])), ("QUAN", TSNS_FL))
        c = E.captured(d, "qwoff")
        t.eq("off VARI: PTCH widget passes the stock dial through", (c["value"], c["fmt"]), (77, PTCH_FMT))
        t.eq("off VARI: captions", (off.name(NAME0[FL]), off.name(NAME11[FL])), ("PTCH", TSNS_FL))
        tf = [(d / f"tf{v}").read_bytes().split(b"\0")[0].decode() for v in range(7)]
        t.eq("tstr_fmt 0..6", tf, ["OFF", "AUTO", "NORM", "BEAT", "VARI", "???", "???"])
        qf_ = [(d / f"qf{v}").read_bytes().split(b"\0")[0].decode() for v in (4, 64, 124)]
        t.eq("quant_fmt 4 / 64 / 124", qf_, ["1/2", "1/1", "2/1"])
    elif name == "item11":
        x = cp
        fl = lambda c: (c.p1(0, FL), c.p2(0, FL), c.park(0, 1, FL), c.park(0, 2, FL), c.rp(0, FL))
        stv = lambda c: (c.p1(0, ST), c.p2(0, ST), c.park(0, 1, ST), c.park(0, 2, ST))
        pu = lambda c: bytes(c.part[E.O_P1 + 6 * PU:E.O_P1 + 6 * PU + 6]) + bytes(c.part[O_P2 + 6 * PU:O_P2 + 6 * PU + 6])
        t.eq("x0 FLEX in VARI", fl(x["x0"]), (109, 30, 70, SENT, 1))
        for k, what in (("x1", "on PICKUP"), ("x2", "back on FLEX"), ("x3", "on THRU"), ("x4", "back on FLEX"),
                        ("x5", "on STATIC"), ("x7", "FLEX after STATIC VARI"), ("x9", "FLEX again")):
            t.eq(f"{k} {what}: FLEX slots, parks, rp_prev unchanged", fl(x[k]), (109, 30, 70, SENT, 1))
        t.eq("x1 on PICKUP: its own Part bytes unchanged", pu(x["x1"]), pu(x["x0"]))
        t.eq("x1 machine bytes", (x["x1"].mach(0), x["x3"].mach(0), x["x5"].mach(0)), (PU, THRU, ST))
        c = E.captured(d, "pu_qw")
        t.eq("PICKUP: PTCH widget = stock dial, no poll", (c["value"], c["fmt"]), (77, PTCH_FMT))
        t.eq("x5 STATIC (not VARI): its bytes untouched", stv(x["x5"]), (80, 40, 0, SENT - 1))
        t.eq("x6 STATIC entered VARI: QUAN fresh (1/1), PTCH 80 parked, TSNS 40 kept", stv(x["x6"]), (64, 40, 80, SENT - 1))
        t.eq("x7 back on FLEX: STATIC kept", stv(x["x7"]), (64, 40, 80, SENT - 1))
        t.eq("x8 STATIC again: unchanged", stv(x["x8"]), (64, 40, 80, SENT - 1))
        t.eq("rp_prev T1 ST / FL at the end", (x["x9"].rp(0, ST), x["x9"].rp(0, FL)), (1, 1))
    elif name == "o2":
        o0 = cp["o0"]
        t.eq("o0: T1 VARI (QUAN 109, TSNS 127), T2 not (PTCH 50, TSNS 20)",
             (o0.p1(0, FL), o0.p2(0, FL), o0.p1(1, FL), o0.p2(1, FL), o0.rp(0, FL), o0.rp(1, FL) in (0, 0xff)),
             (109, 127, 50, 20, 1, True))
        sp = cp["srcpaste"]
        t.eq("SRC paste T1 -> T2: TSTR / QUAN / TSNS as pasted, T2's parks untouched, adopted",
             (sp.p2(1, FL, 4), sp.p1(1, FL), sp.p2(1, FL), sp.park(1, 1, FL), sp.park(1, 2, FL), sp.rp(1, FL) in (1, 0xff)),
             (4, 109, 127, 0, 0, True))
        su = cp["srcundo"]
        t.eq("SRC paste undone: T2 back, adopted",
             (su.p2(1, FL, 4), su.p1(1, FL), su.p2(1, FL), su.park(1, 1, FL), su.rp(1, FL) in (0, 0xff)),
             (o0.p2(1, FL, 4), 50, 20, 0, True))
        tp = cp["trkpaste"]
        t.eq("track paste T1 -> T3: the whole block, the PTCH park included, adopted",
             (tp.p2(2, FL, 4), tp.p1(2, FL), tp.p2(2, FL), tp.park(2, 1, FL), tp.park(2, 2, FL), tp.rp(2, FL)),
             (4, 109, 127, 70, 0, 1))
        cl = cp["clear"]
        t.eq("PART CLEAR: T1 back to defaults, nothing swapped in", (cl.park(0, 1, FL), cl.park(0, 2, FL), cl.rp(0, FL)),
             (0, 0, 0))
        t.eq("PART CLEAR: T1's slots hold the defaults, not a park", (cl.p1(0, FL), cl.p2(0, FL)), (64, 64))
        cu = cp["clearundo"]
        t.eq("PART CLEAR undone: T1 VARI again, adopted",
             (cu.p2(0, FL, 4), cu.p1(0, FL), cu.p2(0, FL), cu.park(0, 1, FL), cu.park(0, 2, FL), cu.rp(0, FL)),
             (4, 109, 127, 70, 0, 1))
        pp = cp["partpaste"]
        t.eq("PART PASTE: T1 as copied, adopted",
             (pp.p2(0, FL, 4), pp.p1(0, FL), pp.p2(0, FL), pp.park(0, 1, FL), pp.park(0, 2, FL), pp.rp(0, FL)),
             (4, 109, 127, 70, 0, 1))
        rl = cp["reload"]
        t.eq("RELOAD PART: the saved T1 (not VARI), adopted, no swap", (rl.p2(0, FL, 4), rl.p1(0, FL), rl.p2(0, FL), rl.rp(0, FL)),
             (1, 64, 64, 0))
        t.eq("no HOLD left behind", [x for x in rl.prev[:16] if x == 0xfe], [])
        t.eq("hold depth back to 0", rl.prev[16], 0)
    elif name == "o2rev":
        r0, r1 = cp["r0"], cp["r1"]
        t.eq("r0: T1 VARI, rp_prev 1", (r0.p2(0, FL, 4), r0.p1(0, FL), r0.p2(0, FL), r0.rp(0, FL)), (4, 109, 127, 1))
        t.eq("pasted over: T1 = T2's page (AUTO, 50, 20), the PTCH park untouched, adopted 0",
             (r1.p2(0, FL, 4), r1.p1(0, FL), r1.p2(0, FL), r1.park(0, 1, FL), r1.park(0, 2, FL), r1.rp(0, FL)),
             (1, 50, 20, 70, 0, 0))
    elif name == "o2late":
        l = cp["late"]
        t.eq("T2 after its trigs: QUAN / TSNS kept, parks untouched, rp_prev 1",
             (l.p2(1, FL, 4), l.p1(1, FL), l.p2(1, FL), l.park(1, 1, FL), l.park(1, 2, FL), l.rp(1, FL)),
             (4, 109, 127, 0, 0, 1))
    elif name == "old56":
        e = cp["end"]
        t.eq("old values still there (stock does nothing with them)", (e.p2(0, FL, 4), e.p2(1, FL, 4)), (5, 6))
        t.eq("not VARI: rp_prev T1..T4", [e.rp(k, FL) for k in range(4)], [0, 0, 0, 0])
    elif name == "spring":
        fx0, fx, live = ((d / k).read_bytes() for k in ("fx0", "fx", "live"))
        t.notes.append(f"T1 FX2 before: 0x{fx0[8]:02x}")
        t.eq("FX2 SPRING REVERB (0x15) chosen on T1: the Part's byte, the live id", (fx[8], live[8]), (0x15, 0x15))
    return t


# deliberately wrong builds: edits of the shared source, built by tools/build_varispeed.py
VARIANTS = {
    "w_mask": [("        .if VEM_EMUS\n        andi.l  #0xfffffff3,%d0         | bits 2-3 are the DSP engine: "
                "never stock's\n        .endif", "        andi.l  #0xfffffff3,%d0")],
    "w_lowbits": [("        moveq   #-16,%d4                | bits 0-3 clear: VARISPEED_EMUS's increment on OT",
                   "        moveq   #-1,%d4")],
}


def build_variants(tags):
    import subprocess
    out = ROOT / "out/vari_variants"
    (out / "src").mkdir(parents=True, exist_ok=True)
    for tag in tags:
        txt = E.SRC.read_text()
        for old, new in VARIANTS[tag]:
            if txt.count(old) != 1:
                sys.exit(f"variant {tag}: the source has {txt.count(old)} of {old[:50]!r}")
            txt = txt.replace(old, new)
        src = out / "src" / f"{tag}.s"
        src.write_text(txt)
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_varispeed.py")], cwd=ROOT,
                           env=dict(os.environ, KYOTI_ALLOW_WIP="1", VARI_VARIANT=tag, VARI_VARIANT_SRC=str(src)),
                           capture_output=True, text=True)
        print(f"variant {tag}: {'built' if r.returncode == 0 else 'FAILED'}")
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--build-variants", default="", help="all, or tags (comma-separated)")
    a = ap.parse_args()
    if a.build_variants:
        return build_variants(list(VARIANTS) if a.build_variants == "all" else a.build_variants.split(","))
    sc = scenarios()
    if a.only:
        sc = {k: v for k, v in sc.items() if k in a.only.split(",")}
    res = []
    if not a.only or "static" in a.only.split(","):
        res.append(static_checks())
    if sc and not a.reuse:
        print(f"running {len(sc)} scenarios on {IMG.name} ...", flush=True)
        E.run(sc, a.jobs)
    for n, s in sc.items():
        res.append(check(n, s))
    for t in res:
        print(f"{'PASS' if not t.fails else 'FAIL'}  {t.name}")
        for f in t.fails:
            print(f"      FAIL {f}")
        for x in t.notes:
            print(f"      ok   {x}")
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / "results.json").write_text(json.dumps({t.name: dict(fails=t.fails, notes=t.notes) for t in res}, indent=1))
    bad = [t for t in res if t.fails]
    print(f"\n{len(res) - len(bad)}/{len(res)} tests pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

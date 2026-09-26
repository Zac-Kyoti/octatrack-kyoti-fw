#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_toast -- the RELOAD messages are stock BLOCK toasts, one taller for 2 lines.

Session 89, hardware report #11, which reverted Session 88's card:
  "I want the toasts to NOT be in cards. I want them to be in the form of the
   previously used larger block toasts. But we need 1) TRK SEQ + PART, RELOADED and
   2) TRK SEQ RELOADED, SAVE PART FIRST! each on two lines (enlarge toast vertical
   size)."
plus, from report #10 and still standing: no OK prompt and no countdown dots anywhere.

WHAT THE BLOCK TOAST IS (decoded from stock TOAST, FUN_4005a2b8)
    width  = text width + 15   (0x4005a2f2)     height = 0x12       (0x4005a2ee)
    style  = 0xa  <- the BLOCK look; 4 is the card look Session 88 wrongly used
    slot     0x460d1e70   countdown 0x460d1e6c   dismiss 0x40056bec
    one line, centred at y = height-11, drawn by FUN_40057008

rl3_toast2 keeps every one of those and changes only the height
(0x12 + 7*(n-1)) and the number of centred lines. So a 1-line call is stock's toast
exactly, and a 2-line call is stock's toast grown upward by one row.

WHY THIS SLOT IS THE SAFE ONE (both measured)
  * its tick 0x40056c28 reads the countdown DIRECTLY (`tstl 0x460d1e6c ; beq rts`) with
    NO enabling flag. The SHOW_WIN slot's tick is gated on CD_FLAG at 0x40056abe, and
    clearing that by mistake is what would have left Session 88's card up forever.
  * the countdown DOTS come from 0x40037cc8, which reads the SHOW_WIN slot ONLY, so
    nothing on the toast path can draw them.

WHAT IS ASSERTED
  * the 2-line messages use rl3_toast2 with style 0xa and height 0x12+7 = 0x19
  * LINE ORDER: line 0 must sit ABOVE line 1. y counts up from the bottom (settled by
    stock's own 3-line message, whose reading order is fixed), so line 0 must have the
    GREATER y. An earlier version of the patch had this inverted, which would have
    printed "RELOADED" above "TRK SEQ + PART".
  * both lines CENTRED: x is computed, never stock's hardcoded 4, and the longer line
    gets the smaller x
  * MLNOTIFY never called and no OK-prompt keymap layer pushed
  * the dot routine never entered
  * the toast countdown is armed
  * the single-line [PTN] message uses stock TOAST itself
  * back-to-back reloads both draw

Usage:
  python3 tools/diag_reload3_toast.py [--chord ptn|bank] [--track N]
"""
import argparse
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE, BANK_CODE = 0x2E, 0x2F
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

TOAST       = 0x4005A2B8
TOAST_SLOT  = 0x460D1E70
TOAST_CD    = 0x460D1E6C
MLNOTIFY    = 0x4006D57C
LAYER_PUSH  = 0x40031494
OK_LAYER    = 0x400CDFF8
DOTS        = 0x40037CC8
DRAWTEXT    = 0x40012BD8
WIN_DRAW1   = 0x40057008
WIN_NEW     = 0x4005829C
G_KIND      = 0x80006A50
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7000
SAVEFIRST   = 0x400B41BB


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--chord", choices=("ptn", "bank"), default="bank")
    ap.add_argument("--track", type=int, default=3)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(rt.uc.mem_read(0x80000002, 1)[0], P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : pattern={P}")

    nm = subprocess.run(["m68k-elf-nm", "out/patch_reload3.elf"],
                        capture_output=True, text=True, cwd=ROOT).stdout
    sym = {q[2]: int(q[0], 16) for q in (l.split() for l in nm.splitlines())
           if len(q) == 3}

    C = {"t2": 0, "toast": 0, "ml": 0, "oklayer": 0, "dots": 0}
    wins, draws = [], []

    def bump(k):
        return lambda u, ad, sz, x: C.__setitem__(k, C[k] + 1)
    for addr, k in ((sym["rl3_toast2"], "t2"), (TOAST, "toast"),
                    (MLNOTIFY, "ml"), (DOTS, "dots")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, bump(k), begin=addr, end=addr)

    def on_push(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        if struct.unpack(">I", u.mem_read(sp + 4, 4))[0] == OK_LAYER:
            C["oklayer"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_push, begin=LAYER_PUSH, end=LAYER_PUSH)

    def on_win(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        w, h, _, _, style, _ = struct.unpack(">6I", u.mem_read(sp + 4, 24))
        wins.append((w, h, style))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_win, begin=WIN_NEW, end=WIN_NEW)

    def on_draw(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        font, winptr, xx, yy, ln, txt = struct.unpack(">6I", u.mem_read(sp + 4, 24))
        draws.append((xx, yy, txt))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=DRAWTEXT, end=DRAWTEXT)

    # WIN_DRAW1(handle, text, top, font) -- line 0 goes through here
    d1 = []
    def on_d1(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        h, text, top, font = struct.unpack(">4I", u.mem_read(sp + 4, 16))
        d1.append(text)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_d1, begin=WIN_DRAW1, end=WIN_DRAW1)
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    for _ in range(20):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    def txt(ptr):
        out = b""
        while len(out) < 40:
            c = rt.uc.mem_read(ptr + len(out), 1)
            if c == b"\x00":
                break
            out += c
        return out.decode("latin1")

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    def fire():
        mod = PTN_CODE if a.chord == "ptn" else BANK_CODE
        key(mod, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(mod, RELEASE)
        for _ in range(200):
            rt.run(ms=10)
            if rt.uc.mem_read(G_KIND, 1)[0] == 0:
                break

    two_line = (a.chord == "bank")
    print(f"\n--- [{a.chord.upper()}] + [TRACK {a.track+1}] ---")
    wins.clear(); draws.clear(); d1.clear()
    fire()

    chk(C["ml"] == 0, f"MLNOTIFY never called (x{C['ml']}) -- no card, no OK dialog")
    chk(C["oklayer"] == 0, f"no OK-prompt keymap layer pushed (x{C['oklayer']})")
    chk(C["dots"] == 0, f"NO countdown dots drawn (x{C['dots']})")
    chk(u32(TOAST_SLOT) != 0, f"a toast is up (slot={u32(TOAST_SLOT):#x})")
    chk(u32(TOAST_CD) != 0, f"the toast countdown is armed (cd={u32(TOAST_CD)})")

    ours = [d for d in draws if CAVE_LO <= d[2] < CAVE_HI or d[2] == SAVEFIRST]
    mine = [t for t in d1 if CAVE_LO <= t < CAVE_HI or t == SAVEFIRST]
    print(f"   WIN_NEW (w,h,style): {wins}")
    print(f"   line 0 via WIN_DRAW1: {[txt(t) for t in mine]}")
    print(f"   extra lines (x,y,text): {[(x, y, txt(t)) for x, y, t in ours]}")

    if two_line:
        chk(C["t2"] == 1, f"rl3_toast2 ran once (x{C['t2']})")
        chk(C["toast"] == 0, f"stock 1-line TOAST not used for a 2-line message "
                             f"(x{C['toast']})")
        tw = [w for w in wins if w[2] == 0xA]
        chk(bool(tw), f"a BLOCK-style window (style 0xa) was made: {wins}")
        if tw:
            w, h, st = tw[-1]
            chk(h == 0x12 + 7,
                f"height enlarged for two lines: {h} == 0x12+7 ({0x12+7})")
            chk(st == 0xA, f"style is the BLOCK look 0xa (got {st:#x}), not the card 4")
        # ** WIN_DRAW1 calls DRAWTEXT internally. ** So `ours` already holds BOTH
        # lines -- line 0 via stock's path and line 1 via ours -- and counting the
        # WIN_DRAW1 hook separately double-counts line 0. Use the DRAWTEXT list as the
        # single source of truth and tell the lines apart by y: stock's path always
        # draws at y = height-11.
        h = tw[-1][1] if tw else 0x19
        chk(len(ours) == 2, f"exactly two lines drawn (n={len(ours)}): "
                            f"{[(x, y, txt(t)) for x, y, t in ours]}")
        chk(len(mine) == 1 and txt(mine[0]) == txt(ours[0][2]) if (mine and ours)
            else False,
            "line 0 went through stock's own single-line path")
        if len(ours) == 2:
            top = [d for d in ours if d[1] == h - 11]
            bot = [d for d in ours if d[1] != h - 11]
            chk(len(top) == 1 and len(bot) == 1,
                f"one line at stock's y={h-11} and one elsewhere "
                f"(y={[d[1] for d in ours]})")
            if top and bot:
                (x0, y0, t0), (x1, y1, t1) = top[0], bot[0]
                l0, l1 = txt(t0), txt(t1)
                print(f"   layout: line0 {l0!r} y={y0} x={x0}   "
                      f"line1 {l1!r} y={y1} x={x1}")
                chk(y0 > y1,
                    f"LINE ORDER: line 0 sits ABOVE line 1 ({y0} > {y1}) -- y counts "
                    f"up from the bottom, so the first line needs the greater y")
                chk(x0 != 4 and x1 != 4,
                    f"both lines CENTRED at computed x ({x0}, {x1}), not stock's 4")
                longer_x, shorter_x = ((x0, x1) if len(l0) >= len(l1) else (x1, x0))
                chk(longer_x <= shorter_x,
                    f"the LONGER line sits further left ({longer_x} <= {shorter_x})")
    else:
        chk(C["toast"] == 1, f"stock's own block TOAST used once (x{C['toast']})")
        chk(C["t2"] == 0, f"the 2-line path not used for a 1-line message (x{C['t2']})")
        chk(len(mine) == 1, f"exactly one line drawn (n={len(mine)})")
        if mine:
            print(f"   text: {txt(mine[0])!r}")

    # ---- repeatable ----
    print("\n--- a second reload must draw too ---")
    b2, bt = C["t2"], C["toast"]
    fire()
    drew = (C["t2"] - b2) if two_line else (C["toast"] - bt)
    chk(drew == 1, f"the message drew again (x{drew})")
    chk(C["ml"] == 0 and C["oklayer"] == 0 and C["dots"] == 0,
        "still no dialog, no OK prompt, no dots")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- block toasts, taller for two lines, correct line order, "
          "centred, no OK prompt, no dots.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

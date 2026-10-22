#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Validate QUANTIZE_LIVE_REC_TOGGLE (out/mainos_quantize_live_rec_toggle.bin) in octabam's
full-firmware emulator.

Boots the image, loads the factory OT DEMO, opens PROJECT -> PERSONALIZE (FUN_40064e48(12):
the menu opener, then screen 12), then drives the stock key handlers directly with [REC]
held (0x460d1726 = 1):
  1. [PLAY] with no toast up  -> toast shows the setting, QUANTIZE LIVE REC unchanged
  2. [PLAY] while it is up    -> setting inverts + shadow + 'ANDY' checksum, toast shows the
                                 new value, and PERSONALIZE is redrawn (its draw 0x40068e00
                                 reads the getter 0x40068ce0 AFTER the flip)
  3. [REC] release            -> toast closed
  4. menu closed, flip again  -> setting inverts, no menu redraw (window 0x400cbf4c == 0)
Logic only: route A does not run the UI frame that composites the menu window and the
toast onto the LCD plane (a screenshot shows only the page underneath), so what the screen
shows on the unit is a hardware question.

    python3 tools/emu_qlrec.py [--image out/mainos_quantize_live_rec_toggle.bin]
"""
import argparse, os, pathlib, struct, sys
sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath  # noqa: E402,F401
import emu_rtos as er
import emu_bringup as eb

REC_HELD, NOTIF_H = 0x460d1726, 0x460d1e70
QLR, QLR_SH = 0x800000ac, 0x100fff3c
PLAY_KEY, REC_KEY = 0x40061778, 0x40048774          # stock key handlers (keycode, event)
MENU_OPEN_AT = 0x40064e48                            # open the PROJECT menu at screen N
MENU_SCR, MENU_WIN = 0x400cbf40, 0x400cbf4c
MENU_REDRAW, PERS_DRAW, QLR_GET = 0x40064d7c, 0x40068e00, 0x40068ce0
NOTIFY = 0x4005a2b8
PERSONALIZE = 12

fails = []


def check(ok, what):
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        fails.append(what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "out" / "mainos_quantize_live_rec_toggle.bin"))
    a = ap.parse_args()
    image = pathlib.Path(a.image)
    if not image.is_absolute():
        image = ROOT / image
    # own staging tree per image: octabam's default (refs/octabam/out/_emu_rtos_tree) is shared
    # with every other run on this Mac, and two runs staging at once collide
    tree = ROOT / "out" / f"_emu_qlrec_tree_{image.stem}"
    card, name = er.stage_project(str(DEMO), "OCTABAM", None, tree=str(tree))
    r, rt = er.attach(str(image), card, tick=True)
    mounted, *_, elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"=== {image.name}: loaded={mounted} ({elapsed:.0f} ms) ===")
    uc = rt.uc
    u32 = lambda adr: struct.unpack(">I", bytes(uc.mem_read(adr, 4)))[0]
    w32 = lambda adr, v: uc.mem_write(adr, struct.pack(">I", v & 0xffffffff))

    trace, toasts = [], []

    def on_pc(u, adr, size, x):
        trace.append(adr)
        if adr == NOTIFY:
            sp = u.reg_read(eb.UC_M68K_REG_A7)
            p = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
            toasts.append(bytes(u.mem_read(p, 32)).split(b"\0")[0].decode(errors="replace"))
        elif adr == QLR_GET:
            trace.append(("get", u32(QLR)))
    for pc in (MENU_REDRAW, PERS_DRAW, QLR_GET, NOTIFY):
        uc.hook_add(eb.UC_HOOK_CODE, on_pc, begin=pc, end=pc)
    uc.ctl_flush_tb()

    def call(entry, *args):
        trace.clear(); toasts.clear()
        rt.run(until=lambda s: s.pc == er.MAIN_SPIN)
        rt.call_as_main(entry, args=args)
        return list(trace), list(toasts)

    print("\nopen PROJECT -> PERSONALIZE")
    t, _ = call(MENU_OPEN_AT, PERSONALIZE)
    check(u32(MENU_SCR) == PERSONALIZE and u32(MENU_WIN) != 0,
          f"menu screen {u32(MENU_SCR)}, window {u32(MENU_WIN):#x}")
    check(PERS_DRAW in t, "PERSONALIZE drew on open")
    q0 = u32(QLR)
    print(f"  QUANTIZE LIVE REC raw {q0}")
    w32(REC_HELD, 1)
    if u32(NOTIF_H):                                  # start from no toast on screen
        call(0x40056bec)

    print("\n1. [REC] held, [PLAY] with no toast up -> show only")
    t, ts = call(PLAY_KEY, 0x28, 1)
    want = "LIVE REC: QUANTIZED" if q0 == 0 else "LIVE REC: UNQUANTIZED"
    check(u32(QLR) == q0, f"setting unchanged ({u32(QLR)})")
    check(ts == [want], f"toast {ts}")
    check(u32(NOTIF_H) != 0, "toast handle set")
    check(MENU_REDRAW not in t, "no menu redraw on a show-only press")

    print("\n2. [PLAY] while the toast is up -> invert + PERSONALIZE redraw")
    t, ts = call(PLAY_KEY, 0x28, 1)
    q1 = u32(QLR)
    want = "LIVE REC: QUANTIZED" if q1 == 0 else "LIVE REC: UNQUANTIZED"
    check(q1 == q0 ^ 1, f"setting inverted {q0} -> {q1}")
    check(u32(QLR_SH) == q1, f"'ANDY' shadow {u32(QLR_SH)}")
    check(ts == [want], f"toast {ts}")
    check(MENU_REDRAW in t and PERS_DRAW in t, "menu redraw ran PERSONALIZE's draw")
    gets = [v for e in t if isinstance(e, tuple) for v in e[1:]]
    check(gets and all(v == q1 for v in gets), f"getter read the NEW value during redraw {gets}")
    if MENU_REDRAW in t and NOTIFY in t:
        check(t.index(MENU_REDRAW) < t.index(NOTIFY), "redraw before the toast opens (toast on top)")

    print("\n3. [REC] release -> toast closed")
    w32(REC_HELD, 1)
    call(REC_KEY, 0x29, 0)
    check(u32(NOTIF_H) == 0 and u32(REC_HELD) == 0, f"handle {u32(NOTIF_H):#x}, REC_HELD {u32(REC_HELD)}")

    print("\n4. menu closed: flip again, no redraw")
    call(0x40064c18)                                  # the menu opener toggles: closes it
    check(u32(MENU_WIN) == 0, f"menu window {u32(MENU_WIN):#x}")
    w32(REC_HELD, 1)
    call(PLAY_KEY, 0x28, 1)
    t, ts = call(PLAY_KEY, 0x28, 1)
    check(u32(QLR) == q0, f"setting inverted back -> {u32(QLR)}")
    check(PERS_DRAW not in t, "PERSONALIZE not drawn with the menu closed")
    call(REC_KEY, 0x29, 0)

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

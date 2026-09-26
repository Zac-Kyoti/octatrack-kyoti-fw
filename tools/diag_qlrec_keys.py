#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Drive the REAL gesture through the REAL per-key dispatcher and watch QLR.

`set_key_state` (0x40031734) is the sole per-key dispatcher: it looks the
keycode up in the runtime table at 0x46c7d8de (stride 24) and calls that
record's handler with (code@4, event@8).  Driving IT -- rather than calling
qlr_play directly -- exercises the whole chain the hardware uses: keymap
lookup, our detour at 0x40061778, the gate, NOTIFY, and stock's live-rec tail.

Reproduces: hold [REC], tap [PLAY] x3.

It also prints PLAY's runtime dispatch slot at each step, because the other
candidate explanation is that starting LIVE RECORDING swaps the keymap layer so
later [PLAY] presses never reach our detour at all -- the exact failure mode
that killed DIRECT JUMP v1-v3 (NOTES Session 61: a held modifier NULLed the
[YES] slot, so the detoured handler was never entered).

Usage:  python3 tools/diag_qlrec_keys.py
"""
import os
import pathlib
import re
import struct
import subprocess
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED_IMAGE = ROOT / "out" / "mainos_qlrec.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402

SET_KEY_STATE = 0x40031734
KEY_TAB = 0x46C7D8DE
PLAY, REC = 0x28, 0x29
NOTIFY = 0x4005A2B8
NOTIF_H, NOTIF_T = 0x460D1E70, 0x460D1E6C
REC_HELD, LIVE_REC = 0x460D1726, 0x460D172A
QLR, QLR_SH = 0x800000AC, 0x100FFF3C
G_OWN = 0x80006A60


def _equ(name):
    src = (ROOT / "tools/patch_qlrec.s").read_text()
    return int(re.search(rf"^\s*\.equ\s+{name},\s*(0x[0-9a-fA-F]+|\d+)", src, re.M).group(1), 0)


def _sym(name):
    out = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_qlrec.elf")],
                         capture_output=True, text=True).stdout
    for l in out.splitlines():
        p = l.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)


MAGIC = _equ("MAGIC")
LIVE_DUR = _equ("LIVE_DUR")
QLR_PLAY = _sym("qlr_play")


def rd(rt, a):
    return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]


def wr(rt, a, v):
    rt.uc.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))


def slot(rt, code):
    return rd(rt, KEY_TAB + code * 24)


def show(rt, tag, hits):
    print(f"  {tag:<20} QLR={rd(rt, QLR)}  G_OWN=0x{rd(rt, G_OWN):08x}"
          f"  H=0x{rd(rt, NOTIF_H):08x}  T={rd(rt, NOTIF_T)}"
          f"  RECHELD={rd(rt, REC_HELD)}  LIVEREC={rd(rt, LIVE_REC)}")
    print(f"  {'':<20} PLAY slot=0x{slot(rt, PLAY):08x}  "
          f"qlr_play entered {hits['play']}x, NOTIFY {hits['notify']}x")


def main():
    if not PATCHED_IMAGE.exists():
        sys.exit(f"missing {PATCHED_IMAGE} -- run tools/build_qlrec.py first")
    print(f"qlr_play=0x{QLR_PLAY:08x}  MAGIC=0x{MAGIC:08x}  LIVE_DUR={LIVE_DUR}")
    print(f"PLAY runtime slot addr = 0x{KEY_TAB + PLAY*24:08x}\n")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(PATCHED_IMAGE), card, tick=True)
    mounted, *_rest, elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"project load: mounted={mounted} ({elapsed:.0f} ms)\n")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)

    hits = {"play": 0, "notify": 0}
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, lambda *a: hits.__setitem__("play", hits["play"] + 1),
                   begin=QLR_PLAY, end=QLR_PLAY + 1)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, lambda *a: hits.__setitem__("notify", hits["notify"] + 1),
                   begin=NOTIFY, end=NOTIFY + 1)

    wr(rt, QLR, 0)
    wr(rt, QLR_SH, 0)
    wr(rt, G_OWN, 0)
    show(rt, "at rest:", hits)

    seen = [rd(rt, QLR)]

    def key(code, event, tag):
        try:
            rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=20_000_000)
        except Exception as e:
            print(f"  {tag}: set_key_state DID NOT RETURN: {type(e).__name__}: {e}")
            return
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN, max_bursts=300000)
        show(rt, tag, hits)
        seen.append(rd(rt, QLR))

    print()
    key(REC, 1, "[REC] down:")
    for n in (1, 2, 3):
        key(PLAY, 1, f"[PLAY] tap {n}:")
    key(REC, 0, "[REC] up:")

    print()
    q = rd(rt, QLR)
    flips = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    # 3 taps -> 3 entries is CORRECT.  (An earlier version compared against 4 and
    # cried wolf; read the per-step QLR column, not this line, if they disagree.)
    if hits["play"] < 3:
        print(f"  *** qlr_play entered only {hits['play']}x for 3 [PLAY] taps --")
        print("      later taps are NOT reaching our detour (keymap/dispatch), not a gate bug.")
    elif flips >= 2:
        print(f"  qlr_play entered {hits['play']}x and QLR flipped {flips}x -- the whole")
        print("      gesture works end to end against the real firmware.")
    else:
        print(f"  *** every tap ran qlr_play but QLR flipped only {flips}x.")
        print("      The per-step state above says which gate word is wrong.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Run OUR OWN qlr_play inside the REAL firmware, twice, and watch the flip gate.

The isolation harness (emu_qlrec.py) stubs NOTIFY to `rts`, so it can only prove
the logic is self-consistent.  This runs the actual cave bytes against the real
FUN_4005a2b8 after a real project load, which is the only way to see what the
gate words really hold at the moment of the second press.

Gate:  G_OWN == MAGIC  &&  *0x460d1e70 != 0  &&  *0x460d1e6c > 0

Setup: REC_HELD = 1 and LIVE_REC = 1 so qlr_play swallows the press with a plain
`rts` (no stock tail to chase), exactly as presses 2..n do on hardware.

Usage:  python3 tools/diag_qlrec_live.py
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

NOTIFY = 0x4005A2B8
NOTIF_H = 0x460D1E70
NOTIF_T = 0x460D1E6C
REC_HELD = 0x460D1726
LIVE_REC = 0x460D172A
QLR = 0x800000AC
QLR_SH = 0x100FFF3C
G_OWN = 0x80006A60


def _syms():
    out = subprocess.run(["m68k-elf-nm", str(ROOT / "out/patch_qlrec.elf")],
                         capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in out.splitlines()) if len(p) == 3}


def _equ(name):
    src = (ROOT / "tools/patch_qlrec.s").read_text()
    return int(re.search(rf"^\s*\.equ\s+{name},\s*(0x[0-9a-fA-F]+|\d+)", src, re.M).group(1), 0)


SYM = _syms()
QLR_PLAY = SYM["qlr_play"]
MAGIC = _equ("MAGIC")
LIVE_DUR = _equ("LIVE_DUR")


def rd(rt, a):
    return struct.unpack(">I", rt.uc.mem_read(a, 4))[0]


def wr(rt, a, v):
    rt.uc.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))


def state(rt, tag):
    own, h, t, q = rd(rt, G_OWN), rd(rt, NOTIF_H), rd(rt, NOTIF_T), rd(rt, QLR)
    gate = (own == MAGIC) and h != 0 and (0 < t < 0x80000000)
    print(f"  {tag:<22} QLR={q}  G_OWN=0x{own:08x}{'(MAGIC)' if own == MAGIC else ''}"
          f"  H=0x{h:08x}  T={t}   gate={'OPEN' if gate else 'SHUT'}")
    return gate, q


def main():
    if not PATCHED_IMAGE.exists():
        sys.exit(f"missing {PATCHED_IMAGE} -- run tools/build_qlrec.py first")
    print(f"qlr_play=0x{QLR_PLAY:08x}  MAGIC=0x{MAGIC:08x}  LIVE_DUR={LIVE_DUR}\n")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(PATCHED_IMAGE), card, tick=True)
    mounted, *_rest, elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"project load: mounted={mounted} ({elapsed:.0f} ms)\n")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)

    # presses 2..n on hardware: REC held, live rec already running -> swallowed
    wr(rt, REC_HELD, 1)
    wr(rt, LIVE_REC, 1)
    wr(rt, QLR, 0)
    wr(rt, QLR_SH, 0)
    wr(rt, G_OWN, 0)
    wr(rt, NOTIF_H, 0)
    wr(rt, NOTIF_T, 0)

    calls = {"notify": 0}

    def on_notify(u, addr, size, ctx):
        calls["notify"] += 1

    h = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_notify, begin=NOTIFY, end=NOTIFY + 1)

    state(rt, "before press 1:")
    for n in (1, 2, 3):
        try:
            rt.call_as_main(QLR_PLAY, args=(0x28, 1), budget=8_000_000)
        except Exception as e:
            print(f"  press {n}: qlr_play DID NOT RETURN: {type(e).__name__}: {e}")
            break
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN, max_bursts=200000)
        gate, q = state(rt, f"after press {n}:")
    rt.uc.hook_del(h)

    print(f"\n  NOTIFY called {calls['notify']} times (expect one per press)")
    print()
    print("  NB: read the PER-STEP QLR column, not the final value -- an even number")
    print("  of flips lands back on 0, which is success, not failure.")


if __name__ == "__main__":
    main()

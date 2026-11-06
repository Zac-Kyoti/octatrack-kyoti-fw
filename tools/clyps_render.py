#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- render the screen in the emulator (route A does not run the UI task's redraw, so the
plane at 0x46c7e0ea is never composed on its own). After the key steps, this calls stock's
composer 0x40013abc() itself -- what the UI task does when RDRAW (0x46c7c72c) is set -- and
writes the plane as a PNG (octabam's lcd_view).

  python3 tools/clyps_render.py --project DIR --name NAME --keys "2e+ 2f+ 33 33" --out x.png
      keys: HEX+ = press, HEX- = release, HEX = tap; "call:ADDR" = call_as_main(ADDR);
            "poke:ADDR=TEXT" writes ASCII there ('_' = space), e.g. into the name editor; "peek:ADDR:N" prints N bytes; "wait:MS" runs the system
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY, COMPOSE, PLANE = 0x40031734, 0x40013ABC, 0x46C7E0EA


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "out/mainos_clyps.bin"))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--keys", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--each", action="store_true", help="also write a PNG after every step")
    ap.add_argument("--ascii", action="store_true", help="also print the final screen as text")
    a = ap.parse_args(argv)
    image = str(pathlib.Path(a.image).resolve())
    out = pathlib.Path(a.out).resolve()
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    import lcd_view
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree="out/_emu_clyps_render")
    r, rt = er.attach(image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000)
    rt.run(ms=300)

    def call(addr, *args):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        return rt.call_as_main(addr, args=args, budget=600000)

    def snap(path):
        buf = int.from_bytes(bytes(rt.uc.mem_read(0x400B9710, 4)), "big")   # before: double-buffered
        call(COMPOSE)
        raw = bytes(rt.uc.mem_read(buf, 1024))
        # the composer's own buffer has the LCD plane's rotated layout (lcd_view.pixels)
        px = lcd_view.pixels(raw)
        lcd_view.png(px, str(path))
        if a.ascii:
            print("\n".join(f"{y:2d} " + "".join("#" if v else "." for v in row) for y, row in enumerate(px)))

    for i, k in enumerate(a.keys.split()):
        if k.startswith("call:"):
            call(int(k[5:], 16))
        elif k.startswith("pokex:"):                   # pokex:ADDR=HEXBYTES
            ad, hx = k[6:].split("=", 1)
            rt.uc.mem_write(int(ad, 16), bytes.fromhex(hx))
        elif k.startswith("wait:"):                    # wait:MS -- let the system run (e.g. a card job)
            rt.run(ms=int(k[5:]))
        elif k.startswith("peek:"):                    # peek:ADDR:N -- print N bytes (hex)
            ad, nb = k[5:].split(":")
            print(f"peek 0x{int(ad, 16):08x}: {bytes(rt.uc.mem_read(int(ad, 16), int(nb, 0))).hex()}", flush=True)
        elif k.startswith("poke:"):                    # poke:ADDR=TEXT (ASCII; '_' = space)
            ad, txt = k[5:].split("=", 1)
            rt.uc.mem_write(int(ad, 16), txt.replace("_", " ").encode())
        elif k.endswith("+"):
            if 0x10 <= int(k[:-1], 16) <= 0x17:
                rt.uc.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))   # no double tap (as diag_clyps_ui.py)
            call(SET_KEY, int(k[:-1], 16), 1)
        elif k.endswith("-"):
            call(SET_KEY, int(k[:-1], 16), 0)
        else:
            if 0x10 <= int(k, 16) <= 0x17:
                rt.uc.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))
            call(SET_KEY, int(k, 16), 1)
            call(SET_KEY, int(k, 16), 0)
        if not k.startswith(("call:", "poke")):
            # the UI tail (0x40062d1c) runs after every SYS message on hardware, a key included: a
            # type-0 message goes straight to it (the loop's range check), as in diag_clyps_ui.py
            rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
            rt.uc.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
            rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
        rt.run(ms=60)
        if a.each:
            snap(out.with_name(f"{out.stem}_{i:02d}{out.suffix}"))
    rd = lambda ad, n: int.from_bytes(bytes(rt.uc.mem_read(ad, n)), "big")
    syms = {k: int(v, 16) for k, v in (l.split() for l in (ROOT / "out/clyps_syms.txt").read_text().splitlines())}
    print(f"saved {list(bytes(rt.uc.mem_read(syms['cl_svalid'], 4)))} src T1 {bytes(rt.uc.mem_read(syms['cl_src'], 2)).hex()} "
          f"home T1 {bytes(rt.uc.mem_read(syms['cl_home'], 2)).hex()}")
    print(f"cl_open {rd(syms['cl_open'], 1)} cl_win 0x{rd(syms['cl_win'], 4):08x} POPUP 0x{rd(0x460E5CD0, 4):08x} "
          f"ARR 0x{rd(0x460D1AEC, 4):08x}")
    print(f"compose target [0x400b9710] = 0x{rd(0x400B9710, 4):08x}; plane 0x{PLANE:08x}")
    w = rd(0x460BABF0, 4)
    while w and w < 0x50000000:
        f = [rd(w + o, 4) for o in range(0, 0x30, 4)]
        print(f"  window 0x{w:08x}: " + " ".join(f"{x:08x}" for x in f))
        w = rd(w, 4)
    snap(out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

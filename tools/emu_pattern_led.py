#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Validate tools/patch_pattern_led.s in octabam's full-firmware emulator.

Boots the image (stock, then out/mainos_patternled.bin with --patched), mounts the
factory OT DEMO, and drives FUN_4009a464 -- the pattern-grid "has content"
predicate -- through the cases the fix cares about.  Pattern 15 is reset to a
genuine stock-empty state with the real initialiser FUN_4009abdc(blob+15*0x8ed8)
before each probe, so "empty stays empty" is a true no-false-positive test (not
an artefact of zero-filling RAM).

    python3 tools/emu_pattern_led.py            # stock  -> reproduces the bug
    python3 tools/emu_pattern_led.py --patched  # fixed  -> LED-content predicate now sees p-locks

~2-3 min wall per boot.
"""
import argparse, os, pathlib, struct, sys
sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
PATCHED_IMAGE = ROOT / "out" / "mainos_patternled.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath  # noqa: E402  -- octabam's tools/ reorganized into build/harness/emu/hw/verify; this adds them to sys.path
import emu_rtos as er
import emu_card as ec

HAS_CONTENT = 0x4009a464
PAT_INIT = 0x4009abdc
PSTRIDE = 0x8ed8
AUD_STRIDE = 0x91a
MID_STRIDE = 0x8b0
AUD_PLOCK = 0x59
MID_PLOCK = 0x4900
MID_HEAD = 0x48d0        # first MIDI-track block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patched", action="store_true")
    ap.add_argument("--image", help="explicit MAIN OS section to boot (e.g. out/mainos_merged.bin)")
    args = ap.parse_args()
    if args.image:
        image = pathlib.Path(args.image)
        if not image.is_absolute():
            image = ROOT / image        # args are relative to the repo, not octabam (we chdir'd)
        tag = f"IMAGE {image.name}"
    else:
        image = PATCHED_IMAGE if args.patched else STOCK_IMAGE
        tag = "PATCHED" if args.patched else "STOCK"
    if not image.exists():
        sys.exit(f"missing {image} -- run tools/build_pattern_led.py (or build_merged.py) first")
    fixed = image != STOCK_IMAGE          # the fix is present in anything but bare stock
    print(f"=== {tag}  ({image.name}) ===")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    print(f"boot   : {r.stopped}")
    mounted, *_ , elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load   : mounted={mounted} ({elapsed:.0f} ms)")
    uc = rt.uc
    rt.run(until=lambda s: s.pc == er.MAIN_SPIN)
    blob = struct.unpack(">I", uc.mem_read(ec.PART_PTR, 4))[0]
    print(f"blob   : {blob:#x}\n")

    def spin():
        rt.run(until=lambda s: s.pc == er.MAIN_SPIN)

    def has_content(pat, bank=0):
        spin()
        return rt.call_as_main(HAS_CONTENT, args=(pat & 0xffffffff, bank & 0xffffffff))

    def reset_pat(pat):
        spin()
        rt.call_as_main(PAT_INIT, args=((blob + pat * PSTRIDE) & 0xffffffff,))

    def wr(a, d): uc.mem_write(a, d)
    def rd(a, n): return bytes(uc.mem_read(a, n))

    ok = True
    def check(label, got, want):
        nonlocal ok
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] {label}: got {got}, want {want}")

    P = 15
    pb = blob + P * PSTRIDE

    print("--- sweep all 16 patterns (DEMO; every one has audio trigs) ---")
    sweep = [has_content(p) for p in range(16)]
    print(f"  {sweep}")
    check("all 16 report content", all(v == 1 for v in sweep), True)

    print(f"\n--- reset pattern {P} to stock-empty, then probe ---")
    reset_pat(P)
    check(f"empty pattern {P} -> empty", has_content(P), 0)

    print(f"\n--- MIDI-track p-lock only (track 3, step 10), no trig anywhere ---")
    reset_pat(P)
    rec = pb + MID_PLOCK + 3 * MID_STRIDE + 10 * 0x20
    wr(rec, bytes([0x40] + [0xff] * 31))       # one param locked to 0x40
    want = 1 if fixed else 0
    check("MIDI p-lock pattern lights the grid LED", has_content(P), want)

    print(f"\n--- audio-track trigless p-lock only (track 2, step 6), no trig ---")
    reset_pat(P)
    rec = pb + 2 * AUD_STRIDE + AUD_PLOCK + 6 * 0x20
    wr(rec, bytes([0xff, 0x20] + [0xff] * 30))
    check("audio trigless-lock pattern lights the grid LED", has_content(P), want)

    print(f"\n--- MIDI note trig present (stock fast path, must be unchanged) ---")
    reset_pat(P)
    wr(pb + MID_HEAD + 4 * MID_STRIDE, b"\x00" * 7 + b"\x01")   # a trig bit in MIDI track 4
    check("MIDI trig -> content (both stock & patched)", has_content(P), 1)

    print(f"\n--- restore pattern {P}: genuinely empty again ---")
    reset_pat(P)
    check(f"pattern {P} -> empty after restore", has_content(P), 0)

    print(f"\n{tag}: {'ALL GOOD' if ok else 'FAILURES ABOVE'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

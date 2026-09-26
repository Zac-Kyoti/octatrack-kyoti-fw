#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
tools/emu_pattern_led.py, ported to octabam's NATIVE C++ ColdFire port
(`refs/octabam/tools/emu/ot_emu`) instead of route A (Unicorn + a Python
scheduler).  Same image, same card staging (`stage_card.py` calls route A's own
`stage_project`), same six assertions -- so the two are directly comparable and
the A/B is the point of this file.

    python3 tools/port_pattern_led.py            # stock  -> reproduces the bug
    python3 tools/port_pattern_led.py --patched  # fixed
    python3 tools/port_pattern_led.py --keep     # leave the steps file for reading

How it works: the whole diagnostic is emitted as a `--steps` script (the verb
list is documented at the executor in main.cpp), ot_emu runs it in ONE boot +
load, and this side parses the `step ` records and owns the assertions.  Route A
needed ~3 min for this; the port needs seconds.

⚠️ `--steps` is a Kyoti addition to ot_emu, carried in
`tools/refs/local-patches/octabam-ot-emu-steps.patch`.  A `sync.py --update
octabam` removes it -- re-apply, then `cmake --build refs/octabam/out/emu`.
"""
import argparse, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
OT_EMU = OCTABAM / "out" / "emu" / "ot_emu"
CARD = OCTABAM / "out" / "kyoti_led_card.img"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
PATCHED_IMAGE = ROOT / "out" / "mainos_patternled.bin"

# the same constants tools/emu_pattern_led.py uses
PART_PTR = 0x46C82456          # project database pointer (emu_card.PART_PTR)
HAS_CONTENT = 0x4009A464
PAT_INIT = 0x4009ABDC
PSTRIDE = 0x8ED8
AUD_STRIDE = 0x91A
MID_STRIDE = 0x8B0
AUD_PLOCK = 0x59
MID_PLOCK = 0x4900
MID_HEAD = 0x48D0
P = 15


def steps():
    """The step list, in tools/emu_pattern_led.py's exact order."""
    out, probes = [], []          # probes: (label, want-key) per `call HAS_CONTENT`
    out.append(f"ptr blob={PART_PTR:#x}")

    def spin_call(target, *args):
        out.append("spin")
        out.append("call " + ",".join([f"{target:#x}", *args]))

    def has_content(pat, label, want):
        spin_call(HAS_CONTENT, f"{pat:#x}", "0x0")
        probes.append((label, want))

    def reset_pat():
        spin_call(PAT_INIT, f"blob+{P * PSTRIDE:#x}")

    pb = f"blob+{P * PSTRIDE:#x}"

    out.append("echo sweep all 16 patterns")
    for p in range(16):
        has_content(p, f"sweep p{p}", 1)

    out.append(f"echo reset pattern {P} to stock-empty, then probe")
    reset_pat()
    has_content(P, f"empty pattern {P} -> empty", 0)

    out.append("echo MIDI-track p-lock only (track 3, step 10), no trig anywhere")
    reset_pat()
    rec = P * PSTRIDE + MID_PLOCK + 3 * MID_STRIDE + 10 * 0x20
    out.append(f"poke blob+{rec:#x}=40" + "ff" * 31)
    has_content(P, "MIDI p-lock pattern lights the grid LED", "want")

    out.append("echo audio-track trigless p-lock only (track 2, step 6), no trig")
    reset_pat()
    rec = P * PSTRIDE + 2 * AUD_STRIDE + AUD_PLOCK + 6 * 0x20
    out.append(f"poke blob+{rec:#x}=ff20" + "ff" * 30)
    has_content(P, "audio trigless-lock pattern lights the grid LED", "want")

    out.append("echo MIDI note trig present (stock fast path, must be unchanged)")
    reset_pat()
    rec = P * PSTRIDE + MID_HEAD + 4 * MID_STRIDE
    out.append(f"poke blob+{rec:#x}=" + "00" * 7 + "01")
    has_content(P, "MIDI trig -> content (both stock & patched)", 1)

    out.append(f"echo restore pattern {P}: genuinely empty again")
    reset_pat()
    has_content(P, f"pattern {P} -> empty after restore", 0)
    return out, probes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patched", action="store_true")
    ap.add_argument("--image")
    ap.add_argument("--keep", action="store_true", help="keep the generated steps file")
    a = ap.parse_args()

    if a.image:
        image = pathlib.Path(a.image)
        if not image.is_absolute():
            image = ROOT / image
        tag = f"IMAGE {image.name}"
    else:
        image = PATCHED_IMAGE if a.patched else STOCK_IMAGE
        tag = "PATCHED" if a.patched else "STOCK"
    for need, why in ((OT_EMU, "cmake --build refs/octabam/out/emu"),
                      (CARD, "tools/emu/ot_emu/stage_card.py (see the module docstring)"),
                      (image, "build it first")):
        if not need.exists():
            sys.exit(f"missing {need} -- {why}")
    fixed = image != STOCK_IMAGE
    want = 1 if fixed else 0
    print(f"=== {tag}  ({image.name})  [ot_emu, native] ===")

    lines, probes = steps()
    sf = ROOT / "out" / "steps_pattern_led.txt"
    sf.write_text("\n".join(lines) + "\n")

    cmd = [str(OT_EMU), "--image", str(image), "--card", str(CARD),
           "--set", "OCTABAM", "--project", "OT DEMO", "--steps", str(sf)]
    p = subprocess.run(cmd, cwd=OCTABAM, capture_output=True, text=True)
    if not a.keep:
        sf.unlink(missing_ok=True)

    got = [int(m, 16) for m in re.findall(r"^step call   : 0x4009a464 -> d0 = (0x[0-9a-f]+|0)$",
                                          p.stdout, re.M)]
    blob = re.search(r"^step ptr    : blob = (0x[0-9a-f]+|0)$", p.stdout, re.M)
    bad = re.findall(r"^(step (?:\?|spin|call).*(?:unknown|DID NOT|NOT PARK).*)$", p.stdout, re.M)
    print(f"blob   : {blob.group(1) if blob else 'NOT RESOLVED'}")
    if bad:
        print("\n".join("  !! " + b for b in bad))
    if len(got) != len(probes):
        print(p.stdout[-3000:], file=sys.stderr)
        sys.exit(f"expected {len(probes)} predicate results, parsed {len(got)}")

    ok = True
    sweep = got[:16]
    print("\n--- sweep all 16 patterns (DEMO; every one has audio trigs) ---")
    print(f"  {sweep}")
    ok &= _check("all 16 report content", all(v == 1 for v in sweep), True)
    for (label, w), g in list(zip(probes, got))[16:]:
        ok &= _check(label, g, want if w == "want" else w)

    ok = ok and not bad
    print(f"\n{tag}: {'ALL GOOD' if ok else 'FAILURES ABOVE'}")
    return 0 if ok else 1


def _check(label, got, want):
    good = got == want
    print(f"  [{'OK ' if good else 'FAIL'}] {label}: got {got}, want {want}")
    return good


if __name__ == "__main__":
    sys.exit(main())

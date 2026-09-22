#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Validate the trigless-lock fix by driving the REAL LIVE erase worker -- the one a
hardware trace named, not one inferred -- through stock and patched images on the user's
real ARTLTEST1 export, and diffing.

FUN_40038874(trackmask, clear_trigs, param_mask) is what opcode 8's case reaches via
FUN_40041af4 when LIVE REC is active. It takes the step from FUN_4009b2b0(track), which
reads [0x800064e0 + track] & 0x3f -- so the step is poked there, exactly as the running
sequencer would have set it, rather than passed as an argument.

ARTLTEST1: one trigless lock, bank 1 / pattern 1 / track 1 (0-indexed 0), step 6,
p-locked to PTCH (`#1` byte 0x00) and LEN (`#1` byte 0x02).

  A. erase PTCH (param_mask 1<<0) -- one of two. The step must stay lit in BOTH images.
  B. erase LEN  (param_mask 1<<2) -- the last. Stock leaves TRAC+0x10 set; patch clears it.

ARTLTEST3 is the other half of the test, and it is real hardware-exported data, not a
synthesised state: step 6 carries a trigless lock with ZERO p-locks -- exactly what
FUNC+TRIG places as a deliberate placeholder.

  C. erase a param that was never locked on that placeholder. BOTH images must leave the
     trigless-lock flag alone. An earlier build of this patch deleted it, which is why the
     detour moved onto the erase store where the pre-erase value is still readable.

    python3 tools/emu_triglock.py [project-dir]
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
PATCHED = ROOT / "out" / "mainos_triglock.bin"
DEFAULT_PROJECT = pathlib.Path.home() / "Desktop" / "ARTLTEST1"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath          # noqa: E402
import emu_rtos as er    # noqa: E402
import emu_card as ec    # noqa: E402

PAT, TRK, STEP = 0, 0, 6
ERASE_FN = 0x40038874
EDIT_STEP_TBL = 0x800064e0        # FUN_4009b2b0(track) reads [this + track] & 0x3f
LAYERS = ((0x00, "trig"), (0x08, "layerA"), (0x10, "TRIGLESS"), (0x18, "layerC"),
          (0x20, "rec1"), (0x28, "rec2"), (0x30, "rec3"))


def run(image, project):
    card, name = er.stage_project(str(project), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    trac = blob + PAT * er.PATTERN_STRIDE + TRK * er.TRAC_STRIDE

    def one():
        v = bytes(rt.uc.mem_read(trac + 0x59 + STEP * 32, 32))
        return {i: v[i] for i in range(32) if v[i] != 0xFF}

    def layers():
        out = {}
        for off, label in LAYERS:
            v = bytes(rt.uc.mem_read(trac + off, 8))
            out[label] = [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]
        return out

    loaded = one()
    if loaded != {0x00: 0x30, 0x02: 0x4e}:
        sys.exit(f"!! {image.name}: expected ARTLTEST1's two real locks, got {loaded} -- "
                 f"wrong project or the load did not take; stopping.")

    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.uc.mem_write(EDIT_STEP_TBL + TRK, bytes([STEP]))   # the step the worker will use
    step_seen = rt.call_as_main(0x4009b2b0, args=(TRK,), budget=200_000)
    if step_seen != STEP:
        sys.exit(f"!! FUN_4009b2b0({TRK}) returned {step_seen}, not {STEP} -- the worker "
                 f"would edit the wrong step and this test would be meaningless.")

    out = {"loaded": (loaded, layers()), "step_seen": step_seen}
    for tag, pmask in (("A", 1 << 0), ("B", 1 << 2)):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(ERASE_FN, args=(1 << TRK, 0, pmask), budget=2_000_000)
        out[tag] = (one(), layers())
    return out


def placeholder_run(image, project):
    """C: a real FUNC+TRIG-style empty trigless lock must survive a [NO]+knob erase."""
    card, name = er.stage_project(str(project), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    rt.load_project_live("OCTABAM", name, run_ms=6000, mount_ms=3000)
    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    trac = blob + PAT * er.PATTERN_STRIDE + TRK * er.TRAC_STRIDE

    def one():
        v = bytes(rt.uc.mem_read(trac + 0x59 + STEP * 32, 32))
        return {i: v[i] for i in range(32) if v[i] != 0xFF}

    def trigless():
        v = bytes(rt.uc.mem_read(trac + 0x10, 8))
        return [i for i in range(64) if v[7 - i // 8] & (1 << (i % 8))]

    if one() or STEP not in trigless():
        sys.exit(f"!! {project.name} is not an empty trigless lock at step {STEP} "
                 f"(locks={one()}, trigless={trigless()}) -- wrong project; stopping.")
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.uc.mem_write(EDIT_STEP_TBL + TRK, bytes([STEP]))
    before = trigless()
    rt.call_as_main(ERASE_FN, args=(1 << TRK, 0, 1 << 0), budget=2_000_000)
    return before, trigless(), one()


def fmt(st):
    locks, lay = st
    live = {k: v for k, v in lay.items() if v}
    return (f"#1[{STEP}]={ {hex(k): hex(v) for k, v in locks.items()} or 'EMPTY' }"
            f"  layers={live or 'none'}")


def main():
    project = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    if not project.exists():
        sys.exit(f"missing {project}")
    if not PATCHED.exists():
        sys.exit(f"missing {PATCHED} -- run python3 tools/build_triglock.py first")

    print(f"project: {project.name}   track {TRK}, pattern {PAT}, step {STEP}")
    print(f"driving FUN_40038874 -- the worker the hardware trace named\n")
    res = {}
    for label, image in (("stock", STOCK), ("patched", PATCHED)):
        print(f"=== {label} ({image.name}) ===")
        res[label] = run(image, project)
        print(f"  FUN_4009b2b0 -> step {res[label]['step_seen']}")
        for tag, desc in (("loaded", "as loaded (2 locks)"),
                          ("A", "after erasing PTCH (1 of 2)"),
                          ("B", "after erasing LEN (the last)")):
            print(f"  {desc:32} {fmt(res[label][tag])}")
        print()

    s, p = res["stock"], res["patched"]
    checks: list = [
        ("A: 1-of-2 erased, stock keeps the step lit",
         s["A"][0] == {0x02: 0x4e} and STEP in s["A"][1]["TRIGLESS"]),
        ("A: 1-of-2 erased, PATCH ALSO keeps it lit (multi-pass intact)",
         p["A"][0] == {0x02: 0x4e} and STEP in p["A"][1]["TRIGLESS"]),
        ("B: last erased, stock LEAVES the flag set (the bug)",
         s["B"][0] == {} and STEP in s["B"][1]["TRIGLESS"]),
        ("B: last erased, patch CLEARS the flag (the fix)",
         p["B"][0] == {} and STEP not in p["B"][1]["TRIGLESS"]),
        ("no other trig layer disturbed by the patch",
         all(p["B"][1][k] == s["B"][1][k] for _, k in LAYERS if k != "TRIGLESS")),
        ("patch leaves `#1` byte-for-byte identical to stock",
         p["A"][0] == s["A"][0] and p["B"][0] == s["B"][0]),
    ]
    # --- C: the placeholder case, on real hardware data ---
    ph = pathlib.Path.home() / "Desktop" / "ARTLTEST3"
    if ph.exists():
        print("=== C: empty trigless lock (ARTLTEST3, real FUNC+TRIG-style placeholder) ===")
        for label, image in (("stock", STOCK), ("patched", PATCHED)):
            b, a, locks = placeholder_run(image, ph)
            print(f"  {label:8} before={b}  after a [NO]+knob erase on an unlocked param -> {a}"
                  f"   #1[{STEP}]={locks or 'EMPTY'}")
            checks.append((f"C: {label} leaves the empty placeholder intact",
                           STEP in a and a == b))
        print()
    else:
        print(f"(skipping C -- {ph} not present)\n")

    print("=== verdict ===")
    for desc, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {desc}")
    bad = [d for d, ok in checks if not ok]
    print()
    if bad:
        print(f"{len(bad)} check(s) FAILED -- do not flash.")
        return 1
    print("All checks pass, driving the function the hardware trace actually implicated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

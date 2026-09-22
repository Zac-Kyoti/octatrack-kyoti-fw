#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Decode the patch_triglock_diag v3 log out of an exported bank file.

The diagnostic build records into `#1` of bank 1 / pattern 16 / track 8, which a project
save serialises to disk at offset 0x8a042 of bank01.work / bank01.strd. That RAM<->disk
mapping was verified independently against a real export (RAM TRAC(pat,trk) == disk
trac_off+9, whole 0x91a block identical for every pattern/track including (15,7)).

    python3 tools/read_triglock_log.py ~/Desktop/ARTLTEST7
    python3 tools/read_triglock_log.py ~/Desktop/ARTLTEST7/bank01.work
"""
import pathlib
import sys

PAT1, PSTRIDE, PHDR, TRAC, PLOCK = 0x16, 0x8EEC, 8, 0x922, 0x62
LOG_DISK = PAT1 + PSTRIDE * 15 + PHDR + TRAC * 7 + PLOCK      # 0x8a042
LOG_LEN = 0x150
OPHIST = 0x80
SHADOW, PREVOP, NCHG, CHGRING, CULPRIT = 0x20, 0x25, 0x26, 0x28, 0x100
WATCHED = {0: "#1[step6][param0] (PTCH)", 1: "#1[step6][param1]",
           2: "#1[step6][param2] (LEN)", 3: "#1[step6][param3]",
           4: "TRAC+0x10 steps 0-7  <- THE TRIGLESS FLAG"}

REASONS = {
    1: "not the audio bitmap (a0 != 0x46c7d48c) -- MIDI path, out of scope",
    2: "this track had NO stored p-lock at this step -- nothing was erased",
    3: "the value written was not 0xFF -- a p-lock was written, not erased",
    4: "#1[step] is not all-0xFF -- some param is still locked",
    5: "a real trig owns the step -- note / layerA / layerC / recorder",
    6: "TRAC+0x10's bit is not set -- not a trigless lock",
    7: "DELETED -- every guard passed and the flag was cleared",
}

# From the 78-entry table at 0x40061cfa (index = msg[0]-1), decoded this session.
ROUTING = {
    64: "0x40062496 -> FUN_40054cd8 (clamp) then FUN_40042158  [WRITES #1]",
    65: "0x400625b8 -> FUN_40042d1c",
    66: "0x40062640 -> FUN_40042d1c",
    70: "0x400629ee -> FUN_4004f124 (armed) / FUN_40041bc4 (LIVE)",
    74: "0x40062a56 -> FUN_4004ef54 (armed) / FUN_40041784 (LIVE)",
}


def cnt(v):
    """0xFF means the counter was never written (a fresh project is all-0xFF there)."""
    return None if v == 0xFF else v


def decode(b, label):
    log = b[LOG_DISK:LOG_DISK + LOG_LEN]
    print(f"=== {label} ===")
    if len(log) < LOG_LEN:
        print(f"  file too short for the log area ({len(b)} bytes)")
        return

    beacon = log[0:5]
    if beacon != b"KYOTI":
        print(f"  NO BEACON (found {beacon.hex(' ')}).")
        print("  The diagnostic firmware was not running when this project was saved --")
        print("  either a different image is flashed, or the project was saved on another")
        print("  unit. Nothing else in this log means anything. Re-flash")
        print("  out/OCTATRACK_OS1.40C_TRIGLOCK_DIAG.syx and repeat.")
        return
    print(f"  beacon OK (build id {log[5]}) -- the diagnostic firmware was running.")

    ops = [(i + 1, log[OPHIST + i]) for i in range(78)]
    seen = [(op, cnt(v)) for op, v in ops if cnt(v) is not None]
    print()
    print("  UI message opcodes seen (msg[0] -> count):")
    if not seen:
        print("    NONE. The dispatcher hook never ran, which contradicts the beacon --")
        print("    treat this log as broken rather than informative.")
    else:
        for op, c in seen:
            route = ROUTING.get(op, "")
            star = "  <<<<" if op in ROUTING else ""
            print(f"    {op:3d} x{c:4d}   {route}{star}")

    plock_ops = [(op, c) for op, c in seen if op in ROUTING]
    print()
    if plock_ops:
        print("  p-lock-related opcodes present:", ", ".join(str(o) for o, _ in plock_ops))
    else:
        print("  ==> NONE of the known p-lock opcodes (64/65/66/70/74) occurred. The")
        print("      gesture is routed somewhere else entirely; the opcodes listed above")
        print("      are the candidates, and their table entries name the handlers.")

    # --- the decisive part: who actually changed the data ---
    nchg = cnt(log[NCHG])
    print()
    print("  observed changes to the watched bytes"
          f" (bank 1 / pattern 1 / track 1, step 7):  {'NONE' if nchg is None else nchg}")
    if nchg is not None:
        shown = min(nchg, 8)
        print("   most recent %d, oldest first:" % shown)
        order = [(nchg - shown + i) & 7 for i in range(shown)]
        for slot in order:
            op, which, old, new = log[CHGRING + slot * 4: CHGRING + slot * 4 + 4]
            w = WATCHED.get(which, f"index {which}")
            print(f"     opcode {op:3d} changed {w:42s} {old:#04x} -> {new:#04x}")
        # the cave indexes this array BY THE OPCODE ITSELF (1-based), not opcode-1
        culp = [(i, cnt(log[CULPRIT + i])) for i in range(1, 79)]
        culp = [(o, c) for o, c in culp if c is not None]
        if culp:
            print()
            print("  CULPRIT HISTOGRAM -- opcodes whose handler changed a watched byte:")
            for o, c in culp:
                print(f"     opcode {o:3d}  x{c:4d}   {ROUTING.get(o, '(handler not yet decoded)')}")
            print()
            print("  ==> Those opcodes' table entries are the handlers to decompile. This is")
            print("      measured, not inferred: the byte changed while that message was in")
            print("      flight.")

    entries = cnt(log[8])
    reason = log[9]
    print()
    print(f"  FUN_40042158 cave entries : {'NEVER' if entries is None else entries}")
    if entries is None:
        print("  ==> That function's tail was never reached -- consistent with ARTLTEST6.")
        return
    print(f"  most recent reason        : {reason}  {REASONS.get(reason, '?')}")
    track, value, bank, pattern, step, a0lo, prebits, trackbit = log[10:18]
    print(f"  snapshot (last 0xFF store): track {track}  value {value:#04x}  bank {bank}  "
          f"pattern {pattern}  step {step}")
    print(f"    bitmap base low {a0lo:#04x} "
          f"({'audio' if a0lo == 0x8c else 'MIDI' if a0lo == 0xe4 else 'UNEXPECTED'})"
          f"   pre-bitmap {prebits:#04x} & bit {trackbit:#04x} -> "
          f"{'SET' if prebits & trackbit else 'CLEAR'}")
    print("  reason histogram:")
    for i in range(1, 8):
        c = cnt(log[18 + i])
        if c is not None:
            print(f"    {c:3d} x  [{i}] {REASONS[i]}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    p = pathlib.Path(sys.argv[1]).expanduser()
    if p.is_dir():
        targets = [p / f"bank01.{e}" for e in ("work", "strd") if (p / f"bank01.{e}").exists()]
        if not targets:
            sys.exit(f"no bank01.work / bank01.strd in {p}")
    else:
        targets = [p]
    for f in targets:
        decode(f.read_bytes(), f"{f.parent.name}/{f.name}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

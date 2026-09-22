#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 79, continued a twenty-second time. Before any further DIRECT JUMP build, the
harness has to be able to observe PLAYBACK. Two facts make the existing tooling unfit:

  1. Every dynamic run to date reports `total-fires=0` and `TRANSPORT=0`, so no build's
     playback correctness has ever actually been tested. That is how the flashed
     regression shipped.
  2. Session 79 cont.20 (commit a072eaf) showed the "fires" metric was aimed at the wrong
     instruction anyway: `0x400a536c` is reached only when a track's step counter completes
     a full cycle of its length -- a track-WRAP callback, not a per-step or per-trig event.
     A zero count there is not even evidence of silence.

So this tool does not try to prove anything about a patch. It measures, for a given image
and project, exactly how deep into the sequencer the emulator actually gets -- by counting
executions of named instructions along the per-track path, and watching the per-track STEP
array advance. The point is to establish a real, non-vacuous liveness signal that a
stock-vs-patched diff can then be built on. If the counters below are all zero, the
emulator never runs the sequencer and NO emulator-based validation of this feature means
anything; that needs to be known plainly rather than inferred from an empty green result.

Addresses are from GhidraDirectJump47/50 (commits a072eaf, 309c614), measured not assumed.

Usage:
  python3 tools/diag_seq_activity.py [--image IMG] [--project DIR] [--bank N]
                                     [--pattern N] [--frames N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

# --- per-track sequencer path, all measured (see NOTES.md Session 79 cont.20/21) ---
PCS = [
    ("audio loop top      0x400a3cd0", 0x400A3CD0),
    ("ARMED gate passed   0x400a3cda", 0x400A3CDA),
    ("TICKS_IN_STEP++     0x400a3ce2", 0x400A3CE2),
    ("step boundary (wrap)0x400a3cf6", 0x400A3CF6),
    ("STEP++              0x400a3d78", 0x400A3D78),
    ("track-wrap callback 0x400a3d98", 0x400A3D98),
    ("MIDI loop top       0x400a3df6", 0x400A3DF6),
    ("stock rebuild loop  0x400a4884", 0x400A4884),
    ("master STEP cleared 0x400a4842", 0x400A4842),
]

# per-track arrays, 16 entries each (audio 0-7 then MIDI 8-15)
STEP_ARR = 0x800064D0          # per-track STEP
TICKS_ARR = 0x800064F0         # per-track ticks-within-step
ARMED_ARR = 0x80006500
SCALE_ARR = 0x8000663E
MASTER_STEP = 0x800065B6
TRANSPORT = 0x800065B8

# Pattern blob addressing, all measured. The blob base is confirmed twice over:
# stock's own D7 setup uses 0x400eb034 for the pattern-default scale, and
# 0x400eb034 - 0x400e21e0 == 0x8e54 exactly (NOTES.md Session 79 cont.23).
BLOB_BASE = 0x400E21E0
BANK_STRIDE = 0x9B340
PAT_STRIDE = 0x8ED8
TRK_STRIDE = 0x91A          # audio track record stride; scale at +0x51, length at +0x50
MIDI_OFF = 0x48F8           # MIDI records start here; stride 0x8b0, length +0, scale +1
MIDI_STRIDE = 0x8B0
MASTER_STEPS = 0x80006628   # long: master pattern length in STEPS (D7's multiplier)
LEN_TBL = 0x400ABA50        # scale index -> TICKS PER STEP (3,4,6,8,12,24,48,96,...)


def dump_pattern(rt, bank, pat):
    """Print the pattern-level and per-track SCALE/LENGTH fields.

    SCALE_MODE (+0x8e55) decides which branch of the sequencer runs, and the
    SCALE_MODE==0 branch is the one whose out-of-bounds LEN_TBL index caused the
    flashed hardware regression -- while both validations at the time happened to use
    SCALE_MODE==1 patterns, so it never executed. Being able to see this per pattern is
    the difference between choosing a fixture and hoping one covers the case.
    """
    base = BLOB_BASE + bank * BANK_STRIDE + pat * PAT_STRIDE
    try:
        rd = lambda a, n=1: bytes(rt.uc.mem_read(a, n))
        p52, p53, p54, p55 = (rd(base + o)[0] for o in (0x8E52, 0x8E53, 0x8E54, 0x8E55))
        tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
        steps = int.from_bytes(rd(MASTER_STEPS, 4), "big")
        mscale = p52 if p55 else p54
        tps = tbl[mscale] if mscale < 12 else None
        print(f"\n=== pattern blob bank={bank} pat={pat} (base {base:#x}) ===")
        print(f"  +0x8e52 master scale (per-track mode) = {p52}")
        print(f"  +0x8e53 default LENGTH               = {p53}")
        print(f"  +0x8e54 default SCALE                = {p54}")
        print(f"  +0x8e55 SCALE_MODE                   = {p55}"
              f"   ({'PER-TRACK' if p55 else 'UNIFORM -- the regression branch'})")
        print(f"  LEN_TBL[0..11] (ticks per step)      = {tbl}")
        print(f"  master steps (0x80006628)            = {steps}")
        if tps:
            print(f"  => D7 = LEN_TBL[{mscale}] * {steps} = {tps * steps} ticks per pattern")
        print("  t   LENGTH  SCALE   (per-track records)")
        for t in range(8):
            r = base + t * TRK_STRIDE
            print(f"  {t:2d}  {rd(r + 0x50)[0]:6d}  {rd(r + 0x51)[0]:5d}")
        for t in range(8):
            r = base + MIDI_OFF + t * MIDI_STRIDE
            print(f"  {t + 8:2d}  {rd(r)[0]:6d}  {rd(r + 1)[0]:5d}")
    except Exception as e:                                   # noqa: BLE001
        print(f"\n  (pattern blob unreadable at {base:#x}: {e})")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(STOCK))
    ap.add_argument("--project", default=str(
        pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"))
    ap.add_argument("--bank", type=int, default=None)
    ap.add_argument("--pattern", type=int, default=None)
    ap.add_argument("--frames", type=int, default=1400)
    ap.add_argument("--tree", default="out/_emu_seqact")
    ap.add_argument("--scan-patterns", type=int, default=0,
                    help="dump header fields for the first N patterns and exit")
    a = ap.parse_args(argv)

    if not pathlib.Path(a.image).exists():
        sys.exit(f"missing image {a.image}")
    if not pathlib.Path(a.project).is_dir():
        sys.exit(f"missing project dir {a.project}")

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000)
    if a.bank is not None and final_bank != a.bank:
        final_bank = rt.select_bank_live(a.bank)
    pat = a.pattern if a.pattern is not None else rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    counts = {name: 0 for name, _ in PCS}

    def mk(name):
        def cb(u, addr, size, user):
            counts[name] += 1
        return cb

    for name, pc in PCS:
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(name), begin=pc, end=pc)

    # distinct values ever seen in each per-track STEP slot -- the real liveness signal:
    # a running sequencer makes these advance, and a frozen one does not.
    seen_step = [set() for _ in range(16)]
    seen_ticks = [set() for _ in range(16)]

    def sample():
        s = bytes(rt.uc.mem_read(STEP_ARR, 16))
        t = bytes(rt.uc.mem_read(TICKS_ARR, 16))
        for i in range(16):
            seen_step[i].add(s[i])
            seen_ticks[i].add(t[i])

    print(f"image   {a.image}")
    print(f"project {a.project}  bank={final_bank} pattern={pat}")
    if a.scan_patterns:
        # Looking for a pattern with SCALE_MODE=1 AND +0x8e52 != +0x8e54 -- the only
        # case that can distinguish Hook D's unconditional +0x8e54 read from stock's
        # own master-scale convention (cont.23/cont.30).
        rd = lambda ad, n=1: bytes(rt.uc.mem_read(ad, n))
        print(f"\n=== pattern header scan, bank {final_bank} ===")
        print("  pat  +8e52  +8e53(LEN)  +8e54(SCALE)  +8e55(MODE)   note")
        for q in range(a.scan_patterns):
            b = BLOB_BASE + final_bank * BANK_STRIDE + q * PAT_STRIDE
            try:
                v52, v53, v54, v55 = (rd(b + o)[0] for o in (0x8E52, 0x8E53, 0x8E54, 0x8E55))
            except Exception:
                continue
            note = ""
            if v55 and v52 != v54:
                note = "<<< SCALE_MODE=1 and 8e52 != 8e54 -- distinguishes Hook D"
            elif v55:
                note = "per-track mode"
            print(f"  {q:3d}  {v52:5d}  {v53:10d}  {v54:12d}  {v55:10d}   {note}")
        # also report per-track scale spread
        for q in range(a.scan_patterns):
            b = BLOB_BASE + final_bank * BANK_STRIDE + q * PAT_STRIDE
            sc = [rd(b + t * TRK_STRIDE + 0x51)[0] for t in range(8)]
            ln = [rd(b + t * TRK_STRIDE + 0x50)[0] for t in range(8)]
            if len(set(sc)) > 1 or len(set(ln)) > 1:
                print(f"  pat {q}: per-track SCALE={sc} LEN={ln}")
        return 0
    dump_pattern(rt, final_bank, pat)
    sample()
    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)
        sample()

    print("\n=== instruction execution counts along the per-track path ===")
    for name, _ in PCS:
        print(f"  {name:32s} {counts[name]:9d}")

    print("\n=== per-track state (16 tracks: 0-7 audio, 8-15 MIDI) ===")
    armed = bytes(rt.uc.mem_read(ARMED_ARR, 16))
    scale = bytes(rt.uc.mem_read(SCALE_ARR, 16))
    step = bytes(rt.uc.mem_read(STEP_ARR, 16))
    print("  t  ARMED SCALE STEP  distinct STEP values  distinct TICK values")
    for i in range(16):
        print(f"  {i:2d}  {armed[i]:5d} {scale[i]:5d} {step[i]:4d}  "
              f"{len(seen_step[i]):20d}  {len(seen_ticks[i]):20d}")

    ms = rt.uc.mem_read(MASTER_STEP, 1)[0]
    tp = rt.uc.mem_read(TRANSPORT, 1)[0]
    print(f"\n  master STEP={ms}  TRANSPORT={tp}  frames={rt.frame_count}")

    advancing = sum(1 for s in seen_step if len(s) > 1)
    ticking = sum(1 for s in seen_ticks if len(s) > 1)
    print(f"  tracks whose STEP advanced: {advancing}/16")
    print(f"  tracks whose TICK counter moved: {ticking}/16")

    # This is the precondition every later comparison must clear. Report it as a verdict
    # so that a vacuous run can never be mistaken for a passing one.
    if counts["audio loop top      0x400a3cd0"] == 0:
        print("\n  VERDICT: the per-track loop NEVER EXECUTED. The emulator is not running "
              "the sequencer at all; no playback claim can be made from it in this state.")
        return 2
    if advancing == 0 and ticking == 0:
        print("\n  VERDICT: the per-track loop ran but NO per-track counter ever moved. "
              "Still no usable liveness signal.")
        return 2
    print("\n  VERDICT: live sequencer activity observed -- this is a usable, non-vacuous "
          "signal for a stock-vs-patched comparison.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

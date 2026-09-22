#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Does D7 actually drive stock's per-track rebuild coherently?  (Session 79 cont.27)

Session 79 cont.26 measured D7 = 0 at an armed DIRECT JUMP commit (frame 1437, PEND=(0,1)
vs ACT=(0,0) -> ARM on the two preceding ticks), with *(long)0x80006628 = 0. With D7 = 0
both divide stages in stock's rebuild loop (0x400a4884-0x400a49e2, MIDI twin from
0x400a49e6) yield NEXT_STEP[t] = 0 and PAIR[t] = 0 for all 16 tracks -- i.e. every track is
primed to restart at step 0, which is right for a natural boundary and wrong for a jump.

That produced a hypothesis: 0x80006628 is a START OFFSET IN STEPS (normally 0), D7 is that
offset in ticks, and the loop's job is to distribute it across tracks respecting each one's
own scale and length:

    tps_t        = LEN_TBL[scale_t]                      ticks per step for this track
    q            = (D7 - 1 + tps_t) / tps_t              0x400a4912, signed
    NEXT_STEP[t] = q mod length_t                        0x400a4976 remainder, stored 0x400a497a
    PAIR[t]      = D7 - q*tps_t                          0x400a4920, stored 0x400a4924

If that is right, DIRECT JUMP is one hook: put the resume offset in 0x80006628 before the
loop runs. If it is wrong, the whole one-hook design dies here and nothing should be built.

cont.23 already died of being asserted from a plausible static chain without a runtime
check, so this does not argue from the disassembly: it OVERRIDES the D7 register at
0x400a4834 (after D7 is built, before the loop reads it) and checks the per-track arrays the
loop actually produces against the model above. No firmware bytes are modified -- this is an
emulator register poke, so it tests the hypothesis without committing to a patch.

Snapshots are taken at the right moments rather than at end-of-run, because normal per-tick
operation overwrites these arrays within a few ticks:
  - NEXT_STEP / PAIR at the first 0x400a4bbc (boundary body's audio loop top; both D7-driven
    loops have finished by then)
  - STEP / CNTDN at the first 0x400a4d36 (after the boundary body's audio+MIDI loops, which
    seed STEP[t] from NEXT_STEP[t]'s low byte at 0x400a4be6)

Usage:
  python3 tools/diag_d7_inject.py [--inject N] [--dj 0|1] [--from-pattern N] [--to-pattern N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"
STOCK = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

DJ_MODE = 0x800000D8
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
ACT_PAT, ACT_BANK = 0x800065BE, 0x800065BD
STEP_ARR, CNTDN_ARR = 0x800064D0, 0x800065C3
NEXT_STEP, PAIR_ARR, SCALE_ARR = 0x800065E4, 0x80006604, 0x8000663E
MULT_LONG = 0x80006628
LEN_TBL = 0x400ABA50
BLOB, BANK_STRIDE, PAT_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8
TRK_STRIDE, MIDI_OFF, MIDI_STRIDE = 0x91A, 0x48F8, 0x8B0

D7_PC = 0x400A4834          # D7 fully built, before the rebuild loop's cursor setup
BOUNDARY_PC = 0x400A4BBC    # boundary body audio loop top (D7 loops done)
AFTER_PC = 0x400A4D36       # after the boundary body's audio+MIDI loops


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTESTxxx"))
    ap.add_argument("--from-pattern", type=int, default=0)
    ap.add_argument("--to-pattern", type=int, default=1)
    ap.add_argument("--dj", type=int, default=1, choices=(0, 1))
    ap.add_argument("--inject", type=int, default=-1,
                    help="value to force into D7 at 0x400a4834 (-1 = observe only)")
    ap.add_argument("--pre", type=int, default=1200)
    ap.add_argument("--post", type=int, default=900)
    ap.add_argument("--tree", default="out/_emu_d7inj")
    a = ap.parse_args(argv)

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
    er_loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    final_bank = er_loaded[3]
    rt.seq_select_live(final_bank, a.from_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))

    st = dict(d7=[], nxt=None, pair=None, step=None, cntdn=None, scale=None, injected=0)

    def on_d7(u, addr, size, user):
        got = u.reg_read(er.eb.UC_M68K_REG_D7)
        mult = int.from_bytes(bytes(u.mem_read(MULT_LONG, 4)), "big")
        st["d7"].append((round(rt.frame_count), got, mult))
        if a.inject >= 0:
            u.reg_write(er.eb.UC_M68K_REG_D7, a.inject)
            st["injected"] += 1

    def on_boundary(u, addr, size, user):
        if st["nxt"] is None and st["d7"]:
            st["nxt"] = bytes(u.mem_read(NEXT_STEP, 32))
            st["pair"] = bytes(u.mem_read(PAIR_ARR, 32))
            st["scale"] = bytes(u.mem_read(SCALE_ARR, 16))

    def on_after(u, addr, size, user):
        if st["step"] is None and st["nxt"] is not None:
            st["step"] = bytes(u.mem_read(STEP_ARR, 16))
            st["cntdn"] = bytes(u.mem_read(CNTDN_ARR, 16))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_d7, begin=D7_PC, end=D7_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_boundary, begin=BOUNDARY_PC, end=BOUNDARY_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_after, begin=AFTER_PC, end=AFTER_PC)

    rt.start_transport_live()
    t = rt.frame_count + a.pre
    while rt.frame_count < t:
        rt.run(ms=60)
    rt.uc.mem_write(PEND_BANK, bytes([final_bank]))
    rt.uc.mem_write(PEND_PAT, bytes([a.to_pattern]))
    t = rt.frame_count + a.post
    while rt.frame_count < t:
        rt.run(ms=60)

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    base = BLOB + final_bank * BANK_STRIDE + a.to_pattern * PAT_STRIDE
    smode = rd(base + 0x8E55, 1)[0]
    dflt_len, dflt_scale = rd(base + 0x8E53, 1)[0], rd(base + 0x8E54, 1)[0]

    def track_fields(i):
        if i < 8:
            r = base + i * TRK_STRIDE
            ln, sc = rd(r + 0x50, 1)[0], rd(r + 0x51, 1)[0]
        else:
            r = base + MIDI_OFF + (i - 8) * MIDI_STRIDE
            ln, sc = rd(r, 1)[0], rd(r + 1, 1)[0]
        return (ln, sc) if smode else (dflt_len, dflt_scale)

    print(f"image {a.image}\nproject {a.project}  bank={final_bank} "
          f"pattern {a.from_pattern} -> {a.to_pattern}")
    print(f"DJ_MODE={a.dj}   inject={'(none)' if a.inject < 0 else a.inject}"
          f"   injections applied={st['injected']}")
    print(f"target pattern: SCALE_MODE={smode} default LEN={dflt_len} SCALE={dflt_scale}")
    print(f"LEN_TBL={tbl}")

    print("\n=== D7 observed at 0x400a4834 ===")
    for fr, got, mult in st["d7"][:8]:
        print(f"  frame {fr:6d}  D7={got:8d}  *(long)0x80006628={mult}")
    if not st["d7"]:
        print("  (never reached -- no commit ran)")
        return 2

    if st["nxt"] is None:
        print("\n  boundary body never ran after the commit -- nothing to compare")
        return 2

    d7 = a.inject if a.inject >= 0 else st["d7"][0][1]
    print(f"\n=== per-track arrays the loop produced, vs the model (D7={d7}) ===")
    print("  t  SCALE LEN  tps |  NEXT_STEP  expect |  PAIR  expect | STEP  CNTDN")
    bad = 0
    for i in range(16):
        ln, sc = track_fields(i)
        tps = tbl[sc] if sc < 12 else 0
        nx = int.from_bytes(st["nxt"][2 * i:2 * i + 2], "big", signed=True)
        pr = int.from_bytes(st["pair"][2 * i:2 * i + 2], "big", signed=True)
        if tps and ln:
            q = int((d7 - 1 + tps) / tps)        # ColdFire divsl truncates toward zero
            e_nx, e_pr = q % ln, d7 - q * tps
        else:
            e_nx = e_pr = None
        okn = (e_nx is None) or (nx == e_nx)
        okp = (e_pr is None) or (pr == e_pr)
        if not (okn and okp):
            bad += 1
        print(f"  {i:2d}  {sc:5d} {ln:3d} {tps:4d} |  {nx:9d} {str(e_nx):7s}{'' if okn else ' X'}"
              f" | {pr:5d} {str(e_pr):7s}{'' if okp else ' X'} |"
              f" {st['step'][i] if st['step'] else -1:4d}"
              f"  {st['cntdn'][i] if st['cntdn'] else -1:5d}")

    print(f"\n  tracks matching the model: {16 - bad}/16")
    if bad == 0:
        print("  => D7 drives the per-track rebuild exactly as modelled.")
        if a.inject > 0:
            print("     A non-zero D7 distributes coherently across scales and lengths,")
            print("     so 0x80006628 is the correct single lever for DIRECT JUMP.")
    else:
        print("  => MODEL MISMATCH. The one-hook design does not hold as stated;")
        print("     do not build on it.")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

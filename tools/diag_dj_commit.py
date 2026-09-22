#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
The DIRECT JUMP commit itself, observed per track across a real mid-pattern switch.

Everything validated so far has left the feature OFF. `0x400a4884` (stock's per-track
rebuild loop) executes 0 times in most runs and 8 times only when a natural pattern boundary
is crossed, and hooks A/B/C/F have never executed in the emulator at all. So the DJ-ON path
is entirely untested -- which is exactly the gap that matters, and exactly what was true when
the last build was flashed.

What this measures, and why these quantities:

Session 79 cont.21/23 established that stock already contains AR's per-track rebuild
(0x400a4884-0x400a49e2), driven by ONE input: D7 = LEN_TBL[masterScale] * masterSteps, i.e.
the pattern's whole length in ticks. Per track it writes
    NEXT_STEP[t] (0x800065e4) = ceil(D7 / ticksPerStep_t)
    PAIR[t]      (0x80006604) = D7 - NEXT_STEP[t]*ticksPerStep_t
    CNTDN_TBL[t] (0x800065c3) = LEN_TBL-difference  -- the per-track scale PHASE delay
and the boundary body then seeds STEP[t] (0x800064d0) from NEXT_STEP[t]'s low byte.

So the interesting question for a mid-pattern jump is not "did the pattern change" but
"did every track land at a coherent position for ITS OWN scale". DJTESTxxx pattern 0 has
track 1 at SCALE=0 (3 ticks/step = 2x) against SCALE=2 (6 ticks = 1x) elsewhere, so a
correct commit must leave the 2x track at twice the step index of the 1x tracks, and an
incorrect one will show up as that ratio breaking.

This tool does not assert a pass/fail verdict on correctness -- the ground truth for
"correct mid-pattern position" has not been established yet, and manufacturing one would
repeat the invented-G_ABSTICK mistake. It reports the trajectory and the cross-track
relationship so the ground truth can be established by comparison (DJ on vs DJ off vs a
natural boundary).

Usage:
  python3 tools/diag_dj_commit.py [--image IMG] [--project DIR] [--from-pattern N]
                                  [--to-pattern N] [--dj 0|1] [--pre N] [--post N]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"

DJ_MODE = 0x800000D8          # patch state word: 0 = OFF/stock, 1 = ON
G_ARMED = 0x80006A40          # patch scratch: !=0 while a jump is armed
ACT_PAT = 0x800065BE
ACT_BANK = 0x800065BD
# Hook A arms ONLY when a pattern is CUED and differs from the active one:
#   PEND_PAT != -1  &&  (PEND_PAT != ACT_PAT || PEND_BANK != ACT_BANK)
# rt.seq_select_live() calls 0x400a1030(bank,pattern), which writes ACT_PAT/ACT_BANK
# DIRECTLY and never cues -- so it can never arm DIRECT JUMP. Measured: a run driven that
# way leaves G_ARMED at 0 for its whole duration, i.e. it tests a plain pattern change and
# not the feature. Cueing these two bytes is what tapping a pattern during playback does;
# poking them here mirrors that UI effect, the same class of shortcut as poking DJ_MODE.
PEND_PAT = 0x800065C0
PEND_BANK = 0x800065BF
D7_FORMED_PC = 0x400A4834     # D7 fully built here, just before the rebuild loop's setup
MULT_LONG = 0x80006628        # D7's multiplier
MULT_SRC = 0x80006630         # what the three writers copy into it
STEP_ARR = 0x800064D0
TICKS_ARR = 0x800064F0
ARMED_ARR = 0x80006500
CNTDN_ARR = 0x800065C3
NEXT_STEP = 0x800065E4        # 2 bytes/track
PAIR_ARR = 0x80006604         # 2 bytes/track
SCALE_ARR = 0x8000663E
MASTER_STEP = 0x800065B6
MASTER_STEPS = 0x80006628     # long
REBUILD_LOOP = 0x400A4884


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTESTxxx"))
    ap.add_argument("--from-pattern", type=int, default=0)
    ap.add_argument("--to-pattern", type=int, default=1)
    ap.add_argument("--dj", type=int, default=1, choices=(0, 1))
    ap.add_argument("--pre", type=int, default=1200, help="frames before the switch request")
    ap.add_argument("--post", type=int, default=1800, help="frames after")
    ap.add_argument("--tree", default="out/_emu_djcommit")
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
    rt.seq_select_live(final_bank, a.from_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    # Arm the feature the same way emu_directjump_dynamic.py does: poke the state word
    # directly rather than driving the [PTN]+[YES] key path, whose toast/checksum/SRAM
    # side effects are irrelevant to the commit under test.
    rt.uc.mem_write(DJ_MODE, bytes([a.dj]))

    rebuild = [0]

    def on_rebuild(u, addr, size, user):
        rebuild[0] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_rebuild,
                   begin=REBUILD_LOOP, end=REBUILD_LOOP)

    # Settle D7's units by measurement. cont.23 inferred D7 = LEN_TBL[masterScale] *
    # *(long)0x80006628 = "pattern length in ticks", but sampling 0x80006628 from the main
    # loop reads 0 while NEXT_STEP reads 2 -- inconsistent with a static length. Capture the
    # actual register and both globals at the instant D7 is finished being built.
    # G_ARMED is a ONE-TICK flag: dj_a sets it to -1 on tick 1 (dja_armstep) and dj_c clears
    # it on tick 2. Sampling it from the main loop every ~166 frames (~3 ticks) will miss it
    # essentially always -- which is exactly the mistake that produced cont.25's claim that
    # the DJ path never armed. Watch the WRITES, and count the detour sites, instead.
    armed_writes = []

    def on_armed_write(u, access, addr, size, value, user):
        armed_writes.append((round(rt.frame_count), addr, size, value))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_armed_write,
                   begin=0x80006A40, end=0x80006A4B)

    # The six DIRECT JUMP detour sites, from tools/build_directjump_v4.py.
    hook_sites = {
        "dj_abstick 0x400a3fe4": 0x400A3FE4,
        "dj_a       0x400a4006": 0x400A4006,
        "dj_scaleix 0x400a4220": 0x400A4220,
        "dj_b       0x400a42fa": 0x400A42FA,
        "dj_c       0x400a4840": 0x400A4840,
        "dj_pertrk  0x400a4d36": 0x400A4D36,
    }
    hook_counts = {k: 0 for k in hook_sites}

    def mkh(name):
        def cb(u, addr, size, user):
            hook_counts[name] += 1
        return cb

    for name, pc in hook_sites.items():
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mkh(name), begin=pc, end=pc)

    # Hook A runs every step tick but was measured taking dja_disarm every single time.
    # Capture its five gate inputs AT ENTRY so the disarm reason is measured, not guessed:
    #   DJ_MODE(long)==0 | ARR_ACT!=0 | CHAIN_ACT!=0 | PEND_PAT==-1 | PEND==ACT
    ARR_ACT, CHAIN_ACT = 0x460D1AEC, 0x80006546
    gates = []

    def on_dja(u, addr, size, user):
        rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
        gates.append((round(rt.frame_count), rd(DJ_MODE, 4), rd(ARR_ACT, 4),
                      rd(CHAIN_ACT, 4), rd(PEND_PAT, 1), rd(PEND_BANK, 1),
                      rd(ACT_PAT, 1), rd(ACT_BANK, 1)))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_dja, begin=0x400A4006, end=0x400A4006)

    d7log = []

    def on_d7(u, addr, size, user):
        d7log.append((round(rt.frame_count),
                      u.reg_read(er.eb.UC_M68K_REG_D7),
                      int.from_bytes(bytes(u.mem_read(MULT_LONG, 4)), "big"),
                      int.from_bytes(bytes(u.mem_read(MULT_SRC, 4)), "big"),
                      bytes(u.mem_read(MASTER_STEP, 1))[0]))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_d7, begin=D7_FORMED_PC, end=D7_FORMED_PC)

    trace = []

    def sample(tag=""):
        rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
        trace.append(dict(
            frame=round(rt.frame_count), tag=tag,
            act_pat=rd(ACT_PAT, 1)[0], act_bank=rd(ACT_BANK, 1)[0],
            armed_flag=rd(G_ARMED, 1)[0],
            master_step=rd(MASTER_STEP, 1)[0],
            master_steps=int.from_bytes(rd(MASTER_STEPS, 4), "big"),
            step=rd(STEP_ARR, 16), ticks=rd(TICKS_ARR, 16),
            armed=rd(ARMED_ARR, 16), cntdn=rd(CNTDN_ARR, 16),
            scale=rd(SCALE_ARR, 16),
            nxt=rd(NEXT_STEP, 32), pair=rd(PAIR_ARR, 32),
            rebuild=rebuild[0]))

    print(f"image        {a.image}")
    print(f"project      {a.project}")
    print(f"DJ_MODE      {a.dj}   ({'ON' if a.dj else 'OFF (stock reference)'})")
    print(f"switch       pattern {a.from_pattern} -> {a.to_pattern} "
          f"(bank {final_bank}), requested mid-pattern")

    sample("pre-transport")
    rt.start_transport_live()

    target = rt.frame_count + a.pre
    while rt.frame_count < target:
        rt.run(ms=60)
        sample()
    sample("PRE-SWITCH")

    # CUE the target, rather than selecting it, so Hook A can actually arm.
    rt.uc.mem_write(PEND_BANK, bytes([final_bank]))
    rt.uc.mem_write(PEND_PAT, bytes([a.to_pattern]))
    sample("CUED")

    target = rt.frame_count + a.post
    while rt.frame_count < target:
        rt.run(ms=60)
        sample()
    sample("END")

    print(f"\n=== timeline (rebuild-loop executions cumulative) ===")
    print("  frame  tag           ACT_PAT G_ARMED mSTEP mSTEPS rebuild  "
          "STEP[0] STEP[1] STEP[2]  SCALE[0..2]")
    prev_pat = None
    for t in trace:
        mark = ""
        if prev_pat is not None and t["act_pat"] != prev_pat:
            mark = "   <<< ACT_PAT CHANGED"
        prev_pat = t["act_pat"]
        if t["tag"] or mark or t is trace[-1]:
            pass
        print(f"  {t['frame']:6d}  {t['tag']:13s} {t['act_pat']:7d} {t['armed_flag']:7d} "
              f"{t['master_step']:5d} {t['master_steps']:6d} {t['rebuild']:7d}  "
              f"{t['step'][0]:7d} {t['step'][1]:7d} {t['step'][2]:7d}  "
              f"{t['scale'][0]},{t['scale'][1]},{t['scale'][2]}{mark}")

    last = trace[-1]
    print(f"\n=== final per-track state ===")
    print("  t  SCALE ARMED STEP TICKS CNTDN  NEXT_STEP  PAIR")
    for i in range(16):
        nx = int.from_bytes(last["nxt"][2 * i:2 * i + 2], "big")
        pr = int.from_bytes(last["pair"][2 * i:2 * i + 2], "big")
        print(f"  {i:2d}  {last['scale'][i]:5d} {last['armed'][i]:5d} "
              f"{last['step'][i]:4d} {last['ticks'][i]:5d} {last['cntdn'][i]:5d}  "
              f"{nx:9d}  {pr:5d}")

    print("\n=== DIRECT JUMP detour sites reached ===")
    for name in hook_sites:
        print(f"  {name:24s} {hook_counts[name]:8d}")

    print(f"\n=== writes to the patch's scratch globals 0x80006a40..4b "
          f"({len(armed_writes)} total) ===")
    print("  G_ARMED 0x80006a40 | G_STEP ..41 | G_PCPAT ..42 | G_ABSTICK ..46 | "
          "G_JUST_COMMITTED ..4a")
    for fr, ad, sz, val in armed_writes[:24]:
        if ad == 0x80006A46:            # G_ABSTICK ticks every step; not interesting here
            continue
        print(f"  frame {fr:6d}  [{ad:#010x}] size={sz} <- {val & 0xFFFFFFFF:#x}")
    nz = [w for w in armed_writes if w[1] != 0x80006A46]
    print(f"  ({len(nz)} writes outside G_ABSTICK)")
    if not nz:
        print("  NONE -- the DIRECT JUMP arm/commit path did not run at all.")

    print("\n=== Hook A gate inputs at entry (why it arms or disarms) ===")
    print("   frame   DJ_MODE     ARR_ACT   CHAIN_ACT  PEND(b,p)  ACT(b,p)   verdict")
    for fr, dj, arr, ch, pp, pb, ap, ab in gates:
        if dj == 0:
            why = "DISARM: DJ_MODE==0"
        elif arr:
            why = "DISARM: arranger active"
        elif ch:
            why = "DISARM: chain active"
        elif pp == 0xFF:
            why = "DISARM: nothing cued"
        elif pp == ap and pb == ab:
            why = "DISARM: cue == active"
        else:
            why = "ARM"
        print(f"  {fr:6d}  {dj:#010x} {arr:#010x} {ch:#010x}   "
              f"({pb},{pp})     ({ab},{ap})    {why}")

    print("\n=== D7 at formation (0x400a4834) -- settles D7's units by measurement ===")
    if not d7log:
        print("  (never reached -- no commit ran through the D7 setup)")
    for fr, d7, mult, src, ms in d7log[:12]:
        print(f"  frame {fr:6d}  D7={d7:8d}  *(long)0x80006628={mult:6d}  "
              f"*(long)0x80006630={src:6d}  masterSTEP={ms}")
    if len(d7log) > 12:
        print(f"  ... {len(d7log) - 12} more")

    print(f"\n  rebuild-loop executions: {rebuild[0]}"
          f"   (8 per commit -- 0 means no commit happened at all)")
    print(f"  ACT_PAT: {trace[0]['act_pat']} -> {last['act_pat']}"
          f"   ({'SWITCHED' if last['act_pat'] != trace[0]['act_pat'] else 'NO SWITCH'})")

    # Cross-track scale coherence. On DJTESTxxx pattern 0, track 1 is 2x the others, so a
    # coherent commit keeps its step index at roughly twice theirs. Reported, not asserted:
    # the ground truth for a mid-pattern position is not yet established.
    ref = [last["step"][i] for i in range(16) if last["scale"][i] == 2]
    odd = [(i, last["step"][i], last["scale"][i])
           for i in range(16) if last["scale"][i] != 2]
    if ref and odd:
        import statistics
        m = statistics.median(ref)
        print(f"\n  1x-track (SCALE=2) median STEP = {m}")
        for i, st, sc in odd:
            print(f"  track {i} SCALE={sc} STEP={st}"
                  f"   ratio vs 1x median = {st / m if m else float('nan'):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

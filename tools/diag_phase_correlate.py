#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 89: per commit -- was it ARMED, did Hook S run, and did the track re-phase?

V5.4 stopped the re-phase at armed commits (t42, t147) but not at t90/t189/t201/t255. Two
very different situations are consistent with that, and only a correlation tells them apart:

  (a) those commits ARE armed and Hook S is not reaching them  -> a gating bug, ours
  (b) those commits are NATURAL master-cycle boundaries        -> stock re-phases on EVERY
      wrap at non-1x, a bigger and separate problem

So for every commit this tags: armed (djc_fix executed), Hook S executed (djs3_loop), what
0x400a354a wrote into TICKS_IN_STEP[0], and the track's advance congruence class after it.

Cave symbol addresses are read from the built ELF so they cannot drift from the image.

Usage: python3 tools/diag_phase_correlate.py --project DIR --pattern N --to-pattern M
"""
import argparse
import bisect
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
V5 = ROOT / "out" / "mainos_directjump_v5.bin"
ELF = ROOT / "out" / "patch_directjump_v5.elf"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
TAIL_PC, ADV_PC, CATCHUP_COPY_PC = 0x400A4BE6, 0x400A3D78, 0x400A354A
STEP_ARR, TICKS_ARR = 0x800064D0, 0x800064F0
TRK_SCALE_IX, LEN_TBL = 0x8000663E, 0x400ABA50
SCRATCH_LO, SCRATCH_HI = 0x80006A40, 0x80006A60
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF


def sym(name):
    out = subprocess.run(["m68k-elf-nm", "-n", str(ELF)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--jumps", type=int, default=6)
    ap.add_argument("--gap", type=int, default=53)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=400)
    # resolved to absolute because attach() runs after os.chdir(OCTABAM) -- the same trap
    # diff_stock_vs_patch.py hit in Session 97
    ap.add_argument("--image", default=str(V5),
                    type=lambda p: str(pathlib.Path(p).resolve()))
    a = ap.parse_args(argv)

    # Session 99: pair the ELF to the image, or the cave-symbol hooks land at ANOTHER
    # build's addresses and the armed? column silently lies (the diag build's cave
    # layout differs from mainline V5's).
    global ELF
    cand = pathlib.Path(a.image).with_name(
        "patch_directjump_" + pathlib.Path(a.image).stem.split("_")[-1] + ".elf")
    if cand.exists():
        ELF = cand
    print(f"cave symbols from: {ELF.name}")

    ARMED_PC, HOOKS_PC = sym("djc_fix"), sym("djs3_loop")
    print(f"djc_fix=0x{ARMED_PC:x}  djs3_loop="
          f"{'0x%x' % HOOKS_PC if HOOKS_PC else 'ABSENT (Hook S not in this build)'}")

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"{pathlib.Path(a.image).stem}_{pathlib.Path(a.project).name}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_pc_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1).to_bytes(4, "big"))
    rt.uc.mem_write(SCRATCH_LO, bytes([0xAA]) * (SCRATCH_HI - SCRATCH_LO))

    st = dict(tick=0, njump=0, commits=[], armed=set(), hooks=set(), adv=[], catch=[])
    targets = [a.to_pattern, a.pattern]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["njump"] += 1

    def snap_at_commit(u):
        rd = lambda ad, n: bytes(u.mem_read(ad, n))
        return dict(pair=int.from_bytes(rd(0x80006604, 2), "big"),
                    rem=rd(0x80006A41, 1)[0],
                    catchup=rd(0x800065D3, 1)[0])

    def on_armed(u, addr, size, user):
        st["armed"].add(st["tick"])

    def on_hooks(u, addr, size, user):
        st["hooks"].add(st["tick"])

    def on_write(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if addr == STEP_ARR:
            if pc == TAIL_PC and (not st["commits"] or st["commits"][-1] != st["tick"]):
                st["commits"].append(st["tick"])
                st.setdefault("snap", {})[st["tick"]] = snap_at_commit(u)
            elif pc == ADV_PC:
                st["adv"].append(st["tick"])
        elif addr == TICKS_ARR and pc == CATCHUP_COPY_PC:
            st["catch"].append((st["tick"], value & 0xFF))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_armed, begin=ARMED_PC, end=ARMED_PC)
    if HOOKS_PC:
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hooks, begin=HOOKS_PC, end=HOOKS_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=STEP_ARR, end=STEP_ARR)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=TICKS_ARR, end=TICKS_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    tsc = bytes(rt.uc.mem_read(TRK_SCALE_IX, 1))[0]
    tps = int.from_bytes(bytes(rt.uc.mem_read(LEN_TBL + 4 * tsc, 4)), "big")
    catch = dict(st["catch"])
    buckets = {}
    for tk in st["adv"]:
        buckets.setdefault(bisect.bisect_right(st["commits"], tk), []).append(tk)
    cls = {k: sorted({t % tps for t in v}) for k, v in buckets.items()}

    # THE REQUIRED VALUE: if the track last advanced at A (its counter reset to 0 there),
    # then at commit tick C its counter must read (C - A) mod tps to keep the same grid.
    # Compute that, then see which available quantity equals it -- rather than proposing.
    adv = st["adv"]
    print(f"\ntrack 0 tps={tps}; commits={st['commits']}")
    print(f"\n{'commit':>7} {'prevAdv':>8} {'REQUIRED':>9} {'PAIR':>5} {'rem':>4} "
          f"{'catchup':>8} {'0x354a':>7}  match?")
    for c in st["commits"]:
        i = bisect.bisect_left(adv, c) - 1
        if i < 0:
            continue
        A = adv[i]
        req = (c - A) % tps
        sn = st.get("snap", {}).get(c, {})
        pr, rm, cu = sn.get("pair"), sn.get("rem"), sn.get("catchup")
        got = catch.get(c)
        cands = []
        if pr is not None and pr % tps == req: cands.append("PAIR")
        if rm is not None and rm % tps == req: cands.append("rem")
        if pr is not None and rm is not None and (pr + rm) % tps == req: cands.append("PAIR+rem")
        if cu is not None and cu % tps == req: cands.append("catchup")
        print(f"{c:7d} {A:8d} {req:9d} {str(pr):>5} {str(rm):>4} {str(cu):>8} "
              f"{str(got):>7}  {','.join(cands) if cands else 'NONE of them'}")
    print(f"{'commit':>7} {'armed?':>7} {'HookS?':>7} {'0x400a354a wrote':>17} "
          f"{'class after':>12} {'re-phased?':>11}")
    prev = cls.get(0)
    for i, c in enumerate(st["commits"], start=1):
        after = cls.get(i)
        rp = "" if after is None or prev is None else ("YES" if after != prev else "no")
        print(f"{c:7d} {('YES' if c in st['armed'] else 'no'):>7} "
              f"{('YES' if c in st['hooks'] else 'no'):>7} "
              f"{str(catch.get(c, '--')):>17} {str(after):>12} {rp:>11}")
        if after is not None:
            prev = after
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

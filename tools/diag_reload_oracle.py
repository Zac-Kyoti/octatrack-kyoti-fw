#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
The re-phase oracle for RELOAD_FROM_PROJECT (emulator, 2026-11-08): a reload that changes the
pattern's own length lands on the next step with the master and every track placed where the SAVED
pattern would be had it played since the master cycle began. The oracle is that run itself.

  --role reference   pattern 1 of OT DEMO set to NORMAL, length --saved (in RAM), PLAY from the start
  --role candidate   the same, SAVE PROJECT (the card holds --saved), then the length --edit, PLAY,
                     and [PTN] + [TRACK 1] at tick --at (a NORMAL track reload brings the length back)

Each run writes a per-tick log (phase D's entry 0x400a1f72: the master step and tick, every track's
STEP / STEP-1 / TICKS / scale cache) and every step the scheduler builds (stock's step handlers
0x4009d1e8 / 0x4009cf4c: track, step). --compare REF CAND: from the candidate's landing tick on, both
must match tick for tick.

  python3 tools/diag_reload_oracle.py --role reference --out out/oracle_ref.json --image IMG --elf ELF \
      --project DIR --name NAME [--saved 12] [--ticks 200]
  python3 tools/diag_reload_oracle.py --role candidate --out out/oracle_cand.json ... [--edit 16] [--at 40]
  python3 tools/diag_reload_oracle.py --compare out/oracle_ref.json out/oracle_cand.json
"""
import argparse, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY, SAVE_PROJECT = 0x40031734, 0x40022850
PHASE_D, STEP_A, STEP_M = 0x400A1F72, 0x4009D1E8, 0x4009CF4C
BLOB, BANKSTRIDE, PATSTRIDE = 0x400E21E0, 0x9B340, 0x8ED8
MSTEP, TICK_CTR, SCALE_IX = 0x800065B2, 0x800065B6, 0x8000663D
STEP_ARR, STEPM1_ARR, TICKS_ARR, TSCALE_ARR = 0x800064D0, 0x800064E0, 0x800064F0, 0x8000663E
PTN = 0x2E


def compare(ref_p, cand_p):
    ref, cand = json.loads(pathlib.Path(ref_p).read_text()), json.loads(pathlib.Path(cand_p).read_text())
    L = cand["landed"]
    if L is None:
        sys.exit("the candidate never landed")
    rs, cs = {s["t"]: s for s in ref["states"]}, {s["t"]: s for s in cand["states"]}
    rb, cb = {}, {}
    for t, trk, step in ref["built"]:
        rb.setdefault(t, set()).add((trk, step))
    for t, trk, step in cand["built"]:
        cb.setdefault(t, set()).add((trk, step))
    last = min(max(rs), max(cs))
    print(f"landed at tick {L} (master step {cand['landed_ms']}); comparing ticks {L + 1}..{last}")
    bad = []
    for t in range(L + 1, last + 1):
        a, b = rs.get(t), cs.get(t)
        if a is None or b is None:
            continue
        for k in ("ms", "tc", "sc", "step", "stepm1", "ticks", "tscale"):
            if a[k] != b[k]:
                bad.append((t, k, a[k], b[k]))
        if rb.get(t, set()) != cb.get(t, set()):
            bad.append((t, "built", sorted(rb.get(t, set())), sorted(cb.get(t, set()))))
    pre = [t for t in range(1, L) if rs.get(t) and cs.get(t) and rs[t]["step"] != cs[t]["step"]]
    print(f"  before the landing the runs differ on {len(pre)} ticks (expected: the edited length)")
    if bad:
        print(f"  FAIL: {len(bad)} differences after the landing; the first ones:")
        for x in bad[:12]:
            print("   ", x)
        print("VERDICT: FAIL")
        return 1
    built = sum(len(v) for t, v in cb.items() if t > L)
    print(f"  identical: every tick's counters and all {built} steps built after the landing")
    print("VERDICT: PASS")
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--role", choices=("reference", "candidate"))
    ap.add_argument("--out")
    ap.add_argument("--image", type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--elf", type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name")
    ap.add_argument("--saved", type=int, default=12)
    ap.add_argument("--edit", type=int, default=16)
    ap.add_argument("--at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=200)
    a = ap.parse_args(argv)
    if a.compare:
        return compare(*a.compare)
    out = pathlib.Path(a.out).resolve()
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name,
                                    tree=f"out/_emu_reload_oracle_{a.role}{a.at}_{pathlib.Path(a.image).stem}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def key(code, ev):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY, args=(code, ev), budget=600000)

    if rd(0x80000012, 4):
        key(0x35, 1); key(0x35, 0)
    act = rd(0x800065BE, 1)
    sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
    u.mem_write(sl + 0x8E55, b"\x00")                       # NORMAL
    u.mem_write(sl + 0x8E53, bytes([a.saved]))
    if a.role == "candidate":
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SAVE_PROJECT, budget=600000)
        rt.run(ms=8000)                                     # the card: NORMAL, --saved steps
        u.mem_write(sl + 0x8E53, bytes([a.edit]))           # live: --edit steps
    print(f"{a.role}: bank {bank + 1} pattern {act + 1}, NORMAL, length {rd(sl + 0x8E53, 1)}, "
          f"scale {rd(sl + 0x8E54, 1)}", flush=True)

    st = dict(t=0, states=[], built=[], landed=None, landed_ms=None)

    def on_d(uc, ad, sz, ud):
        st["t"] += 1
        st["states"].append(dict(t=st["t"], ms=rd(MSTEP, 2), tc=rd(TICK_CTR, 1), sc=rd(SCALE_IX, 1),
                                 step=list(u.mem_read(STEP_ARR, 16)), stepm1=list(u.mem_read(STEPM1_ARR, 16)),
                                 ticks=list(u.mem_read(TICKS_ARR, 16)), tscale=list(u.mem_read(TSCALE_ARR, 16))))

    def on_step(uc, ad, sz, ud, midi=False):
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        trk = rd(sp + 4, 4) + (8 if midi else 0)
        st["built"].append([st["t"], trk, rd(sp + 16, 4)])

    def on_put(uc, ad, sz, ud):
        if st["landed"] is None:
            st["landed"], st["landed_ms"] = st["t"], rd(MSTEP, 2)

    u.hook_add(er.eb.UC_HOOK_CODE, on_d, begin=PHASE_D, end=PHASE_D)
    u.hook_add(er.eb.UC_HOOK_CODE, on_step, begin=STEP_A, end=STEP_A)
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: on_step(uc, ad, sz, ud, True), begin=STEP_M, end=STEP_M)
    if a.role == "candidate":
        u.hook_add(er.eb.UC_HOOK_CODE, on_put, begin=syms["rl_put"], end=syms["rl_put"])
    rt.seq_select_live(bank, act)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    pressed = False
    while st["t"] < a.ticks:
        if a.role == "candidate" and not pressed and st["t"] >= a.at:
            pressed = True
            print(f"  [PTN] + [TRACK 1] at tick {st['t']}", flush=True)
            key(PTN, 1); key(0x10, 1); key(0x10, 0); key(PTN, 0)
        t0 = st["t"]
        rt.run(ms=17)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(0x40056C28, budget=600000)          # the UI tick (route A runs none)
        if st["t"] == t0 and rt.sample > 1e12:
            break
    print(f"  {st['t']} ticks; landed at {st['landed']}; length now {rd(sl + 0x8E53, 1)}", flush=True)
    out.write_text(json.dumps(st))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

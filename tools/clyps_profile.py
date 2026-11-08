#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS -- CPU cost in the emulator (the user, 2026-11-07: "cycles / performance" for the stats).

The emulator models the CPU at `ips` instructions per audio sample (3,990 x 44,100 = ~176 M/s). Measured:
  * Clyps' own code (the DRAM unit's Clyps part): instructions per emulated second and per sequencer tick
    (phase D, 0x400a1f72, Clyps' landing site), the peak tick, by state -- stopped, playing with Clyps closed /
    open, and the landing of each kind of load;
  * what Clyps hands stock's memcpy (0x40020898, ~0.375 instructions a byte: 4 longs per 6 instructions),
    called from Clyps' code (its return address in the range), per tick;
  * UI-side work per call, every instruction counted (stock's text / rect routines included): a full Clyps
    redraw (cl_draw), the tab hook (cl_tabhook) with and without a group, stock's tab painters with Clyps'
    active-track tests in them.
Route A runs no UI redraw pass or UI tick of its own, so the UI-side costs are per call, not per second.

  python3 tools/clyps_profile.py --image out/clyps/mainos_cl21.bin --syms out/clyps/kyoti_cl21_syms.txt \\
      --project ~/Desktop/OT\\ Backup/KYOTI/OT\\ DEMO
"""
import argparse
import bisect
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
PHASE_D, MEMCPY = 0x400A1F72, 0x40020898
PTN, BANK, NO, FUNC, PAGE, CUE = 0x2E, 0x2F, 0x32, 0x2D, 0x1B, 0x2A
BLOB, BANKSTRIDE, PATSTRIDE = 0x400E21E0, 0x9B340, 0x8ED8


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--syms", required=True)
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", default="CLPROF")
    a = ap.parse_args(argv)
    image = str(pathlib.Path(a.image).resolve())
    syms = {k: int(v, 16) for k, v in (l.split() for l in pathlib.Path(a.syms).read_text().splitlines())}
    lo, hi = syms["cl_ptn"], syms["cl_bss"]
    lo = min(v for k, v in syms.items() if k.startswith("cl_") and 0x40a00000 <= v < hi)
    names = sorted((v, k) for k, v in syms.items() if lo <= v < hi)
    addrs = [v for v, _ in names]
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_clyps_prof_{a.name}")
    r, rt = er.attach(image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000)
    rt.run(ms=300)
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    IPS_S = 3990.0 * 44100

    st = {"on": False, "ex": 0, "fn": collections.Counter(), "ticks": 0, "tick_ex": 0, "tick_mc": 0,
          "peak_ex": 0, "peak_mc": 0, "mc": 0}

    def on_code(uc, ad, sz, ud):
        if st["on"]:
            st["ex"] += 1
            st["tick_ex"] += 1
            i = bisect.bisect_right(addrs, ad) - 1
            if i >= 0:
                st["fn"][names[i][1]] += 1

    def on_tick(uc, ad, sz, ud):
        if st["on"]:
            st["ticks"] += 1
            st["peak_ex"] = max(st["peak_ex"], st["tick_ex"])
            st["peak_mc"] = max(st["peak_mc"], st["tick_mc"])
            st["tick_ex"] = st["tick_mc"] = 0

    def on_mc(uc, ad, sz, ud):
        if st["on"]:
            sp_ = uc.reg_read(er.eb.UC_M68K_REG_A7)
            if lo <= rd(sp_, 4) < hi:
                n_ = rd(sp_ + 12, 4)
                st["mc"] += n_
                st["tick_mc"] += n_

    u.hook_add(er.eb.UC_HOOK_CODE, on_code, begin=lo, end=hi - 1)
    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=PHASE_D, end=PHASE_D)
    u.hook_add(er.eb.UC_HOOK_CODE, on_mc, begin=MEMCPY, end=MEMCPY)

    def call(addr, *args):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        return rt.call_as_main(addr, args=args, budget=4_000_000)

    def key(code, ev):
        if ev and 0x10 <= code <= 0x17:
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))
        call(SET_KEY, code, ev)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        u.mem_write(er.SYS_MSG_SCRATCH, bytes([0, 0]))
        rt.post_message(er.SYS_QUEUE, er.SYS_MSG_SCRATCH)
        rt.run(ms=60)

    def tap(code):
        key(code, 1)
        key(code, 0)

    rows = []

    def measure(label, ms, action=None):
        st.update(on=True, ex=0, fn=collections.Counter(), ticks=0, tick_ex=0, tick_mc=0, peak_ex=0, peak_mc=0, mc=0)
        s0 = rt.sample
        if action:
            action()
        rt.run(ms=ms)
        st["on"] = False
        secs = (rt.sample - s0) / 44100.0
        mc_i = st["mc"] * 0.375
        tot = st["ex"] + mc_i
        top = ", ".join(f"{k} {v:,}" for k, v in st["fn"].most_common(4))
        rows.append((label, secs, st["ex"], st["mc"], st["ticks"], st["peak_ex"], st["peak_mc"], tot / max(secs, 1e-9)))
        print(f"  {label}: {secs:.2f} s, Clyps code {st['ex']:,} instr + memcpy {st['mc']:,} B (~{mc_i:,.0f} instr); "
              f"{tot / max(secs, 1e-9):,.0f} instr/s = {100 * tot / max(secs, 1e-9) / IPS_S:.4f} % of the CPU model; "
              f"ticks {st['ticks']}, peak tick: {st['peak_ex']:,} instr + {st['peak_mc']:,} B memcpy; top: {top}",
              flush=True)

    def inclusive(label, fn, *args):
        cnt = [0]
        h = u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: cnt.__setitem__(0, cnt[0] + 1), begin=0, end=0xFFFFFFFF)
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(fn, args=args, budget=4_000_000)
        u.hook_del(h)
        print(f"  {label}: {cnt[0]:,} instructions (all code, one call)", flush=True)
        rows.append((label, None, cnt[0]))

    print("stopped, Clyps closed")
    measure("stopped, closed", 1000)
    act = rd(0x800065BE, 1)
    bank = rd(0x800065BD, 1)
    sl = BLOB + bank * BANKSTRIDE + act * PATSTRIDE
    q0 = rd(sl + 0x8E56, 1)
    u.mem_write(sl + 0x8E56, bytes([1]))            # CHAIN AFTER 1 step: loads land at the next step
    rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=300)
    print(f"playing (pattern {act + 1}, bank {bank}), Clyps closed")
    measure("playing, closed", 2000)
    key(PTN, 1)
    key(BANK, 1)
    key(BANK, 0)
    key(PTN, 0)
    measure("playing, open, idle", 2000)
    q = (act + 1) % 16
    measure(f"playing: trig {q + 1} (TRK SEQ) + its landing", 1500, lambda: tap(q))
    def full():
        key(FUNC, 1)
        tap((q + 1) % 16)
        key(FUNC, 0)
    measure(f"playing: [FUNC]+trig {(q + 1) % 16 + 1} (TRK FULL) + landing", 1500, full)
    def grp():
        key(CUE, 1)
        for t in (0x10, 0x11, 0x12):
            tap(t)
        key(CUE, 0)
        tap((q + 2) % 16)
    measure("playing: group T1-T3 + trig (3 loads) + landings", 1500, grp)
    tap(NO)
    def orig():
        key(PTN, 1)
        key(BANK, 1)
        tap(PAGE)
        key(BANK, 0)
        key(PTN, 0)
    measure("playing: ORIG PTN+PRT (the self-switch) + landing", 2500, orig)
    tap(NO)
    key(0x27, 1)
    key(0x27, 0)
    rt.run(ms=300)
    u.mem_write(sl + 0x8E56, bytes([q0]))
    rt.frame = False
    print("UI side, per call (every instruction counted)")
    key(PTN, 1)
    key(BANK, 1)
    key(BANK, 0)
    key(PTN, 0)
    inclusive("cl_draw (a full Clyps redraw, open)", syms["cl_draw"])
    inclusive("cl_tabhook, no group (incl. stock's mark painter)", syms["cl_tabhook"])
    inclusive("stock mark painter 0x40044804 alone", 0x40044804)
    key(CUE, 1)
    tap(0x11)
    tap(0x12)
    tap(0x13)
    key(CUE, 0)
    inclusive("cl_tabhook, group of 3 (2 outlines)", syms["cl_tabhook"])
    inclusive("stock upper tab painter 0x4003fed8 (Clyps' tests inside)", 0x4003FED8)
    inclusive("stock lower tab painter 0x4004bd48 (Clyps' tests inside)", 0x4004BD48)
    tap(NO)
    tap(NO)


if __name__ == "__main__":
    main(sys.argv[1:])

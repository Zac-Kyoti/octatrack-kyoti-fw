#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS phase 1 -- the landing oracle, recorder half (reference/handoffs/CLYPS_SCOPE.md §3.4, §7).

Question: at which point must a one-track record copy happen so that the track plays exactly
as it would after a stock pattern change to a pattern that differs from the playing one in
that track only?

    B (reference): PLAY on P, cue a stock change to Q at tick K, where Q = P with track T
                   replaced by S's track T (built in RAM after the load, --copypat/--copytrk,
                   exactly what stock's pattern copy and track paste do -- no file is written).
    A (candidate): PLAY on P, and from tick K on, copy S's track T into P's track T the first
                   time the code at --clyp-pc runs (hook fires BEFORE that instruction).
    PASS: from the landing on, A's engine state and live events equal B's (cmp_clyps.py).

The recorder is diag_reflock.py's (states sampled at phase-G entry 0x400a3fdc, event
tables, builder calls); only the setup and the harness-side copy are new.

Usage:
  python3 tools/diag_clyps_landing.py --project DIR --name NAME --info --out X.json
  python3 tools/diag_clyps_landing.py --project DIR --name NAME --start P \
      [--copypat DST:SRC] [--copytrk DST:SRC:T] [--cue K:Q] \
      [--clyp K:S:T --clyp-pc 0x400a43a0] --ticks N --tag TAG --out out/clyps_X.json
Tracks T: 0-7 audio, 8-15 MIDI. Patterns are 0-based. Bank = the bank the project loads into.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

BLOB, BANKSTRIDE, PATSTRIDE = 0x400E21E0, 0x9B340, 0x8ED8
TRAC_A, MIDI_BASE, TRAC_M = 0x91A, 0x48D0, 0x8B0
DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
FIRE_TBL, FIRE_END = 0x80001904, 0x80001904 + 8 * 8 * 4
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
STEP_ARR = 0x800064D0
LAND_PC, TAIL_PC = 0x400A20DE, 0x400A4BE6
EV_TABLES = {"a": (0x80001904, 0x46C7FE44), "b": (0x80001984, 0x46C7FE8C),
             "m": (0x46C76A26, 0x46C77BE2)}
BUILDER_A, BUILDER_A_RET = 0x4009D1E8, 0x400A2D82
BUILDER_M, BUILDER_M_RET = 0x4009CF4C, 0x400A39CA
SCALARS = {
    "act_bank": (0x800065BD, 1), "act_pat": (0x800065BE, 1), "pend_pat": (0x800065C0, 1),
    "m_step": (0x800065B2, 2), "m_tick": (0x800065B6, 1), "scale_ix": (0x8000663D, 1),
    "ff_mask": (0x80006624, 2), "hold_mask": (0x80006626, 2),
    "met_run": (0x80006510, 1), "met_beat": (0x80006511, 1), "met_tick": (0x80006512, 1),
    "sclk": (0x4610757C, 4),
}
ARRAYS = {"step": 0x800064D0, "step_m1": 0x800064E0, "ticks": 0x800064F0, "armed": 0x80006500,
          "cntdn": 0x800065C3, "reload": 0x800065D3, "trk_scale": 0x8000663E}


def slab(bank, pat):
    return BLOB + bank * BANKSTRIDE + pat * PATSTRIDE


def trk_span(t):
    return (t * TRAC_A, TRAC_A) if t < 8 else (MIDI_BASE + (t - 8) * TRAC_M, TRAC_M)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(IMAGE), type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True, help="staged project name (no spaces)")
    ap.add_argument("--info", action="store_true", help="dump the bank's pattern settings and exit")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--copypat", action="append", default=[], help="DST:SRC whole-slab copy")
    ap.add_argument("--copytrk", action="append", default=[], help="DST:SRC:T track-record copy")
    ap.add_argument("--cue", action="append", default=[], help="K:Q stock cue written at tick K")
    ap.add_argument("--setb", action="append", default=[],
                    help="PAT:OFF=VAL poke one pattern-slab byte after the copies (e.g. 14:0x8e56=4)")
    ap.add_argument("--clyp", default="", help="K:S:T harness clyp armed at tick K")
    ap.add_argument("--clyp-pc", type=lambda v: int(v, 0), default=0x400A43A0)
    ap.add_argument("--dj", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=300)
    ap.add_argument("--tag", default="clyps")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_{a.tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    u = rt.uc

    def rd(addr, n):
        return int.from_bytes(bytes(u.mem_read(addr, n)), "big")

    if a.info:
        rows = []
        for p in range(16):
            s = slab(bank, p)
            mlen = rd(s + 0x8E50, 2)
            rows.append(dict(
                pat=p, mlen=mlen - 0x10000 if mlen & 0x8000 else mlen, mscale=rd(s + 0x8E52, 1),
                plen=rd(s + 0x8E53, 1), pscale=rd(s + 0x8E54, 1), mode=rd(s + 0x8E55, 1),
                change=rd(s + 0x8E56, 1), part=rd(s + 0x8E57, 1),
                tlen=[rd(s + trk_span(t)[0] + 0x50, 1) for t in range(8)],
                tscale=[rd(s + trk_span(t)[0] + 0x51, 1) for t in range(8)],
                mlen_m=[rd(s + trk_span(t)[0] + 0x28, 1) for t in range(8, 16)],
                trigs=[bin(rd(s + trk_span(t)[0], 8)).count("1") for t in range(16)]))
        for row in rows:
            print(row)
        print("bank", bank, "default change 0x8000004e =", rd(0x8000004E, 1))
        pathlib.Path(a.out if os.path.isabs(a.out) else ROOT / a.out).write_text(
            json.dumps(dict(bank=bank, patterns=rows)))
        return 0

    setup = []
    for spec in a.copypat:
        d, s_ = (int(x) for x in spec.split(":"))
        u.mem_write(slab(bank, d), bytes(u.mem_read(slab(bank, s_), PATSTRIDE)))
        setup.append(["copypat", d, s_])
    for spec in a.copytrk:
        d, s_, t = (int(x) for x in spec.split(":"))
        off, ln = trk_span(t)
        u.mem_write(slab(bank, d) + off, bytes(u.mem_read(slab(bank, s_) + off, ln)))
        setup.append(["copytrk", d, s_, t])

    for spec in a.setb:
        pat, rest = spec.split(":", 1)
        off, val = rest.split("=")
        u.mem_write(slab(bank, int(pat)) + int(off, 0), bytes([int(val, 0) & 0xFF]))
        setup.append(["setb", int(pat), int(off, 0), int(val, 0)])

    cues = sorted((int(k), int(q)) for k, q in (c.split(":") for c in a.cue))
    clyp = [int(x) for x in a.clyp.split(":")] if a.clyp else None

    rt.seq_select_live(bank, a.start)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    u.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))

    st = dict(tick=0, states=[], fires=[], commits=[], cues=[], calls=[], clyp=None)
    pend = list(cues)

    def on_tick(uc, addr, size, user):
        st["tick"] += 1
        s = {k: rd(ad, n) for k, (ad, n) in SCALARS.items()}
        for k, base in ARRAYS.items():
            s[k] = list(bytes(uc.mem_read(base, 16)))
        for kind, (tb, mb) in EV_TABLES.items():
            raw = bytes(uc.mem_read(tb, 3 * 8 * 4))
            s["ev_" + kind] = [int.from_bytes(raw[i * 4:i * 4 + 4], "big") for i in range(24)]
            s["mask_" + kind] = list(bytes(uc.mem_read(mb, 8)))
        s["t"] = st["tick"]
        st["states"].append(s)
        while pend and pend[0][0] == st["tick"]:
            _, q = pend.pop(0)
            uc.mem_write(PEND_BANK, bytes([bank]))
            uc.mem_write(PEND_PAT, bytes([q]))
            st["cues"].append([st["tick"], q])

    def on_clyp(uc, addr, size, user):
        if clyp is None or st["clyp"] is not None or st["tick"] < clyp[0]:
            return
        _, s_, t = clyp
        dst_pat = rd(0x800065BE, 1)
        dst_bank = rd(0x800065BD, 1)
        off, ln = trk_span(t)
        uc.mem_write(slab(dst_bank, dst_pat) + off, bytes(uc.mem_read(slab(bank, s_) + off, ln)))
        st["clyp"] = [st["tick"], hex(addr), dst_bank, dst_pat, s_, t,
                      rd(0x800065B2, 2), rd(0x800065B6, 1)]

    def on_builder(uc, addr, size, user):
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        w = [int.from_bytes(bytes(uc.mem_read(sp + 4 * i, 4)), "big") for i in range(6)]
        if w[0] not in (BUILDER_A_RET, BUILDER_M_RET):
            return
        sx = lambda v: v - (1 << 32) if v & 0x80000000 else v
        st["calls"].append([st["tick"], "a" if addr == BUILDER_A else "m",
                            sx(w[1]), sx(w[2]), sx(w[3]), sx(w[4]), sx(w[5])])

    def on_fire(uc, access, addr, size, value, user):
        st["fires"].append([st["tick"], (addr - FIRE_TBL) // 4, value & 0xFFFFFFFF,
                            uc.reg_read(er.eb.UC_M68K_REG_PC)])

    def on_commit(uc, access, addr, size, value, user):
        pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
        if pc in (LAND_PC, TAIL_PC) and (not st["commits"] or st["commits"][-1][0] != st["tick"]):
            st["commits"].append([st["tick"], "LAND" if pc == LAND_PC else "WRAP"])

    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    u.hook_add(er.eb.UC_HOOK_CODE, on_clyp, begin=a.clyp_pc, end=a.clyp_pc)
    u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_fire, begin=FIRE_TBL, end=FIRE_END - 1)
    u.hook_add(er.eb.UC_HOOK_CODE, on_builder, begin=BUILDER_A, end=BUILDER_A)
    u.hook_add(er.eb.UC_HOOK_CODE, on_builder, begin=BUILDER_M, end=BUILDER_M)
    u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_commit, begin=STEP_ARR, end=STEP_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 400:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    meta = dict(image=a.image, project=a.project, start=a.start, setup=setup, cues=cues,
                clyp_req=clyp, clyp_pc=hex(a.clyp_pc), dj=a.dj, bank=bank, ticks=st["tick"])
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(json.dumps(dict(meta=meta, cues=st["cues"], commits=st["commits"],
                                   clyp=st["clyp"], states=st["states"], fires=st["fires"],
                                   calls=st["calls"])))
    print(f"wrote {out}: ticks={st['tick']} cues={st['cues']} commits={st['commits']} "
          f"clyp={st['clyp']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

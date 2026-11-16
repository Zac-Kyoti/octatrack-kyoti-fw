#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI -- the pop at a Part-changing jump (the user, 2026-11-14: OT DEMO A05 (Part 2) -> A03 (Part 1)
with a sample ringing: DIRECT JUMP pops, stock's fastest change (CHAIN AFTER 2) does not). Measurement only.

Plays OT DEMO from --start, cues --cue T:P (written at phase-G entry of tick T, as diag_reflock does), DJ on or
off (--dj), optionally sets the playing pattern's CHAIN AFTER index (--chainq, blob +0x8e56; 2 = 2 steps), and
records, for every engine frame (frame ISR entry 0x4000aad0) inside --window A:B (ticks):
  * calls: light / full / saved Part apply, TRK_APPLY, tempo 0x4009c550, kernel posts (queue + message bytes),
    the engine switch's branches (0x4000af38.. bit1, the 0x80006904 paths, the 0x8000182a reset, 0x4000b1d8);
  * reads of either Part's FX1 / FX2 / machine bytes (who reads the Part's track types, and when);
  * writes (with PC) to the publish bytes 0x80001828/29, 0x8000182a..39, the restart bytes 0x8000184a..4c,
    the switch flags 0x46c7fa80 and 0x46c7fb08..0b;
  * per-frame byte diffs of the engine's per-track records 0x80000100..0x80001900, the voices
    0x800049d8..0x80004d20 and 0x46c7f800..0x46c80400.

  python3 tools/diag_dj_switchpop.py --image IMG --project DIR --start 4 --cue 100:2 --dj 0 --chainq 2 \
      --window 95:130 --out out/djpop/a.json
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
TICK_PC, FRAME_PC = 0x400A3FDC, 0x4000AAD0
BLOB, BANKSTRIDE, PATSTRIDE = 0x400E21E0, 0x9B340, 0x8ED8
PART0 = 0x8ED80
CALLS = {0x40009E00: "LIGHT_APPLY", 0x40009094: "PART_APPLY", 0x40009848: "SAVED_APPLY", 0x40001F18: "TRK_APPLY",
         0x4009C550: "TEMPO_APPLY", 0x4000AF38: "sw: flags due", 0x4000AF4C: "sw: bit1 (real switch)",
         0x4000AF44: "sw: no bit1", 0x4000AF98: "sw: 6904 bit1 path", 0x4000B0A6: "sw: 6904 path 2",
         0x4000B1A4: "sw: 182a reset", 0x4000B1D8: "sw: -> light apply", 0x4000C9E8: "eng: voice part compare",
         0x4000CA16: "eng: restart bit write", 0x400A43A0: "seq: wrap body", 0x400A44A0: "seq: wrap commit",
         0x400A1F88: "seq: landing loader", 0x40006820: "VOICE_KILL", 0x4000D45A: "sw: silence -> voice kill",
         0x4000672C: "voice kill: pickup bookkeeping"}
WRITES = [(0x80001828, 2, "publish"), (0x8000182A, 16, "182a"), (0x8000184A, 3, "restart"),
          (0x46C7FA80, 4, "ENG_AFLAGS"), (0x46C7FB08, 4, "fb08")]
REGS = [(0x80000100, 0x1800), (0x80001900, 0x100), (0x800049D8, 0x348), (0x46C7E990, 0x120), (0x46C7F800, 0xC00)]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--cue", required=True)
    ap.add_argument("--dj", type=int, default=0)
    ap.add_argument("--dj-mode-addr", type=lambda v: int(v, 0), default=0x800000D8)
    ap.add_argument("--chainq", type=int, default=None)
    ap.add_argument("--window", required=True)
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument("--poke", action="append", default=[], help="ADDR=VAL[:SIZE] after the load")
    ap.add_argument("--mrq", action="store_true",
                    help="experiment: at the first switch frame after the cue (0x4000b1d8), queue the master-track "
                         "restart the way stock's voice-start path does (0x46c7feb4 bit 7, 0x46c7fe1c..1f = bank, "
                         "Part, 0, 6) -- to see whether the engine acts on it in that same frame")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="djpop")
    a = ap.parse_args(argv)
    ct, cp = map(int, a.cue.split(":"))
    w0, w1 = map(int, a.window.split(":"))
    out = pathlib.Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{a.tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    bb = BLOB + bank * BANKSTRIDE
    for spec in a.poke:
        ad, rest = spec.split("=")
        val, _, sz = rest.partition(":")
        u.mem_write(int(ad, 0), int(val, 0).to_bytes(int(sz or 1), "big"))
    if a.chainq is not None:
        u.mem_write(bb + a.start * PATSTRIDE + 0x8E56, bytes([a.chainq]))
    rt.seq_select_live(bank, a.start)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    u.mem_write(a.dj_mode_addr, (1 if a.dj else 0).to_bytes(4, "big"))
    st = dict(tick=0, frame=0)
    ev, frames, ticks = [], [], []
    prev = {}
    inw = lambda: w0 <= st["tick"] <= w1

    def on_tick(uc, ad, sz, ud):
        st["tick"] += 1
        if st["tick"] == ct:
            uc.mem_write(0x800065BF, bytes([bank]))
            uc.mem_write(0x800065C0, bytes([cp]))
        if inw():
            ticks.append([st["tick"], st["frame"], rd(0x4610757C, 4), rd(0x800065BE, 1), rd(0x800065B2, 2),
                          rd(0x800065B6, 1), list(bytes(uc.mem_read(0x800064D0, 8)))])

    def on_frame(uc, ad, sz, ud):
        st["frame"] += 1
        if not inw():
            prev.clear()
            return
        fr = {"f": st["frame"], "t": st["tick"], "clk": rd(0x46104CF0, 4), "d": []}
        for base, n in REGS:
            cur = bytes(uc.mem_read(base, n))
            old = prev.get(base)
            if old is not None:
                i = 0
                while i < n:
                    if cur[i] != old[i]:
                        j = i
                        while j < n and cur[j] != old[j]:
                            j += 1
                        fr["d"].append([base + i, old[i:j].hex(), cur[i:j].hex()])
                        i = j
                    else:
                        i += 1
            prev[base] = cur
        frames.append(fr)

    def on_call(uc, ad, sz, ud):
        if not inw():
            return
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        ev.append([st["frame"], st["tick"], "call", CALLS[ad], [rd(sp + 4 * k, 4) for k in (0, 1, 2)],
                   uc.reg_read(er.eb.UC_M68K_REG_D3), rd(0x46104CF0, 4)])

    def on_post(uc, ad, sz, ud):
        if not inw():
            return
        sp = uc.reg_read(er.eb.UC_M68K_REG_A7)
        q, m = rd(sp + 4, 4), rd(sp + 8, 4)
        ev.append([st["frame"], st["tick"], "post", hex(q), hex(m), bytes(uc.mem_read(m, 3)).hex()])

    def on_read(uc, acc, ad, sz, val, ud):
        if not inw():
            return
        pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
        ev.append([st["frame"], st["tick"], "read", hex(ad), sz, hex(pc)])

    def on_write(uc, acc, ad, sz, val, ud):
        if not inw():
            return
        pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
        ev.append([st["frame"], st["tick"], "write", hex(ad), sz, val & 0xFFFFFFFF, hex(pc)])

    u.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    u.hook_add(er.eb.UC_HOOK_CODE, on_frame, begin=FRAME_PC, end=FRAME_PC)
    mrq = {"done": False}

    def on_mrq(uc, ad, sz, ud):
        if mrq["done"] or st["tick"] < ct:
            return
        mrq["done"] = True
        part = rd(0x46C7FF62, 1)
        uc.mem_write(0x46C7FEB4, bytes([rd(0x46C7FEB4, 1) | 0x80]))
        uc.mem_write(0x46C7FE1C, bytes([rd(0x46C7FF40, 1), part, 0, 6]))
        ev.append([st["frame"], st["tick"], "MRQ queued", part])
    if a.mrq:
        u.hook_add(er.eb.UC_HOOK_CODE, on_mrq, begin=0x4000B1D8, end=0x4000B1D8)
    for ad in CALLS:
        u.hook_add(er.eb.UC_HOOK_CODE, on_call, begin=ad, end=ad)
    u.hook_add(er.eb.UC_HOOK_CODE, on_post, begin=0x40000C3C, end=0x40000C3C)
    for p in range(4):          # FX1 0..7, FX2 8..15, machine 0x22..0x29 of every Part of the bank
        pb = bb + PART0 + p * 0x18B2
        u.hook_add(er.eb.UC_HOOK_MEM_READ, on_read, begin=pb, end=pb + 15)
        u.hook_add(er.eb.UC_HOOK_MEM_READ, on_read, begin=pb + 0x22, end=pb + 0x29)
    for ad, n, _ in WRITES:
        u.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=ad, end=ad + n - 1)
    rt.start_transport_live()
    goal = a.ticks or (w1 + 5)
    spins = 0
    while st["tick"] < goal and spins < 600:
        b = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == b:
            break
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(meta=dict(image=a.image, start=a.start, cue=[ct, cp], dj=a.dj, chainq=a.chainq,
                                             window=[w0, w1], bank=bank), ticks=ticks, ev=ev, frames=frames)))
    print(f"wrote {out}: ticks {st['tick']} frames-in-window {len(frames)} events {len(ev)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

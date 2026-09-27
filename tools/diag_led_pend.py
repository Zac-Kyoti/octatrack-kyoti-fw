#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 107: the LED-predicate trace (V6 handoff section 2.3).

The PTN-page LED painter FUN_4007afe8 at 0x4007b182 paints "cued" (yellow) when
PEND_PAT (0x800065c0) != [0x100b14d0] while PEND_BANK == [0x80000002].  V6's landing
copies PEND -> ACT and never touches 0x100b14d0, so the LED stays yellow.  This tool
does not theorise: it logs every write to the whole predicate neighbourhood, with the
writer PC and the tick, plus every UI-queue post (FUN_40000c3c) with the message bytes,
across one run.  Run it once on stock (DJ off, the cue commits at a natural wrap) and
once on a V6 image (DJ on, the cue commits at a landing), then diff the two logs at the
commit tick.

Usage:
  python3 tools/diag_led_pend.py --project ~/Desktop/DJTEST2 --pattern 3 --to-pattern 4 \
      --image out/raw/section_3_MAIN_OS.bin --dj 0 --out out/led_stock.txt
  python3 tools/diag_led_pend.py --project ~/Desktop/DJTEST2 --pattern 3 --to-pattern 4 \
      --image out/mainos_directjump_v6.bin --dj 1 --out out/led_v62.txt
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"

DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC          # phase G entry: once per tick, same site diag_tablearm_phase uses
POST_PC = 0x40000C3C          # the kernel UI-queue post; args on the stack

# the predicate's own operands, and their neighbours
ACT_BANK, ACT_PAT = 0x800065BD, 0x800065BE
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
PREV_LO, PREV_HI = 0x800065C1, 0x800065C2
CUR_BANK = 0x80000002
UI_LO, UI_HI = 0x100B14C8, 0x100B14D8      # 0x100b14d0 and its neighbours
STEP_ARR = 0x800064D0
LAND_PC, TAIL_PC = 0x400A20DE, 0x400A4BE6   # V6 landing / stock wrap-change STEP write

NAMES = {ACT_BANK: "ACT_BANK", ACT_PAT: "ACT_PAT", PEND_BANK: "PEND_BANK",
         PEND_PAT: "PEND_PAT", PREV_LO: "PREV_LO", PREV_HI: "PREV_HI",
         CUR_BANK: "CUR_BANK", 0x100B14D0: "UI_PAT(0x100b14d0)"}


def nm(addr):
    return NAMES.get(addr, f"{addr:#x}")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--pattern", type=int, required=True)
    ap.add_argument("--to-pattern", type=int, required=True)
    ap.add_argument("--image", required=True,
                    type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--dj", type=int, default=0)
    ap.add_argument("--jumps", type=int, default=2)
    ap.add_argument("--gap", type=int, default=100)
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=260)
    ap.add_argument("--len", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    tag = f"led_{pathlib.Path(a.image).stem}_dj{a.dj}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{tag}")
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
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))
    if a.len:
        for pat, ln in ((a.pattern, None), (a.to_pattern, a.len)):
            blob = 0x400E21E0 + bank * 0x9B340 + pat * 0x8ED8
            rt.uc.mem_write(blob + 0x8E55, b"\x00")
            if ln:
                rt.uc.mem_write(blob + 0x8E53, bytes([ln]))

    st = dict(tick=0, njump=0, ev=[], commits=[], cues=[])
    targets = [a.to_pattern, a.pattern]

    def snap(u):
        g = lambda ad: bytes(u.mem_read(ad, 1))[0]
        return (g(ACT_BANK), g(ACT_PAT), g(PEND_BANK), g(PEND_PAT),
                g(CUR_BANK), g(0x100B14D0))

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        st["ev"].append(("TICK", st["tick"], None, snap(u)))
        if st["njump"] < a.jumps and st["tick"] >= a.cue_at + st["njump"] * a.gap:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([targets[st["njump"] % 2]]))
            st["cues"].append((st["tick"], targets[st["njump"] % 2]))
            st["njump"] += 1

    def on_w(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["ev"].append(("W", st["tick"], (addr, size, value & ((1 << (8 * size)) - 1), pc), None))

    def on_commit(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        if pc in (LAND_PC, TAIL_PC) and (not st["commits"] or st["commits"][-1][0] != st["tick"]):
            st["commits"].append((st["tick"], pc))

    def on_post(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        try:
            msgp = int.from_bytes(bytes(u.mem_read(sp + 8, 4)), "big")
            ret = int.from_bytes(bytes(u.mem_read(sp, 4)), "big")
            body = bytes(u.mem_read(msgp, 4))
        except Exception:
            return
        st["ev"].append(("POST", st["tick"], (msgp, ret, body.hex()), None))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_post, begin=POST_PC, end=POST_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=ACT_BANK, end=PREV_HI)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=UI_LO, end=UI_HI)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=CUR_BANK, end=CUR_BANK)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_commit, begin=STEP_ARR, end=STEP_ARR)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break

    out = []
    out.append(f"image={a.image} dj={a.dj} project={a.project} "
               f"pattern={a.pattern}->{a.to_pattern} ticks={st['tick']}")
    out.append(f"cues={st['cues']}")
    out.append(f"commits={[(t, hex(p)) for t, p in st['commits']]}")
    out.append("")
    out.append("--- event log (TICK lines only where a sampled byte changed) ---")
    last = None
    for kind, tk, d, s in st["ev"]:
        if kind == "TICK":
            if s != last:
                out.append(f"t{tk:<4} STATE act={s[0]}/{s[1]} pend={s[2]}/{s[3]} "
                           f"curbank={s[4]} ui14d0={s[5]}")
                last = s
        elif kind == "W":
            addr, size, val, pc = d
            out.append(f"t{tk:<4}   W {nm(addr):>18} <- {val:#x} ({size}B) pc={pc:#x}")
        else:
            msgp, ret, body = d
            out.append(f"t{tk:<4}   POST msg={msgp:#x} body={body} ret={ret:#x}")
    txt = "\n".join(out)
    print(txt)
    if a.out:
        p = pathlib.Path(a.out)
        if not p.is_absolute():
            p = ROOT / p
        p.write_text(txt + "\n")
        print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

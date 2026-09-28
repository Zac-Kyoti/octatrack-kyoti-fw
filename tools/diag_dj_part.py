#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 108: does a DIRECT JUMP V7 landing change the PART the way a stock cued switch does?

V6/V7 land through stock's transport-start path and post the same UI messages as stock's
wrap-change ({0x15, bank}, {0x11, pat, 1}) but skip the wrap-change code itself.  Neither
Part-apply function (light 0x40009e00, full 0x40009094) is called from the wrap-change
region, so a stock cued switch presumably applies the Part on the UI side from the {0x11}
message -- which V7 posts too.  This run checks it instead of assuming it: give pattern B a
different Part (pattern blob +0x8e57, the byte case 0x10 of the UI dispatcher reads), switch
A -> B once, and log every call into either Part-apply function (with its caller) plus every
write to the current-Part bytes 0x100b14cf / 0x80000003.

    python3 tools/diag_dj_part.py --image STOCK_OR_V7 --dj 0|1 --out out/djpart_X.txt
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
DJ_MODE = 0x800000D8
TICK_PC = 0x400A3FDC
PEND_BANK, PEND_PAT = 0x800065BF, 0x800065C0
ACT_PAT = 0x800065BE
PART_APPLY = {0x40009E00: "LIGHT part apply 0x40009e00", 0x40009094: "FULL part apply 0x40009094"}
PART_BYTES = {0x100B14CF: "UI_PART(0x100b14cf)", 0x80000003: "CUR_PART(0x80000003)"}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--dj", type=int, default=1)
    ap.add_argument("--from-pat", type=int, default=3)
    ap.add_argument("--to-pat", type=int, default=4)
    ap.add_argument("--to-part", type=int, default=2, help="0-based Part given to the target pattern")
    ap.add_argument("--cue-at", type=int, default=40)
    ap.add_argument("--ticks", type=int, default=150)
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

    tag = f"djpart_{pathlib.Path(a.image).stem}_dj{a.dj}"
    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=f"out/_emu_{tag}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    blob = lambda p: 0x400E21E0 + bank * 0x9B340 + p * 0x8ED8
    part_from = bytes(rt.uc.mem_read(blob(a.from_pat) + 0x8E57, 1))[0]
    rt.uc.mem_write(blob(a.to_pat) + 0x8E57, bytes([a.to_part]))
    rt.seq_select_live(bank, a.from_pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1 if a.dj else 0).to_bytes(4, "big"))

    st = dict(tick=0, cued=False, log=[])
    rd = lambda u, ad: bytes(u.mem_read(ad, 1))[0]

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if not st["cued"] and st["tick"] >= a.cue_at:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pat]))
            st["cued"] = True
            st["log"].append(f"t{st['tick']:<4} CUE pattern {a.to_pat}")

    def on_apply(u, addr, size, user):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        ret = int.from_bytes(bytes(u.mem_read(sp, 4)), "big")
        st["log"].append(f"t{st['tick']:<4} CALL {PART_APPLY[addr]}  from {ret:#x}  act_pat={rd(u, ACT_PAT)}")

    def on_w(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["log"].append(f"t{st['tick']:<4} W {PART_BYTES.get(addr, hex(addr))} <- {value & 0xff} pc={pc:#x}")

    def on_act(u, access, addr, size, value, user):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        st["log"].append(f"t{st['tick']:<4} ACT_PAT <- {value & 0xff} pc={pc:#x}")

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    for pc in PART_APPLY:
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_apply, begin=pc, end=pc)
    for ad in PART_BYTES:
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_w, begin=ad, end=ad)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_act, begin=ACT_PAT, end=ACT_PAT)
    rt.start_transport_live()
    spins = 0
    while st["tick"] < a.ticks and spins < 90:
        before = st["tick"]
        rt.run(ms=60)
        spins += 1
        if st["tick"] == before:
            break
    # let the UI task drain its queue after the switch
    rt.run(ms=300)
    head = [f"image={a.image} dj={a.dj} pattern {a.from_pat} (part {part_from}) -> "
            f"{a.to_pat} (part poked to {a.to_part}); ticks={st['tick']}",
            f"final: CUR_PART(0x80000003)={rd(rt.uc, 0x80000003)} UI_PART(0x100b14cf)="
            f"{rd(rt.uc, 0x100B14CF)} ACT_PAT={rd(rt.uc, ACT_PAT)}", ""]
    txt = "\n".join(head + st["log"])
    print(txt)
    out = pathlib.Path(a.out)
    (out if out.is_absolute() else ROOT / out).write_text(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

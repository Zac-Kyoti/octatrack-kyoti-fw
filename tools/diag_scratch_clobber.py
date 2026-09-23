#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_scratch_clobber -- does STOCK code write RELOAD2's scratch at 0x80006a50..55?

Hardware report #7 (Session 84): RELOAD BUSY appears after EDITING the sequence
with the transport running -- not after a reload. That is a different trigger
from report #6 and it points at the scratch itself, because BUSY can only mean
G_KIND != 0 and our own code sets G_KIND only in the arm path.

The "these globals are genuinely free" verdict (DIRECT JUMP thread, Session 79
cont.) came from scanning the stock image for ABSOLUTE-LONG references to
0x80006a30..0x80006a5f and finding zero. That scan cannot see register-indirect
writes (`move.b d0,d16(a0)` with a base in a register), which is exactly the
blind spot that forced this thread's earlier xref retraction for CODE refs.

So: watch the bytes directly, with the transport genuinely running, while
driving real key input -- and report the PC of every writer.

  G_KIND  0x80006a50   G_PAT 0x51   G_MENU 0x52
  G_SEL   0x80006a53   G_TRK 0x54   G_TMIDI 0x55

A write from a PC inside our cave is ours and expected. A write from anywhere
else is the bug.

Usage: python3 tools/diag_scratch_clobber.py [--trigs N]
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PRESS, RELEASE = 1, 0
SCRATCH_LO, SCRATCH_HI = 0x80006A50, 0x80006A55
NAMES = {0x80006A50: "G_KIND", 0x80006A51: "G_PAT", 0x80006A52: "G_MENU",
         0x80006A53: "G_SEL", 0x80006A54: "G_TRK", 0x80006A55: "G_TMIDI"}
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C3C
REC_CODE, PLAY_CODE = 0x2B, 0x2C      # best-effort; reported, not assumed


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigs", type=int, default=8)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.RELOAD_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    pat = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : mounted={mounted} bank={final_bank} pattern={pat}")

    writes = []
    phase = ["boot"]

    def on_write(u, access, addr, size, value, x):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        writes.append((phase[0], addr, size, value, pc))

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=SCRATCH_LO, end=SCRATCH_HI)
    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    phase[0] = "playback"
    for _ in range(40):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=2_000_000)

    # --- edit the sequence while running: tap trig keys 0x00.. ---
    phase[0] = "trig-edit"
    for i in range(a.trigs):
        key(i & 0x0F, PRESS)
        key(i & 0x0F, RELEASE)
        for _ in range(4):
            rt.run(ms=60)

    # --- same again with REC held (live record), best effort ---
    phase[0] = "rec-edit"
    key(REC_CODE, PRESS)
    for i in range(a.trigs):
        key(i & 0x0F, PRESS)
        key(i & 0x0F, RELEASE)
        for _ in range(4):
            rt.run(ms=60)
    key(REC_CODE, RELEASE)
    for _ in range(20):
        rt.run(ms=60)

    print(f"\nscratch reads now: " + "  ".join(
        f"{NAMES[a_]}={rt.uc.mem_read(a_,1)[0]}" for a_ in sorted(NAMES)))

    print(f"\n{len(writes)} write(s) to 0x80006a50..55")
    foreign = [w for w in writes if not (CAVE_LO <= w[4] < CAVE_HI)]
    seen = {}
    for ph, addr, size, val, pc in writes:
        key_ = (ph, addr, size, pc)
        seen[key_] = seen.get(key_, 0) + 1
    for (ph, addr, size, pc), n in sorted(seen.items()):
        who = "OURS" if CAVE_LO <= pc < CAVE_HI else "** STOCK **"
        nm = NAMES.get(addr, f"0x{addr:08x}")
        print(f"  [{ph:<9}] {nm:<7} size={size} pc=0x{pc:08x} {who:<12} x{n}")

    print()
    if foreign:
        print(f"   ** FOUND IT: {len(foreign)} write(s) from OUTSIDE our cave. "
              "The scratch is NOT free. **")
        return 1
    print("   no foreign writes seen in these phases -- the scratch was not "
          "clobbered by what this test drove.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

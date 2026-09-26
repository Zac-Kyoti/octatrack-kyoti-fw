#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_readsrc -- does the RUNNING engine read trigs from the COLD blob or the
LIVE cache? And does our reload's propagation actually reach whatever it reads?

WHY: report #14 item 1 survived the PLAY_BANK fix. The sharpest clue is the asymmetry
the user reports -- "Parts ALWAYS reload well. However the sequence data does not always
reload reliably." PARTAPPLY (FUN_40009094) is an ACTIVE engine call; the sequence is a
PASSIVE memcpy that something else has to read. So suspect propagation, not copying.

TWO PRIOR MEASUREMENTS IN THIS REPO APPEAR TO CONFLICT
  * Session 84 (diag_seq_edit_io.py): the firmware's own EDIT path writes the COLD blob,
    blob + P*0x8ed8 + trk*0x91a + 0x00..0x0f (the trig masks). Gated on the firmware
    really writing them, so it is trustworthy.
  * Session 80 (rlj_setflag's comment): our worker wrote only the cold blob and
    "playback keeps reading stale bytes" -- i.e. playback reads the LIVE cache
    (0x1001614e), which is why LIVE_REFRESH (FUN_4000faf0) was added to the worker.
Both cannot be wholly true: if edits land only in the cold blob and playback reads only
the live cache, a live edit would be inaudible until something refreshed -- which is not
how the machine behaves.

LIVE_REFRESH, disassembled this session (0x4000faf0), has NO early-exit and copies the
WHOLE bank: memcpy(0x1001614e, blob + bank*0x9b340, 0x8ed80) -- 585,088 B = 16 * 0x8ed8 --
plus four smaller region copies. So if the cold blob is the truth, the refresh is
complete; if the live cache is also written by edits, the refresh would REVERT them.

WHAT THIS MEASURES (read hooks, transport running, no reload involved yet)
  * reads of the COLD trig region for the playing pattern/track
  * reads of the LIVE cache's corresponding window
  each bucketed by the reading PC, so the engine's own reads are identifiable.
Then it fires a reload and reports whether the bytes the engine READS actually changed.

Usage: python3 tools/diag_reload3_readsrc.py [--track N]
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE, TRACK0 = 0x2E, 0x10
PRESS, RELEASE = 1, 0

BLOB = 0x400E21E0
LIVE = 0x1001614E              # LIVE_REFRESH's destination
BANKSTRIDE, PATSTRIDE, TRAC_A = 0x9B340, 0x8ED8, 0x91A
PLAY_BANK, ACT_PAT = 0x800065BD, 0x800065BE
G_KIND = 0x80006A50
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, default=3)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail[:150])

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    b0 = rt.uc.mem_read(0x80000002, 1)[0]
    rt.seq_select_live(b0, P)
    rt.internal_clock(); rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD; rt.exact_clock()
    rt.start_transport_live()
    for _ in range(10):
        rt.run(ms=60)

    bank, pat = rt.uc.mem_read(PLAY_BANK, 1)[0], rt.uc.mem_read(ACT_PAT, 1)[0]
    cold = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE + a.track * TRAC_A
    live = LIVE + pat * PATSTRIDE + a.track * TRAC_A     # LIVE holds this bank's 16 slabs
    print(f"load : bank={bank} pattern={pat} track={a.track+1}")
    print(f"   cold trig masks @ {cold:#x}..{cold+0x0f:#x}")
    print(f"   live trig masks @ {live:#x}..{live+0x0f:#x}")

    cold_r, live_r = {}, {}

    def mk(bucket):
        def cb(uc, access, address, size, value, ud):
            pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
            if not (CAVE_LO <= pc < CAVE_HI):        # ignore our own cave's reads
                bucket[pc] = bucket.get(pc, 0) + 1
            return True
        return cb

    h1 = rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk(cold_r), begin=cold, end=cold + 0x0F)
    h2 = rt.uc.hook_add(er.eb.UC_HOOK_MEM_READ, mk(live_r), begin=live, end=live + 0x0F)

    print("\n--- transport running, NO reload: who reads the trig masks? ---")
    for _ in range(25):
        rt.run(ms=60)
    def top(d):
        return [(hex(k), v) for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:5]]
    print(f"   COLD reads: total={sum(cold_r.values())}  top PCs={top(cold_r)}")
    print(f"   LIVE reads: total={sum(live_r.values())}  top PCs={top(live_r)}")
    if sum(cold_r.values()) and not sum(live_r.values()):
        print("   >> the engine reads the COLD blob directly. Our slab copy is visible "
              "immediately; LIVE_REFRESH is for something else.")
    elif sum(live_r.values()) and not sum(cold_r.values()):
        print("   >> the engine reads the LIVE cache only. Our copy reaches it ONLY via "
              "LIVE_REFRESH -- so that call is load-bearing, and anything that skips or "
              "races it loses the reload.")
    elif sum(live_r.values()) and sum(cold_r.values()):
        print("   >> BOTH are read. Which one wins for trigs needs the PCs above.")
    else:
        print("   >> NEITHER was read in 1.5 s of transport. Inconclusive -- the engine "
              "may cache per step, or this pattern/track may be empty.")

    # ---- now: does a reload change the bytes the engine actually reads? ----
    print("\n--- fire a reload; do the ENGINE-VISIBLE bytes change? ---")
    before_cold = bytes(rt.uc.mem_read(cold, 0x10))
    before_live = bytes(rt.uc.mem_read(live, 0x10))
    # scribble the cold masks so a successful reload has something to undo
    rt.uc.mem_write(cold, bytes((b ^ 0xFF) for b in before_cold))
    scrib_cold = bytes(rt.uc.mem_read(cold, 0x10))
    print(f"   scribbled cold: {before_cold.hex()} -> {scrib_cold.hex()}")

    def key(c, e):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(c, e), budget=4_000_000)

    key(PTN_CODE, PRESS); key(TRACK0 + a.track, PRESS)
    key(TRACK0 + a.track, RELEASE); key(PTN_CODE, RELEASE)
    for _ in range(250):
        rt.run(ms=10)
        if rt.uc.mem_read(G_KIND, 1)[0] == 0:
            break
    for _ in range(10):
        rt.run(ms=60)

    after_cold = bytes(rt.uc.mem_read(cold, 0x10))
    after_live = bytes(rt.uc.mem_read(live, 0x10))
    print(f"   cold after reload: {after_cold.hex()}  "
          f"{'RESTORED' if after_cold == before_cold else 'NOT restored'}")
    print(f"   live before      : {before_live.hex()}")
    print(f"   live after       : {after_live.hex()}  "
          f"{'CHANGED' if after_live != before_live else 'unchanged'}")
    if after_cold == before_cold and after_live == before_cold:
        print("   >> cold restored AND live now matches it -- propagation is complete.")
    elif after_cold == before_cold and after_live != before_cold:
        print("   >> ** cold restored but LIVE does NOT match it ** -- the reload landed "
              "in the blob and never reached what the engine reads. This is report #14 "
              "item 1's mechanism.")
    else:
        print("   >> the cold copy itself did not restore; the failure is upstream of "
              "propagation.")
    rt.uc.hook_del(h1); rt.uc.hook_del(h2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

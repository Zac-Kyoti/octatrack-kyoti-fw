#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_bankvar -- WHICH bank variable does the reload worker follow?

Hardware report #14 item 1: "the sequence data does not always reload reliably. Most of
the time it does. Occasionally the toast will show 'reloaded', but the sequence is not
actually restored."

THE QUESTION THIS ANSWERS, AND THE ONE IT DOES NOT
  The worker takes its PATTERN from ACT_PAT (0x800065be) but its BANK from CUR_BANK
  (0x80000002). ACT_PAT's real partner is 0x800065bd: all three of its writers set the
  two together (0x400a05f6 direct goto; 0x400a40aa and 0x400a44dc the boundary latches,
  both gated on the queued bytes being != -1). CUR_BANK has no such pairing -- it is
  written at 0x400622b8 (a UI path) and 0x40087d26 (project load). Pair CUR_BANK with
  ACT_PAT and you can name a slab nothing is reading: the .strd is read, the slab is
  rewritten, LIVE_REFRESH runs, the toast says RELOADED, and nothing the user hears
  changes.

  ** This test answers "which variable does the code follow", NOT "does hardware ever
  reach the divergent state". ** It CREATES divergence by poking CUR_BANK, because
  reaching it honestly needs a queued bank change to survive to a pattern boundary, and
  at ~140x slower than realtime that costs ~30 min of wall time per run
  (diag_reload3_whichbank.py does it the honest way and is the slow one). Whether the
  divergence occurs on hardware remains UNPROVEN either way -- what is settled here is
  which slab the worker aims at once it does.

  Poking CUR_BANK deliberately does NOT update 0x46c82456 (the cached cold-blob bank base
  stock derives from it at 0x400622aa / 0x40087d44), so stock is left mildly
  inconsistent. That is acceptable for this narrow question -- our worker reads CUR_BANK
  itself, directly -- but it is why this file asserts nothing about stock's own behaviour.

WHAT IT REPORTS
  * a gate that the two variables really do differ before the chord
  * which slab the worker wrote: PLAY_BANK's (follows the sequencer) or CUR_BANK's
    (follows the UI -- the suspected bug)
  * a gate that the worker wrote at all, so "wrote neither" is not read as a pass

Usage:
  python3 tools/diag_reload3_bankvar.py [--track N] [--fake-bank N]
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
BANKSTRIDE, PATSTRIDE = 0x9B340, 0x8ED8
NBANKS = 16
CUR_BANK, PLAY_BANK, ACT_PAT = 0x80000002, 0x800065BD, 0x800065BE
G_KIND = 0x80006A50


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--fake-bank", type=int, default=2)
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
    b0 = rt.uc.mem_read(CUR_BANK, 1)[0]
    rt.seq_select_live(b0, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    for _ in range(10):
        rt.run(ms=60)

    def rb(ad):
        return rt.uc.mem_read(ad, 1)[0]

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    play_b, pat = rb(PLAY_BANK), rb(ACT_PAT)
    print(f"load : CUR_BANK={rb(CUR_BANK)} PLAY_BANK={play_b} ACT_PAT={pat}")
    if a.fake_bank == play_b:
        sys.exit(f"GATE FAIL: --fake-bank {a.fake_bank} equals the playing bank; there "
                 f"would be no divergence to observe.")

    print(f"\n--- creating divergence: CUR_BANK {rb(CUR_BANK)} -> {a.fake_bank}, "
          f"PLAY_BANK stays {play_b} ---")
    rt.uc.mem_write(CUR_BANK, bytes([a.fake_bank]))
    chk(rb(CUR_BANK) != rb(PLAY_BANK),
        f"the two now differ (CUR_BANK={rb(CUR_BANK)}, PLAY_BANK={rb(PLAY_BANK)}) -- "
        f"GATE: without divergence this test cannot distinguish the two behaviours")

    writes = {}
    lo, hi = BLOB, BLOB + NBANKS * BANKSTRIDE

    def on_write(uc, access, address, size, value, ud):
        if lo <= address < hi:
            off = address - BLOB
            k = (off // BANKSTRIDE, (off % BANKSTRIDE) // PATSTRIDE)
            writes[k] = writes.get(k, 0) + size
        return True

    h = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=lo, end=hi - 1)
    print(f"--- firing [PTN] + [TRACK {a.track+1}] ---")
    key(PTN_CODE, PRESS)
    key(TRACK0 + a.track, PRESS)
    key(TRACK0 + a.track, RELEASE)
    key(PTN_CODE, RELEASE)
    for _ in range(250):
        rt.run(ms=10)
        if rb(G_KIND) == 0:
            break
    for _ in range(8):
        rt.run(ms=60)
    rt.uc.hook_del(h)

    tgt_play = (play_b, pat)
    tgt_cur = (a.fake_bank, pat)
    ranked = sorted(writes.items(), key=lambda kv: -kv[1])
    print(f"\n   BLOB writes by (bank,pattern): {ranked[:6]}")
    print(f"   PLAY_BANK's slab would be {tgt_play}; CUR_BANK's would be {tgt_cur}")
    chk(bool(writes),
        f"the worker wrote SOMETHING ({len(writes)} slab(s)) -- GATE: 'wrote neither' must "
        f"not be mistaken for a pass")

    followed_play = tgt_play in writes
    followed_cur = tgt_cur in writes
    if followed_play and not followed_cur:
        print("   >> VERDICT: the worker follows PLAY_BANK -- it targets the slab the "
              "sequencer reads. This is the FIXED behaviour.")
    elif followed_cur and not followed_play:
        print("   >> VERDICT: the worker follows CUR_BANK -- it targets a slab the "
              "sequencer is NOT reading. ** This is report #14 item 1's mechanism, "
              "reproduced. **")
    elif followed_play and followed_cur:
        print("   >> VERDICT: BOTH slabs written -- unexpected; inspect the ranking above.")
    else:
        print("   >> VERDICT: NEITHER slab written -- the reload probably failed outright "
              "(a poked CUR_BANK changes the .strd filename too). Inconclusive.")
    chk(followed_play or followed_cur,
        "the write landed on one of the two candidate slabs, so the verdict is meaningful")

    print()
    if fails:
        print(f"   {len(fails)} gate/assert failure(s):")
        for f in fails:
            print(f"     - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

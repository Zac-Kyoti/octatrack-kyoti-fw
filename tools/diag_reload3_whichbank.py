#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_whichbank -- a reload must target the bank that is actually PLAYING.

Session 92, hardware report #14: "parts always reload well. However, the sequence data
does not always reload reliably. Most of the time it does. Occasionally the toast will
show 'reloaded', but the sequence is not actually restored."

THE SUSPECT -- two different "current bank" variables
  Our worker targets the reload with CUR_BANK (0x80000002) in FOUR places: the .strd
  filename (rl_openstrd), the cold-blob slab pointer (rlj_ours), the Part apply
  (rlj_faithful) and LIVE_REFRESH (rlj_setflag). The PATTERN, though, comes from
  ACT_PAT (0x800065be).

  ACT_PAT's own partner is 0x800065bd, NOT 0x80000002. Every one of the three writers
  of 0x800065bd sets it in the same breath as ACT_PAT:
      0x400a05f6  the direct/immediate goto  -- 65bd=bank, 65be=pattern
      0x400a40aa  boundary latch  -- gated on BOTH queued values being != -1
      0x400a44dc  boundary latch (second site), identically gated
  So (0x800065bd, 0x800065be) is always a consistent pair describing what is PLAYING,
  and it moves only when the sequencer says so. 0x80000002 has no such pairing: it is
  written at 0x400622b8 (a UI path, alongside LIVE_REFRESH and the cached blob base
  0x46c82456) and at 0x40087d26 (clamped 0..15, project load).

  If the two can differ, our worker reads bank X's .strd and writes bank X's slab while
  the sequencer plays bank Y -- and reports success. Nothing the user can hear changes.
  That is report #14's symptom exactly, and it would be INTERMITTENT in precisely the
  way described: harmless while you stay in one bank, wrong right after you leave it.

WHAT IS ASSERTED
  * a gate first: at rest the two agree, and the test can SEE both (otherwise a later
    "they agree" proves only that the diagnostic is blind).
  * after a real performance bank change -- driven through the true per-key dispatcher
    as hold-[BANK] + bank trig + pattern trig, not by poking memory -- report whether
    they diverge, and by how long.
  * the decisive one: run the reload chord and watch which BLOB slab the worker writes.
    It must be the slab the sequencer reads, i.e. bank 0x800065bd / pattern 0x800065be.

Usage:
  python3 tools/diag_reload3_whichbank.py [--track N] [--to-bank N]
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
PTN_CODE = 0x2E
BANK_CODE = 0x2F
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

BLOB = 0x400E21E0
BANKSTRIDE, PATSTRIDE = 0x9B340, 0x8ED8
NBANKS = 16

CUR_BANK = 0x80000002          # the one our worker uses
PLAY_BANK = 0x800065BD         # ACT_PAT's actual partner
ACT_PAT = 0x800065BE
QUEUED_BANK = 0x800065BF
QUEUED_PAT = 0x800065C0
G_KIND = 0x80006A50
RUNNING = 0x800065B8            # LONGWORD, != 0 while playing
PLAYHEAD = 0x800065B2           # bounded master playhead (word)
OPEN_BUF = 0x460A8F60           # a STOCK buffer; every stock user passes size 0x10000
SCRATCH = 0x460AFF60            # = OPEN_BUF + 0x7000 -- inside that window
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--to-bank", type=int, default=1)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    bank0 = rt.uc.mem_read(CUR_BANK, 1)[0]
    rt.seq_select_live(bank0, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()

    def rb(ad):
        return rt.uc.mem_read(ad, 1)[0]

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def drain(n=6, ms=60):
        for _ in range(n):
            rt.run(ms=ms)

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    def state(tag):
        cb, pb, ap_, qb, qp = (rb(CUR_BANK), rb(PLAY_BANK), rb(ACT_PAT),
                               rb(QUEUED_BANK), rb(QUEUED_PAT))
        print(f"   {tag:<22} CUR_BANK={cb}  PLAY_BANK={pb}  ACT_PAT={ap_}  "
              f"queued=({qb if qb != 0xFF else '-'},{qp if qp != 0xFF else '-'})")
        return cb, pb, ap_

    rt.start_transport_live()
    drain(20)

    print(f"load : bank={bank0} pattern={P}")
    print("\n--- gate: at rest the two bank variables must agree, and be readable ---")
    cb, pb, ap_ = state("at rest")
    chk(cb == pb, f"CUR_BANK == PLAY_BANK at rest ({cb} == {pb}) -- the baseline")
    if a.to_bank == cb:
        sys.exit(f"GATE FAIL: --to-bank {a.to_bank} is already the current bank; the "
                 f"change below would be a no-op and could prove nothing.")

    # ---- a REAL performance bank change, through the dispatcher ----
    print(f"\n--- performance bank change to bank {a.to_bank}, pattern 1 "
          f"(hold [BANK], bank trig, pattern trig, release) ---")
    key(BANK_CODE, PRESS); drain(4)
    key(a.to_bank, PRESS); key(a.to_bank, RELEASE); drain(4)   # pick the BANK
    key(1, PRESS); key(1, RELEASE); drain(4)                   # pick the PATTERN
    key(BANK_CODE, RELEASE); drain(4)
    cb1, pb1, ap1 = state("right after")
    diverged_now = cb1 != pb1

    # ===== the gate that the FIRST version of this test got wrong =====
    # A queued bank/pattern change lands only at a pattern BOUNDARY (0x400a40aa /
    # 0x400a44dc, both gated on the two queued bytes being != -1). Until it latches,
    # PLAY_BANK and ACT_PAT still describe the OLD pattern -- correctly -- so the two
    # variables agreeing says nothing at all about divergence. v1 drained a fixed 40
    # frames, never saw the latch, and printed "CUR_BANK tracked the performance
    # change". That was a blind detector reporting a pass. So: require the latch, and
    # if it never comes, say INCONCLUSIVE rather than anything reassuring.
    run_l = int.from_bytes(rt.uc.mem_read(RUNNING, 4), "big")
    ph0 = int.from_bytes(rt.uc.mem_read(PLAYHEAD, 2), "big")
    rt.run(ms=300)
    ph1 = int.from_bytes(rt.uc.mem_read(PLAYHEAD, 2), "big")
    chk(run_l != 0 and ph1 != ph0,
        f"the transport is RUNNING and the playhead advances (RUNNING={run_l}, "
        f"playhead {ph0} -> {ph1}) -- GATE: a stopped transport never reaches a "
        f"pattern boundary, so the latch below could not fire for a trivial reason")
    qb, qp = rb(QUEUED_BANK), rb(QUEUED_PAT)
    print(f"   queued=({qb},{qp}); waiting for the boundary latch (ACT_PAT {ap_} -> {qp})")
    latched = False
    for i in range(200):                       # up to ~12 s of emulated time
        rt.run(ms=60)
        if rb(ACT_PAT) != ap_ or rb(PLAY_BANK) != pb:
            latched = True
            print(f"   latched after ~{(i+1)*60} ms")
            break
    cb2, pb2, ap2 = state("after the latch" if latched else "after ~12 s (no latch)")
    diverged_later = cb2 != pb2

    chk(latched,
        f"the queued change LATCHED (playing went ({pb},{ap_}) -> ({pb2},{ap2})) -- "
        f"GATE: without the latch, PLAY_BANK has not moved yet and comparing it to "
        f"CUR_BANK proves nothing in either direction")

    if not latched:
        print("   >> INCONCLUSIVE, not a pass: the boundary never arrived, so this run "
              "never entered the state the hypothesis is about. Do NOT read the "
              "agreement above as evidence.")
    elif diverged_now or diverged_later:
        print(f"   >> THE TWO DIVERGE (at queue time={diverged_now}, after the "
              f"latch={diverged_later}) -- CUR_BANK is NOT the playing bank, so a "
              f"reload taken in this state targets the wrong slab and the wrong .strd.")
    else:
        print("   >> they did NOT diverge even across the latch -- CUR_BANK tracked the "
              "performance change, so this window is not the cause.")

    # ---- the decisive test: which slab does the worker actually write? ----
    print("\n--- decisive: the worker must write the slab the SEQUENCER reads ---")
    banks_written = {}
    lo, hi = BLOB, BLOB + NBANKS * BANKSTRIDE
    # -- second, free measurement: is SCRATCH really private while the job runs? --
    # SCRATCH (0x460aff60) is OPEN_BUF + 0x7000, and OPEN_BUF is a STOCK buffer. All 14
    # stock users of 0x460a8f60 pass size 0x10000 (e.g. 0x4008fbde, 0x400916d4), so
    # SCRATCH sits 28 KB INSIDE stock's own 64 KB read window. Our source asserts it is
    # "idle while we hold the task" -- untested until now. Record every PC that writes
    # there during the job; anything outside our own cave is the hazard going live.
    scratch_pcs = {}

    def on_scratch(uc, access, address, size, value, ud):
        pc = uc.reg_read(er.eb.UC_M68K_REG_PC)
        scratch_pcs[pc] = scratch_pcs.get(pc, 0) + 1
        return True

    def on_write(uc, access, address, size, value, ud):
        if lo <= address < hi:
            off = address - BLOB
            b = off // BANKSTRIDE
            p = (off % BANKSTRIDE) // PATSTRIDE
            banks_written[(b, p)] = banks_written.get((b, p), 0) + size
        return True

    h = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=lo, end=hi - 1)
    h2 = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_scratch,
                        begin=SCRATCH, end=SCRATCH + PATSTRIDE - 1)
    key(PTN_CODE, PRESS)
    key(TRACK0 + a.track, PRESS)
    key(TRACK0 + a.track, RELEASE)
    key(PTN_CODE, RELEASE)
    for _ in range(250):
        rt.run(ms=10)
        if rb(G_KIND) == 0:
            break
    drain(10)
    rt.uc.hook_del(h)
    rt.uc.hook_del(h2)

    play_b, play_p = rb(PLAY_BANK), rb(ACT_PAT)
    tgt = (play_b, play_p)
    ranked = sorted(banks_written.items(), key=lambda kv: -kv[1])
    print(f"   sequencer is playing bank {play_b} pattern {play_p}")
    print(f"   BLOB writes during the job, by (bank,pattern): {ranked[:6]}")
    chk(bool(banks_written),
        f"the worker wrote SOMETHING into the blob ({len(banks_written)} slabs) -- "
        f"gate: the hook is live and the job ran")
    chk(tgt in banks_written,
        f"the worker wrote the PLAYING slab (bank {play_b}, pattern {play_p}) -- "
        f"this is what the user hears")
    stray = {k: v for k, v in banks_written.items() if k != tgt}
    chk(not stray,
        f"and wrote NO other slab ({stray if stray else 'none'}) -- a write to a "
        f"non-playing slab is a reload the user cannot hear, reported as success")

    print("\n--- hazard check: who writes SCRATCH while our job holds the task? ---")
    ours = {pc: n for pc, n in scratch_pcs.items() if CAVE_LO <= pc < CAVE_HI}
    stockw = {pc: n for pc, n in scratch_pcs.items() if not (CAVE_LO <= pc < CAVE_HI)}
    print(f"   writers from our cave: {[hex(x) for x in ours]}")
    print(f"   writers from stock   : {[hex(x) for x in stockw][:8]}"
          f"{' ...' if len(stockw) > 8 else ''}  ({len(stockw)} distinct PCs)")
    chk(bool(scratch_pcs),
        f"SCRATCH was written at all during the job ({sum(scratch_pcs.values())} "
        f"writes) -- gate: the hook is live and the parse really lands there")
    # PARSEPAT (0x4008cebc) is stock code we CALL, so stock PCs are expected; what
    # would be the hazard is a write from a DIFFERENT subsystem interleaving. Report,
    # do not fail: this run cannot prove absence under card contention.
    print("   NOTE stock PCs here are expected -- PARSEPAT (0x4008cebc) is stock code we "
          "call ourselves. This measures presence, and cannot prove SCRATCH stays "
          "private under real card contention; it is reported, not asserted.")

    print()
    if fails:
        print(f"   {len(fails)} FAILURE(S):")
        for f in fails:
            print(f"     - {f}")
        return 1
    print("   ALL GOOD -- the reload targets the slab the sequencer is actually reading.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

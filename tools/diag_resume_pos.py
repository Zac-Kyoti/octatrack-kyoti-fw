#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Where does each TRACK actually land after an armed DIRECT JUMP commit?  (Session 85)

Every test through Session 84 checked the MASTER counter (grid lock, playhead continuity) or
one cache (per-track scale). None checked the thing the user is actually reporting: the
per-track STEP positions after a switch between patterns with DIFFERENT MASTER SCALES.

The specification is AR's arithmetic, and nothing else (AR_DIRECT_JUMP.md section 7c):

    new_step = masterStep mod newMasterLen        AR 0x40099274
    pos_t    = new_step mod trackLen_t            AR 0x400992b6, per track

The track's RESOLUTION never enters the position -- on AR it sets only the track's rate.
Note this is NOT elapsed-time alignment: the two coincide only when the patterns share a
master scale, and reasoning in ticks here is a different machine's behaviour.

This computes that model in Python, straight from the pattern blob and from values captured
BEFORE the commit clobbers them, and compares it against the per-track STEP array the
firmware actually produces. The model is derived here independently of the patch's
arithmetic -- Session 79 cont.37 records what happens when a checker inherits the code's own
assumption (model and firmware agreed with each other while both were wrong).

Captured at 0x400a47f6 (Hook H's own site, before stock rebuilds anything):
  0x800065b2  masterStep -- the outgoing playhead
  0x8000663d  SCALE_IX   -- still the OUTGOING master scale index there (see Hook H)
Snapshotted at 0x400a4d36, after the commit body's audio+MIDI loops and its tail:
  0x800064d0[0..15]  per-track STEP (audio 0-7, MIDI 8-15)

DJTEST2 A07 (index 6, SCALE_MODE=1, MASTER 1x) <-> A08 (index 7, MASTER 2x) is the fixture
the user's report describes: two 16-step patterns differing only in master scale.

Usage:
  python3 tools/diag_resume_pos.py [--from-pattern N] [--to-pattern N] [--image F]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"

DJ_MODE = 0x800000D8
MASTER_STEP = 0x800065B2
SCALE_IX = 0x8000663D
STEP_ARR = 0x800064D0
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
ACT_PAT = 0x800065BE
LEN_TBL = 0x400ABA50
TICK_PC = 0x400A3FDC
HOOKH_PC = 0x400A47F6
AFTER_PC = 0x400A4D3C           # NOT 0x400a4d36: that address is Hook P's own `jsr`, and a
                                # code hook there fires BEFORE the hook body runs. Session 79
                                # cont.29 produced a false 16/16 this exact way (AR_DIRECT_JUMP
                                # section 8, "a snapshot at a hook's entry measures the state
                                # before that hook"). 0x400a4d3c is the instruction the jsr
                                # returns to, so the snapshot sees Hook P's output.
BLOB, BANK_STRIDE, PAT_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8
TRK_STRIDE, MIDI_OFF, MIDI_STRIDE = 0x91A, 0x48F8, 0x8B0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--from-pattern", type=int, default=6)
    ap.add_argument("--to-pattern", type=int, default=7)
    ap.add_argument("--pre", type=int, default=40)
    ap.add_argument("--frames", type=int, default=9000)
    ap.add_argument("--tree", default="out/_emu_respos")
    a = ap.parse_args(argv)

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(a.project, "OCTABAM", None, tree=a.tree)
    r, rt = er.attach(str(a.image), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    loaded = rt.load_project_live("OCTABAM", staged, run_ms=6000)
    bank = loaded[3]
    rt.seq_select_live(bank, a.from_pattern)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.uc.mem_write(DJ_MODE, (1).to_bytes(4, "big"))

    st = dict(tick=0, cued=None, pre=None, snap=None, acts=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["cued"] is None and st["tick"] >= a.pre:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
        ap_ = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap_:
            st["acts"].append((st["tick"], ap_))

    def on_hookh(u, addr, size, user):
        if st["pre"] is None and st["cued"] is not None:
            st["pre"] = (int.from_bytes(bytes(u.mem_read(MASTER_STEP, 2)), "big"),
                         bytes(u.mem_read(SCALE_IX, 1))[0])

    def on_after(u, addr, size, user):
        if st["snap"] is None and st["pre"] is not None \
                and bytes(u.mem_read(ACT_PAT, 1))[0] == a.to_pattern:
            st["snap"] = list(bytes(u.mem_read(STEP_ARR, 16)))

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hookh, begin=HOOKH_PC, end=HOOKH_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_after, begin=AFTER_PC, end=AFTER_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]

    def fields(pat):
        base = BLOB + bank * BANK_STRIDE + pat * PAT_STRIDE
        sm = rd(base + 0x8E55, 1)[0]
        mlen = rd(base + 0x8E51, 1)[0] if sm else rd(base + 0x8E53, 1)[0]
        msc = rd(base + 0x8E52, 1)[0] if sm else rd(base + 0x8E54, 1)[0]
        tr = []
        for i in range(16):
            if sm:
                if i < 8:
                    rr = base + i * TRK_STRIDE
                    ln, sc = rd(rr + 0x50, 1)[0], rd(rr + 0x51, 1)[0]
                else:
                    rr = base + MIDI_OFF + (i - 8) * MIDI_STRIDE
                    ln, sc = rd(rr, 1)[0], rd(rr + 1, 1)[0]
            else:
                ln, sc = rd(base + 0x8E53, 1)[0], rd(base + 0x8E54, 1)[0]
            tr.append((ln, sc))
        return sm, mlen, msc, tr

    sm_t, mlen_t, msc_t, tr_t = fields(a.to_pattern)
    print(f"image   {a.image}")
    print(f"project {a.project}  bank {bank}   pattern {a.from_pattern} -> {a.to_pattern}")
    print(f"  incoming: SCALE_MODE={sm_t} MASTER LEN={mlen_t} MASTER SCALE idx={msc_t} "
          f"(tps {tbl[msc_t] if msc_t < 12 else '?'})")
    print(f"  cued tick {st['cued']}   ACT_PAT changes {st['acts']}")

    if st["pre"] is None or st["snap"] is None:
        print("\n** NO ARMED COMMIT OBSERVED -- result proves nothing. Raise --frames.")
        return 2

    ms, six = st["pre"]
    new_step = ms % mlen_t if mlen_t else ms
    print(f"\ncaptured at Hook H: masterStep={ms}  (SCALE_IX={six}, not used by AR's rule)")
    print(f"  new_step = {ms} mod {mlen_t} = {new_step}        <- AR 0x40099274")

    print(f"\n  {'trk':>4} {'len':>4} {'want':>5} {'got':>5}")
    bad = []
    for i in range(16):
        ln, sc = tr_t[i]
        want = (new_step % ln) if ln else 0        # AR 0x400992b6 -- LENGTH only, no tps
        got = st["snap"][i]
        flag = "" if want == got else "  <-- MISMATCH"
        if want != got:
            bad.append(i)
        kind = f"T{i}" if i < 8 else f"M{i-8}"
        print(f"  {kind:>4} {ln:>4} {want:>5} {got:>5}{flag}")
    if bad:
        print(f"\n  ** {len(bad)}/16 tracks do not match AR's rule: {bad}")
        return 1
    print("\n  16/16 tracks match AR's `new_step mod trackLen`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

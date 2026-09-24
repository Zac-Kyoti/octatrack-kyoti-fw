#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Is the LIVE per-track scale cache stale after a DIRECT JUMP commit?  (Session 84)

Hardware report on the Session 83 AR-port build: two patterns of equal master length and
scale switch correctly, but giving a track a DIFFERENT SCALE on the target pattern brings
back both a fractional-step symptom and a permanent step-count offset.

Suspected mechanism, and it is a gap in the AR port rather than a new bug:

  * `TRK_SCALE_IX` (`0x8000663e[t]`, MIDI twin `0x80006646[t]`) is the LIVE per-track scale
    index. The per-track wrap check at `0x400a3cee` compares that track's tick counter
    against `LEN_TBL[TRK_SCALE_IX[t]]`, so THIS is what sets each track's real tick rate.
  * Stock refreshes it only LAZILY -- at `0x400a3d08` / `0x400a3d0e`, reached only when a
    track's tick counter wraps. An image-wide scan finds writers ONLY at `0x4009b6e6`
    (sequencer init), `0x400a292a` / `0x400a2970`, and `0x400a3cb4` (that lazy per-tick
    loop). The commit path `0x400a4884..0x400a4be6` NEVER writes it.
  * So after a mid-pattern commit every track keeps running at the OUTGOING pattern's
    ticks-per-step until it next wraps -- a wrong rate for up to a full track cycle, which
    is exactly "between steps" plus a permanent offset afterwards.
  * AR does NOT have this gap: its commit rebuilds `0x40566775[t]`, "per-track resolution
    index", for all 13 tracks (AR_DIRECT_JUMP.md 2, inventory row 5). The Session 83 port
    carried over AR's POSITION but not its RESOLUTION CACHE.

Note stock's rebuild loop reads the per-track scale correctly for its OWN math at
`0x400a4900` (`SCALE_MODE ? blob[t][+0x51] : pattern[+0x8e54]`), so NEXT_STEP / PAIR /
CNTDN_TBL are all computed against the right scale. Only the live cache is stale, which is
why the landing positions look right and the playback rate does not.

This measures the mechanism directly: snapshot `TRK_SCALE_IX` right after an armed commit
and compare it against the incoming pattern's own per-track scale bytes.

DJTEST2 bank 0: pattern index 0 is all-tracks 1x (scale idx 2, tps 6), index 1 is
all-tracks 2x (scale idx 0, tps 3) -- a real hardware-exported fixture for exactly this.

Usage:
  python3 tools/diag_trkscale.py [--from-pattern N] [--to-pattern N] [--image F]
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED = ROOT / "out" / "mainos_directjump_v4.bin"

DJ_MODE = 0x800000D8
TRK_SCALE_IX = 0x8000663E      # live per-track scale index, audio t0..t7
MIDI_SCALE_IX = 0x80006646     # its MIDI twin
TICK_CTR = 0x800065B6
PEND_PAT, PEND_BANK = 0x800065C0, 0x800065BF
ACT_PAT = 0x800065BE
LEN_TBL = 0x400ABA50
TICK_PC = 0x400A3FDC
COMMIT_DONE_PC = 0x400A4D36    # after the boundary body's audio+MIDI rebuild loops
BLOB, BANK_STRIDE, PAT_STRIDE = 0x400E21E0, 0x9B340, 0x8ED8
TRK_STRIDE, MIDI_OFF, MIDI_STRIDE = 0x91A, 0x48F8, 0x8B0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(PATCHED))
    ap.add_argument("--project", default=str(pathlib.Path.home() / "Desktop" / "DJTEST2"))
    ap.add_argument("--from-pattern", type=int, default=0)
    ap.add_argument("--to-pattern", type=int, default=1)
    ap.add_argument("--pre", type=int, default=40)
    ap.add_argument("--frames", type=int, default=9000)
    ap.add_argument("--tree", default="out/_emu_trkscale")
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

    st = dict(tick=0, cued=None, snap=None, snap_tick=None, acts=[])

    def on_tick(u, addr, size, user):
        st["tick"] += 1
        if st["cued"] is None and st["tick"] >= a.pre:
            u.mem_write(PEND_BANK, bytes([bank]))
            u.mem_write(PEND_PAT, bytes([a.to_pattern]))
            st["cued"] = st["tick"]
        ap_ = bytes(u.mem_read(ACT_PAT, 1))[0]
        if not st["acts"] or st["acts"][-1][1] != ap_:
            st["acts"].append((st["tick"], ap_))

    def on_commit(u, addr, size, user):
        # first pass through the post-rebuild point after ACT_PAT has become the target
        if st["snap"] is None and bytes(u.mem_read(ACT_PAT, 1))[0] == a.to_pattern:
            st["snap"] = (bytes(u.mem_read(TRK_SCALE_IX, 8)),
                          bytes(u.mem_read(MIDI_SCALE_IX, 8)))
            st["snap_tick"] = st["tick"]

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_tick, begin=TICK_PC, end=TICK_PC)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_commit, begin=COMMIT_DONE_PC, end=COMMIT_DONE_PC)

    rt.start_transport_live()
    target = rt.frame_count + a.frames
    while rt.frame_count < target:
        rt.run(ms=60)

    rd = lambda ad, n: bytes(rt.uc.mem_read(ad, n))
    tbl = [int.from_bytes(rd(LEN_TBL + 4 * i, 4), "big") for i in range(12)]
    tps = lambda i: tbl[i] if i < 12 else None

    def want(pat):
        base = BLOB + bank * BANK_STRIDE + pat * PAT_STRIDE
        smode = rd(base + 0x8E55, 1)[0]
        dflt = rd(base + 0x8E54, 1)[0]
        au = [rd(base + t * TRK_STRIDE + 0x51, 1)[0] if smode else dflt for t in range(8)]
        mi = [rd(base + MIDI_OFF + m * MIDI_STRIDE + 1, 1)[0] if smode else dflt
              for m in range(8)]
        return smode, au, mi

    smode_f, au_f, _ = want(a.from_pattern)
    smode_t, au_t, mi_t = want(a.to_pattern)

    print(f"image   {a.image}")
    print(f"project {a.project}  bank {bank}   pattern {a.from_pattern} -> {a.to_pattern}")
    print(f"  FROM pattern: SCALE_MODE={smode_f} per-track scale idx {au_f} "
          f"(tps {[tps(i) for i in au_f]})")
    print(f"  TO   pattern: SCALE_MODE={smode_t} per-track scale idx {au_t} "
          f"(tps {[tps(i) for i in au_t]})")
    print(f"\ncued at tick {st['cued']}   ACT_PAT changes {st['acts']}")

    if st["snap"] is None:
        print("\n** NO COMMIT OBSERVED -- result proves nothing. Raise --frames.")
        return 2

    got_a, got_m = st["snap"]
    print(f"\nsnapshot taken at tick {st['snap_tick']}, right after the commit's rebuild loops")
    print(f"  TRK_SCALE_IX audio : got {list(got_a)}  want {au_t}")
    print(f"  TRK_SCALE_IX MIDI  : got {list(got_m)}  want {mi_t}")
    bad_a = [t for t in range(8) if got_a[t] != au_t[t]]
    bad_m = [m for m in range(8) if got_m[m] != mi_t[m]]
    if bad_a or bad_m:
        print(f"\n  ** STALE: audio tracks {bad_a}, MIDI tracks {bad_m} still hold the "
              f"OUTGOING pattern's scale.")
        for t in bad_a:
            print(f"     T{t}: cache says idx {got_a[t]} (tps {tps(got_a[t])}), "
                  f"pattern says idx {au_t[t]} (tps {tps(au_t[t])}) "
                  f"-> runs at the wrong rate until it next wraps")
        return 1
    print("\n  OK: the live per-track scale cache matches the incoming pattern on all 16.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

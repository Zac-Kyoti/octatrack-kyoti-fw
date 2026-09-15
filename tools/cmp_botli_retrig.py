#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 56: frame-by-frame T1 raw-voice-source comparison between two
`ot_emu --block-dump` captures of the BOTLI retrig scenario (Session 55
continued / Session 56, NOTES.md) -- a muted-from-frame-5, forced-retrig-at-
frame-441 run vs an unmuted control. Reuses octabam's own `blockdump.py` /
`o10_recloop.py` decode (`track_audio`'s per-record parse), NOT aggregate
RMS/nonzero-count -- Session 55 continued already found aggregate metrics
hide a real, working fade (`pre`'s ramp) and can't be trusted for this class
of comparison.

    python3 tools/cmp_botli_retrig.py CTRL.dump MUTED.dump [FIRST] [LAST]

Prints per-frame peak dBFS for both captures and whether the raw records are
byte-identical, over [FIRST, LAST] (default 435..460, bracketing the known
frame-441 retrig).
"""
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(OCTABAM / "tools"))
sys.path.insert(0, str(OCTABAM / "tools" / "scratch"))
import toolpath          # noqa: E402,F401
import blockdump as bd   # noqa: E402
import o10_recloop as rl  # noqa: E402


def db(x):
    return 20 * math.log10(x / 8388608) if x > 0 else -200


def per_frame_records(path, track=1):
    """Raw voice-source ('src' in Session 55's own naming) -- the voice
    generator's own output, upstream of the track's FX chain and the
    mute-gate mixing that applies after it."""
    c = bd.classes(bd.read(path))
    core = 0 if track >= 5 else 1
    pos = (track - 1) % 4
    addrs = {1: (0x80001c90, 0x80002710), 0: (0x800021d0, 0x80002c50)}[core]
    rec = sorted(sum((c.get(('>', 0, core, a), []) for a in addrs), []))
    out = {}
    for frame, w in rec:
        ws = rl.words(w)
        out[frame] = rl.record_audio(ws[pos * 84:(pos + 1) * 84])
    return out


def per_frame_readback(path, track=1, right=False):
    """Chain OUTPUT ('rb' in Session 55's own naming) -- the track's post-FX
    contribution just before the master mix. This is the signal that
    actually determines audibility; track_audio/per_frame_records can stay
    fully "live" (the voice generator's own output) while this stays gated,
    if the mute mechanism works at the mix stage rather than the source."""
    c = bd.classes(bd.read(path))
    core = 0 if track >= 5 else 1
    pos = (track - 1) % 4
    o = 1 if right else 0
    addrs = {1: (0x80003190, 0x80003590), 0: (0x80003390, 0x80003790)}[core]
    rb = sorted(sum((c.get(('<', 1, core, a), []) for a in addrs), []))
    out = {}
    for frame, w in rb:
        ws = rl.words(w)
        out[frame] = ws[pos * 32 + o: pos * 32 + 32: 2]
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ctrl_path, muted_path = sys.argv[1], sys.argv[2]
    lo = int(sys.argv[3]) if len(sys.argv) > 3 else 435
    hi = int(sys.argv[4]) if len(sys.argv) > 4 else 460

    src_ctrl = per_frame_records(ctrl_path)
    src_muted = per_frame_records(muted_path)
    rb_ctrl = per_frame_readback(ctrl_path)
    rb_muted = per_frame_readback(muted_path)
    frames = sorted(set(src_ctrl) & set(src_muted) & set(rb_ctrl) & set(rb_muted))
    print(f"{len(frames)} common frames")
    print(f"{'frame':>6} {'src_ctrl':>9} {'src_muted':>10} {'src=?':>6}"
          f"   {'rb_ctrl':>8} {'rb_muted':>9} {'rb=?':>5}")
    for f in frames:
        if lo <= f <= hi:
            sc, sm = src_ctrl[f], src_muted[f]
            rc, rm = rb_ctrl[f], rb_muted[f]
            scpk = max((abs(x) for x in sc), default=0)
            smpk = max((abs(x) for x in sm), default=0)
            rcpk = max((abs(x) for x in rc), default=0)
            rmpk = max((abs(x) for x in rm), default=0)
            print(f"{f:6d} {db(scpk):9.1f} {db(smpk):10.1f} {str(sc == sm):>6}"
                  f"   {db(rcpk):8.1f} {db(rmpk):9.1f} {str(rc == rm):>5}")


if __name__ == "__main__":
    main()

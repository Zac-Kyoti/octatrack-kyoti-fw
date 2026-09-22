#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 57: compare the REAL ESAI audio output (`ot_emu --audio-out`) of two or
more BOTLI-retrig runs, per sequencer frame.

Why this exists: `tools/cmp_botli_retrig.py` reads the host-port block dumps --
`src` (the voice generator's own record) and `rb` (the per-track chain output
before the master mix). Session 57 established that NEITHER can see the mute
gate: a stock-OT hard-muted run (GATE=0 + MUTE_STATE bit set), which is muted
by FUN_40004dbc zeroing the frame level word, comes back byte-identical to an
unmuted control in BOTH of those signals. The frame level word is applied
downstream of both capture points, so only the ESAI output -- what the codec
actually receives -- shows whether a track is audible.

    python3 tools/cmp_botli_audio.py REF.wav OTHER.wav [OTHER2.wav ...] \
        [--first N] [--last N] [--start ESAI_FRAME] [--slots 2,3,4,5]

Per sequencer frame (16 ESAI frames each, counted from --start, default 279380
= the transport start ot_emu itself reports), prints peak dBFS per run for the
summed selected slots, plus whether each run's samples are byte-identical to
the reference over that frame.
"""
import argparse
import math
import pathlib
import struct
import sys
import wave

FRAME = 16            # ESAI frames per sequencer frame
TRANSPORT = 279380    # ot_emu's own reported transport start, this scenario


def read_wav24(path):
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width != 3:
        sys.exit(f"{path}: expected 24-bit, got {width * 8}-bit")
    out = []
    for i in range(0, len(raw), 3):
        v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
        out.append(v - (1 << 24) if v >= (1 << 23) else v)
    return out, ch, rate


def db(x):
    return 20 * math.log10(x / 8388608) if x > 0 else -200


def frame_slice(pcm, ch, slots, seqframe, start):
    base = (start + seqframe * FRAME) * ch
    vals = []
    for f in range(FRAME):
        o = base + f * ch
        if o + ch > len(pcm):
            break
        vals.append(sum(pcm[o + s] for s in slots))
    return vals


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("wavs", nargs="+", help="first is the reference")
    ap.add_argument("--first", type=int, default=435)
    ap.add_argument("--last", type=int, default=460)
    ap.add_argument("--start", type=int, default=TRANSPORT)
    ap.add_argument("--slots", default="2,3,4,5")
    a = ap.parse_args()

    slots = [int(s) for s in a.slots.split(",")]
    runs = []
    for p in a.wavs:
        pcm, ch, rate = read_wav24(pathlib.Path(p))
        runs.append((pathlib.Path(p).stem, pcm, ch))
    names = [n for n, _, _ in runs]

    print(f"slots {slots}, transport start ESAI frame {a.start}, {FRAME} ESAI frames per seq frame")
    head = f"{'frame':>6}"
    for n in names:
        head += f" {n[-14:]:>15}"
    for n in names[1:]:
        head += f" {'=ref?':>6}"
    print(head)

    for sf in range(a.first, a.last + 1):
        cols, ident = [], []
        ref = None
        for i, (n, pcm, ch) in enumerate(runs):
            vals = frame_slice(pcm, ch, slots, sf, a.start)
            if i == 0:
                ref = vals
            else:
                ident.append(vals == ref)
            pk = max((abs(v) for v in vals), default=0)
            cols.append(db(pk))
        row = f"{sf:6d}" + "".join(f" {c:15.1f}" for c in cols)
        row += "".join(f" {str(x):>6}" for x in ident)
        print(row)


if __name__ == "__main__":
    main()

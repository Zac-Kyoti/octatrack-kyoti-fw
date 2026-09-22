#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 58 part 18 addendum 12: the SAFETY check for adding a MUTE MODE value.

The project's standing rule for this work (addendum 10) is that any change must leave the
already-working modes BIT-IDENTICAL when the new mode is not selected -- not "sounds the
same", not "same RMS", sample-exact across every ESAI slot. That matters here because this
region is timing-sensitive: addendum 10 measured a real perturbation (0.994 correlation at
zero lag, same energy, no time shift) from adding ~3 instructions per track per frame, and
the emulator was separately confirmed deterministic (two renders of one build: max|diff| 0),
so a non-zero diff is a real regression and never noise.

    python3 tools/cmp_render_exact.py REF_PREFIX NEW_PREFIX [...]

Each argument is an `emu_echo_dsp.py --label` prefix (or a path to the _core0.wav itself);
pairs are compared REF vs NEW in order. Prints max|diff| and the first differing sample per
slot, and exits non-zero if any pair differs.
"""
import pathlib
import sys
import wave

import numpy as np

OUTDIR = pathlib.Path(__file__).resolve().parents[1] / "refs/octabam/out"


def wav_path(arg):
    p = pathlib.Path(arg)
    if p.suffix == ".wav":
        return p
    for cand in (OUTDIR / f"echo_{arg}_core0.wav", OUTDIR / f"{arg}_core0.wav", pathlib.Path(f"{arg}_core0.wav")):
        if cand.exists():
            return cand
    sys.exit(f"no wav for {arg!r}")


def load(path):
    w = wave.open(str(path), "rb")
    nch, sw, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
    raw = w.readframes(n)
    w.close()
    if sw != 3:
        sys.exit(f"{path}: unexpected sample width {sw}")
    buf = np.frombuffer(raw, dtype=np.uint8).reshape(-1, nch, 3).astype(np.int32)
    val = buf[:, :, 0] | (buf[:, :, 1] << 8) | (buf[:, :, 2] << 16)
    return np.where(val & 0x800000, val - 0x1000000, val)


def compare(ref_arg, new_arg):
    rp, np_ = wav_path(ref_arg), wav_path(new_arg)
    a, b = load(rp), load(np_)
    print(f"\n{ref_arg}  vs  {new_arg}")
    if a.shape != b.shape:
        print(f"  SHAPE MISMATCH {a.shape} vs {b.shape} -- not comparable")
        return False
    n, slots = a.shape
    d = np.abs(a - b)
    worst = int(d.max())
    print(f"  {n} samples x {slots} slots, integer-exact comparison")
    for s in range(slots):
        ds = d[:, s]
        m = int(ds.max())
        if m:
            first = int(np.nonzero(ds)[0][0])
            print(f"    slot{s}: max|diff| = {m:>8}   first differing sample {first} "
                  f"({100.0 * first / n:.1f}% in)   {int((ds > 0).sum())} samples differ")
        else:
            print(f"    slot{s}: max|diff| = {m:>8}   BIT-IDENTICAL")
    print(f"  => {'BIT-IDENTICAL' if worst == 0 else f'DIFFERS (max|diff| = {worst})'}")
    return worst == 0


def main():
    args = sys.argv[1:]
    if len(args) < 2 or len(args) % 2:
        sys.exit(__doc__)
    ok = all([compare(args[i], args[i + 1]) for i in range(0, len(args), 2)])
    print("\nALL PAIRS BIT-IDENTICAL" if ok else "\nAT LEAST ONE PAIR DIFFERS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

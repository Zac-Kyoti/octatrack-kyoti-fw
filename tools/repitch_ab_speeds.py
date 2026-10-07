#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
RPSP stereo options at several speeds (listening pack 7): for each source and QUAN
ratio, the clean reference, mid + side (rev 17 as built), the left channel in mono and
the (L + R) / 2 sum in mono, each through the SP path and channel 5. Rendered by the
float design (tools/repitch_engine_model.py; the DSP matches it to -114 dBFS) at the
OT's own increment (24.24 with the mode tag), sliced in eighth notes as the other packs.

    python3 tools/repitch_ab_speeds.py OUTDIR name=source.wav[,...] --bpm 104
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import repitch_ab_pack as p              # noqa: E402
import repitch_engine_model as m         # noqa: E402

SR = 44100
RATIOS = (("3/4", 0.75), ("1/1", 1.0), ("5/4", 1.25), ("3/2", 1.5))


def tagged(ratio):
    inc = int(round(ratio * (1 << 24)))
    return ((inc >> 24 << 24) | ((inc & 0xFFFFFF) & ~3) | m.MODE_RPSP) / float(1 << 24)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("sources", nargs="+", help="name=file.wav")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--avg", action="store_true", help="pack 8: mid + side before and after the side average")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    p.configure(taps=8, L=10)
    manifest = []
    for spec in a.sources:
        name, path = spec.split("=", 1)
        src = p.read_wav(path)
        for label, ratio in RATIOS:
            r = tagged(ratio)
            slice_len = SR * 60.0 / a.bpm / 2
            n_out = int((len(src) - 64) / r) // 16 * 16
            trig = [t for t in (int(round(j * slice_len / r)) for j in range(int(len(src) / slice_len) + 1)) if t < n_out]
            mid = (src[:, :1] + src[:, 1:]) / 2
            if a.avg:
                m.Engine.side_avg = False
                prev = p.run(m.MODE_RPSP, src, r, trig, ms=True)
                m.Engine.side_avg = True
                clips = {"ref": p.rpch(src, r, n_out), "ms": prev, "msavg": p.run(m.MODE_RPSP, src, r, trig, ms=True)}
            else:
                clips = {
                    "ref": p.rpch(src, r, n_out),
                    "ms": p.run(m.MODE_RPSP, src, r, trig, ms=True),
                    "monol": p.run(m.MODE_RPSP, np.repeat(src[:, :1], 2, axis=1), r, trig, ms=True),
                    "monos": p.run(m.MODE_RPSP, np.repeat(mid, 2, axis=1), r, trig, ms=True),
                }
            target = p.active_rms(clips["ref"])
            g = {k: target / p.active_rms(y) for k, y in clips.items()}
            trim = min(1.0, 0.89 / max(np.abs(y).max() * g[k] for k, y in clips.items()))
            for k, y in clips.items():
                f = f"{name}_{label.replace('/', '-')}_{k}.wav"
                p.write_wav(out / f, y * g[k] * trim)
                manifest.append(dict(source=name, ratio=label, key=k, file=f, gain_db=round(20 * math.log10(g[k] * trim), 2)))
            print(f"{name} {label}: done", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()

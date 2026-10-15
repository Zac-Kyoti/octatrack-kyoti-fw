#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
VARISPEED_EMUS listening check: the three engines (OT, S950, SP12) at several project tempos on
the two pack-10 loops, rendered the way the unit renders them.

  * The increment is the firmware's: floor(2^26 * T / S) in Q26 (T, S = project and sample
    BPM x 24), bits 0-3 cleared and the engine tagged in bits 2-3, then the DSP's net >> 2
    (24.24).
  * S950 and SP12 use the DSP-exact twin (repitch_engine_model.DspExact), which
    tools/repitch_dsp_engine_check.py holds bit-for-bit to the kernel the unit runs. OT is the
    stock DSP read: 2-tap linear at the same 24.24 positions.
  * One trig at the start of the loop, AMP held at 0.95: a loop played once, as from a
    sequencer trig.
  * One common gain per source, the same for every engine and tempo, so the engines' relative
    levels are the unit's.

    python3 tools/varispeed_emus_listen.py OUTDIR beat=beat.wav wide=wide.wav --bpm 104
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import repitch_ab_pack as p              # noqa: E402  (read_wav / write_wav)
import repitch_dsp_engine_check as ec    # noqa: E402  (exact_for)
import repitch_dsp_src as dsrc           # noqa: E402
import repitch_engine_model as m         # noqa: E402

TEMPOS = (78, 104, 130, 156)            # project BPM against a 104 BPM loop: 3/4, 1/1, 5/4, 3/2
ENGINES = (("OT", 0), ("S950", m.MODE_RPS9), ("SP12", m.MODE_RPSP))


def increment(project_bpm, sample_bpm, mode):
    T, S = int(round(project_bpm * 24)), int(round(sample_bpm * 24))
    q26 = (0x04000000 * T) // S
    q26 = min(q26, 0x07FFFFF0)
    q26 = (q26 & ~0xF) | (mode << 2)
    return q26 >> 2                    # the DSP's 24.24 increment, the engine in its low 2 bits


def render(src, inc, mode):
    x = np.clip(np.round(src * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64)
    rint, tagged = inc >> 24, inc & 0xFFFFFF
    frames = len(x)
    if mode == 0:                      # OT: the stock 2-tap read
        n = int((frames - 3) * (1 << 24) // inc) // 16 * 16
        pos = np.arange(n, dtype=np.int64) * inc
        i, f = pos >> 24, (pos & 0xFFFFFF)[:, None] / float(1 << 24)
        y = x[i] + (x[i + 1] - x[i]) * f
        return y / float(1 << 23)
    eng = m.DspExact(mode, *ec.exact_for(mode, dsrc.constants("A")), ch12=dsrc.CH12)
    level = int(round(0.95 * (1 << 23)))
    out, pos, written, f = [], 0, 0, 0
    while True:
        last = pos + 15 * inc
        need = (last >> 24) + 1 + (1 if last & 0xFFFFFF else 0)
        if need + 1 > frames:
            break
        if need > written:
            eng.fill(written, x[written:need])
            written = need
        table = [(((pos + i * inc) >> 24) % 64, (pos + i * inc) & 0xFFFFFF) for i in range(16)]
        out.append(eng.render(table, rint, tagged, 0x1000 if f == 0 else 0, level, 1))
        pos += 16 * inc
        f += 1
    return np.concatenate(out).astype(float) / (1 << 23)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("sources", nargs="+", help="name=file.wav")
    ap.add_argument("--bpm", type=float, required=True, help="the loops' own tempo")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for spec in a.sources:
        name, path = spec.split("=", 1)
        src = p.read_wav(path)
        clips = {}
        for bpm in TEMPOS:
            for eng, mode in ENGINES:
                inc = increment(bpm, a.bpm, mode)
                clips[(bpm, eng)] = (render(src, inc, mode), inc)
                print(f"{name} {bpm} BPM {eng}: inc 0x{inc:08x}", flush=True)
        peak = max(np.abs(y).max() for y, _ in clips.values())
        g = min(1.0, 0.89 / peak)
        for (bpm, eng), (y, inc) in clips.items():
            f = f"{name}_{bpm}_{eng}.wav"
            p.write_wav(out / f, y * g)
            manifest.append(dict(source=name, bpm=bpm, engine=eng, file=f, inc=f"0x{inc:08x}",
                                 gain_db=round(20 * math.log10(g), 2)))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()

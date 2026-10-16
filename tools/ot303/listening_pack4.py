#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 2: listening pack round 4 -- the top end, then the corrector.
#   pick   Hot, Accents: Open303 as shipped vs the DSP voice with the safe resonance curve
#          (ktab 4.5) and the circuit accent charging in 25 ms or 12 ms (shuffled letters)
#   ABX    the 12 ms voice with vs without the Heun corrector (Hot, Sweep)
import json, os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = os.path.join(ROOT, 'out', 'ot303', 'top'); VO = os.path.join(ROOT, 'out', 'ot303', 'voicing')
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100; SECONDS = 10.0
START = {'hot': 2.0, 'accents': 2.0, 'sweep': 5.6}
CLIPS = [
    ('hot', 'o303', os.path.join(VO, 'hot.o303-4-ell.f32')), ('hot', 'c25', os.path.join(T, 'hot.tc25-d0.5.f32')),
    ('hot', 'c12', os.path.join(T, 'hot.tc12-d0.5.f32')), ('hot', 'c12h0', os.path.join(T, 'hot.C3h0.f32')),
    ('accents', 'o303', os.path.join(VO, 'accents.o303-4-ell.f32')), ('accents', 'c25', os.path.join(T, 'accents.tc25-d0.5.f32')),
    ('accents', 'c12', os.path.join(T, 'accents.tc12-d0.5.f32')),
    ('sweep', 'c12', os.path.join(T, 'sweep.C3h1.f32')), ('sweep', 'c12h0', os.path.join(T, 'sweep.C3h0.f32')),
]


def main():
    os.makedirs(os.path.join(OUT, 'clips4'), exist_ok=True)
    rng = np.random.default_rng(3034); xs = []
    for sc, key, path in CLIPS:
        x = np.fromfile(path, dtype=np.float32).astype(np.float64)
        a = int(START[sc] * FS); x = x[a:a + int(SECONDS * FS)]; x = x / np.sqrt(np.mean(x ** 2))
        n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]; xs.append((sc, key, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs)
    target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)
    for sc, key, x in xs:
        pcm = x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))
        pcm = np.clip(np.round(pcm), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips4', f'{sc}-{key}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    print(f'{len(xs)} clips at {20*np.log10(target):.1f} dBFS RMS, loudest peak {20*np.log10(crest*target):.1f} dBFS')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 Phase 2: listening pack round 3 -- the DSP twin.
#   ABX 1  the DSP twin (2x, BLEP osc, closed-form ladder, half-band, tables, 24-bit) vs the
#          approved voice (double precision, matrix solve, Kaiser decimator); both with the
#          resonance ceiling k = 16.5 and the circuit accent
#   ABX 2  the twin with vs without the Heun corrector (decides ~40% of the filter's cost)
#   pref   Hot: the twin vs Open303 as shipped
# Renders in out/ot303/p2 (`.K.` = k ceiling 16.5) and out/ot303/voicing (Open303 as shipped).
import json, os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P2 = os.path.join(ROOT, 'out', 'ot303', 'p2'); VO = os.path.join(ROOT, 'out', 'ot303', 'voicing')
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100; SECONDS = 10.0
START = {'hot': 2.0, 'sweep': 5.6}
CLIPS = [  # (scene, key, path)
    ('hot', 'approved', os.path.join(P2, 'hot.K.R0.f32')), ('hot', 'twin', os.path.join(P2, 'hot.K.S6.f32')),
    ('hot', 'twin_h0', os.path.join(P2, 'hot.K.S6h0.f32')), ('hot', 'o303', os.path.join(VO, 'hot.o303-4-ell.f32')),
    ('sweep', 'approved', os.path.join(P2, 'sweep.K.R0.f32')), ('sweep', 'twin', os.path.join(P2, 'sweep.K.S6.f32')),
    ('sweep', 'twin_h0', os.path.join(P2, 'sweep.K.S6h0.f32')),
]


def main():
    os.makedirs(os.path.join(OUT, 'clips3'), exist_ok=True)
    rng = np.random.default_rng(3033)
    xs = []
    for sc, key, path in CLIPS:
        x = np.fromfile(path, dtype=np.float32).astype(np.float64)
        a = int(START[sc] * FS); x = x[a:a + int(SECONDS * FS)]
        x = x / np.sqrt(np.mean(x ** 2))
        n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
        xs.append((sc, key, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs)
    target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)
    for sc, key, x in xs:
        pcm = x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))
        pcm = np.clip(np.round(pcm), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips3', f'{sc}-{key}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    print(f'{len(xs)} clips at {20*np.log10(target):.1f} dBFS RMS, loudest peak {20*np.log10(crest*target):.1f} dBFS')


if __name__ == '__main__':
    main()

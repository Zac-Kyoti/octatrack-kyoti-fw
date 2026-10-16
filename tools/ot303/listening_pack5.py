#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 2: listening pack round 5 -- confirmation of the final voicing against Open303.
# Final voicing (out/ot303/final/*.final.f32): 2x, no Heun, stage saturation 0.5, k = min(16.998792 r,
# 16.5) + ktab 4.5 above ~2 kHz, circuit accent charging in 25 ms (150 ms discharge).
import os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FI = os.path.join(ROOT, 'out', 'ot303', 'final'); VO = os.path.join(ROOT, 'out', 'ot303', 'voicing')
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100; SECONDS = 10.0
CLIPS = [('accents', 'o303', os.path.join(VO, 'accents.o303-4-ell.f32')), ('accents', 'final', os.path.join(FI, 'accents.final.f32')),
         ('squelch', 'o303', os.path.join(VO, 'squelch.o303-4-ell.f32')), ('squelch', 'final', os.path.join(FI, 'squelch.final.f32'))]


def main():
    os.makedirs(os.path.join(OUT, 'clips5'), exist_ok=True)
    rng = np.random.default_rng(3035); xs = []
    for sc, key, path in CLIPS:
        x = np.fromfile(path, dtype=np.float32).astype(np.float64)[int(2.0 * FS):int(2.0 * FS) + int(SECONDS * FS)]
        x = x / np.sqrt(np.mean(x ** 2)); n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
        xs.append((sc, key, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs); target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)
    for sc, key, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips5', f'{sc}-{key}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    print(f'{len(xs)} clips at {20*np.log10(target):.1f} dBFS RMS')


if __name__ == '__main__':
    main()

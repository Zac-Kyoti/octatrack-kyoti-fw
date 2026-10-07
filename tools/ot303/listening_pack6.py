#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 Phase 2: listening pack round 6 -- Open303's own algorithm as the DSP will run it
# (o303q: the TB_303 filter transcribed, 4x, BLEP oscillator, 23+79-tap half-bands, tables, 24-bit),
# plus a fixed one-pole top rounding (on the DSP: folded into the decimator).
#   pick  Hot: Open303 as shipped vs DSP + rounding 16 kHz vs DSP + rounding 13 kHz
#   ABX   Squelch, Accents: Open303 as shipped vs DSP + rounding 13 kHz
import os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
O3 = os.path.join(ROOT, 'out', 'ot303', 'o3'); OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100; SECONDS = 10.0
CLIPS = [('hot', 'o303', 'hot.O0'), ('hot', 'r16', 'hot.O4t16000'), ('hot', 'r13', 'hot.O4t13000'),
         ('squelch', 'o303', 'squelch.O0'), ('squelch', 'r13', 'squelch.O4t13000'),
         ('accents', 'o303', 'accents.O0'), ('accents', 'r13', 'accents.O4t13000')]


def main():
    os.makedirs(os.path.join(OUT, 'clips6'), exist_ok=True)
    rng = np.random.default_rng(3036); xs = []
    for sc, key, f in CLIPS:
        x = np.fromfile(os.path.join(O3, f + '.f32'), dtype=np.float32).astype(np.float64)[int(2.0 * FS):int(2.0 * FS) + int(SECONDS * FS)]
        x = x / np.sqrt(np.mean(x ** 2)); n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
        xs.append((sc, key, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs); target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)
    for sc, key, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips6', f'{sc}-{key}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    print(f'{len(xs)} clips at {20*np.log10(target):.1f} dBFS RMS')


if __name__ == '__main__':
    main()

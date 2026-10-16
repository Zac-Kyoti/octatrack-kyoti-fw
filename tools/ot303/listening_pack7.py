#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 2b: listening pack round 7 -- the lean engine (the integer twin, tools/ot303/twin.h,
# with the option-3 savings) against the approved voice (round 6's pick).
#   ABX  Hot, Squelch, Accents, Square: A = approved voice, B = lean engine
# Renders: python3 tools/ot303/twin_check.py lean LEAN_OPTS (out/ot303/twin/SCENE.{ref,lean}.f32).
import os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TW = os.path.join(ROOT, 'out', 'ot303', 'twin'); OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100; SECONDS = 10.0
SCENES = ['hot', 'squelch', 'accents', 'square']


def main():
    os.makedirs(os.path.join(OUT, 'clips7'), exist_ok=True)
    rng = np.random.default_rng(3037); xs = []
    for sc in SCENES:
        for key, f in (('ref', f'{sc}.ref'), ('lean', f'{sc}.lean')):
            x = np.fromfile(os.path.join(TW, f + '.f32'), dtype=np.float32).astype(np.float64)[int(2.0 * FS):int(2.0 * FS) + int(SECONDS * FS)]
            x = x / np.sqrt(np.mean(x ** 2)); n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
            xs.append((sc, key, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs); target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)
    for sc, key, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips7', f'{sc}-{key}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    print(f'{len(xs)} clips at {20*np.log10(target):.1f} dBFS RMS')


if __name__ == '__main__':
    main()

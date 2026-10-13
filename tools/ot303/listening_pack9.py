#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 listening pack round 9, from the user's round 8 notes: the note start against a kick
# (free-running vs MT7's restart), envelope edges three ways (none / 1 ms + 2 ms / 2 ms + 4 ms), the
# square shaper three ways (36.9 / 32 / 28 dB), the output drive three ways (none / +4.5 / +9 dB).
# Renders tools/ot303/listening_pack9.cpp (the machine as MT8 plays it), cuts 10 s clips at one
# loudness into out/ot303/listen/clips9/, writes manifest9.json (the page's PICK list).
#   python3 tools/ot303/listening_pack9.py
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack9')
FS = 44100; SECONDS = 10.0; STEP = 5088
SCENE_TEXT = {
    'line': 'A classic acid line around C2: cutoff low, resonance 90, env mod 70, accents and slides.',
    'hot': 'Env mod, resonance and accent near the top.',
    'locks': 'CUT, ENV and DEC locked to new values on every step, resonance 100.',
    'square': 'WAVE at square, the cutoff sweeping up.',
    'low': 'The same line an octave lower, from D1 (37 Hz).',
}
NAMES = {'base': 'MT8 as built', 'free': 'oscillator free-running (MT6)', 'drive45': 'output drive +4.5 dB',
         'drive9': 'output drive +9 dB', 'edgesmid': 'soft attack 1 ms + release 2 ms', 'edges': 'soft attack 2 ms + release 4 ms',
         'sq32': 'square shaper 32 dB', 'sq28': 'square shaper 28 dB'}
# (key, title, what, scenes, variants, with the kick)
PAIRS = [
    ('start', 'Note start, with a kick', 'A four-on-the-floor kick under both, so you can hear where each note lands. One is '
     'MT8 (a note from silence starts on its step), one lets the oscillator run free (MT6, Open303).', ['low', 'line'], ['base', 'free'], True),
    ('edges', 'Envelope edges', 'No soft attack, your in-between (1 ms attack, 2 ms release), and round 8\'s (2 ms, 4 ms).',
     ['locks', 'line'], ['base', 'edgesmid', 'edges'], False),
    ('square', 'Square shaper', 'The square\'s shaper at 36.9 dB (as built), 32 dB (in between) and 28 dB (round 8\'s).',
     ['square'], ['base', 'sq32', 'sq28'], False),
    ('drive', 'Output drive amount', 'No drive, +4.5 dB and +9 dB into the soft clip. If drive becomes part of VOL\'s top range, '
     'this sets how far it goes.', ['hot', 'line'], ['base', 'drive45', 'drive9'], False),
]


def kick():
    """a plain analog-style kick: a sine falling 140 -> 45 Hz, 260 ms decay, a short click"""
    n = int(0.35 * FS); t = np.arange(n) / FS
    f = 45 + 95 * np.exp(-t / 0.03)
    ph = 2 * np.pi * np.cumsum(f) / FS
    return np.sin(ph) * np.exp(-t / 0.26) + 0.3 * np.exp(-t / 0.002) * np.sin(2 * np.pi * 1800 * t)


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips9'), exist_ok=True)
    exe = os.path.join(RENDER, 'listening_pack9')
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack9.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    subprocess.run([exe, RENDER], check=True)
    rng = np.random.default_rng(3039); xs = []
    k = kick(); a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    for key, _, _, scs, vars_, withKick in PAIRS:
        for sc in scs:
            for v in vars_:
                x = np.fromfile(os.path.join(RENDER, f'{sc}.{v}.f32'), dtype=np.float32).astype(np.float64)
                x = x / np.sqrt(np.mean(x[a:b] ** 2))
                if withKick:                          # quarter notes, on the steps (every 4th 16th)
                    kk = np.zeros_like(x)
                    for s in range(0, len(x) // STEP, 4):
                        p = s * STEP; m = min(len(k), len(x) - p); kk[p:p + m] += k[:m]
                    x = x + 1.4 * kk / np.sqrt(np.mean(kk[a:b] ** 2))
                x = x[a:b]; x = x / np.sqrt(np.mean(x ** 2))
                n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
                xs.append((f'{key}-{sc}-{v}', x))
    crest = max(np.max(np.abs(x)) for _, x in xs); target = min(10 ** (-20 / 20), 10 ** (-1.0 / 20) / crest)
    for name, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips9', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': f'{key}-{sc}', 'group': title, 'scene': sc.capitalize(), 'what': what, 'sceneText': SCENE_TEXT[sc],
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips9/{key}-{sc}-{v}.wav'} for v in vars_]}
             for key, title, what, scs, vars_, _ in PAIRS for sc in scs]
    json.dump(picks, open(os.path.join(OUT, 'manifest9.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {20 * np.log10(target):.1f} dBFS RMS (crest {20 * np.log10(crest):.1f} dB), {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

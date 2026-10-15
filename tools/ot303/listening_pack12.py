#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 12, from the round 11 results: a tie-breaker on the note start (round 10
# kept free-running on Low and Line, round 11 kept notes starting on the step on Hot), with MT10's planned
# voice in both: soft attack 1 ms faded out from RES 100 to 115 (round 11: kept on Locks and Line, not
# Hot) and the output drive at +2.5 dB (the VOL-driven drive at its default VOL 119; round 11: none on
# Locks, +2.5 dB on Line). Over the round 10 kick. Renders tools/ot303/listening_pack12.cpp, cuts 10 s
# clips at one loudness into out/ot303/listen/clips12/, writes manifest12.json (the page's PICK list).
#   python3 tools/ot303/listening_pack12.py
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack12')
FS = 44100; SECONDS = 10.0; STEP = 5088
SCENE_TEXT = {
    'line': 'A classic acid line around C2: cutoff low, resonance 90, env mod 70, accents and slides.',
    'hot': 'Env mod, resonance and accent near the top (resonance 115: no soft attack).',
    'locks': 'CUT, ENV and DEC locked to new values on every step, resonance 100.',
    'low': 'The same line an octave lower, from D1 (37 Hz).',
}
NAMES = {'step': 'notes start on the step', 'free': 'oscillator free-running'}
# (key, title, what, scenes, variants, with the kick)
PAIRS = [
    ('start', 'Note start, tie-breaker', 'The kick from round 10 on every beat. Both versions have the voice planned '
     'for MT10: soft attack (none at high resonance) and drive +2.5 dB. One starts each note on its step, the other '
     'lets the oscillator run free (Open303).', ['low', 'line', 'hot', 'locks'], ['step', 'free'], True),
]


def kick():
    """a kick that small speakers still mark: a sine falling 160 -> 50 Hz (180 ms decay) under a bright
    click (band-limited noise 2-9 kHz, 12 ms) and a 1 kHz tick"""
    n = int(0.35 * FS); t = np.arange(n) / FS
    f = 50 + 110 * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(f) / FS) * np.exp(-t / 0.18)
    rng = np.random.default_rng(7); nz = rng.standard_normal(n)
    N = 1 << int(np.ceil(np.log2(n))); F = np.fft.rfft(nz, N); fr = np.fft.rfftfreq(N, 1 / FS)
    F[(fr < 2000) | (fr > 9000)] = 0; nz = np.fft.irfft(F, N)[:n]; nz /= np.max(np.abs(nz))
    click = nz * np.exp(-t / 0.012) * 0.9 + 0.5 * np.sin(2 * np.pi * 1000 * t) * np.exp(-t / 0.008)
    return body + click


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips12'), exist_ok=True)
    exe = os.path.join(RENDER, 'listening_pack12')
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack12.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    subprocess.run([exe, RENDER], check=True)
    rng = np.random.default_rng(3042); xs = []
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
        with wave.open(os.path.join(OUT, 'clips12', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': f'{key}-{sc}', 'group': title, 'scene': sc.capitalize(), 'what': what, 'sceneText': SCENE_TEXT[sc],
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips12/{key}-{sc}-{v}.wav'} for v in vars_]}
             for key, title, what, scs, vars_, _ in PAIRS for sc in scs]
    json.dump(picks, open(os.path.join(OUT, 'manifest12.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {20 * np.log10(target):.1f} dBFS RMS (crest {20 * np.log10(crest):.1f} dB), {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

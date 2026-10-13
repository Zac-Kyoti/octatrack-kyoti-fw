#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 listening pack round 13, from MT12 on the unit: the bass lost as RES rises (a clip sweeping RES
# 0 -> 127: as built / makeup gain by RES / feedback high-pass 350 Hz / a gentler RES curve) and the pops on
# big lock or LFO jumps inside held notes (as built / the words glided over 1 ms / 3 ms). Renders
# tools/ot303/listening_pack13.cpp, cuts 10 s clips at one loudness into out/ot303/listen/clips13/, writes
# manifest13.json (the page's PICK list). The bass clips share one gain (as built's at -20 dBFS RMS), so
# their RES-0 first bar is identical and the level each keeps as RES rises is heard as it is; the jump
# clips are level-matched one by one.
#   python3 tools/ot303/listening_pack13.py
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack13')
FS = 44100; SECONDS = 10.0; STEP = 5088
SCENE_TEXT = {
    'sweep': 'The acid line around C2 (CUT 45, ENV 70): RES 0 for the first bar, then rising to 127. All four play '
             'at the same gain, so the first bar is identical and the level each keeps is heard as it is.',
    'jumps': 'Held notes (one every bar quarter, tied); CUT, ENV and RES jump to new values on every step, '
             'as trigless locks or a square / random LFO do.',
}
NAMES = {'base': 'as built (MT13)', 'makeup': 'makeup gain by RES', 'fb350': 'feedback high-pass 350 Hz',
         'gentle': 'gentler RES curve', 'sm1': 'glide 1 ms', 'sm3': 'glide 3 ms'}
# (key, title, what, scenes, variants, with the kick)
PAIRS = [
    ('bass', 'Bass as RES rises', 'Listen to how much low end survives as the resonance comes up. As built, RES 8 already '
     'loses 4.6 dB and RES 64 and up about 10 dB. Makeup gain turns the voice up by RES to hold the level of RES 0 '
     '(the resonant peak gets louder too). The 350 Hz feedback high-pass feeds less bass back into the filter, so less '
     'is cancelled (about -3 dB at most). The gentler curve keeps the bottom of the RES knob light (RES 32 acts as 8 '
     'does now); the top is unchanged.', ['sweep'], ['base', 'makeup', 'fb350', 'gentle'], False),
    ('pops', 'Pops on big jumps', 'The cutoff, env amount and resonance glide to each new value instead of jumping at '
     'the frame: as built, over 1 ms, over 3 ms. Measured: the average click above 3 kHz drops 1.6 dB (1 ms) and '
     '3.2 dB (3 ms); the worst ones barely change.', ['jumps'], ['base', 'sm1', 'sm3'], False),
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
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips13'), exist_ok=True)
    exe = os.path.join(RENDER, 'listening_pack13')
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack13.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    subprocess.run([exe, RENDER], check=True)
    rng = np.random.default_rng(3043); xs = []
    k = kick(); a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    for key, _, _, scs, vars_, withKick in PAIRS:
        for sc in scs:
            ref = np.fromfile(os.path.join(RENDER, f'{sc}.base.f32'), dtype=np.float32).astype(np.float64)[a:b]
            for v in vars_:
                x = np.fromfile(os.path.join(RENDER, f'{sc}.{v}.f32'), dtype=np.float32).astype(np.float64)
                shared = key == 'bass'                # one gain for the bass clips: as built's
                x = x / np.sqrt(np.mean((ref if shared else x[a:b]) ** 2))
                if withKick:                          # quarter notes, on the steps (every 4th 16th)
                    kk = np.zeros_like(x)
                    for s in range(0, len(x) // STEP, 4):
                        p = s * STEP; m = min(len(k), len(x) - p); kk[p:p + m] += k[:m]
                    x = x + 1.4 * kk / np.sqrt(np.mean(kk[a:b] ** 2))
                x = x[a:b]
                if not shared:
                    x = x / np.sqrt(np.mean(x ** 2))
                n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
                xs.append((f'{key}-{sc}-{v}', x))
    crest = max(np.max(np.abs(x)) for _, x in xs); target = min(10 ** (-20 / 20), 10 ** (-1.0 / 20) / crest)
    for name, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips13', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': f'{key}-{sc}', 'group': title, 'scene': sc.capitalize(), 'what': what, 'sceneText': SCENE_TEXT[sc],
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips13/{key}-{sc}-{v}.wav'} for v in vars_]}
             for key, title, what, scs, vars_, _ in PAIRS for sc in scs]
    json.dump(picks, open(os.path.join(OUT, 'manifest13.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {20 * np.log10(target):.1f} dBFS RMS (crest {20 * np.log10(crest):.1f} dB), {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

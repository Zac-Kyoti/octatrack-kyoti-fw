#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 17: a level trim at the bottom of RES. The voice is up to ~9 dB louder at RES 0
# than from RES ~48 up (twin, CUT 45); the candidates take 10-50 % of that boost off as a gain on the amp
# scaler by RES, fading out where the boost does. Each clip holds RES 0 for 24 steps (2.8 s) so the ear can
# settle on the bass, then sweeps RES to 127 over 64 steps. The versions of a scene share one gain (as built's
# at -20 dBFS RMS over the clip), so the trimmed RES-0 holds are heard at their real level. Labelled, in order.
#   python3 tools/ot303/listening_pack17.py
# Renders tools/ot303/listening_pack17.cpp, writes out/ot303/listen/clips17/*.wav and manifest17.json.
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack17')
FS = 44100; SECONDS = 11.0; HOLD = 24
# (key, CUT, ENV, VOL, ACC, title, scene text)
CLIPS = [
    ('clean', 45, 70, 64, 100, 'RES sweep, clean VOL 64',
     'The acid line (CUT 45, ENV 70, accents): RES 0 held for 2.8 s, then rising to 127 over 7.4 s.'),
    ('driven', 45, 70, 99, 100, 'RES sweep, default VOL 99',
     'The same at the default VOL 99 (+2.5 dB into the soft clip).'),
]
PCTS = [0, 10, 20, 30, 40, 50]
NAMES = {p: ('as built' if p == 0 else f'{p}% trim') for p in PCTS}


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips17'), exist_ok=True)
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf'); exe = os.path.join(RENDER, 'listening_pack17')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack17.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    procs = [subprocess.Popen([exe, os.path.join(RENDER, f'{key}.{p}.f32'), str(c), str(e), str(vol), str(acc), str(p), str(HOLD)],
                              stderr=subprocess.DEVNULL) for key, c, e, vol, acc, *_ in CLIPS for p in PCTS]
    for pr in procs:
        if pr.wait(): sys.exit('render failed')
    n = int(SECONDS * FS); rng = np.random.default_rng(3047); xs = []; hold = HOLD * 5088
    for key, *_ in CLIPS:
        ref = np.fromfile(os.path.join(RENDER, f'{key}.0.f32'), dtype=np.float32).astype(np.float64)[:n]
        gain = 10 ** (-20 / 20) / np.sqrt(np.mean(ref ** 2))
        for p in PCTS:
            x = np.fromfile(os.path.join(RENDER, f'{key}.{p}.f32'), dtype=np.float32).astype(np.float64)[:n] * gain
            k = int(0.005 * FS); rr = np.linspace(0, 1, k); x[-k:] *= rr[::-1]
            lv = 20 * np.log10(np.sqrt(np.mean(x[:hold] ** 2)) / np.sqrt(np.mean((ref[:hold] * gain) ** 2)))
            xs.append((f'{key}-{p}', x)); print(f'  {key} {NAMES[p]:9s}: RES-0 hold {lv:+.2f} dB against as built')
    crest = max(np.max(np.abs(x)) for _, x in xs)
    trim = min(1.0, 10 ** (-1.0 / 20) / crest)
    for name, x in xs:
        pcm = np.clip(np.round(x * trim * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips17', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': key, 'group': 'RES level trim', 'scene': title, 'labeled': True,
              'what': 'Listen to the bass in the RES-0 hold, then how the level moves as RES comes up. As built, RES 0 is '
                      'about 9 dB louder than RES 64 and up; each trim takes that share of the boost off, fading out by RES ~48.',
              'sceneText': text, 'items': [{'key': str(p), 'name': NAMES[p], 'file': f'clips17/{key}-{p}.wav'} for p in PCTS]}
             for key, _, _, _, _, title, text in CLIPS]
    json.dump(picks, open(os.path.join(OUT, 'manifest17.json'), 'w'), indent=1)
    print(f'{len(xs)} clips, as built at {-20 + 20 * np.log10(trim):.1f} dBFS RMS, {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

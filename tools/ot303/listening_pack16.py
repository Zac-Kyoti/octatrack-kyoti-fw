#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 16: a soft knee for clean VOL. Round 15's soft ceiling (the drive's tanh at unity)
# softened clean sounds below the old clip point too; the author wants them untouched and only what hit the
# ceiling rounded. The knee (simulated after the twin, listening_pack15.cpp KNEE): 4x headroom, linear to the
# knee, then a tanh bend into the ceiling. Versions: as built (hard clip), knee at -3 dBFS, at -1 dBFS, and
# round 15's full soft ceiling; all at clean VOL 64, one shared gain per scene (as built's at -20 dBFS RMS).
#   python3 tools/ot303/listening_pack16.py
# Renders tools/ot303/listening_pack15.cpp, writes out/ot303/listen/clips16/*.wav and manifest16.json.
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack16')
FS = 44100; SECONDS = 10.0
# (key, CUT, RES, ENV, VOL, ACC, title, scene text, what to listen for)
CLIPS = [
    ('wide', 127, 0, 100, 64, 127, 'Wide open, full accents',
     'Filter all the way open (CUT 127, RES 0, ENV 100), full accents, clean VOL 64: the heaviest clipping.',
     'As built, the accents are chopped flat: a harsh, splintery fizz on every loud hit. Listen for how much of '
     'that grit each version keeps, and whether the knees sound like the as-built tone with the splinters sanded off.'),
    ('bright-clean', 80, 0, 70, 64, 127, 'Bright accents',
     'CUT 80, RES 0, ENV 70, full accents, clean VOL 64.',
     'The same question one notch tamer: only the accents reach the ceiling.'),
    ('bright-plain', 80, 0, 70, 64, 0, 'Bright, no accents',
     'The bright line with no accents: as built, nothing clips (peaks at -1.4 dBFS).',
     'What each version costs below the ceiling. The -1 dB knee leaves this untouched; the -3 dB knee touches '
     'only the very tops; the full soft ceiling rounds it all a little.'),
    ('classic', 45, 64, 70, 64, 100, 'Classic line',
     'A typical acid line: CUT 45, RES 64, ENV 70, clean VOL 64, accents at ACC 100.',
     'The control: both knees are identical to as built here. Only the full soft ceiling differs.'),
]
NAMES = {'base': 'as built (MT32)', 'knee3': 'knee at -3 dBFS', 'knee1': 'knee at -1 dBFS', 'soft': 'full soft ceiling (round 15)'}
ARGS = {'base': ['1'], 'knee3': ['4', '0.708'], 'knee1': ['4', '0.891'], 'soft': ['4']}


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips16'), exist_ok=True)
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf'); exe = os.path.join(RENDER, 'listening_pack15')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack15.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    procs = [subprocess.Popen([exe, os.path.join(RENDER, f'{key}.{v}.f32'), str(c), str(r), str(e), str(vol), str(acc)] + ARGS[v],
                              stderr=subprocess.DEVNULL)
             for key, c, r, e, vol, acc, *_ in CLIPS for v in NAMES]
    for p in procs:
        if p.wait(): sys.exit('render failed')
    a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    rng = np.random.default_rng(3046); xs = []
    for key, *_ in CLIPS:
        ref = np.fromfile(os.path.join(RENDER, f'{key}.base.f32'), dtype=np.float32).astype(np.float64)[a:b]
        gain = 10 ** (-20 / 20) / np.sqrt(np.mean(ref ** 2))
        for v in NAMES:
            x = np.fromfile(os.path.join(RENDER, f'{key}.{v}.f32'), dtype=np.float32).astype(np.float64)[a:b] * gain
            n = int(0.005 * FS); rr = np.linspace(0, 1, n); x[:n] *= rr; x[-n:] *= rr[::-1]
            xs.append((f'{key}-{v}', x))
    crest = max(np.max(np.abs(x)) for _, x in xs)
    trim = min(1.0, 10 ** (-1.0 / 20) / crest)
    for name, x in xs:
        pcm = np.clip(np.round(x * trim * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips16', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': key, 'group': 'Clean-VOL knee', 'scene': title, 'what': what, 'sceneText': text,
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips16/{key}-{v}.wav'} for v in NAMES]}
             for key, _, _, _, _, _, title, text, what in CLIPS]
    json.dump(picks, open(os.path.join(OUT, 'manifest16.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {-20 + 20 * np.log10(trim):.1f} dBFS RMS, {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

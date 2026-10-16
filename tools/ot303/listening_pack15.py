#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 15: output headroom. Bright settings hard-clip at the voice's output stage (out4,
# before the drive), most of all on accents, even at clean VOL. The candidate gives that stage 4x the headroom
# (the amp scaler / 4, the drive gain x 4, the drive's soft clip switched on at unity for clean VOL), so what
# was chopped flat is rounded by tanh instead: ColdFire words only. Each scene is as built against the
# candidate, at one shared gain (as built's at -20 dBFS RMS; one trim for all if a peak would pass -1 dBFS).
#   python3 tools/ot303/listening_pack15.py
# Renders tools/ot303/listening_pack15.cpp, writes out/ot303/listen/clips15/*.wav and manifest15.json.
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack15')
FS = 44100; SECONDS = 10.0
# (key, CUT, RES, ENV, VOL, ACC, title, scene text, what to listen for)
CLIPS = [
    ('bright-clean', 80, 0, 70, 64, 127, 'Bright accents, clean',
     'The acid line wide open (CUT 80, RES 0, ENV 70) at clean VOL 64, accents at full (ACC 127).',
     'As built, the accented notes slam into the output ceiling and get chopped flat: listen for a fizzy, '
     'crackly edge on the loud hits. The candidate rounds them off instead.'),
    ('bright-driven', 80, 0, 70, 127, 127, 'Bright accents, driven',
     'The same line at VOL 127 (full drive).',
     'Here the drive already rounds things, but the accents were squared off before reaching it. Listen to '
     'the top of each accent: buzzy and hard, or thick and rounded?'),
    ('bright-plain', 80, 0, 70, 64, 0, 'Bright, no accents, clean',
     'The bright line at clean VOL 64 with no accents: nothing clips here as built.',
     'This is what the candidate costs: its soft ceiling is always in the path at clean VOL, so loud clean '
     'peaks lose about 2 dB and get a touch rounder. Is clean still clean enough?'),
    ('classic', 45, 64, 70, 64, 100, 'Classic line',
     'A typical acid line: CUT 45, RES 64, ENV 70, clean VOL 64, accents at ACC 100.',
     'The control. Nothing clips; the two should sound the same or nearly so.'),
]
NAMES = {'base': 'as built (MT32)', 'head': 'headroom + soft ceiling'}
K = {'base': 1, 'head': 4}


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips15'), exist_ok=True)
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf'); exe = os.path.join(RENDER, 'listening_pack15')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack15.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    procs = [subprocess.Popen([exe, os.path.join(RENDER, f'{key}.{v}.f32'), str(c), str(r), str(e), str(vol), str(acc), str(K[v])],
                              stderr=subprocess.DEVNULL)
             for key, c, r, e, vol, acc, *_ in CLIPS for v in NAMES]
    for p in procs:
        if p.wait(): sys.exit('render failed')
    a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    rng = np.random.default_rng(3045); xs = []
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
        with wave.open(os.path.join(OUT, 'clips15', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': key, 'group': 'Output headroom', 'scene': title, 'what': what, 'sceneText': text,
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips15/{key}-{v}.wav'} for v in NAMES]}
             for key, _, _, _, _, _, title, text, what in CLIPS]
    json.dump(picks, open(os.path.join(OUT, 'manifest15.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {-20 + 20 * np.log10(trim):.1f} dBFS RMS, {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

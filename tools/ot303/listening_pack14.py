#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 14: WAVE loudness. The user hears the square end, and more the blends between, as
# quieter than the saw; tools/ot303/wave_loudness.py measured it (ISO 532-1) and fitted a WAVE gain (MT29,
# tools/ot303/cf/params.c's OT_WGAIN). Each comparison is MT28 (commit 2a0d07f's params.c) against the working
# tree's params.c with the gain, in a clip where WAVE moves
# (a sweep 0 -> 127, or bars alternating the saw and one WAVE value), so the question is whether the level holds
# as WAVE changes. The two clips of a comparison share one gain (as built's saw bars at -20 dBFS RMS): the saw
# bars are identical and the other bars are heard at their own level.
#   python3 tools/ot303/listening_pack14.py
# Renders tools/ot303/listening_pack14.cpp, writes
# out/ot303/listen/clips14/*.wav and manifest14.json (the page's PICK list).
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack14')
FS = 44100; SECONDS = 10.0; STEP = 5088
# (key, scene, CUT, RES, VOL, title, scene text)
CLIPS = [
    ('sweep-clean', 'sweep', 45, 64, 64, 'WAVE sweep, clean',
     'The acid line (CUT 45, RES 64, ENV 70, VOL 64): WAVE 0 for the first bar, then rising to 127 over three bars.'),
    ('sweep-driven', 'sweep', 30, 100, 99, 'WAVE sweep, driven',
     'The same sweep darker and hotter: CUT 30, RES 100, VOL 99 (into the drive).'),
    ('alt64', 'alt64', 45, 64, 64, 'Saw against the middle',
     'Bars alternate WAVE 0 (saw) and WAVE 64 (half way), CUT 45, RES 64, VOL 64.'),
    ('alt96', 'alt96', 45, 64, 64, 'Saw against WAVE 96',
     'Bars alternate WAVE 0 and WAVE 96 (mostly square), CUT 45, RES 64, VOL 64.'),
    ('alt127', 'alt127', 45, 64, 64, 'Saw against the square',
     'Bars alternate WAVE 0 and WAVE 127 (full square), CUT 45, RES 64, VOL 64.'),
]
NAMES = {'base': 'as built (MT28)', 'gain': 'WAVE gain (MT29)'}
BASE_REV = '2a0d07f'


def main():
    os.makedirs(os.path.join(OUT, 'clips14'), exist_ok=True)
    exe = {}
    for var in NAMES:                                   # base: MT28's params.c / .h; gain: the working tree's
        cf = os.path.join(RENDER, var)
        os.makedirs(cf, exist_ok=True)
        for f in ('params.c', 'params.h', 'params_const.h'):
            src = subprocess.run(['git', 'show', f'{BASE_REV}:tools/ot303/cf/{f}'], cwd=ROOT, capture_output=True, check=True).stdout \
                if var == 'base' else open(os.path.join(ROOT, 'tools/ot303/cf', f), 'rb').read()
            open(os.path.join(cf, f), 'wb').write(src)
        exe[var] = os.path.join(cf, 'listening_pack14')
        subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(cf, 'params.o')], check=True)
        subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack14.cpp'),
                        os.path.join(cf, 'params.o'), '-o', exe[var]], check=True)
    procs = []
    for key, sc, c, r, v, _, _ in CLIPS:
        for var in NAMES:
            p = os.path.join(RENDER, f'{key}.{var}.f32')
            procs.append(subprocess.Popen([exe[var], p, sc, str(c), str(r), str(v)]))
    for p in procs:
        if p.wait(): sys.exit('render failed')
    a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    rng = np.random.default_rng(3044); xs = []
    for key, sc, *_ in CLIPS:
        ref = np.fromfile(os.path.join(RENDER, f'{key}.base.f32'), dtype=np.float32).astype(np.float64)
        saw = ref[a:a + 16 * STEP - int(0.5 * FS)] if sc == 'sweep' else ref[16 * STEP * 2:16 * STEP * 3]   # a saw bar
        gain = 10 ** (-20 / 20) / np.sqrt(np.mean(saw ** 2))
        for var in NAMES:
            x = np.fromfile(os.path.join(RENDER, f'{key}.{var}.f32'), dtype=np.float32).astype(np.float64)[a:b] * gain
            n = int(0.005 * FS); rr = np.linspace(0, 1, n); x[:n] *= rr; x[-n:] *= rr[::-1]
            xs.append((f'{key}-{var}', x))
    crest = max(np.max(np.abs(x)) for _, x in xs)
    trim = min(1.0, 10 ** (-1.0 / 20) / crest)          # one trim for every clip if a peak would pass -1 dBFS
    for name, x in xs:
        pcm = np.clip(np.round(x * trim * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips14', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': key, 'group': title, 'scene': title, 'what': '', 'sceneText': text,
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips14/{key}-{v}.wav'} for v in NAMES]}
             for key, _, _, _, _, title, text in CLIPS]
    json.dump(picks, open(os.path.join(OUT, 'manifest14.json'), 'w'), indent=1)
    print(f'{len(xs)} clips, saw bars at {-20 + 20 * np.log10(trim):.1f} dBFS RMS, {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

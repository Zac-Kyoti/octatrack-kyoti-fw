#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 listening pack round 11, from the round 10 results: the oscillator free-running in both
# note-start tests (Low, Line); clicks on Hot's transients in MT9's voice; Locks: MT8's punch, MT9's
# detail. Measured (onset 4-20 kHz peak over RMS, non-slide notes): Hot restart 0.45 -> restart + soft
# attack 0.92 (the clicks), but free-running alone 0.91 (a free saw starts mid-cycle: the amp's onset
# steps it), so Hot gets its own note-start test. Then soft attack 1 ms / none, free-running (Locks,
# Line), and the drive none / +2.5 / +4.5 dB (Locks, Line).
# Renders tools/ot303/listening_pack11.cpp, cuts 10 s clips at one loudness into
# out/ot303/listen/clips11/, writes manifest11.json (the page's PICK list).
#   python3 tools/ot303/listening_pack11.py
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack11')
FS = 44100; SECONDS = 10.0
SCENE_TEXT = {
    'line': 'A classic acid line around C2: cutoff low, resonance 90, env mod 70, accents and slides.',
    'hot': 'Env mod, resonance and accent near the top (resonance 115).',
    'locks': 'CUT, ENV and DEC locked to new values on every step, resonance 100.',
}
NAMES = {'restart0': 'notes start on the step, no soft attack', 'atk0': 'free-running, no soft attack',
         'atk1': 'free-running, soft attack 1 ms (MT9)', 'drv0': 'no drive', 'drv25': 'drive +2.5 dB',
         'drv45': 'drive +4.5 dB (MT9)'}
RENDERED = {'drv45': 'atk1'}                # the same clip under the drive test's name
# (key, title, what, scenes, variants)
PAIRS = [
    ('hot', 'Hot: where the clicks come from', 'Round 10 heard clicks on Hot in MT9\'s voice; they came from the soft '
     'attack together with notes starting on the step. A free-running oscillator (your round 10 pick) has its own '
     'onset click: a note starts wherever the saw happens to be. Drive +4.5 dB in all three.', ['hot'],
     ['restart0', 'atk0', 'atk1']),
    ('attack', 'Soft attack', 'With the oscillator free-running: the filter glides open over 1 ms at each note, or '
     'jumps (MT8). Drive +4.5 dB in both.', ['locks', 'line'], ['atk1', 'atk0']),
    ('drive', 'Output drive', 'The soft clip after the voice at three levels; free-running, soft attack 1 ms.',
     ['locks', 'line'], ['drv0', 'drv25', 'drv45']),
]


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips11'), exist_ok=True)
    exe = os.path.join(RENDER, 'listening_pack11')
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack11.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    subprocess.run([exe, RENDER], check=True)
    rng = np.random.default_rng(3041); xs = []
    a, b = int(0.5 * FS), int(0.5 * FS) + int(SECONDS * FS)
    for key, _, _, scs, vars_ in PAIRS:
        for sc in scs:
            for v in vars_:
                x = np.fromfile(os.path.join(RENDER, f'{sc}.{RENDERED.get(v, v)}.f32'), dtype=np.float32).astype(np.float64)
                x = x[a:b]; x = x / np.sqrt(np.mean(x ** 2))
                n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
                xs.append((f'{key}-{sc}-{v}', x))
    crest = max(np.max(np.abs(x)) for _, x in xs); target = min(10 ** (-20 / 20), 10 ** (-1.0 / 20) / crest)
    for name, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips11', f'{name}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = [{'key': f'{key}-{sc}', 'group': title, 'scene': sc.capitalize(), 'what': what, 'sceneText': SCENE_TEXT[sc],
              'items': [{'key': v, 'name': NAMES[v], 'file': f'clips11/{key}-{sc}-{v}.wav'} for v in vars_]}
             for key, title, what, scs, vars_ in PAIRS for sc in scs]
    json.dump(picks, open(os.path.join(OUT, 'manifest11.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {20 * np.log10(target):.1f} dBFS RMS (crest {20 * np.log10(crest):.1f} dB), {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

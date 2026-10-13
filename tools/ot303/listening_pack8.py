#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 listening pack round 8: the fatness candidates (reference/handoffs/OT303_SCOPE.md, "Research
# (2026-10-12)") and MT7's saw restart, each against the machine as MT7 plays it, blind, two at a time.
# Renders tools/ot303/listening_pack8.cpp (the integer twin driven as the DSP host drives the engine),
# then cuts 10 s clips at one loudness (RMS) into out/ot303/listen/clips8/ and writes manifest8.json
# (the page's PICK list).
#   python3 tools/ot303/listening_pack8.py
import json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen'); RENDER = os.path.join(ROOT, 'out', 'ot303', 'pack8')
FS = 44100; SECONDS = 10.0
SCENE_TEXT = {
    'line': 'A classic acid line around C2: cutoff low, resonance 90, env mod 70, accents and slides.',
    'hot': 'Env mod, resonance and accent near the top.',
    'locks': 'CUT, ENV and DEC locked to new values on every step, resonance 100.',
    'square': 'WAVE at square, the cutoff sweeping up.',
    'low': 'The same line two octaves down (23-46 Hz).',
}
VAR_TEXT = {
    'base': 'MT7 as built', 'free': 'oscillator free-running (MT6)', 'drive': 'output drive (soft clip, +9 dB)',
    'fbhp': 'feedback high-pass 250 Hz', 'grit': 'oscillator grit (curve + noise)', 'edges': 'soft attack + 4 ms release',
    'sq28': 'square shaper 28 dB', 'combo': 'drive + feedback 250 Hz + grit + edges',
}
# (key, title, what it changes, scenes, variant); A/B order is shuffled per visitor
PAIRS = [
    ('restart', 'Note start', 'MT7 starts a note from silence just before the saw\'s edge, so it lands on its step; '
     'MT6 let the oscillator run free (Open303\'s behaviour).', ['low', 'line'], 'free'),
    ('drive', 'Output drive', 'A soft clip after the voice, driven 9 dB (ABL3 clips when VOL passes 75 %).', ['line', 'hot'], 'drive'),
    ('fbhp', 'Feedback high-pass', 'The filter\'s resonance feedback high-passed at 250 Hz instead of 150 Hz: less bass '
     'fed back, so more bass kept under high resonance (JC-303 makes it a knob, 350 to 100 Hz).', ['hot', 'line'], 'fbhp'),
    ('grit', 'Oscillator grit', 'A slight curve on the saw (even harmonics) and faint VCO noise (ABL3\'s default VCO).',
     ['line'], 'grit'),
    ('edges', 'Envelope edges', 'A 2 ms soft attack on the filter envelope and a 4 ms release instead of 1 ms: '
     'softer clicks on locks and gate ends.', ['locks', 'line'], 'edges'),
    ('sq28', 'Square shaper', 'The square\'s shaper driven 28 dB instead of 36.9 dB: a rounder square.', ['square'], 'sq28'),
    ('combo', 'All together', 'Drive, feedback 250 Hz, grit and edges at once.', ['line', 'hot'], 'combo'),
]


def main():
    os.makedirs(RENDER, exist_ok=True); os.makedirs(os.path.join(OUT, 'clips8'), exist_ok=True)
    exe = os.path.join(RENDER, 'listening_pack8')
    cf = os.path.join(ROOT, 'tools', 'ot303', 'cf')
    subprocess.run(['cc', '-O2', '-std=c99', f'-I{cf}', '-c', os.path.join(cf, 'params.c'), '-o', os.path.join(RENDER, 'params.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-O2', '-w', f'-I{ROOT}/tools/ot303', f'-I{cf}', os.path.join(ROOT, 'tools/ot303/listening_pack8.cpp'),
                    os.path.join(RENDER, 'params.o'), '-o', exe], check=True)
    subprocess.run([exe, RENDER], check=True)
    need = sorted({(sc, 'base') for _, _, _, scs, _ in PAIRS for sc in scs} | {(sc, v) for _, _, _, scs, v in PAIRS for sc in scs})
    rng = np.random.default_rng(3038); xs = []
    for sc, var in need:
        x = np.fromfile(os.path.join(RENDER, f'{sc}.{var}.f32'), dtype=np.float32).astype(np.float64)[int(0.5 * FS):int(0.5 * FS) + int(SECONDS * FS)]
        x = x / np.sqrt(np.mean(x ** 2)); n = int(0.005 * FS); r = np.linspace(0, 1, n); x[:n] *= r; x[-n:] *= r[::-1]
        xs.append((sc, var, x))
    crest = max(np.max(np.abs(x)) for _, _, x in xs); target = min(10 ** (-20 / 20), 10 ** (-1.0 / 20) / crest)
    for sc, var, x in xs:
        pcm = np.clip(np.round(x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips8', f'{sc}-{var}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    picks = []
    for key, title, what, scs, var in PAIRS:
        for sc in scs:
            picks.append({'key': f'{key}-{sc}', 'group': title, 'scene': sc.capitalize(), 'what': what, 'sceneText': SCENE_TEXT[sc],
                          'items': [{'key': 'base', 'name': VAR_TEXT['base'], 'file': f'clips8/{sc}-base.wav'},
                                    {'key': var, 'name': VAR_TEXT[var], 'file': f'clips8/{sc}-{var}.wav'}]})
    json.dump(picks, open(os.path.join(OUT, 'manifest8.json'), 'w'), indent=1)
    print(f'{len(xs)} clips at {20 * np.log10(target):.1f} dBFS RMS (crest {20 * np.log10(crest):.1f} dB), {len(picks)} comparisons')


if __name__ == '__main__':
    sys.exit(main())

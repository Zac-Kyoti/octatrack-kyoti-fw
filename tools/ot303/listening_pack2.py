#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 1c: listening pack round 2 -- voicing at the chosen 2x, and the accent circuit.
# Renders: out/ot303/voicing (voice_study zdf2 / o303, see the scope's §10 "Phase 1c").
#   out/ot303/listen/clips2/*.wav  16-bit mono, TPDF, 10 s, all at one common RMS
#   out/ot303/listen/manifest2.json  scene -> shuffled letters -> what each one is
# Letters are shuffled per scene (fixed seed) so names cannot bias the choice; the page's
# copied results name every pick.
import json, os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = os.path.join(ROOT, 'out', 'ot303', 'voicing')
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100
SCENES = [   # key, label, excerpt start (s), what it is
    ('sweep', 'Sweep', 5.6, 'The cutoff knob sweeping up through its top half, resonance 85.'),
    ('hot', 'Hot', 2.0, 'Env mod, resonance and accent at 100. The highest cutoffs.'),
    ('squelch', 'Squelch', 2.0, 'Low cutoff, resonance 95, short decay. Classic acid squelch.'),
    ('accents', 'Accents', 2.0, 'Runs of consecutive accents with slides, cutoff low, resonance 85.'),
]
VOICINGS = [  # key, render suffix, true name
    ('o303', 'o303-4-ell', 'Open303 as shipped (4x)'),
    ('lin', 'zdf2-2-in-0', 'Linear circuit model'),
    ('st05', 'zdf2-2-st-0.5', 'Stage saturation, light (round 1 Hot favourite)'),
    ('st1c', 'zdf2-2-st-1_comp-1', 'Stage saturation, cutoff-compensated'),
    ('st2c', 'zdf2-2-st-2_comp-1', 'Stage saturation x2, cutoff-compensated'),
    ('in1', 'zdf2-2-in-1', 'Input-pair saturation'),
    ('fb1', 'zdf2-2-fb-1', 'Resonance-loop saturation'),
]
ACCENT = [('o303acc', 'zdf2-2-in-0', 'Open303 accent'), ('rcacc', 'zdf2-2-acc', '303 circuit accent')]
ACCENT_SCENES = ['accents', 'hot']
SECONDS = 10.0


def load(name):
    return np.fromfile(os.path.join(R, name + '.f32'), dtype=np.float32).astype(np.float64)


def main():
    os.makedirs(os.path.join(OUT, 'clips2'), exist_ok=True)
    rng = np.random.default_rng(3032)
    jobs = []
    for sc, lab, start, what in SCENES:
        for key, src, name in VOICINGS:
            jobs.append((sc, 'voice', key, src, name, start))
        if sc in ACCENT_SCENES:
            for key, src, name in ACCENT:
                jobs.append((sc, 'accent', key, src, name, start))
    clips = []
    for sc, group, key, src, name, start in jobs:
        x = load(f'{sc}.{src}')
        a = int(start * FS); x = x[a:a + int(SECONDS * FS)]
        x = x / np.sqrt(np.mean(x ** 2))
        n = int(0.005 * FS); ramp = np.linspace(0, 1, n)
        x[:n] *= ramp; x[-n:] *= ramp[::-1]
        clips.append([sc, group, key, name, src, x])
    crest = max(np.max(np.abs(c[5])) for c in clips)
    target = min(10 ** (-23 / 20), 10 ** (-1.5 / 20) / crest)      # common RMS, peaks <= -1.5 dBFS
    manifest = {'scenes': [], 'rms_dbfs': round(20 * np.log10(target), 1)}
    order = np.random.default_rng(303).permutation
    for sc, lab, start, what in SCENES:
        vs = [c for c in clips if c[0] == sc and c[1] == 'voice']
        perm = order(len(vs))
        voice = [dict(letter='ABCDEFG'[i], key=vs[j][2], name=vs[j][3], file=f'clips2/{sc}-v-{vs[j][2]}.wav')
                 for i, j in enumerate(perm)]
        acc = []
        ac = [c for c in clips if c[0] == sc and c[1] == 'accent']
        if ac:
            p2 = order(len(ac))
            acc = [dict(letter=str(i + 1), key=ac[j][2], name=ac[j][3], file=f'clips2/{sc}-a-{ac[j][2]}.wav')
                   for i, j in enumerate(p2)]
        manifest['scenes'].append(dict(key=sc, label=lab, what=what, voicing=voice, accent=acc))
    for sc, group, key, name, src, x in clips:
        fn = f"{sc}-{'v' if group == 'voice' else 'a'}-{key}.wav"
        pcm = x * target * 32767 + (rng.random(len(x)) - rng.random(len(x)))
        pcm = np.clip(np.round(pcm), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips2', fn), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    with open(os.path.join(OUT, 'manifest2.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    print(f"{len(clips)} clips at {manifest['rms_dbfs']} dBFS RMS, loudest peak "
          f"{20*np.log10(crest*target):.1f} dBFS")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 1: the listening pack's clips, from tools/ot303/run_study.sh renders.
#   out/ot303/listen/clips/*.wav   16-bit mono 44.1 kHz, TPDF-dithered, 10 s excerpts
#   out/ot303/listen/manifest.json what each clip is
# Every clip is matched to the same RMS (-23 dBFS) so level never gives a version away; the
# common target is low enough that the loudest peak stays below -1 dBFS.
import json, os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = os.path.join(ROOT, 'out', 'ot303', 'renders')
OUT = os.path.join(ROOT, 'out', 'ot303', 'listen')
FS = 44100
SCENES = {   # name: (label, excerpt start s, what it stresses)
    'hot': ('Hot', 2.0, 'env mod, resonance and accent all at 100: the highest cutoffs'),
    'sweep': ('Sweep', 5.6, 'cutoff knob sweeping up through its top half, resonance 85'),
    'squelch': ('Squelch', 2.0, 'low cutoff, resonance 95, short decay: classic acid squelch'),
}
RATE = [('ideal', 'refnl-8-d1', 'Ideal (8x reference)'), ('4x', 'zdfnl-4-d1-h1', '4x'),
        ('3x', 'zdfnl-3-d1-h1', '3x'), ('2x', 'zdfnl-2-d1-h1', '2x')]
DRIVE = [('o303', 'o303-4-ell', 'Open303 as shipped'), ('lin', 'zdf-4', 'Linear model'),
         ('d05', 'zdfnl-4-d0.5-h1', 'Drive 0.5'), ('d1', 'zdfnl-4-d1-h1', 'Drive 1'),
         ('d2', 'zdfnl-4-d2-h1', 'Drive 2')]
SECONDS = 10.0
TARGET_RMS = 10 ** (-23 / 20)


def load(name):
    return np.fromfile(os.path.join(R, name + '.f32'), dtype=np.float32).astype(np.float64)


def main():
    os.makedirs(os.path.join(OUT, 'clips'), exist_ok=True)
    rng = np.random.default_rng(303)
    clips, peaks = [], []
    for sc, (lab, start, what) in SCENES.items():
        for group, table in (('rate', RATE), ('drive', DRIVE)):
            for key, src, label in table:
                x = load(f'{sc}.{src}')
                a = int(start * FS); x = x[a:a + int(SECONDS * FS)]
                x = x * (TARGET_RMS / np.sqrt(np.mean(x ** 2)))
                n = int(0.005 * FS)                       # 5 ms fades: the loop seam
                ramp = np.linspace(0, 1, n)
                x[:n] *= ramp; x[-n:] *= ramp[::-1]
                peaks.append(np.max(np.abs(x)))
                clips.append(dict(scene=sc, group=group, key=key, label=label, src=src, x=x))
    pk = max(peaks)
    assert pk < 10 ** (-1 / 20), f'peak {20*np.log10(pk):.1f} dBFS: lower TARGET_RMS'
    manifest = {'scenes': {k: {'label': v[0], 'what': v[2]} for k, v in SCENES.items()},
                'rate': [dict(key=k, label=l) for k, _, l in RATE],
                'drive': [dict(key=k, label=l) for k, _, l in DRIVE], 'clips': []}
    for c in clips:
        fn = f"{c['scene']}-{c['group']}-{c['key']}.wav"
        pcm = c['x'] * 32767 + (rng.random(len(c['x'])) - rng.random(len(c['x'])))   # TPDF
        pcm = np.clip(np.round(pcm), -32768, 32767).astype('<i2')
        with wave.open(os.path.join(OUT, 'clips', fn), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
        manifest['clips'].append(dict(scene=c['scene'], group=c['group'], key=c['key'],
                                      label=c['label'], file='clips/' + fn, render=c['src']))
    with open(os.path.join(OUT, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    print(f'{len(clips)} clips, loudest peak {20*np.log10(pk):.1f} dBFS -> {OUT}')


if __name__ == '__main__':
    main()

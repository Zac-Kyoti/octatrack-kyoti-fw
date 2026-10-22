#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# The joint-calibration yardstick against Din Sync's real TB-303 (realref.py's notes and segmentation):
#   * third-octave bands 50 Hz .. 10 kHz (23), so a resonance's frequency and width show;
#   * windows from 15 ms (15-40, 40-100, 100-250, 250-600, 600-1300 ms): the note's first 15 ms are not fitted
#     (the onset stays the final build's: declicker and soft attack are not free);
#   * a cell counts when its window holds 2 cycles of its band and it is within 40 dB of the note's loudest cell
#     (in the recording or the model);
#   * one global gain; the error is the RMS of the dB differences.
import math, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from scipy.signal import butter, sosfilt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import realref as RR

FS = 44100
CENTERS = [50.0 * 2 ** (i / 3) for i in range(23)]
WINS_MS = [(15, 40), (40, 100), (100, 250), (250, 600), (600, 1300)]
FLOOR = 40.0
VALID = np.array([[(e - a) >= 2000.0 / c for (a, e) in WINS_MS] for c in CENTERS])
_SOS = None

def sos():
    global _SOS
    if _SOS is None:
        _SOS = [butter(3, [c * 2 ** (-1 / 6), min(c * 2 ** (1 / 6), 0.45 * FS)], 'bandpass', fs=FS, output='sos') for c in CENTERS]
    return _SOS

def feats(x, onsets):
    out = np.zeros((len(onsets), len(CENTERS), len(WINS_MS)))
    for b, s in enumerate(sos()):
        y = sosfilt(s, x) ** 2
        for n, o in enumerate(onsets):
            for w, (a, e) in enumerate(WINS_MS):
                out[n, b, w] = 10 * math.log10(y[o + int(a * FS / 1000): o + int(e * FS / 1000)].mean() + 1e-20)
    return out

def ref_features():
    cache = os.path.join(RR.WORK, 'ref_feats2.npz')
    if os.path.exists(cache):
        return dict(np.load(cache))
    F = {}
    for s in RR.SETS:
        x = RR.rd(os.path.join(RR.RAW, 'SET-%s.wav' % s))
        F[s] = feats(x, [o - int(round(RR.detect_bias())) for o in RR.ref_onsets(x)])
    np.savez(cache, **F)
    return F

# BASS_FREE (env, Hz): on notes with RESONANCE >= 50 % the bands below this are not fitted, so the voice may keep its
# bass as RES rises (the author's choice) instead of copying the 303's bass loss
BASS_FREE = float(os.environ.get('BASS_FREE', 0))
def _valid(sets):
    v = np.broadcast_to(VALID[None, None], (len(sets), 16) + VALID.shape).copy()
    if BASS_FREE > 0:
        lo = np.array([c < BASS_FREE for c in CENTERS])
        for i, s in enumerate(sets):
            for n, (kn, sq, acc) in enumerate(RR.notes_of(s)):
                if kn['res'] >= 50: v[i, n, lo, :] = False
    return v
def compare(R, M, sets=RR.SETS):
    r = np.stack([R[s] for s in sets]); m = np.stack([M[s] for s in sets])
    fl = r.max(axis=(2, 3), keepdims=True) - FLOOR
    valid = _valid(sets) if (BASS_FREE > 0 and r.shape[1] == 16 and all(s in RR.SETS for s in sets)) else VALID[None, None]
    gain = float(np.median((r - m)[(r > fl) & valid]))
    for _ in range(4):
        keep = ((r > fl) | (m + gain > fl)) & valid
        d = np.maximum(r, fl) - np.maximum(m + gain, fl); gain += float(d[keep].mean())
    keep = ((r > fl) | (m + gain > fl)) & valid
    d = np.maximum(r, fl) - np.maximum(m + gain, fl)
    return float(np.sqrt(np.mean(d[keep] ** 2))), gain, np.where(keep, d, np.nan)

def _render_batch(args):
    tuples, params, tag, idx = args
    lines = ['%d %d %d %d %d %d' % (RR.STEP, 2 * len(tuples), RR.GATE, 38, 64, 64)]; frames = []
    for (c, r, e, d, a, w) in tuples:
        lines.append('N 24 %d 0' % a); lines.append('R 0 0 0')
        frames += ['%d %d %d %d %d' % (c, e, r, d, w)] * (RR.NSTEP // 16)
    sc = os.path.join(RR.WORK, 'j_%s_%d.txt' % (tag, idx)); out = sc[:-4] + '.f32'
    open(sc, 'w').write('\n'.join(lines + frames) + '\n')
    subprocess.run([RR.EXE, sc, out] + ([params] if params else []), check=True, stderr=subprocess.DEVNULL)
    x = np.fromfile(out, dtype=np.float32).astype(np.float64)
    f = feats(x, [n * RR.NSTEP for n in range(len(tuples))])
    pk = [float(np.abs(x[n * RR.NSTEP:(n + 1) * RR.NSTEP]).max()) for n in range(len(tuples))]
    return list(zip(tuples, f, pk))

class NoteCache:
    def __init__(self, params_path=None, tag='j', pool=None):
        self.params, self.tag, self.f, self.pk = params_path, tag, {}, {}
        self.pool = pool or ProcessPoolExecutor(8)
    def need(self, tuples):
        todo = sorted(set(t for t in tuples if t not in self.f))
        if not todo: return
        chunks = [todo[i::8] for i in range(8) if todo[i::8]]
        for res in self.pool.map(_render_batch, [(ch, self.params, self.tag, i) for i, ch in enumerate(chunks)]):
            for t, f, p in res: self.f[t] = f; self.pk[t] = p
    def model(self, law):
        keys = {s: [RR.note_tuple(kn, sq, acc, law) for kn, sq, acc in RR.notes_of(s)] for s in RR.SETS}
        self.need([t for v in keys.values() for t in v])
        return {s: np.stack([self.f[t] for t in keys[s]]) for s in RR.SETS}, max(self.pk[t] for v in keys.values() for t in v)

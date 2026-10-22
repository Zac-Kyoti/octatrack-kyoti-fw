#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# BLACKPYRAMIDS_303 against a real TB-303: Din Sync's reference recordings for x0xb0x builders (dinsync.info,
# 12 Feb 2010; 25 sets x 16 notes, C2, CUTOFF / RESONANCE / ENV MOD / DECAY / ACCENT at 0/25/50/75/100 %).
# The recordings are measured, never redistributed: fetch them yourself into out/dinsync/raw/ (README in
# tools/ot303/body/). Each set's note n: position n//4 of the set's chart, saw (n%4 < 2) or square, accented
# when n is odd. The gate on the recording is 1.32 s, a note every 3.0 s.
#
# Features: 16 half-octave bands (55 Hz .. 10 kHz, 3rd-order Butterworth) x 7 windows after the note start
# (0-5, 5-15, 15-40, 40-100, 100-250, 250-600, 600-1300 ms), energy in dB; cells below the reference note's
# loudest cell - 60 dB are floored there. One global gain (the model's level against the recording) is
# fitted; the error is the RMS of the cell differences.
import json, math, os, subprocess, sys, wave
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.signal import butter, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW = os.path.join(ROOT, 'out', 'dinsync', 'raw'); WORK = os.path.join(ROOT, 'out', 'body')
EXE = os.environ.get('BP_RENDER', os.path.join(WORK, 'bp_render'))
FS = 44100
SETS = ['%s%d' % (g, i) for g in 'ABCDE' for i in range(1, 6)]
BASE = {'A': 0, 'B': 25, 'C': 50, 'D': 75, 'E': 100}
KNOBS = ('cut', 'res', 'env', 'dec', 'acc')
WINS_MS = [(0, 5), (5, 15), (15, 40), (40, 100), (100, 250), (250, 600), (600, 1300)]
CENTERS = [55.0 * 2 ** (i / 2) for i in range(16)]
FLOOR = 60.0
VALID = np.array([[(e - a) >= 2000.0 / c for (a, e) in WINS_MS] for c in CENTERS])   # [band, window]

def chart(s):
    """the four positions of set s: dicts of knob -> percent"""
    g, i = s[0], int(s[1]) - 1
    out = []
    for pos in range(4):
        v = {k: BASE[g] for k in KNOBS}
        if g == 'A':
            v = {k: 0 for k in KNOBS}
        v[KNOBS[i]] = 25 * (pos + 1)
        out.append(v)
    return out

def notes_of(s):
    """16 (knobs, wave 0/1, accent bool) for set s"""
    return [(chart(s)[n // 4], (n % 4) >= 2, (n % 2) == 1) for n in range(16)]

_SOS = None
def sos():
    global _SOS
    if _SOS is None:
        _SOS = [butter(3, [c * 2 ** -0.25, min(c * 2 ** 0.25, 0.45 * FS)], 'bandpass', fs=FS, output='sos') for c in CENTERS]
    return _SOS

def feats(x, onsets):
    """(len(onsets), 16, 7) dB"""
    out = np.zeros((len(onsets), len(CENTERS), len(WINS_MS)))
    for b, s in enumerate(sos()):
        y = sosfilt(s, x) ** 2
        for n, o in enumerate(onsets):
            for w, (a, e) in enumerate(WINS_MS):
                seg = y[o + int(a * FS / 1000): o + int(e * FS / 1000)]
                out[n, b, w] = 10 * math.log10(seg.mean() + 1e-20)
    return out

def rd(p):
    w = wave.open(p); x = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels())
    return x.mean(1) / 32768.0

def ref_onsets(x):
    """16 note starts: a 3.0 s grid fitted to the clear onsets, each refined to where the 1-ms envelope first
    passes 10 % of that note's peak"""
    e10 = np.sqrt(np.convolve(x ** 2, np.ones(441) / 441, 'same'))       # 10 ms: does not ripple at 65 Hz
    up = np.flatnonzero(np.diff((e10 > 0.02 * e10.max()).astype(int)) == 1)
    big = [up[0]] + [u for a, u in zip(up, up[1:]) if u - a > 1.5 * FS]   # one rise a note
    per = 3.0 * FS
    t0 = float(np.median([b - round((b - big[0]) / per) * per for b in big]))
    peak = np.abs(x)
    out = []
    for n in range(16):
        g = int(t0 + n * per)
        lo = max(0, g - int(0.03 * FS))
        seg = peak[lo:g + int(0.03 * FS)]
        pk = peak[g:g + int(0.2 * FS)].max()
        idx = np.flatnonzero(seg > 0.25 * pk)                          # the first sample past a quarter of the note's peak
        out.append(lo + int(idx[0]) if len(idx) else g)
    n = np.arange(16); a, b = np.polyfit(n, np.asarray(out, float), 1)          # the sequencer's clock is steady:
    res = np.asarray(out) - (a * n + b); ok = np.abs(res) < 3 * np.std(res) + 1   # fit a line, drop outliers, refit
    a, b = np.polyfit(n[ok], np.asarray(out, float)[ok], 1)
    return [int(round(a * k + b)) for k in n]

DETECT_BIAS = None
def detect_bias():
    """how late ref_onsets lands on a note that starts at a known sample (measured on the model's renders)"""
    global DETECT_BIAS
    if DETECT_BIAS is None:
        p = os.path.join(WORK, 'detect_bias.json')
        if os.path.exists(p):
            DETECT_BIAS = json.load(open(p))['bias']
        else:
            bs = []
            for s in ('A1', 'B2', 'C3', 'D4', 'E5'):
                x = render_set(s, law_identity(), tag='bias'); on = ref_onsets(np.concatenate([np.zeros(FS), x]))
                bs += [o - FS - 2 * k * STEP for k, o in enumerate(on)]
            DETECT_BIAS = float(np.median(bs)); json.dump({'bias': DETECT_BIAS, 'spread': float(np.std(bs))}, open(p, 'w'))
    return DETECT_BIAS

def ref_features():
    cache = os.path.join(WORK, 'ref_feats.npz')
    if os.path.exists(cache):
        return dict(np.load(cache))
    os.makedirs(WORK, exist_ok=True)
    F = {}
    for s in SETS:
        x = rd(os.path.join(RAW, 'SET-%s.wav' % s)); on = [o - int(round(detect_bias())) for o in ref_onsets(x)]
        F[s] = feats(x, on)
    np.savez(cache, **F)
    return F

# ----------------------------------------------------------------------------- the model --
STEP = 66144                       # two steps a note: a note every 3.0 s
GATE = 112                         # (112 + 1) / 128 of a step = 1.324 s, the recording's gate
def law_identity():
    return {'cut': lambda p: p / 100 * 127 * 256, 'res': lambda p: p / 100 * 127, 'env': lambda p: p / 100 * 127 * 256,
            'dec': lambda p: p / 100 * 127, 'acc': lambda p: p / 100 * 127}
def law_table(tab):
    """tab: knob -> 5 values at 0/25/50/75/100 % (CUT and ENV in 1/256 knob steps)"""
    return {k: (lambda p, v=tab[k]: float(np.interp(p, [0, 25, 50, 75, 100], v))) for k in KNOBS}

def score_text(s, law, vol=64):
    lines = ['%d %d %d %d %d %d' % (STEP, 32, GATE, 38, vol, 64)]
    frames = []
    for n, (kn, sq, acc) in enumerate(notes_of(s)):
        a = max(1, int(round(law['acc'](kn['acc'])))) if acc else 0
        lines.append('N %d %d 0' % (24, a)); lines.append('R 0 0 0')
        row = '%d %d %d %d %d' % (int(round(law['cut'](kn['cut']))), int(round(law['env'](kn['env']))),
                                  int(round(law['res'](kn['res']))), int(round(law['dec'](kn['dec']))), 127 if sq else 0)
        frames += [row] * (2 * STEP // 16)
    return '\n'.join(lines + frames) + '\n'

def render_set(s, law, params=None, tag='x', vol=64):
    sc = os.path.join(WORK, 'sc_%s_%s.txt' % (tag, s)); out = os.path.join(WORK, 'out_%s_%s.f32' % (tag, s))
    open(sc, 'w').write(score_text(s, law, vol))
    cmd = [EXE, sc, out] + ([params] if params else [])
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    x = np.fromfile(out, dtype=np.float32).astype(np.float64)
    return x

def model_features(law, params=None, tag='x', sets=SETS, vol=64):
    def one(s):
        x = render_set(s, law, params, tag, vol)
        return s, feats(x, [2 * n * STEP for n in range(16)]), float(np.abs(x).max())
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, sets))
    return {s: f for s, f, _ in res}, {s: p for s, _, p in res}

def compare(R, M, sets=SETS, gain=None):
    """returns (rms dB, gain, per-cell error array [set, note, band, win])"""
    r = np.stack([R[s] for s in sets]); m = np.stack([M[s] for s in sets])
    valid = VALID[None, None]                    # a cell counts when its window holds 2 cycles of its band
    top = r.max(axis=(2, 3), keepdims=True)
    fl = top - FLOOR
    rr = np.maximum(r, fl)
    if gain is None:
        mask = (r > fl) & valid
        gain = float(np.median((r - m)[mask]))
        for _ in range(3):                      # refine as the mean over the cells that count
            mm = np.maximum(m + gain, fl); d = rr - mm; gain += float(d[mask].mean())
    mm = np.maximum(m + gain, fl)
    d = rr - mm
    keep = ((r > fl) | (m + gain > fl)) & valid
    return float(np.sqrt(np.mean(d[keep] ** 2))), gain, np.where(keep, d, np.nan)

def report(name, d, rms):
    """d: [set, note, band, win] ref - model (positive: the real 303 has more)"""
    print('%s: RMS %.2f dB' % (name, rms))
    groups = [('sub 55-110', 0, 3), ('low-mid 110-440', 2, 7), ('mid 440-1250', 6, 10), ('presence 1.25-5k', 9, 14), ('air 5-10k', 13, 16)]
    print('   mean (real - model) dB by band and window (+ = the real 303 has more):')
    print('   %-18s' % '' + ''.join('%9s' % ('%d-%d' % w) for w in WINS_MS))
    for nm, a, b in groups:
        print('   %-18s' % nm + ''.join('%9.1f' % np.nanmean(d[:, :, a:b, w]) for w in range(len(WINS_MS))))

if __name__ == '__main__':
    R = ref_features()
    print('reference features:', {s: R[s].shape for s in SETS[:1]}, 'loudest cell', max(R[s].max() for s in SETS))

# ------------------------------------------------------------------ note-level cache (for fitting) --
# A note's features depend (to within the recording's own noise) on its own knobs only: the notes are 3 s
# apart and the VCA is closed for 1.7 s before the next. So each distinct knob tuple is rendered once.
from concurrent.futures import ProcessPoolExecutor
NSTEP = 2 * STEP
def note_tuple(kn, sq, acc, law):
    a = max(1, int(round(law['acc'](kn['acc'])))) if acc else 0
    return (int(round(law['cut'](kn['cut']))), int(round(law['res'](kn['res']))), int(round(law['env'](kn['env']))),
            int(round(law['dec'](kn['dec']))), a, 127 if sq else 0)

def _render_batch(args):
    tuples, params, tag, vol, idx = args
    lines = ['%d %d %d %d %d %d' % (STEP, 2 * len(tuples), GATE, 38, vol, 64)]; frames = []
    for (c, r, e, d, a, w) in tuples:
        lines.append('N 24 %d 0' % a); lines.append('R 0 0 0')
        frames += ['%d %d %d %d %d' % (c, e, r, d, w)] * (NSTEP // 16)
    sc = os.path.join(WORK, 'nb_%s_%d.txt' % (tag, idx)); out = os.path.join(WORK, 'nb_%s_%d.f32' % (tag, idx))
    open(sc, 'w').write('\n'.join(lines + frames) + '\n')
    subprocess.run([EXE, sc, out] + ([params] if params else []), check=True, stderr=subprocess.DEVNULL)
    x = np.fromfile(out, dtype=np.float32).astype(np.float64)
    f = feats(x, [n * NSTEP for n in range(len(tuples))])
    pk = [float(np.abs(x[n * NSTEP:(n + 1) * NSTEP]).max()) for n in range(len(tuples))]
    return list(zip(tuples, f, pk))

class NoteCache:
    def __init__(self, params=None, tag='c', vol=64):
        self.params, self.tag, self.vol, self.f, self.pk = params, tag, vol, {}, {}
        self.pool = ProcessPoolExecutor(8)
    def need(self, tuples):
        todo = sorted(set(t for t in tuples if t not in self.f))
        if not todo: return
        chunks = [todo[i::8] for i in range(8) if todo[i::8]]
        for res in self.pool.map(_render_batch, [(ch, self.params, self.tag, self.vol, i) for i, ch in enumerate(chunks)]):
            for t, f, p in res: self.f[t] = f; self.pk[t] = p
    def model(self, law):
        keys = {s: [note_tuple(kn, sq, acc, law) for kn, sq, acc in notes_of(s)] for s in SETS}
        self.need([t for v in keys.values() for t in v])
        return {s: np.stack([self.f[t] for t in keys[s]]) for s in SETS}, max(self.pk[t] for v in keys.values() for t in v)

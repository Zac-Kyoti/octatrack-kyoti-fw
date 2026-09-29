#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 14, gate 1: the channel 1/2 listening pack.

RPSP as rev 13 plays it (raw outputs 7/8, the float model), then the same
through the SSM2044-style channel 1/2 stage (tools/repitch_engine_model.py,
Ch12) with each envelope candidate, for two ways of triggering:

  loop    one trig per loop pass (the user's pattern A02: T2 has a single trig
          on step 1 and plays isaak.wav through) -- the filter opens once per pass
  16ths   a trig on every 16th note, as an SP-1200 plays a break chopped onto
          pads (on the OT: slices, one trig per step) -- it opens on every hit

    python3 tools/repitch_ch12_listen.py SOURCE.wav [OUT_DIR]

Writes 16-bit WAVs to OUT_DIR (default out/rev14_listen/) and prints, per
file, the spectral balance and the fold of rev 13's render vs the box render
through each candidate.
"""
import math
import pathlib
import sys
import wave

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repitch_engine_model as m   # noqa: E402

SR = 44100


def load(path):
    w = wave.open(str(path))
    assert w.getsampwidth() == 2 and w.getframerate() == SR, "16-bit 44.1 kHz"
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels()) / 32768.0
    return x if x.shape[1] == 2 else np.repeat(x, 2, axis=1)


def save(path, y):
    y = np.clip(np.round(np.asarray(y) * 32767), -32768, 32767).astype("<i2")
    w = wave.open(str(path), "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(y.tobytes()); w.close()


def drum_loop(bpm=120.0, bars=2, seed=7):
    """A synthetic kick/snare/hat break (NOT a recording), 16ths."""
    rng = np.random.default_rng(seed)
    step = 60.0 / bpm / 4
    n = int(round(bars * 16 * step * SR))
    y = np.zeros(n)
    kick = {0, 6, 10, 16, 22, 26}
    snare = {4, 12, 20, 28}
    for s in range(bars * 16):
        i0 = int(round(s * step * SR))
        t = np.arange(min(n - i0, int(0.4 * SR))) / SR
        if s in kick:
            y[i0:i0 + len(t)] += 0.9 * np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-t * 35)) / SR) * np.exp(-t * 9)
        if s in snare:
            y[i0:i0 + len(t)] += 0.45 * rng.standard_normal(len(t)) * np.exp(-t * 22) \
                + 0.35 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
        h = 0.18 if s % 2 else 0.10
        y[i0:i0 + len(t)] += h * np.diff(rng.standard_normal(len(t) + 1)) * np.exp(-t * 90)
    y *= 0.8 / np.max(np.abs(y))
    return np.stack([y, np.roll(y, 3)], 1)


def rpsp78(src, r, render="rev13"):
    """rev 13's RPSP (float model). render='box' swaps in rev 11/12's box render."""
    if render == "box":
        saved = m.render_gc
        L, R = m.RENDER["L"], m.RENDER["R"]
        # a box: all of the step lands in the current output, weighted by 1-u
        gc = np.zeros(L * R + 1)
        gc[(L - 1) * R:] = np.linspace(0.0, 1.0, R + 1)
        m.render_gc = lambda: gc
        try:
            return m.run(m.MODE_RPSP, src, r)
        finally:
            m.render_gc = saved
    return m.run(m.MODE_RPSP, src, r)


def ch12(y, hits, env, amp=None, **kw):
    f = m.Ch12(env, **kw)
    out = np.empty_like(y)
    hs = set(int(h) for h in hits)
    for i in range(len(y)):
        if i in hs:
            f.hit()
        if amp is not None:
            f.amp(amp[i])
        out[i] = f(y[i])
    return out


def band_db(y, lo, hi):
    Y = np.abs(np.fft.rfft(y[:, 0] * np.hanning(len(y)))) ** 2
    fr = np.fft.rfftfreq(len(y), 1 / SR)
    return 10 * np.log10(Y[(fr >= lo) & (fr < hi)].sum() + 1e-20)


def fold_report(envs=("A", "B", "C"), bpm=120.0):
    """Rev 13's band-limited render vs rev 11/12's box, through each candidate:
    a tone f at 1/1 leaves a fold line at 18.06 kHz - f (the staircase image at
    26.04 kHz + f, folded at 22.05 kHz; a real SP has none). Level of that
    line relative to the tone, averaged over 1 s with a trig on every 16th."""
    n = SR
    t = np.arange(n) / SR
    hits = [int(round(k * 60.0 / bpm / 4 * SR)) for k in range(int(n / (60.0 / bpm / 4 * SR)) + 1)]
    lines = []
    for f0 in (1000.0, 3000.0, 5000.0, 8000.0):
        src = np.stack([0.5 * np.sin(2 * np.pi * f0 * t)] * 2, 1)
        ff = SR - m.FS_SP - f0
        row = []
        for render in ("rev13", "box"):
            y78 = rpsp78(src, 1.0, render)[2000:]
            for env in ("7/8",) + tuple(envs):
                y = y78 if env == "7/8" else ch12(y78, [h - 2000 for h in hits if h >= 2000], env,
                                                   amp=np.ones(len(y78)) if env == "A" else None)
                Y = np.abs(np.fft.rfft(y[:, 0] * np.blackman(len(y))))
                fr = np.fft.rfftfreq(len(y), 1 / SR)

                def pk(x):
                    k = np.argmin(np.abs(fr - x))
                    return Y[max(k - 3, 0):k + 4].max()
                row.append((render, env, 20 * np.log10(pk(ff) / pk(f0) + 1e-12)))
        lines.append(f"tone {f0/1e3:g} kHz, fold at {ff/1e3:.2f} kHz (dB re tone): " +
                     "  ".join(f"{r}/{e} {v:6.1f}" for r, e, v in row))
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--fold":
        print(fold_report())
        return
    src_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path.home() / "Desktop/isaak.wav"
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE.parent / "out/rev14_listen"
    out.mkdir(parents=True, exist_ok=True)
    sources = {"isaak": load(src_path), "drumloop_synthetic": drum_loop()}
    cases = [("isaak", 0.75, 90), ("isaak", 1.0, 120), ("drumloop_synthetic", 0.75, 90), ("drumloop_synthetic", 1.0, 120)]
    for name, r, bpm in cases:
        src = np.concatenate([sources[name]] * 2)            # two passes of the loop
        y78 = rpsp78(src, r)
        n = len(y78)
        loop_len = int(round(len(sources[name]) / r))
        hits = {"loop": list(range(0, n, loop_len)),
                "16ths": [int(round(k * 60.0 / bpm / 4 * SR)) for k in range(int(n / (60.0 / bpm / 4 * SR)) + 1)]}
        tag = f"{name}_{bpm}bpm_{r:g}"
        save(out / f"{tag}_0_rev13_ch78.wav", y78)
        for trig, hs in hits.items():
            for env in ("A", "A-shortamp", "B", "C", "D-extra"):
                if env == "A":                      # your T2: ATK 0 / HOLD 127 / REL 127 -> level 1 from each trig
                    y = ch12(y78, hs, "A", amp=amp_hold(n, hs))
                elif env == "A-shortamp":           # the same with a short AMP (HOLD 0, a 0.25 s linear release)
                    a = amp_decay(n, hs, 0.25)
                    y = ch12(y78, hs, "A", amp=a) * a[:, None]
                elif env == "D-extra":              # NOT SP-authentic: the diode + RC fed the audio's own level
                    lvl = np.minimum(1.0, np.abs(y78).max(1) / 0.6)
                    y = ch12(y78, [], dict(kind="amp", tau=0.08), amp=lvl)
                else:
                    y = ch12(y78, hs, env)
                save(out / f"{tag}_{trig}_{env}.wav", y)
                print(f"{tag} {trig:5} {env:10}: 1-4k {band_db(y, 1e3, 4e3) - band_db(y78, 1e3, 4e3):+6.1f} dB, "
                      f"4-10k {band_db(y, 4e3, 1e4) - band_db(y78, 4e3, 1e4):+6.1f}, "
                      f"10-20k {band_db(y, 1e4, 2e4) - band_db(y78, 1e4, 2e4):+6.1f} vs ch 7/8")


def amp_hold(n, hits):
    """The OT AMP level with ATK 0 / HOLD 127: full from the first trig on
    (measured in ot_emu: X:(x:$20a+8) jumps to ~1 at a trig)."""
    a = np.zeros(n)
    if hits:
        a[min(hits):] = 1.0
    return a


def amp_decay(n, hits, t_rel):
    """ATK 0 / HOLD 0: from 1 at each trig, a LINEAR fall to 0 over t_rel
    (the DSP's AMP stage ramps linearly: REL 30 measured at -5.08e-4/sample)."""
    a = np.zeros(n)
    k = int(t_rel * SR)
    for h in sorted(hits):
        seg = np.clip(1.0 - np.arange(n - h) / k, 0.0, 1.0)
        a[h:] = seg
    return a

if __name__ == "__main__":
    main()

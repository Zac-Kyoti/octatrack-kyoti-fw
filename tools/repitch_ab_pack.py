#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
A/B listening pack for REPITCH_REPEAT98_KYOTI's sound decisions: one source, every
candidate design rendered by the float reference model (tools/repitch_engine_model.py)
under the same OT protocol, level-matched, written as WAVs plus a manifest.

The source is a drum break played the way an SP-1200 user plays one: chopped IN ORDER at
every eighth note (each slice is its own trig, so a new sound starts there, as from a
pad), tuned down by --ratio. Positions advance continuously, as the OT plays an in-order
chop; each trig runs the engine's own trig bookkeeping (silence behind the new sound, a
clean RPSP state) and starts the per-hit filter sweep where a variant has one. AMP is
held at 0.95 between trigs (a track's default envelope).

Variants (see VARIANTS): the shipping RPSP, lean mono candidates (the left channel on
both sides), shorter input / render kernels, Yeh's measured channel 1/2 sweep, a fixed
channel 3/4 filter, and RPS9 stereo vs mono. A clean varispeed (the OT's own 2-tap
read, RPCH) is the level reference.

    python3 tools/repitch_ab_pack.py SOURCE.wav --bpm 95 --ratio 0.84 --out out/ab_pack1
"""
import argparse
import json
import math
import pathlib
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import repitch_engine_model as m          # noqa: E402

SR = 44100
# Yeh, Nolting, Smith 2007 (ICMC slides, "Dynamic filters"): the SP-12's VCF channel,
# fitted -- exponential time constant 0.085 s, initial Fc 14,150 Hz, final Fc 1,150 Hz.
YEH = dict(f_rest=1150.0, f_top=14150.0, tau=0.085)


def read_wav(path):
    with wave.open(str(path)) as w:
        n, ch, sw, fs = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    assert fs == SR, f"{path}: {fs} Hz, want {SR}"
    if sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v & 0x800000, v - (1 << 24), v) / float(1 << 23)
    elif sw == 2:
        v = np.frombuffer(raw, dtype="<i2") / 32768.0
    else:
        raise SystemExit(f"{path}: {8 * sw}-bit not handled")
    v = v.reshape(-1, ch)
    return np.repeat(v, 2, axis=1) if ch == 1 else v[:, :2]


def write_wav(path, x):
    y = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(y.tobytes())


def configure(taps=12, L=10):
    """Point the model at a candidate's kernel sizes (both are design parameters)."""
    m.FIR[m.MODE_RPSP]["taps"] = taps
    m.RENDER["L"] = L
    m.render_kernel.cache_clear()


def run(mode, src, ratio, trig_at, *, ch12=False, post_ch=None, sweep=None, ms=False):
    """The OT protocol (as repitch_dsp_engine_check.model_run, float path), with trigs
    at the given output-sample indices. post_ch: a fixed SP channel filter (3..6);
    sweep: a per-hit channel 1/2 stage (Yeh's numbers); ms: rev 17's design (mid + side,
    channel 5) -- the model's default since rev 17, so the older designs pass False."""
    eng = m.Engine(mode, ch12=ch12, ms=ms)
    if post_ch:
        eng.post = m.Biquads(m.sp_channel_filter(post_ch))
    stage = None
    if sweep:
        depth = math.log2(sweep["f_top"] / sweep["f_rest"])
        stage = m.Ch12(dict(kind="ar", attack=0.0, tau=sweep["tau"]), f_rest=sweep["f_rest"], depth=depth)
    inc = ratio
    frames = len(src)
    trigs = sorted(set(trig_at))
    out, pos, written, n = [], 0.0, 0, 0
    ti = 0
    while True:
        last = pos + 15 * inc
        need = int(math.floor(last)) + 2
        if need + 1 > frames:
            break
        if need > written:
            eng.fill(written, src[written:need])
            written = need
        k = 0
        trig = False
        if ti < len(trigs) and trigs[ti] < n + 16:
            k = trigs[ti] - n
            trig = True
            ti += 1
        parts = []
        for (i0, i1), lc in (((0, k), 2), ((k, 16), 1)):
            if i1 == i0:
                continue
            table = [(int(math.floor(pos + i * inc)) % 64, (pos + i * inc) % 1.0) for i in range(i0, i1)]
            y = eng.render(table, inc, trig and lc == 1, 0.95, lc)
            if stage is not None:
                if trig and lc == 1:
                    stage.hit()
                y = np.array([stage(s) for s in y])
            parts.append(y)
        out.append(np.concatenate(parts))
        pos += 16 * inc
        n += 16
    return np.concatenate(out)


def run_exact(src, ratio, trig_at):
    """Rev 17 as the DSP renders it: the bit-exact twin (repitch_engine_model.DspExact,
    which tools/repitch_dsp_engine_check.py holds the kernel to), fed 24-bit samples and
    the OT's 24.24 positions with the mode tag, trigs as run()'s."""
    import repitch_dsp_src as dsrc
    c = dsrc.constants("A")
    rows = [[v - (1 << 24) if v & 0x800000 else v for v in row]
            for row in (m.fir_q23(m.MODE_RPSP) & 0xFFFFFF).tolist()]
    eng = m.DspExact(m.MODE_RPSP, c, rows)
    x = np.clip(np.round(src * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64)
    inc = int(round(ratio * (1 << 24)))
    rint, rfrac = inc >> 24, inc & 0xFFFFFF
    tagged = (rfrac & ~3) | m.MODE_RPSP
    inc_eff = (rint << 24) | tagged
    frames = len(x)
    trigs = sorted(set(trig_at))
    out, pos, written, n, ti = [], 0, 0, 0, 0
    while True:
        last = pos + 15 * inc_eff
        need = (last >> 24) + 2
        if need + 1 > frames:
            break
        if need > written:
            eng.fill(written, x[written:need])
            written = need
        k, trig = 0, False
        if ti < len(trigs) and trigs[ti] < n + 16:
            k, trig = trigs[ti] - n, True
            ti += 1
        parts = []
        for (i0, i1), lc in (((0, k), 2), ((k, 16), 1)):
            if i1 == i0:
                continue
            table = [(((pos + i * inc_eff) >> 24) % 64, (pos + i * inc_eff) & 0xFFFFFF) for i in range(i0, i1)]
            parts.append(eng.render(table, rint, tagged, 0x1000 if trig and lc == 1 else 0, 0, lc))
        out.append(np.concatenate(parts))
        pos += 16 * inc_eff
        n += 16
    return np.concatenate(out).astype(float) / (1 << 23)


def rpch(src, ratio, n):
    """The OT's own read (RPCH / stock): 2-tap linear interpolation."""
    p = np.arange(n) * ratio
    i = np.floor(p).astype(int)
    f = (p - i)[:, None]
    i = np.minimum(i, len(src) - 2)
    return src[i] * (1 - f) + src[i + 1] * f


def active_rms(x):
    """RMS over the samples within 40 dB of the clip's peak (the listening protocol's
    'active RMS': silence between hits does not count)."""
    a = np.abs(x).max(axis=1)
    keep = a > a.max() * 0.01
    return float(np.sqrt(np.mean(x[keep] ** 2)))


VARIANTS = [
    # key, label, kwargs for run(), configure(), source channels, estimated cost note
    ("ref", "Reference: clean varispeed (RPCH, the OT's own read)", None, None, "stereo", "~0 extra"),
    ("now", "RPSP today (rev 16): stereo, 12-tap input, 10-tap render, ch 1/2 following AMP",
     dict(mode=m.MODE_RPSP, ch12=True), dict(taps=12, L=10), "stereo", "234 measured"),
    ("lean10", "Lean: left channel on both sides, 8-tap input, 10-tap render, ch 1/2 as today",
     dict(mode=m.MODE_RPSP, ch12=True), dict(taps=8, L=10), "left", "~85 est."),
    ("lean6", "Lean, 6-tap render: as above with a shorter output render",
     dict(mode=m.MODE_RPSP, ch12=True), dict(taps=8, L=6), "left", "~75 est."),
    ("yeh", "Lean, 6-tap render, ch 1/2 swept per hit as Yeh measured (14.15 kHz to 1.15 kHz, 0.085 s)",
     dict(mode=m.MODE_RPSP, sweep=YEH), dict(taps=8, L=6), "left", "~75 est."),
    ("ch34", "Lean, 6-tap render, fixed channel 3/4 filter instead of ch 1/2",
     dict(mode=m.MODE_RPSP, post_ch=3), dict(taps=8, L=6), "left", "~60 est."),
    ("rps9", "RPS9 today: stereo", dict(mode=m.MODE_RPS9), dict(taps=12, L=10), "stereo", "58 measured"),
    ("rps9m", "RPS9 mono: left channel on both sides", dict(mode=m.MODE_RPS9), dict(taps=12, L=10), "left",
     "~40 est."),
]


def mid_side(src, ratio, trig_at, ch):
    """Stereo kept without a lossy sum: the MID (L+R)/2 through the SP engine, the SIDE
    (L-R)/2 read cleanly (the OT's own 2-tap read) and delayed to line up with the mid's
    latency, then L = M + S, R = M - S. Anti-phase content lives in the side, so nothing
    cancels; the side just does not get the SP's grit."""
    mid = (src[:, :1] + src[:, 1:]) / 2
    side = (src[:, 0] - src[:, 1]) / 2
    y = run(m.MODE_RPSP, np.repeat(mid, 2, axis=1), ratio, trig_at, post_ch=ch)[:, 0]
    clean = rpch(np.repeat(mid, 2, axis=1), ratio, len(y))[:, 0]
    seg = slice(0, min(len(y), 4 * SR))
    xc = [np.dot(y[seg][lag:], clean[seg][:len(y[seg]) - lag]) for lag in range(0, 64)]
    lag = int(np.argmax(xc))                              # the SP path's latency, in samples
    s = rpch(np.stack([side, side], 1), ratio, len(y))[:, 0]
    s = np.concatenate([np.zeros(lag), s])[:len(y)]
    return np.stack([y + s, y - s], 1)


SETS = {
    "1": None,                                            # VARIANTS above
    "2": [
        ("ref", "Reference: clean varispeed (RPCH, the OT's own read)", None, None, "stereo", "~0 extra"),
        ("now", "RPSP today: stereo, channel 1/2 following AMP",
         dict(mode=m.MODE_RPSP, ch12=True), dict(taps=12, L=10), "stereo", "234 measured"),
        ("st34", "Stereo, fixed channel 3/4 filter (no sweep)",
         dict(mode=m.MODE_RPSP, post_ch=3), dict(taps=12, L=10), "stereo", "~120 est."),
        ("st56", "Stereo, fixed channel 5/6 filter (lighter, about 10 kHz)",
         dict(mode=m.MODE_RPSP, post_ch=5), dict(taps=12, L=10), "stereo", "~120 est."),
        ("ms34", "SP mid + clean side, fixed channel 3/4 filter",
         dict(ms=3), dict(taps=8, L=10), "stereo", "~75 est."),
        ("mono34", "Left channel on both sides, fixed channel 3/4 filter",
         dict(mode=m.MODE_RPSP, post_ch=3), dict(taps=8, L=10), "left", "~65 est."),
    ],
    "3": [
        ("ref", "Reference: clean varispeed (RPCH, the OT's own read)", None, None, "stereo", "~0 extra"),
        ("now", "RPSP today: stereo, channel 1/2 following AMP",
         dict(mode=m.MODE_RPSP, ch12=True), dict(taps=12, L=10), "stereo", "234 measured"),
        ("st56", "Stereo, fixed channel 5/6 filter (the target sound)",
         dict(mode=m.MODE_RPSP, post_ch=5), dict(taps=12, L=10), "stereo", "~120 est."),
        ("ms56", "SP mid + clean side, channel 5/6, full output render",
         dict(ms=5), dict(taps=8, L=10), "stereo", "~85 est."),
        ("ms56s", "SP mid + clean side, channel 5/6, short output render",
         dict(ms=5), dict(taps=8, L=6), "stereo", "~75 est."),
    ],
    "4": [
        ("ref", "Reference: clean varispeed (RPCH, the OT's own read)", None, None, "stereo", "~0 extra"),
        ("now", "RPSP today (rev 16): stereo, channel 1/2 following AMP",
         dict(mode=m.MODE_RPSP, ch12=True), dict(taps=12, L=10), "stereo", "234 measured"),
        ("ms56", "The design you chose (pack 3): SP mid + clean side, channel 5, full render",
         dict(ms=5), dict(taps=8, L=10), "stereo", "design"),
        ("rev17", "Rev 17 as built: the DSP's own arithmetic, bit for bit",
         dict(exact=True), dict(taps=8, L=10), "stereo", "159 measured"),
    ],
    "5": [
        ("ref", "Reference: clean varispeed (RPCH, the OT's own read)", None, None, "stereo", "~0 extra"),
        ("ms56", "Your pick from pack 3", dict(ms=5), dict(taps=8, L=10), "stereo", "design"),
        ("rev17b", "Rev 17, side aligned to the mid at every ratio (the DSP's arithmetic)",
         dict(exact=True), dict(taps=8, L=10), "stereo", "164 measured"),
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--bpm", type=float, required=True, help="the source's tempo")
    ap.add_argument("--ratio", type=float, default=0.84)
    ap.add_argument("--loops", type=int, default=2)
    ap.add_argument("--only", default="", help="comma list of variant keys")
    ap.add_argument("--out", default="out/ab_pack")
    ap.add_argument("--set", default="1", choices=sorted(SETS))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src0 = read_wav(a.source)
    src0 = np.concatenate([src0] * a.loops)
    slice_len = SR * 60.0 / a.bpm / 2                    # an eighth note, in source frames
    n_out = int((len(src0) - 64) / a.ratio) // 16 * 16
    trig_at = [int(round(j * slice_len / a.ratio)) for j in range(int(len(src0) / slice_len) + 1)]
    trig_at = [t for t in trig_at if t < n_out]
    clips = {}
    want = only = set(filter(None, a.only.split(",")))
    for key, label, kw, cfg, chans, cost in (SETS[a.set] or VARIANTS):
        if only and key not in only:
            continue
        src = src0 if chans == "stereo" else np.repeat(src0[:, :1], 2, axis=1)
        print(f"rendering {key}: {label}", flush=True)
        if kw is None:
            y = rpch(src, a.ratio, n_out)
        else:
            configure(**cfg)
            kw = dict(kw)
            if kw.get("exact"):
                y = run_exact(src, a.ratio, trig_at)
            elif "ms" in kw:
                y = mid_side(src, a.ratio, trig_at, kw["ms"])
            else:
                mode = kw.pop("mode")
                y = run(mode, src, a.ratio, trig_at, **kw)
        clips[key] = (label, y, cost, chans)
    configure()                                          # the shipping design back
    ref = clips.get("ref")
    target = active_rms(ref[1]) if ref else None
    gains = {}
    for key, (label, y, cost, chans) in clips.items():
        g = target / active_rms(y) if target else 1.0
        gains[key] = g
    peak = max(np.abs(y).max() * gains[k] for k, (_, y, _, _) in clips.items())
    trim = min(1.0, 0.89 / peak)                          # every clip the same trim: ~-1 dBFS peak
    manifest = dict(source=pathlib.Path(a.source).name, bpm=a.bpm, ratio=a.ratio,
                    played_bpm=round(a.bpm * a.ratio, 2), slices="eighth notes, in order",
                    level="active RMS matched to the reference, one common trim", clips=[])
    for key, (label, y, cost, chans) in clips.items():
        g = gains[key] * trim
        write_wav(out / f"{key}.wav", y * g)
        manifest["clips"].append(dict(key=key, label=label, file=f"{key}.wav", gain_db=round(20 * math.log10(g), 2),
                                      cost=cost, channels=chans, seconds=round(len(y) / SR, 2)))
        print(f"  {key}: gain {20 * math.log10(g):+.2f} dB, {len(y) / SR:.2f} s")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(clips)} clips to {out}")


if __name__ == "__main__":
    main()

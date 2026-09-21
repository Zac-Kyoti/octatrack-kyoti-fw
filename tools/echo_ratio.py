#!/usr/bin/env python3
"""MUTE MODE "echo": compare a MUTED render against an otherwise-identical UNMUTED one,
sample for sample, to tell a GAIN RAMP apart from LEAKED TRIGS.

If muting only scales the same audio down, every post-mute burst is the unmuted burst
times one smooth, decaying factor -- the echo is then a too-slow level fade, and the fix
belongs wherever that level is computed.  If the bursts are different WAVEFORMS (or land
where the unmuted run has none), real voices are being started that should not be.

Both runs must come from tools/emu_echo_dsp.py with identical flags but --no-mute.

    python3 tools/echo_ratio.py --muted gate2_s1 --unmuted gate2_nomute --mute-frame 5512
"""
import argparse
import importlib.util
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("emu_echo_dsp", ROOT / "tools/emu_echo_dsp.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--muted", required=True, help="label of the muted run")
    ap.add_argument("--unmuted", required=True, help="label of the unmuted baseline")
    ap.add_argument("--mute-frame", type=int, default=5512)
    ap.add_argument("--frames", type=int, default=19300)
    ap.add_argument("--slot", type=int, default=2)
    a = ap.parse_args()

    m, sr = E.load_wav(E.OUTDIR / f"echo_{a.muted}_core0.wav")
    u, _ = E.load_wav(E.OUTDIR / f"echo_{a.unmuted}_core0.wav")
    ms, us = E.find_transport_start(m, sr), E.find_transport_start(u, sr)
    print(f"muted start={ms}  unmuted start={us}  slot{a.slot}")

    win = int(sr * 0.060)   # 60 ms: long enough to hold a whole burst
    print(f"\n  {'loop':>4} {'step':>4} {'cf':>7} {'t_mute':>9} "
          f"{'muted':>8} {'unmuted':>8} {'ratio':>7} {'corr':>6} {'lag':>5}")
    for loop, step, f in E.trig_frames(a.frames):
        i, j = ms + f * 16, us + f * 16
        if i + win > len(m) or j + win > len(u):
            break
        x, y = m[i:i + win, a.slot], u[j:j + win, a.slot]
        rx, ry = float(np.sqrt(np.mean(x ** 2))), float(np.sqrt(np.mean(y ** 2)))
        ratio = rx / ry if ry > 1e-9 else float("nan")
        # normalised cross-correlation, small lag search: is it the SAME waveform?
        best, lag = 0.0, 0
        if rx > 1e-6 and ry > 1e-6:
            for d in range(-64, 65):
                xa = m[i + d:i + d + win, a.slot]
                c = float(np.dot(xa, y) / (np.linalg.norm(xa) * np.linalg.norm(y) + 1e-12))
                if c > best:
                    best, lag = c, d
        dt = (f - a.mute_frame) / E.FRAMES_PER_SEC * 1000.0
        print(f"  {loop:>4} {step:>4} {f:>7} {dt:>+8.0f}ms {rx:>8.4f} {ry:>8.4f} "
              f"{ratio:>7.3f} {best:>6.3f} {lag:>5}")

    # the ratio as a continuous curve: a gain ramp shows up as a smooth decay that is
    # the SAME whether or not a burst is sounding
    print("\n  continuous 20 ms RMS ratio (muted/unmuted), post-mute:")
    w = int(sr * 0.020)
    i0, j0 = ms + a.mute_frame * 16, us + a.mute_frame * 16
    n = min((len(m) - i0), (len(u) - j0)) // w
    for k in range(n):
        x = m[i0 + k * w: i0 + (k + 1) * w, a.slot]
        y = u[j0 + k * w: j0 + (k + 1) * w, a.slot]
        ry = float(np.sqrt(np.mean(y ** 2)))
        if ry < 5e-4:          # only where the unmuted run actually has signal
            continue
        rx = float(np.sqrt(np.mean(x ** 2)))
        t = k * w / sr * 1000.0
        print(f"    {t:7.0f}ms  muted {rx:.4f}  unmuted {ry:.4f}  ratio {rx / ry:6.3f} "
              f"{'#' * min(50, int(rx / ry * 50))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
